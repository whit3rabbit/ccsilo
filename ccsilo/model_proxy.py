"""Local model proxy for Claude Code provider setups.

``architect`` mode requires a Claude Code account: Claude model requests still
rely on the user's normal Claude Code OAuth/session path, while non-Claude model
requests are forwarded to the configured backend provider credential.

``openai`` mode is backend-only. It converts Anthropic Messages requests from
Claude Code into OpenAI-compatible chat completions requests and converts the
responses back.
"""

import argparse
import codecs
import http.client
import json
import os
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urlsplit

from .providers.proxy import (
    decode_gateway_model_id,
    fetch_provider_model_ids,
    gateway_model_id,
    proxy_provider_for_key,
    validate_gateway_provider_key,
)


ANTHROPIC_FALLBACK = "https://api.anthropic.com"
MODEL_PROXY_MODES = {"architect", "openai"}
BACKEND_FORMAT_ANTHROPIC = "anthropic"
BACKEND_FORMAT_OPENAI_CHAT = "openai-chat"
BACKEND_FORMATS = {BACKEND_FORMAT_ANTHROPIC, BACKEND_FORMAT_OPENAI_CHAT}
MESSAGES_PATH = "/v1/messages"
MODELS_PATH = "/v1/models"
OPENAI_CHAT_COMPLETIONS_PATH = "/chat/completions"
DISCOVERED_MODEL_CREATED_AT = "1970-01-01T00:00:00Z"
MIN_AUTH_NONCE_CHARS = 24
DEFAULT_REQUEST_TIMEOUT_MS = 600_000
MAX_REQUEST_TIMEOUT_MS = 24 * 60 * 60 * 1000
MAX_REQUEST_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_SSE_EVENT_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 256 * 1024 * 1024
MAX_STREAM_SECONDS = 60 * 60
MAX_IDLE_SECONDS = 5 * 60
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


@dataclass(frozen=True)
class ModelProxyConfig:
    mode: str
    backend_url: str
    backend_auth: str
    backend_models: Tuple[str, ...]
    anthropic_models: Tuple[str, ...]
    anthropic_url: str = ANTHROPIC_FALLBACK
    timeout_ms: int = DEFAULT_REQUEST_TIMEOUT_MS
    backend_provider_key: str = ""
    backend_provider_label: str = ""
    backend_models_url: str = ""
    backend_format: str = BACKEND_FORMAT_ANTHROPIC


class ModelProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler, *, config: ModelProxyConfig, api_key: str, auth_nonce: str):
        super().__init__(server_address, handler)
        self.config = config
        self.api_key = api_key
        self.auth_nonce = auth_nonce
        self.had_backend_session = False
        self.state_lock = threading.Lock()


def load_config(path: os.PathLike) -> ModelProxyConfig:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("model proxy config must be a JSON object")
    config = ModelProxyConfig(
        mode=str(payload.get("mode") or ""),
        backend_url=str(payload.get("backendUrl") or payload.get("backend_url") or ""),
        backend_auth=str(payload.get("backendAuth") or payload.get("backend_auth") or ""),
        backend_models=_model_list(payload.get("backendModels") or payload.get("backend_models")),
        anthropic_models=_model_list(payload.get("anthropicModels") or payload.get("anthropic_models")),
        anthropic_url=str(payload.get("anthropicUrl") or payload.get("anthropic_url") or ANTHROPIC_FALLBACK),
        timeout_ms=_timeout_ms(payload.get("timeoutMs", payload.get("timeout_ms"))),
        backend_provider_key=str(payload.get("backendProviderKey") or payload.get("backend_provider_key") or "").strip(),
        backend_provider_label=str(payload.get("backendProviderLabel") or payload.get("backend_provider_label") or "").strip(),
        backend_models_url=str(payload.get("backendModelsUrl") or payload.get("backend_models_url") or "").strip(),
        backend_format=str(
            payload.get("backendFormat")
            or payload.get("backend_format")
            or BACKEND_FORMAT_ANTHROPIC
        ).strip(),
    )
    validate_config(config)
    return config


def _model_list(value) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return tuple(out)


def _timeout_ms(value) -> int:
    if value in (None, ""):
        return DEFAULT_REQUEST_TIMEOUT_MS
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        raise ValueError("model proxy timeoutMs must be an integer number of milliseconds") from None
    if timeout < 1:
        raise ValueError("model proxy timeoutMs must be positive")
    if timeout > MAX_REQUEST_TIMEOUT_MS:
        raise ValueError("model proxy timeoutMs exceeds maximum allowed timeout")
    return timeout


