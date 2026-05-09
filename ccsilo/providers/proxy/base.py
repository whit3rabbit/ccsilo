"""Provider-aware helpers for the local Architect model proxy."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..model_discovery import parse_model_ids


GATEWAY_MODEL_PREFIX = "anthropic"


@dataclass(frozen=True)
class DecodedGatewayModelId:
    provider_key: str
    provider_model: str


class ProxyProviderAdapter:
    """Provider-specific model-list behavior for the stdlib model proxy."""

    key = "generic"

    def model_list_headers(self, backend_auth: str, api_key: str) -> Dict[str, str]:
        headers = {
            "User-Agent": "ccsilo-model-proxy",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if api_key:
            if backend_auth == "bearer":
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                headers["x-api-key"] = api_key
        return headers

    def parse_model_ids(self, payload: Any) -> Tuple[str, ...]:
        return tuple(parse_model_ids(payload))

    def display_name(self, provider_label: str, provider_key: str, provider_model: str) -> str:
        label = provider_label or provider_key
        return f"{label}/{provider_model}" if label else provider_model


def validate_gateway_provider_key(provider_key: str) -> None:
    if not provider_key or "/" in provider_key or "\\" in provider_key or provider_key in {".", ".."}:
        raise ValueError("model proxy backendProviderKey must be a single path segment")


def gateway_model_id(provider_key: str, provider_model: str) -> str:
    return f"{GATEWAY_MODEL_PREFIX}/{provider_key}/{provider_model}"


def decode_gateway_model_id(model_name: str, *, expected_provider_key: str = "") -> Optional[DecodedGatewayModelId]:
    prefix, separator, remainder = str(model_name or "").partition("/")
    if prefix != GATEWAY_MODEL_PREFIX or not separator:
        return None
    provider_key, provider_separator, provider_model = remainder.partition("/")
    if not provider_separator or not provider_model:
        return None
    if expected_provider_key and provider_key != expected_provider_key:
        return None
    return DecodedGatewayModelId(provider_key=provider_key, provider_model=provider_model)


def append_unique(model_ids: List[str], model_id: str) -> None:
    model_id = str(model_id or "").strip()
    if model_id and model_id not in model_ids:
        model_ids.append(model_id)
