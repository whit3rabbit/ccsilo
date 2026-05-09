"""Proxy provider adapter registry."""

import json
from typing import Tuple
from urllib.request import Request, urlopen

from .base import ProxyProviderAdapter
from .litellm import LiteLLMProxyProvider
from .openrouter import OpenRouterProxyProvider


_GENERIC = ProxyProviderAdapter()
_ADAPTERS = {
    LiteLLMProxyProvider.key: LiteLLMProxyProvider(),
    OpenRouterProxyProvider.key: OpenRouterProxyProvider(),
}


def proxy_provider_for_key(provider_key: str) -> ProxyProviderAdapter:
    return _ADAPTERS.get(str(provider_key or ""), _GENERIC)


def fetch_provider_model_ids(
    *,
    provider_key: str,
    models_url: str,
    backend_auth: str,
    api_key: str,
    timeout: float,
    max_response_bytes: int,
) -> Tuple[str, ...]:
    adapter = proxy_provider_for_key(provider_key)
    request = Request(
        models_url,
        headers=adapter.model_list_headers(backend_auth, api_key),
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(max_response_bytes + 1)
    if len(raw) > max_response_bytes:
        return ()
    payload = json.loads(raw.decode("utf-8"))
    return adapter.parse_model_ids(payload)
