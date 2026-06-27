import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ccsilo.model_proxy import ModelProxyConfig, SseUsageNormalizer, load_config, main, start_model_proxy

NONCE = "n" * 24


class _RecordingServer:
    def __init__(self, responder):
        self.records = []
        records = self.records

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_GET(self):
                record = {
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": b"",
                }
                records.append(record)
                status, headers, response_body = responder(record)
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("content-length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

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


def _request_response(url, *, method="GET"):
    request = Request(url, method=method)
    with urlopen(request, timeout=5) as response:
        return (
            response.status,
            response.read(),
            {key.lower(): value for key, value in response.headers.items()},
        )


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
                "backendProviderKey": "openrouter",
                "backendProviderLabel": "OpenRouter",
                "backendModelsUrl": "https://backend.example/models",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.timeout_ms == 3_000_000
    assert config.backend_provider_key == "openrouter"
    assert config.backend_provider_label == "OpenRouter"
    assert config.backend_models_url == "https://backend.example/models"


def test_model_proxy_load_config_parses_openai_mode_without_anthropic_models(tmp_path):
    config_path = tmp_path / "model-proxy.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "openai",
                "backendUrl": "https://backend.example/v1",
                "backendAuth": "bearer",
                "backendFormat": "openai-chat",
                "backendModels": ["deepseek-v4-flash"],
                "anthropicModels": [],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.mode == "openai"
    assert config.backend_format == "openai-chat"
    assert config.anthropic_models == ()


def test_model_proxy_rejects_non_architect_mode():
    with pytest.raises(ValueError, match="architect or openai"):
        start_model_proxy(
            ModelProxyConfig(
                mode="worker",
                backend_url="https://backend.example/anthropic",
                backend_auth="x-api-key",
                backend_models=("worker-model",),
                anthropic_models=("claude-opus-4-6",),
            ),
            api_key="backend-key",
            auth_nonce=NONCE,
        )


def test_model_proxy_rejects_openai_mode_without_openai_backend_format():
    with pytest.raises(ValueError, match="openai mode requires backendFormat openai-chat"):
        start_model_proxy(
            ModelProxyConfig(
                mode="openai",
                backend_url="https://backend.example/v1",
                backend_auth="bearer",
                backend_format="anthropic",
                backend_models=("deepseek-v4-flash",),
                anthropic_models=(),
            ),
            api_key="backend-key",
            auth_nonce=NONCE,
        )


def test_model_proxy_rejects_short_nonce():
    with pytest.raises(ValueError, match="missing or too short"):
        start_model_proxy(
            ModelProxyConfig(
                mode="architect",
                backend_url="https://backend.example/anthropic",
                backend_auth="x-api-key",
                backend_models=("worker-model",),
                anthropic_models=("claude-opus-4-6",),
            ),
            api_key="backend-key",
            auth_nonce="short",
        )


def test_model_proxy_main_rejects_missing_nonce(tmp_path, monkeypatch):
    config_path = tmp_path / "model-proxy.json"
    config_path.write_text(
        json.dumps(
            {
                "mode": "architect",
                "backendUrl": "https://backend.example/anthropic",
                "backendAuth": "x-api-key",
                "backendModels": ["worker-model"],
                "anthropicModels": ["claude-opus-4-6"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CCSILO_MODEL_PROXY_API_KEY", "backend-key")
    monkeypatch.delenv("CCSILO_MODEL_PROXY_AUTH_NONCE", raising=False)

    with pytest.raises(SystemExit, match="missing or too short"):
        main(["--config", str(config_path), "--port-file", str(tmp_path / "port")])


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
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}"

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
                            {"type": "redacted_thinking", "data": "opaque"},
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
                            {"type": "redacted_thinking", "data": "opaque"},
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


def test_model_proxy_preserves_anthropic_thinking_blocks_before_backend_session():
    def upstream_response(_record):
        body = json.dumps({"type": "message", "usage": {"input_tokens": 1, "output_tokens": 1}}).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    upstream = _RecordingServer(upstream_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="x-api-key",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-8",),
            anthropic_url=upstream.url,
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        _post_json(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
            {
                "model": "claude-opus-4-8",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "", "signature": "sig"},
                            {"type": "redacted_thinking", "data": "opaque"},
                            {"type": "thinking", "thinking": "local unsigned"},
                            {"type": "text", "text": "plan"},
                        ],
                    }
                ],
            },
        )

        payload = json.loads(upstream.records[0]["body"].decode("utf-8"))
        assert payload["messages"][0]["content"] == [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "redacted_thinking", "data": "opaque"},
            {"type": "text", "text": "plan"},
        ]
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


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
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}"

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


