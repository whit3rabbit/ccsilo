"""OpenRouter-specific model-list behavior for the local model proxy."""

from typing import Any, Mapping, Sequence, Tuple

from .base import ProxyProviderAdapter, append_unique


class OpenRouterProxyProvider(ProxyProviderAdapter):
    key = "openrouter"

    def parse_model_ids(self, payload: Any) -> Tuple[str, ...]:
        data = _field(payload, "data")
        if not _is_sequence(data):
            raise RuntimeError("OpenRouter model list response did not contain data")
        model_ids = []
        for item in data:
            model_id = _field(item, "id")
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            supported_parameters = _field(item, "supported_parameters")
            if not _is_sequence(supported_parameters):
                continue
            parameter_names = {param for param in supported_parameters if isinstance(param, str)}
            if parameter_names.isdisjoint({"tools", "tool_choice"}):
                continue
            append_unique(model_ids, model_id)
        return tuple(model_ids)


def _field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
