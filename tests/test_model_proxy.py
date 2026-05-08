import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ccsilo.model_proxy import ModelProxyConfig, SseUsageNormalizer, load_config, start_model_proxy


class _RecordingServer:
    def __init__(self, responder):
        self.records = []
        records = self.records

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("content-length") or "0")
                body = self.rfile.read(length) if length else b""
                record = {
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": body,
                }
                records.append(record)
                status, headers, response_body = responder(record)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("content-length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _post_json(url, payload, headers=None):
    body, _headers = _post_json_response(url, payload, headers=headers)
    return body


def _post_json_response(url, payload, headers=None):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            **(headers or {}),
        },
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}


def test_model_proxy_load_config_parses_timeout_ms(tmp_path):
    config_path = tmp_path / "model-proxy.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "architect",
                "backendUrl": "https://backend.example/anthropic",
                "backendAuth": "x-api-key",
                "backendModels": ["worker-model"],
                "anthropicModels": ["claude-opus-4-6"],
                "timeoutMs": "3000000",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.timeout_ms == 3_000_000


def test_model_proxy_rejects_non_architect_mode():
    with pytest.raises(ValueError, match="Architect Mode"):
        start_model_proxy(
            ModelProxyConfig(
                mode="worker",
                backend_url="https://backend.example/anthropic",
                backend_auth="x-api-key",
                backend_models=("worker-model",),
                anthropic_models=("claude-opus-4-6",),
            ),
            api_key="backend-key",
            auth_nonce="nonce",
        )


def test_model_proxy_routes_backend_and_anthropic_with_expected_auth_and_body_filters():
    def backend_response(_record):
        body = (
            b'data: {"type":"message_start","message":{"id":"msg_1","type":"message"}}\n\n'
            b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}\n\n'
        )
        return 200, {"content-type": "text/event-stream"}, body

    def anthropic_response(_record):
        body = json.dumps({"type": "message", "usage": {"input_tokens": 1, "output_tokens": 1}}).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    backend = _RecordingServer(backend_response)
    anthropic = _RecordingServer(anthropic_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=f"{backend.url}/anthropic",
            backend_auth="x-api-key",
            backend_models=("deepseek-v4-flash",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=anthropic.url,
        ),
        api_key="backend-key",
        auth_nonce="nonce",
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/nonce"

    try:
        backend_raw, backend_headers = _post_json_response(
            f"{proxy_url}/v1/messages",
            {
                "model": "deepseek-v4-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "thinking", "thinking": "foreign", "signature": "bad"},
                            {"type": "text", "text": "work"},
                        ],
                    }
                ],
            },
            {"authorization": "Bearer oauth-token", "x-api-key": "anthropic-key"},
        )
        backend_body = backend_raw.decode("utf-8")
        assert backend_headers["content-type"] == "text/event-stream"
        assert backend_headers["cache-control"] == "no-cache"
        assert backend_headers["connection"].lower() == "keep-alive"
        assert '"usage":{"input_tokens":0,"output_tokens":0}' in backend_body
        assert '"usage":{"output_tokens":0}' in backend_body

        assert backend.records[0]["path"] == "/anthropic/v1/messages"
        assert backend.records[0]["headers"]["x-api-key"] == "backend-key"
        assert backend.records[0]["headers"].get("authorization") != "Bearer oauth-token"
        backend_payload = json.loads(backend.records[0]["body"].decode("utf-8"))
        assert backend_payload["messages"][0]["content"] == [{"type": "text", "text": "work"}]

        _post_json(
            f"{proxy_url}/v1/messages",
            {
                "model": "claude-opus-4-6",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "foreign", "signature": "bad"},
                            {"type": "text", "text": "plan"},
                        ],
                    }
                ],
            },
            {"authorization": "Bearer oauth-token"},
        )
        assert anthropic.records[0]["path"] == "/v1/messages"
        assert anthropic.records[0]["headers"]["authorization"] == "Bearer oauth-token"
        anthropic_payload = json.loads(anthropic.records[0]["body"].decode("utf-8"))
        assert anthropic_payload["messages"][0]["content"] == [{"type": "text", "text": "plan"}]
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()
        anthropic.close()