def test_model_proxy_openai_mode_transforms_chat_request_and_response():
    def backend_response(_record):
        body = json.dumps(
            {
                "id": "chatcmpl_1",
                "object": "chat.completion",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "done",
                            "reasoning_content": "thinking",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                    "prompt_cache_hit_tokens": 2,
                    "prompt_cache_miss_tokens": 4,
                },
            }
        ).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    backend = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="openai",
            backend_url=f"{backend.url}/v1/chat/completions",
            backend_auth="bearer",
            backend_format="openai-chat",
            backend_models=("deepseek-v4-flash",),
            anthropic_models=(),
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}"

    try:
        raw = _post_json(
            f"{proxy_url}/v1/messages",
            {
                "model": "deepseek-v4-flash[1m]",
                "system": [{"type": "text", "text": "sys"}],
                "max_tokens": 16,
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "work"}]},
                ],
                "tools": [{"name": "Read", "description": "read", "input_schema": {"type": "object"}}],
                "tool_choice": {"type": "tool", "name": "Read"},
            },
            {"authorization": "Bearer oauth-token", "x-api-key": "anthropic-key"},
        )
        payload = json.loads(raw.decode("utf-8"))

        assert backend.records[0]["path"] == "/v1/chat/completions"
        assert backend.records[0]["headers"]["authorization"] == "Bearer backend-key"
        assert "x-api-key" not in backend.records[0]["headers"]
        backend_payload = json.loads(backend.records[0]["body"].decode("utf-8"))
        assert backend_payload["model"] == "deepseek-v4-flash"
        assert backend_payload["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "work"},
        ]
        assert backend_payload["tools"][0]["function"]["name"] == "Read"
        assert backend_payload["tool_choice"] == {"type": "function", "function": {"name": "Read"}}
        assert payload["type"] == "message"
        assert payload["model"] == "deepseek-v4-flash[1m]"
        assert payload["content"] == [
            {"type": "thinking", "thinking": "thinking"},
            {"type": "text", "text": "done"},
        ]
        assert payload["usage"] == {
            "input_tokens": 6,
            "output_tokens": 3,
            "cache_creation_input_tokens": 4,
            "cache_read_input_tokens": 2,
        }
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()


def test_model_proxy_openai_mode_preserves_upstream_rate_limit_response():
    def backend_response(_record):
        body = json.dumps(
            {
                "error": {
                    "type": "rate_limit_error",
                    "message": "OpenCode quota exhausted",
                }
            }
        ).encode("utf-8")
        return 429, {"content-type": "application/json", "retry-after": "120"}, body

    backend = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="openai",
            backend_url=f"{backend.url}/v1/chat/completions",
            backend_auth="bearer",
            backend_format="openai-chat",
            backend_models=("deepseek-v4-flash",),
            anthropic_models=(),
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        with pytest.raises(HTTPError) as exc:
            _post_json(
                f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
                {"model": "deepseek-v4-flash", "messages": []},
            )

        assert exc.value.code == 429
        assert exc.value.headers.get("Retry-After") == "120"
        payload = json.loads(exc.value.read().decode("utf-8"))
        assert payload == {
            "type": "error",
            "error": {
                "type": "rate_limit_error",
                "message": "OpenCode quota exhausted",
            },
        }
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()


def test_model_proxy_openai_mode_adds_kimi_tool_call_reasoning_placeholder():
    def backend_response(_record):
        body = json.dumps(
            {
                "id": "chatcmpl_1",
                "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                "usage": {},
            }
        ).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    backend = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="openai",
            backend_url=f"{backend.url}/v1",
            backend_auth="bearer",
            backend_format="openai-chat",
            backend_models=("kimi-k2.6",),
            anthropic_models=(),
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        _post_json(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
            {
                "model": "kimi-k2.6",
                "messages": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_1",
                                "name": "Read",
                                "input": {"path": "file.py"},
                            }
                        ],
                    }
                ],
            },
        )

        payload = json.loads(backend.records[0]["body"].decode("utf-8"))
        assert payload["messages"][0]["reasoning_content"] == " "
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()