def validate_config(config: ModelProxyConfig) -> None:
    if config.mode not in MODEL_PROXY_MODES:
        raise ValueError("model proxy mode must be architect or openai")
    if config.backend_format not in BACKEND_FORMATS:
        raise ValueError("model proxy backendFormat must be anthropic or openai-chat")
    if config.mode == "openai" and config.backend_format != BACKEND_FORMAT_OPENAI_CHAT:
        raise ValueError("model proxy openai mode requires backendFormat openai-chat")
    if not config.backend_url:
        raise ValueError("model proxy backend_url is required")
    if config.backend_auth not in {"x-api-key", "bearer"}:
        raise ValueError("model proxy backend_auth must be x-api-key or bearer")
    if not config.backend_models:
        raise ValueError("model proxy backendModels must list at least one backend model")
    if config.mode == "architect" and not config.anthropic_models:
        raise ValueError("model proxy anthropicModels must list at least one claude model")
    overlap = set(config.backend_models) & set(config.anthropic_models)
    if overlap:
        raise ValueError(f"model proxy route maps overlap: {', '.join(sorted(overlap))}")
    for model in config.anthropic_models:
        if not model.startswith("claude-"):
            raise ValueError("model proxy anthropicModels entries must be claude-* model ids")
    for label, value in (("backend_url", config.backend_url), ("anthropic_url", config.anthropic_url)):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"model proxy {label} must be an http(s) URL")
    if config.backend_provider_key:
        validate_gateway_provider_key(config.backend_provider_key)
    if config.backend_models_url:
        if not config.backend_provider_key:
            raise ValueError("model proxy backendModelsUrl requires backendProviderKey")
        parsed = urlsplit(config.backend_models_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("model proxy backendModelsUrl must be an http(s) URL")
    _timeout_ms(config.timeout_ms)


def start_model_proxy(
    config: ModelProxyConfig,
    *,
    api_key: str,
    auth_nonce: str,
    host: str = "127.0.0.1",
    port: int = 0,
) -> ModelProxyServer:
    validate_config(config)
    if not api_key:
        raise ValueError("model proxy api key is required")
    _validate_auth_nonce(auth_nonce)
    return ModelProxyServer((host, port), _ModelProxyHandler, config=config, api_key=api_key, auth_nonce=auth_nonce)


def _validate_auth_nonce(auth_nonce: str) -> None:
    if not auth_nonce or len(auth_nonce) < MIN_AUTH_NONCE_CHARS:
        raise ValueError("model proxy auth nonce is missing or too short")
    if "/" in auth_nonce or "\\" in auth_nonce or auth_nonce in {".", ".."}:
        raise ValueError("model proxy auth nonce must be a single path segment")


def strip_all_thinking_blocks(body: Dict) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        message["content"] = [
            block
            for block in message["content"]
            if not (isinstance(block, dict) and block.get("type") == "thinking")
        ]


def strip_unsigned_thinking_blocks(body: Dict) -> None:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("content"), list):
            continue
        message["content"] = [
            block
            for block in message["content"]
            if not (
                isinstance(block, dict)
                and block.get("type") == "thinking"
                and not block.get("signature")
            )
        ]


def normalize_json_body(data: bytes) -> bytes:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data
    if isinstance(payload, dict) and payload.get("type") == "message" and not payload.get("usage"):
        payload["usage"] = {"input_tokens": 0, "output_tokens": 0}
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return data


def anthropic_to_openai_chat_body(body: Dict[str, Any], backend_model: str) -> bytes:
    messages = _openai_messages_from_anthropic(body, backend_model)
    payload: Dict[str, Any] = {
        "model": backend_model,
        "messages": messages,
    }
    for source, target in (
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("max_tokens", "max_tokens"),
    ):
        if source in body:
            payload[target] = body[source]
    if "stop_sequences" in body:
        payload["stop"] = body["stop_sequences"]
    if "stream" in body:
        payload["stream"] = body["stream"]
        if body.get("stream") is True:
            payload["stream_options"] = {"include_usage": True}
    if isinstance(body.get("tools"), list) and body["tools"]:
        payload["tools"] = [_openai_tool(tool) for tool in body["tools"] if isinstance(tool, dict)]
    tool_choice = _openai_tool_choice(body.get("tool_choice"))
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    _apply_openai_thinking(body, backend_model, payload)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def openai_chat_json_to_anthropic(data: bytes, original_model: str) -> bytes:
    payload = json.loads(data.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("OpenAI chat response must be a JSON object")
    choices = payload.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    if not isinstance(message, dict):
        message = {}
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    cache_read = _int_value(usage.get("prompt_cache_hit_tokens"))
    cache_write = _int_value(usage.get("prompt_cache_miss_tokens"))
    input_tokens = max(0, _int_value(usage.get("prompt_tokens")) - cache_read - cache_write)
    output = {
        "id": str(payload.get("id") or f"msg_{int(time.time() * 1000)}"),
        "type": "message",
        "role": "assistant",
        "content": _anthropic_content_from_openai_message(message),
        "model": original_model,
        "stop_reason": _anthropic_stop_reason(choice.get("finish_reason") if isinstance(choice, dict) else None),
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": _int_value(usage.get("completion_tokens")),
            "cache_creation_input_tokens": cache_write,
            "cache_read_input_tokens": cache_read,
        },
    }
    return json.dumps(output, separators=(",", ":")).encode("utf-8")