def test_model_proxy_normalizes_backend_json_usage():
    def backend_response(_record):
        return 200, {"content-type": "application/json"}, b'{"type":"message","content":[]}'

    backend = _RecordingServer(backend_response)
    anthropic = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=backend.url,
            backend_auth="bearer",
            backend_models=("openrouter/deepseek",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=anthropic.url,
        ),
        api_key="backend-key",
        auth_nonce="nonce",
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/nonce"

    try:
        raw = _post_json(
            f"{proxy_url}/v1/messages",
            {"model": "openrouter/deepseek", "messages": []},
        )
        payload = json.loads(raw.decode("utf-8"))
        assert payload["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert backend.records[0]["headers"]["authorization"] == "Bearer backend-key"
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()
        anthropic.close()


def test_model_proxy_rejects_wrong_path_method_and_unknown_model():
    def backend_response(_record):
        return 200, {"content-type": "application/json"}, b"{}"

    upstream = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="x-api-key",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
        ),
        api_key="backend-key",
        auth_nonce="nonce",
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{proxy.server_address[1]}"

    try:
        with pytest.raises(HTTPError) as wrong_path:
            _post_json(f"{base_url}/v1/messages", {"model": "worker-model", "messages": []})
        assert wrong_path.value.code == 404

        with pytest.raises(HTTPError) as wrong_method:
            request = Request(f"{base_url}/nonce/v1/messages", method="GET")
            urlopen(request, timeout=5)
        assert wrong_method.value.code == 405

        with pytest.raises(HTTPError) as unknown_model:
            _post_json(f"{base_url}/nonce/v1/messages", {"model": "not-allowed", "messages": []})
        assert unknown_model.value.code == 400
        assert upstream.records == []
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_rejects_oversized_request(monkeypatch):
    monkeypatch.setattr("ccsilo.model_proxy.MAX_REQUEST_BYTES", 1)
    def backend_response(_record):
        return 200, {"content-type": "application/json"}, b"{}"

    upstream = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="x-api-key",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
        ),
        api_key="backend-key",
        auth_nonce="nonce",
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        request = Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/nonce/v1/messages",
            data=b"{}",
            method="POST",
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(request, timeout=5)
        assert exc.value.code == 413
        assert upstream.records == []
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_rejects_oversized_non_sse_response(monkeypatch):
    monkeypatch.setattr("ccsilo.model_proxy.MAX_RESPONSE_BYTES", 1)

    def backend_response(_record):
        return 200, {"content-type": "application/json"}, b"{}"

    upstream = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="x-api-key",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
        ),
        api_key="backend-key",
        auth_nonce="nonce",
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        with pytest.raises(HTTPError) as exc:
            _post_json(
                f"http://127.0.0.1:{proxy.server_address[1]}/nonce/v1/messages",
                {"model": "worker-model", "messages": []},
            )
        assert exc.value.code == 502
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_sse_usage_normalizer_rejects_oversized_event():
    normalizer = SseUsageNormalizer(max_event_bytes=8)

    with pytest.raises(ValueError, match="SSE event"):
        tuple(normalizer.feed(b"data: 123456789\n\n"))


def test_sse_usage_normalizer_handles_crlf_multiline_data_and_comments():
    normalizer = SseUsageNormalizer()

    chunks = [
        b": keepalive\r\nevent: message\r\nid: 1\r\ndata: {\"type\":\"message_delta\",\r\n",
        b"data: \"delta\":{\"stop_reason\":\"end_turn\"}}\r\n\r\n",
    ]
    out = b"".join(part for chunk in chunks for part in normalizer.feed(chunk))
    out += b"".join(normalizer.flush())

    text = out.decode("utf-8")
    assert text.startswith(": keepalive\nevent: message\nid: 1\n")
    assert 'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":0}}' in text