def test_model_proxy_openai_mode_passes_minimax_models_through_anthropic_messages():
    def backend_response(_record):
        body = json.dumps({"type": "message", "content": [], "usage": {"input_tokens": 1, "output_tokens": 2}}).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    backend = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="openai",
            backend_url=f"{backend.url}/v1/chat/completions",
            backend_auth="bearer",
            backend_format="openai-chat",
            backend_models=("deepseek-v4-flash",),
            anthropic_models=(),
            backend_provider_key="opencode-go",
            backend_provider_label="OpenCode Go",
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        raw = _post_json(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
            {
                "model": "anthropic/opencode-go/minimax-m2.5",
                "messages": [{"role": "user", "content": [{"type": "text", "text": "work"}]}],
            },
        )

        assert json.loads(raw.decode("utf-8"))["usage"] == {"input_tokens": 1, "output_tokens": 2}
        assert backend.records[0]["path"] == "/v1/messages"
        assert backend.records[0]["headers"]["authorization"] == "Bearer backend-key"
        payload = json.loads(backend.records[0]["body"].decode("utf-8"))
        assert payload == {
            "model": "minimax-m2.5",
            "messages": [{"role": "user", "content": [{"type": "text", "text": "work"}]}],
        }
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()


def test_model_proxy_openai_mode_transforms_streaming_chat_response():
    def backend_response(_record):
        body = (
            b'data: {"choices":[{"delta":{"reasoning_content":"think"},"finish_reason":null}],"usage":null}\n\n'
            b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":2,"prompt_cache_hit_tokens":60,"prompt_cache_miss_tokens":30}}\n\n'
            b"data: [DONE]\n\n"
        )
        return 200, {"content-type": "text/event-stream"}, body

    backend = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="openai",
            backend_url=f"{backend.url}/v1",
            backend_auth="bearer",
            backend_format="openai-chat",
            backend_models=("deepseek-v4-flash",),
            anthropic_models=(),
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        raw = _post_json(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
            {"model": "deepseek-v4-flash", "messages": [], "stream": True},
        )
        body = raw.decode("utf-8")
        assert "event: message_start" in body
        assert '"type":"thinking_delta","thinking":"think"' in body
        assert '"type":"text_delta","text":"hi"' in body
        assert '"stop_reason":"end_turn"' in body
        assert '"input_tokens":10' in body
        assert '"output_tokens":2' in body
        assert '"cache_creation_input_tokens":30' in body
        assert '"cache_read_input_tokens":60' in body
        backend_payload = json.loads(backend.records[0]["body"].decode("utf-8"))
        assert backend_payload["stream_options"] == {"include_usage": True}
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()


def test_model_proxy_openai_mode_finishes_eof_tool_call_stream_as_tool_use():
    def backend_response(_record):
        body = (
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"toolu_1","function":{"name":"Read","arguments":""}}]}}]}\n\n'
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"path\\":\\"file.py\\"}"}}]}}]}\n\n'
        )
        return 200, {"content-type": "text/event-stream"}, body

    backend = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="openai",
            backend_url=f"{backend.url}/v1",
            backend_auth="bearer",
            backend_format="openai-chat",
            backend_models=("kimi-k2.6",),
            anthropic_models=(),
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        raw = _post_json(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
            {"model": "kimi-k2.6", "messages": [], "stream": True},
        )
        body = raw.decode("utf-8")
        assert '"type":"tool_use","id":"toolu_1","name":"Read","input":{}' in body
        assert '"type":"content_block_stop","index":0' in body
        assert '"stop_reason":"tool_use"' in body
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        backend.close()