def _openai_messages_from_anthropic(body: Dict[str, Any], backend_model: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    system_text = _anthropic_system_text(body.get("system"))
    if system_text:
        messages.append({"role": "system", "content": system_text})
    anthropic_messages = body.get("messages")
    if not isinstance(anthropic_messages, list):
        return messages
    has_thinking = _has_thinking_blocks(anthropic_messages)
    for message in anthropic_messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        blocks = _anthropic_content_blocks(message.get("content"))
        if role == "user":
            messages.extend(_openai_user_messages(blocks))
        elif role == "assistant":
            messages.append(_openai_assistant_message(blocks, backend_model, has_thinking))
        else:
            text = "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
            messages.append({"role": role or "user", "content": text})
    return messages


def _openai_user_messages(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block_type == "tool_result":
            messages.append(
                {
                    "role": "tool",
                    "content": _anthropic_tool_result_text(block),
                    "tool_call_id": str(block.get("tool_use_id") or block.get("id") or ""),
                }
            )
        elif block_type == "image":
            text_parts.append("[Image]")
    if text_parts:
        messages.append({"role": "user", "content": "".join(text_parts)})
    return messages


def _openai_assistant_message(blocks: List[Dict[str, Any]], backend_model: str, has_thinking: bool) -> Dict[str, Any]:
    text_parts: List[str] = []
    thinking_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block_type == "thinking" and block.get("thinking"):
            thinking_parts.append(str(block.get("thinking")))
        elif block_type == "tool_use":
            if block.get("thinking"):
                thinking_parts.append(str(block.get("thinking")))
            tool_calls.append(
                {
                    "id": str(block.get("id") or f"toolu_{len(tool_calls)}"),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name") or ""),
                        "arguments": _json_string(block.get("input"), default="{}"),
                    },
                }
            )
    message: Dict[str, Any] = {"role": "assistant", "content": "".join(text_parts)}
    if tool_calls:
        message["tool_calls"] = tool_calls
    reasoning_content = "".join(thinking_parts)
    if reasoning_content:
        message["reasoning_content"] = reasoning_content
    elif has_thinking and _is_deepseek_model(backend_model):
        message["reasoning_content"] = " "
    return message


def _anthropic_system_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(
            str(block.get("text") or "")
            for block in value
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _anthropic_content_blocks(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, list):
        return [block for block in value if isinstance(block, dict)]
    return []


def _anthropic_tool_result_text(block: Dict[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    output = block.get("output")
    if isinstance(output, str):
        return output
    if output is not None:
        return _json_string(output, default="")
    return ""


def _openai_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": str(tool.get("name") or ""),
            "description": str(tool.get("description") or ""),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


def _openai_tool_choice(value: Any) -> Any:
    if not isinstance(value, dict):
        return None
    choice_type = value.get("type")
    if choice_type == "auto":
        return "auto"
    if choice_type == "any":
        return "required"
    if choice_type == "tool" and value.get("name"):
        return {"type": "function", "function": {"name": str(value["name"])}}
    return None


def _apply_openai_thinking(source: Dict[str, Any], backend_model: str, target: Dict[str, Any]) -> None:
    if not _is_deepseek_model(backend_model):
        return
    thinking = source.get("thinking")
    if isinstance(thinking, dict):
        target["thinking"] = thinking
        if thinking.get("type") != "disabled":
            effort = _budget_tokens_to_effort(thinking.get("budget_tokens"))
            if effort:
                target["reasoning_effort"] = effort
        return
    messages = source.get("messages")
    if isinstance(messages, list) and _has_assistant_messages(messages) and not _has_thinking_blocks(messages):
        target["thinking"] = {"type": "disabled"}


def _has_assistant_messages(messages: List[Any]) -> bool:
    return any(isinstance(message, dict) and message.get("role") == "assistant" for message in messages)


def _has_thinking_blocks(messages: List[Any]) -> bool:
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for block in _anthropic_content_blocks(message.get("content")):
            if block.get("type") == "thinking":
                return True
            if block.get("type") == "tool_use" and block.get("thinking"):
                return True
    return False


def _budget_tokens_to_effort(value: Any) -> str:
    budget = _int_value(value)
    if budget <= 0:
        return ""
    if budget <= 2048:
        return "low"
    if budget <= 8192:
        return "medium"
    if budget <= 32768:
        return "high"
    return "max"


def _anthropic_content_from_openai_message(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        blocks.append({"type": "thinking", "thinking": reasoning})
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            blocks.append(
                {
                    "type": "tool_use",
                    "id": str(call.get("id") or f"toolu_{len(blocks)}"),
                    "name": str(function.get("name") or ""),
                    "input": _json_object(function.get("arguments")),
                }
            )
    content = message.get("content")
    if isinstance(content, str) and content:
        blocks.append({"type": "text", "text": content})
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return blocks


def _anthropic_stop_reason(reason: Any) -> str:
    if reason in {"tool_calls", "tool_use"}:
        return "tool_use"
    if reason == "length":
        return "max_tokens"
    return "end_turn"


def _json_object(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _json_string(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, separators=(",", ":"))
    except TypeError:
        return default


def _is_deepseek_model(model: str) -> bool:
    return str(model or "").startswith("deepseek-")


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def backend_model_for_request(config: ModelProxyConfig, model: str) -> str:
    if model in config.backend_models:
        return model
    stripped = _strip_context_suffix(model)
    if stripped != model and stripped in config.backend_models:
        return stripped
    provider_model = _decode_gateway_model(config, model)
    return _strip_context_suffix(provider_model) if provider_model else ""


def _strip_context_suffix(model: str) -> str:
    text = str(model or "").strip()
    return text[:-4] if text.lower().endswith("[1m]") else text


def _decode_gateway_model(config: ModelProxyConfig, model: str) -> str:
    if not config.backend_provider_key:
        return ""
    decoded = decode_gateway_model_id(model, expected_provider_key=config.backend_provider_key)
    return decoded.provider_model if decoded else ""


def build_models_payload(config: ModelProxyConfig, api_key: str) -> Dict[str, object]:
    model_ids = advertised_model_ids(config, api_key)
    data = [_model_response(model_id, config) for model_id in model_ids]
    return {
        "data": data,
        "first_id": model_ids[0] if model_ids else None,
        "has_more": False,
        "last_id": model_ids[-1] if model_ids else None,
    }


def advertised_model_ids(config: ModelProxyConfig, api_key: str) -> List[str]:
    model_ids: List[str] = []
    for model in (*config.anthropic_models, *config.backend_models):
        _append_unique(model_ids, model)
    if not config.backend_provider_key or not config.backend_models_url:
        return model_ids
    for model in _fetch_backend_model_ids(config, api_key):
        _append_unique(model_ids, gateway_model_id(config.backend_provider_key, model))
    return model_ids


def _model_response(model_id: str, config: ModelProxyConfig) -> Dict[str, object]:
    display_name = model_id
    decoded = _decode_gateway_model(config, model_id)
    if decoded:
        adapter = proxy_provider_for_key(config.backend_provider_key)
        display_name = adapter.display_name(config.backend_provider_label, config.backend_provider_key, decoded)
    return {
        "id": model_id,
        "type": "model",
        "display_name": display_name,
        "created_at": DISCOVERED_MODEL_CREATED_AT,
    }


def _append_unique(model_ids: List[str], model_id: str) -> None:
    model_id = str(model_id or "").strip()
    if model_id and model_id not in model_ids:
        model_ids.append(model_id)


def _fetch_backend_model_ids(config: ModelProxyConfig, api_key: str) -> Tuple[str, ...]:
    try:
        return fetch_provider_model_ids(
            provider_key=config.backend_provider_key,
            models_url=config.backend_models_url,
            backend_auth=config.backend_auth,
            api_key=api_key,
            timeout=min(config.timeout_ms / 1000, MAX_IDLE_SECONDS),
            max_response_bytes=MAX_RESPONSE_BYTES,
        )
    except Exception:
        return ()


class SseUsageNormalizer:
    def __init__(self, *, max_event_bytes: int = MAX_SSE_EVENT_BYTES):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending_line = ""
        self.event_lines = []
        self.max_event_bytes = max_event_bytes

    def feed(self, chunk: bytes) -> Iterable[bytes]:
        yield from self._feed_text(self.decoder.decode(chunk), final=False)

    def flush(self) -> Iterable[bytes]:
        yield from self._feed_text(self.decoder.decode(b"", final=True), final=True)
        if self.pending_line:
            self.event_lines.append(self.pending_line)
            self.pending_line = ""
        if self.event_lines:
            yield self._emit_event()

    def _feed_text(self, text: str, *, final: bool) -> Iterable[bytes]:
        self.pending_line += text.replace("\r\n", "\n").replace("\r", "\n")
        lines = self.pending_line.split("\n")
        self.pending_line = lines.pop()
        for line in lines:
            if line == "":
                if self.event_lines:
                    yield self._emit_event()
            else:
                self.event_lines.append(line)
                self._check_event_size()
        if final and self.pending_line:
            self._check_event_size(include_pending=True)
        else:
            self._check_event_size(include_pending=True)

    def _check_event_size(self, *, include_pending: bool = False) -> None:
        parts = list(self.event_lines)
        if include_pending and self.pending_line:
            parts.append(self.pending_line)
        if not parts:
            return
        if len("\n".join(parts).encode("utf-8")) > self.max_event_bytes:
            raise ValueError("upstream SSE event exceeded model proxy size limit")

    def _emit_event(self) -> bytes:
        lines = self._fix_event_lines(self.event_lines)
        self.event_lines = []
        return ("\n".join(lines) + "\n\n").encode("utf-8")

    def _fix_event_lines(self, lines):
        data_values = []
        for line in lines:
            field, value = _sse_field(line)
            if field == "data":
                data_values.append(value)
        if not data_values:
            return lines
        raw = "\n".join(data_values)
        if raw.strip() == "[DONE]":
            return lines
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return lines
        if not isinstance(payload, dict):
            return lines
        changed = False
        if payload.get("type") == "message_start" and isinstance(payload.get("message"), dict):
            message = payload["message"]
            if not isinstance(message.get("usage"), dict):
                message["usage"] = {"input_tokens": 0, "output_tokens": 0}
                changed = True
        if payload.get("type") == "message_delta" and not isinstance(payload.get("usage"), dict):
            payload["usage"] = {"output_tokens": 0}
            changed = True
        if not changed:
            return lines
        fixed = json.dumps(payload, separators=(",", ":"))
        out = []
        replaced = False
        for line in lines:
            field, _value = _sse_field(line)
            if field != "data":
                out.append(line)
            elif not replaced:
                out.append(f"data: {fixed}")
                replaced = True
        return out


class _ProxyHttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class _ModelProxyHandler(BaseHTTPRequestHandler):
    server: ModelProxyServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # pragma: no cover - keeps wrapper logs quiet
        return

    def do_GET(self):
        if self._try_probe(MODELS_PATH, allow="GET, HEAD, OPTIONS", status=200, body=True):
            return
        if self._try_model_retrieve(body=True):
            return
        self._reject_method_or_path()

    def do_HEAD(self):
        if self._try_probe(MODELS_PATH, allow="GET, HEAD, OPTIONS", status=204):
            return
        if self._try_model_retrieve(status=204):
            return
        self._reject_method_or_path()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._reject_method_or_path()

    def do_PATCH(self):
        self._reject_method_or_path()

    def do_DELETE(self):
        self._reject_method_or_path()

    def do_OPTIONS(self):
        if self._try_probe(MODELS_PATH, allow="GET, HEAD, OPTIONS", status=204):
            return
        if self._try_model_retrieve(status=204):
            return
        self._reject_method_or_path()

    def _proxy(self) -> None:
        try:
            client_path = self._authorized_client_path()
            body = self._read_body()
            target_url, use_backend, body, original_model = self._prepare_target(body)
            self._forward(target_url, use_backend, body, client_path, original_model)
        except _ProxyHttpError as exc:
            self._send_json(exc.status, {"error": {"message": exc.message}})
        except Exception as exc:
            self._send_json(502, {"error": {"message": f"model proxy upstream error: {exc}"}})

    def _reject_method_or_path(self) -> None:
        try:
            self._authorized_client_path()
        except _ProxyHttpError as exc:
            self._send_json(exc.status, {"error": {"message": exc.message}})
            return
        self._send_json(405, {"error": {"message": "model proxy only accepts POST /v1/messages"}})

    def _authorized_client_path(self) -> str:
        return self._authorized_client_path_for(MESSAGES_PATH)

    def _authorized_client_path_for(self, endpoint_path: str) -> str:
        parsed = urlsplit(self.path)
        expected = f"/{self.server.auth_nonce}{endpoint_path}"
        if parsed.path != expected:
            self.close_connection = True
            raise _ProxyHttpError(404, "model proxy endpoint not found")
        client_path = endpoint_path
        if parsed.query:
            client_path += "?" + parsed.query
        return client_path

    def _try_probe(self, endpoint_path: str, *, allow: str, status: int, body: bool = False) -> bool:
        try:
            self._authorized_client_path_for(endpoint_path)
        except _ProxyHttpError:
            return False
        if body:
            self._send_json(status, build_models_payload(self.server.config, self.server.api_key))
        else:
            self._send_headers(status, "No Content", {"Allow": allow, "content-length": "0"})
        return True

    def _try_model_retrieve(self, *, status: int = 200, body: bool = False) -> bool:
        try:
            model_id = self._authorized_model_retrieve_path()
        except _ProxyHttpError:
            return False
        model_ids = advertised_model_ids(self.server.config, self.server.api_key)
        if model_id not in model_ids and _strip_context_suffix(model_id) not in model_ids:
            self._send_json(404, {"error": {"message": f"model proxy model not found: {model_id}"}})
            return True
        if body:
            self._send_json(status, _model_response(_strip_context_suffix(model_id), self.server.config))
        else:
            self._send_headers(status, "No Content", {"Allow": "GET, HEAD, OPTIONS", "content-length": "0"})
        return True

    def _authorized_model_retrieve_path(self) -> str:
        parsed = urlsplit(self.path)
        prefix = f"/{self.server.auth_nonce}{MODELS_PATH}/"
        if not parsed.path.startswith(prefix) or parsed.path == prefix:
            raise _ProxyHttpError(404, "model proxy endpoint not found")
        return unquote(parsed.path[len(prefix):])

    def _read_body(self) -> bytes:
        raw_length = self.headers.get("content-length")
        if raw_length is None:
            raise _ProxyHttpError(413, "model proxy requires Content-Length")
        try:
            length = int(raw_length)
        except ValueError:
            raise _ProxyHttpError(413, "model proxy received invalid Content-Length") from None
        if length < 0:
            raise _ProxyHttpError(413, "model proxy received invalid Content-Length")
        if length > MAX_REQUEST_BYTES:
            raise _ProxyHttpError(413, "model proxy request body too large")
        return self.rfile.read(length) if length else b""

    def _prepare_target(self, body: bytes) -> Tuple[str, bool, bytes, str]:
        try:
            parsed_body = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _ProxyHttpError(400, "model proxy request body must be valid JSON") from None
        if not isinstance(parsed_body, dict):
            raise _ProxyHttpError(400, "model proxy request body must be a JSON object")
        model = str(parsed_body.get("model") or "")
        original_model = model
        backend_model = backend_model_for_request(self.server.config, model)
        if backend_model:
            use_backend = True
        elif model in self.server.config.anthropic_models:
            use_backend = False
        else:
            raise _ProxyHttpError(400, f"model proxy model is not in the route map: {model or '(missing)'}")

        if use_backend:
            parsed_body["model"] = backend_model
            if self.server.config.backend_format == BACKEND_FORMAT_OPENAI_CHAT:
                body = anthropic_to_openai_chat_body(parsed_body, backend_model)
            else:
                strip_all_thinking_blocks(parsed_body)
                body = json.dumps(parsed_body, separators=(",", ":")).encode("utf-8")
            with self.server.state_lock:
                self.server.had_backend_session = True
            return self.server.config.backend_url, True, body, original_model

        with self.server.state_lock:
            had_backend_session = self.server.had_backend_session
        if had_backend_session:
            strip_all_thinking_blocks(parsed_body)
        else:
            strip_unsigned_thinking_blocks(parsed_body)
        body = json.dumps(parsed_body, separators=(",", ":")).encode("utf-8")
        return self.server.config.anthropic_url, False, body, original_model

    def _forward(self, target_url: str, use_backend: bool, body: bytes, client_path: str, original_model: str) -> None:
        target = urlsplit(target_url)
        upstream_path = (
            _upstream_path(target.path, OPENAI_CHAT_COMPLETIONS_PATH)
            if use_backend and self.server.config.backend_format == BACKEND_FORMAT_OPENAI_CHAT
            else _upstream_path(target.path, client_path)
        )
        headers = _upstream_headers(self.headers.items(), target.netloc)
        if use_backend:
            headers.pop("authorization", None)
            headers.pop("x-api-key", None)
            if self.server.config.backend_auth == "bearer":
                headers["authorization"] = f"Bearer {self.server.api_key}"
            else:
                headers["x-api-key"] = self.server.api_key
        headers["content-length"] = str(len(body))

        conn_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(target.hostname, target.port, timeout=self.server.config.timeout_ms / 1000)
        try:
            conn.request(self.command, upstream_path, body=body, headers=headers)
            response = conn.getresponse()
            if "text/event-stream" in response.getheader("content-type", "") and conn.sock is not None:
                conn.sock.settimeout(min(self.server.config.timeout_ms / 1000, MAX_IDLE_SECONDS))
            self._relay_response(response, use_backend, body, original_model)
        finally:
            conn.close()

    def _relay_response(
        self,
        response: http.client.HTTPResponse,
        use_backend: bool,
        request_body: bytes,
        original_model: str,
    ) -> None:
        content_type = response.getheader("content-type", "")
        backend_format = self.server.config.backend_format if use_backend else BACKEND_FORMAT_ANTHROPIC
        if backend_format == BACKEND_FORMAT_OPENAI_CHAT and "text/event-stream" in content_type:
            headers = _response_headers(response.getheaders(), omit_content_length=True)
            _set_header(headers, "Content-Type", "text/event-stream")
            _set_header(headers, "Cache-Control", "no-cache")
            _set_header(headers, "Connection", "keep-alive")
            self._send_headers(response.status, response.reason, headers)
            transformer = OpenAIChatSseTransformer(original_model=original_model)
            self._relay_stream(response, transformer)
            return

        if use_backend and "text/event-stream" in content_type:
            headers = _response_headers(response.getheaders(), omit_content_length=True)
            _set_header(headers, "Content-Type", "text/event-stream")
            _set_header(headers, "Cache-Control", "no-cache")
            _set_header(headers, "Connection", "keep-alive")
            self._send_headers(response.status, response.reason, headers)
            normalizer = SseUsageNormalizer()
            self._relay_stream(response, normalizer)
            return

        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise _ProxyHttpError(502, "model proxy upstream response body too large")
        if backend_format == BACKEND_FORMAT_OPENAI_CHAT and "application/json" in content_type:
            raw = openai_chat_json_to_anthropic(raw, original_model or _request_model(request_body))
        elif use_backend and "application/json" in content_type:
            raw = normalize_json_body(raw)
        headers = _response_headers(response.getheaders(), content_length=len(raw))
        self._send_headers(response.status, response.reason, headers)
        self.wfile.write(raw)

    def _relay_stream(self, response: http.client.HTTPResponse, transformer) -> None:
        stream_start = time.monotonic()
        last_chunk = stream_start
        total_streamed = 0
        while True:
            now = time.monotonic()
            if now - stream_start > MAX_STREAM_SECONDS:
                self.close_connection = True
                return
            if now - last_chunk > MAX_IDLE_SECONDS:
                self.close_connection = True
                return
            try:
                chunk = response.read(8192)
            except (OSError, TimeoutError):
                self.close_connection = True
                return
            if not chunk:
                break
            last_chunk = time.monotonic()
            total_streamed += len(chunk)
            if total_streamed > MAX_STREAM_BYTES:
                self.close_connection = True
                return
            try:
                fixed_chunks = tuple(transformer.feed(chunk))
            except ValueError:
                self.close_connection = True
                return
            for fixed in fixed_chunks:
                self.wfile.write(fixed)
                self.wfile.flush()
        try:
            fixed_chunks = tuple(transformer.flush())
        except ValueError:
            self.close_connection = True
            return
        for fixed in fixed_chunks:
            self.wfile.write(fixed)
            self.wfile.flush()
        self.close_connection = True

    def _send_headers(self, status: int, reason: str, headers: Dict[str, str]) -> None:
        self.send_response(status, reason)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()

    def _send_json(self, status: int, payload: Dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _upstream_path(base_path: str, client_path: str) -> str:
    parsed_client = urlsplit(client_path)
    request_path = parsed_client.path or "/"
    base = (base_path or "").rstrip("/")
    if not base:
        full = request_path
    else:
        overlap = ""
        max_len = min(len(base), len(request_path))
        for size in range(1, max_len + 1):
            candidate = request_path[:size]
            if base.endswith(candidate):
                overlap = candidate
        full = base + request_path[len(overlap):] if overlap else base + request_path
    if parsed_client.query:
        full += "?" + parsed_client.query
    return full


def _upstream_headers(items, host: str) -> Dict[str, str]:
    headers = {}
    for key, value in items:
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS:
            continue
        headers[lower] = value
    headers["host"] = host
    headers["accept-encoding"] = "identity"
    return headers


def _response_headers(items, *, content_length: Optional[int] = None, omit_content_length: bool = False) -> Dict[str, str]:
    headers = {}
    for key, value in items:
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS:
            continue
        headers[key] = value
    if omit_content_length:
        headers.pop("content-length", None)
        headers.pop("Content-Length", None)
    elif content_length is not None:
        headers["content-length"] = str(content_length)
    return headers


def _set_header(headers: Dict[str, str], key: str, value: str) -> None:
    for existing in list(headers):
        if existing.lower() == key.lower():
            del headers[existing]
    headers[key] = value


def _sse_field(line: str):
    if line.startswith(":"):
        return None, None
    if ":" not in line:
        return line, ""
    field, value = line.split(":", 1)
    if value.startswith(" "):
        value = value[1:]
        return field, value


class OpenAIChatSseTransformer:
    def __init__(self, *, original_model: str, max_event_bytes: int = MAX_SSE_EVENT_BYTES):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending_line = ""
        self.event_lines: List[str] = []
        self.max_event_bytes = max_event_bytes
        self.original_model = original_model
        self.message_id = f"msg_{int(time.time() * 1000)}"
        self.started = False
        self.closed = False
        self.active_block: Optional[str] = None
        self.active_index: Optional[int] = None
        self.next_index = 0
        self.tool_blocks: Dict[int, int] = {}
        self.usage: Dict[str, int] = {"output_tokens": 0}
        self.finish_reason = "end_turn"

    def feed(self, chunk: bytes) -> Iterable[bytes]:
        yield from self._feed_text(self.decoder.decode(chunk), final=False)

    def flush(self) -> Iterable[bytes]:
        yield from self._feed_text(self.decoder.decode(b"", final=True), final=True)
        if self.pending_line:
            self.event_lines.append(self.pending_line)
            self.pending_line = ""
        if self.event_lines:
            yield from self._emit_event()
        yield from self._finish()

    def _feed_text(self, text: str, *, final: bool) -> Iterable[bytes]:
        self.pending_line += text.replace("\r\n", "\n").replace("\r", "\n")
        lines = self.pending_line.split("\n")
        self.pending_line = lines.pop()
        for line in lines:
            if line == "":
                if self.event_lines:
                    yield from self._emit_event()
            else:
                self.event_lines.append(line)
                self._check_event_size()
        if final and self.pending_line:
            self._check_event_size(include_pending=True)

    def _check_event_size(self, *, include_pending: bool = False) -> None:
        parts = list(self.event_lines)
        if include_pending and self.pending_line:
            parts.append(self.pending_line)
        if parts and len("\n".join(parts).encode("utf-8")) > self.max_event_bytes:
            raise ValueError("upstream SSE event exceeded model proxy size limit")

    def _emit_event(self) -> Iterable[bytes]:
        lines = self.event_lines
        self.event_lines = []
        data_values = []
        for line in lines:
            field, value = _sse_field(line)
            if field == "data":
                data_values.append(value)
        if not data_values:
            return
        raw = "\n".join(data_values)
        if raw.strip() == "[DONE]":
            yield from self._finish()
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        yield from self._events_for_chunk(payload)

    def _events_for_chunk(self, payload: Dict[str, Any]) -> Iterable[bytes]:
        if not self.started:
            self.started = True
            yield _anthropic_sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": self.message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": self.original_model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.usage["output_tokens"] = _int_value(usage.get("completion_tokens"))
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0]
        if not isinstance(choice, dict):
            return
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        if choice.get("finish_reason"):
            self.finish_reason = _anthropic_stop_reason(choice.get("finish_reason"))
        reasoning = delta.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            yield from self._text_like_delta("thinking", reasoning)
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield from self._text_like_delta("text", content)
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if isinstance(call, dict):
                    yield from self._tool_call_delta(call)

    def _text_like_delta(self, block_type: str, text: str) -> Iterable[bytes]:
        if self.active_block and self.active_block != block_type:
            yield from self._stop_active_block()
        if self.active_block is None:
            self.active_block = block_type
            self.active_index = self.next_index
            self.next_index += 1
            content_block = {"type": "text", "text": ""} if block_type == "text" else {"type": "thinking", "thinking": ""}
            yield _anthropic_sse(
                "content_block_start",
                {"type": "content_block_start", "index": self.active_index, "content_block": content_block},
            )
        delta = {"type": "text_delta", "text": text} if block_type == "text" else {"type": "thinking_delta", "thinking": text}
        yield _anthropic_sse(
            "content_block_delta",
            {"type": "content_block_delta", "index": self.active_index, "delta": delta},
        )

    def _tool_call_delta(self, call: Dict[str, Any]) -> Iterable[bytes]:
        yield from self._stop_active_block()
        openai_index = _int_value(call.get("index"))
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        if openai_index not in self.tool_blocks:
            block_index = self.next_index
            self.next_index += 1
            self.tool_blocks[openai_index] = block_index
            yield _anthropic_sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": block_index,
                    "content_block": {
                        "type": "tool_use",
                        "id": str(call.get("id") or f"toolu_{openai_index}"),
                        "name": str(function.get("name") or ""),
                        "input": {},
                    },
                },
            )
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            yield _anthropic_sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": self.tool_blocks[openai_index],
                    "delta": {"type": "input_json_delta", "partial_json": arguments},
                },
            )

    def _stop_active_block(self) -> Iterable[bytes]:
        if self.active_block is None or self.active_index is None:
            return
        yield _anthropic_sse(
            "content_block_stop",
            {"type": "content_block_stop", "index": self.active_index},
        )
        self.active_block = None
        self.active_index = None

    def _finish(self) -> Iterable[bytes]:
        if self.closed:
            return
        if not self.started:
            self.started = True
            yield _anthropic_sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": self.message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": self.original_model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )
        yield from self._stop_active_block()
        for block_index in sorted(self.tool_blocks.values()):
            yield _anthropic_sse(
                "content_block_stop",
                {"type": "content_block_stop", "index": block_index},
            )
        yield _anthropic_sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": self.finish_reason, "stop_sequence": None},
                "usage": self.usage,
            },
        )
        yield _anthropic_sse("message_stop", {"type": "message_stop"})
        self.closed = True