def test_model_proxy_lists_configured_and_discovered_models_with_backend_auth():
    def model_list_response(_record):
        body = json.dumps(
            {
                "data": [
                    {"id": "worker-model"},
                    {"id": "deepseek/deepseek-r1"},
                    {"id": "worker-model"},
                ]
            }
        ).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    upstream = _RecordingServer(model_list_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="bearer",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
            backend_provider_key="litellm",
            backend_provider_label="LiteLLM",
            backend_models_url=f"{upstream.url}/v1/models",
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}"

    try:
        status, raw, headers = _request_response(f"{proxy_url}/v1/models")
        payload = json.loads(raw.decode("utf-8"))
        ids = [item["id"] for item in payload["data"]]

        assert status == 200
        assert headers["content-type"] == "application/json"
        assert ids == [
            "claude-opus-4-6",
            "worker-model",
            "anthropic/litellm/worker-model",
            "anthropic/litellm/deepseek/deepseek-r1",
        ]
        assert payload["first_id"] == "claude-opus-4-6"
        assert payload["last_id"] == "anthropic/litellm/deepseek/deepseek-r1"
        assert payload["has_more"] is False
        display = {item["id"]: item["display_name"] for item in payload["data"]}
        assert display["anthropic/litellm/deepseek/deepseek-r1"] == "LiteLLM/deepseek/deepseek-r1"
        assert upstream.records[0]["path"] == "/v1/models"
        assert upstream.records[0]["headers"]["authorization"] == "Bearer backend-key"

        head_status, head_body, head_headers = _request_response(f"{proxy_url}/v1/models", method="HEAD")
        assert head_status == 204
        assert head_body == b""
        assert head_headers["allow"] == "GET, HEAD, OPTIONS"

        options_status, options_body, options_headers = _request_response(f"{proxy_url}/v1/models", method="OPTIONS")
        assert options_status == 204
        assert options_body == b""
        assert options_headers["allow"] == "GET, HEAD, OPTIONS"

        retrieve_status, retrieve_raw, _retrieve_headers = _request_response(
            f"{proxy_url}/v1/models/worker-model?beta=true"
        )
        retrieve_payload = json.loads(retrieve_raw.decode("utf-8"))
        assert retrieve_status == 200
        assert retrieve_payload["id"] == "worker-model"
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_openrouter_discovery_advertises_only_tool_capable_models():
    def model_list_response(_record):
        body = json.dumps(
            {
                "data": [
                    {"id": "meta/llama-3.3", "supported_parameters": ["tools", "stream"]},
                    {"id": "openai/o3-mini", "supported_parameters": ["reasoning"]},
                    {"id": "anthropic/claude-sonnet", "supported_parameters": ["tool_choice"]},
                    {"id": "missing-params"},
                ]
            }
        ).encode("utf-8")
        return 200, {"content-type": "application/json"}, body

    upstream = _RecordingServer(model_list_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="bearer",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
            backend_provider_key="openrouter",
            backend_provider_label="OpenRouter",
            backend_models_url=f"{upstream.url}/v1/models",
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        _status, raw, _headers = _request_response(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/models"
        )
        payload = json.loads(raw.decode("utf-8"))
        assert [item["id"] for item in payload["data"]] == [
            "claude-opus-4-6",
            "worker-model",
            "anthropic/openrouter/meta/llama-3.3",
            "anthropic/openrouter/anthropic/claude-sonnet",
        ]
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_models_endpoint_falls_back_when_discovery_fails():
    def broken_model_list(_record):
        return 200, {"content-type": "application/json"}, b'{"bad": true}'

    upstream = _RecordingServer(broken_model_list)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="x-api-key",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
            backend_provider_key="deepseek",
            backend_provider_label="DeepSeek",
            backend_models_url=f"{upstream.url}/v1/models",
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        _status, raw, _headers = _request_response(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/models"
        )
        payload = json.loads(raw.decode("utf-8"))
        assert [item["id"] for item in payload["data"]] == ["claude-opus-4-6", "worker-model"]
        assert upstream.records[0]["headers"]["x-api-key"] == "backend-key"
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_routes_gateway_backend_model_after_decoding():
    def backend_response(_record):
        return 200, {"content-type": "application/json"}, b'{"type":"message","content":[]}'

    upstream = _RecordingServer(backend_response)
    proxy = start_model_proxy(
        ModelProxyConfig(
            mode="architect",
            backend_url=upstream.url,
            backend_auth="bearer",
            backend_models=("worker-model",),
            anthropic_models=("claude-opus-4-6",),
            anthropic_url=upstream.url,
            backend_provider_key="openrouter",
            backend_provider_label="OpenRouter",
        ),
        api_key="backend-key",
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}"

    try:
        _post_json(
            f"{proxy_url}/v1/messages",
            {"model": "anthropic/openrouter/meta/llama-3.3", "messages": []},
            {"authorization": "Bearer oauth-token"},
        )
        payload = json.loads(upstream.records[0]["body"].decode("utf-8"))
        assert payload["model"] == "meta/llama-3.3"
        assert upstream.records[0]["headers"]["authorization"] == "Bearer backend-key"

        with pytest.raises(HTTPError) as wrong_provider:
            _post_json(
                f"{proxy_url}/v1/messages",
                {"model": "anthropic/deepseek/meta/llama-3.3", "messages": []},
            )
        assert wrong_provider.value.code == 400
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_allows_only_nonce_post_messages_path_and_known_models():
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
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{proxy.server_address[1]}"

    try:
        body = _post_json(
            f"{base_url}/{NONCE}/v1/messages",
            {"model": "worker-model", "messages": []},
        )
        assert json.loads(body.decode("utf-8")) == {}

        with pytest.raises(HTTPError) as wrong_path:
            _post_json(f"{base_url}/v1/messages", {"model": "worker-model", "messages": []})
        assert wrong_path.value.code == 404

        with pytest.raises(HTTPError) as bad_nonce:
            _post_json(f"{base_url}/bad/v1/messages", {"model": "worker-model", "messages": []})
        assert bad_nonce.value.code == 404
        with pytest.raises(HTTPError) as bad_models_nonce:
            _request_response(f"{base_url}/bad/v1/models")
        assert bad_models_nonce.value.code == 404

        for method in ("GET", "HEAD", "PUT", "DELETE", "OPTIONS"):
            with pytest.raises(HTTPError) as wrong_method:
                request = Request(f"{base_url}/{NONCE}/v1/messages", data=b"{}" if method != "GET" else None, method=method)
                urlopen(request, timeout=5)
            assert wrong_method.value.code == 405

        with pytest.raises(HTTPError) as unknown_model:
            _post_json(f"{base_url}/{NONCE}/v1/messages", {"model": "not-allowed", "messages": []})
        assert unknown_model.value.code == 400
        with pytest.raises(HTTPError) as alias_model:
            _post_json(f"{base_url}/{NONCE}/v1/messages", {"model": "anthropic/worker-model", "messages": []})
        assert alias_model.value.code == 400
        assert [record["path"] for record in upstream.records] == ["/v1/messages"]
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
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        request = Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
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
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        with pytest.raises(HTTPError) as exc:
            _post_json(
                f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
                {"model": "worker-model", "messages": []},
            )
        assert exc.value.code == 502
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=2)
        upstream.close()