def _anthropic_sse(event: str, payload: Dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _request_model(body: bytes) -> str:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("model") or "")


def _parse_port(value: str) -> int:
    if value in {"", "auto"}:
        return 0
    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("port must be auto or an integer between 1 and 65535")
    return port


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the ccsilo local model proxy",
        epilog=(
            "Architect mode requires a Claude Code account. OpenAI mode is "
            "backend-only and converts Anthropic Messages requests to "
            "OpenAI-compatible chat completions."
        ),
    )
    parser.add_argument("--config", required=True, help="Path to model proxy JSON config")
    parser.add_argument("--port", default="auto", help="Port number or auto")
    parser.add_argument("--port-file", required=True, help="File to write the selected port into")
    parser.add_argument("--api-key-env", default="CCSILO_MODEL_PROXY_API_KEY", help="Environment variable containing the backend API key")
    parser.add_argument("--auth-nonce-env", default="CCSILO_MODEL_PROXY_AUTH_NONCE", help="Environment variable containing the local proxy path nonce")
    args = parser.parse_args(list(argv) if argv is not None else None)

    config = load_config(args.config)
    api_key = os.environ.get(args.api_key_env, "")
    auth_nonce = os.environ.get(args.auth_nonce_env, "")
    try:
        _validate_auth_nonce(auth_nonce)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    server = start_model_proxy(config, api_key=api_key, auth_nonce=auth_nonce, port=_parse_port(args.port))
    port = int(server.server_address[1])
    port_file = Path(args.port_file)
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(f"{port}\n", encoding="utf-8")
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.05)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