def test_model_proxy_caps_total_sse_stream_bytes(monkeypatch):
    monkeypatch.setattr("ccsilo.model_proxy.MAX_STREAM_BYTES", 1)

    def backend_response(_record):
        return 200, {"content-type": "text/event-stream"}, b'data: {"type":"message_delta"}\n\n'

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
        auth_nonce=NONCE,
        port=0,
    )
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()

    try:
        raw = _post_json(
            f"http://127.0.0.1:{proxy.server_address[1]}/{NONCE}/v1/messages",
            {"model": "worker-model", "messages": []},
        )
        assert raw == b""
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


class _FakeWfile:
    def __init__(self, *, fail_write=False, fail_flush=False):
        self.written = []
        self.fail_write = fail_write
        self.fail_flush = fail_flush

    def write(self, data):
        if self.fail_write:
            raise BrokenPipeError(32, "broken pipe")
        self.written.append(data)

    def flush(self):
        if self.fail_flush:
            raise ConnectionResetError("connection reset")


def _bare_handler(wfile):
    from ccsilo.model_proxy import _ModelProxyHandler

    handler = object.__new__(_ModelProxyHandler)
    handler.close_connection = False
    handler.wfile = wfile
    return handler


def test_write_client_swallows_disconnect_on_write():
    handler = _bare_handler(_FakeWfile(fail_write=True))

    assert handler._write_client(b"payload") is False
    assert handler.close_connection is True


def test_write_client_swallows_disconnect_on_flush():
    handler = _bare_handler(_FakeWfile(fail_flush=True))

    assert handler._write_client(b"payload", flush=True) is False
    assert handler.close_connection is True


def test_send_json_swallows_disconnect():
    handler = _bare_handler(_FakeWfile(fail_write=True))
    # Stub the header machinery so the failure surfaces at the body write,
    # mirroring a client that closed before the response is flushed.
    handler.send_response = lambda *a, **k: None
    handler.send_header = lambda *a, **k: None
    handler.end_headers = lambda: None

    handler._send_json(502, {"error": {"message": "x"}})

    assert handler.close_connection is True


def test_relay_stream_stops_on_client_disconnect():
    class _FakeResponse:
        def __init__(self, chunks):
            self._chunks = list(chunks)

        def read(self, _size):
            return self._chunks.pop(0) if self._chunks else b""

    class _PassthroughTransformer:
        def feed(self, chunk):
            return [chunk]

        def flush(self):
            return []

    handler = _bare_handler(_FakeWfile(fail_write=True))

    # Must not raise even though the first client write fails.
    handler._relay_stream(_FakeResponse([b"chunk"]), _PassthroughTransformer())

    assert handler.close_connection is True
