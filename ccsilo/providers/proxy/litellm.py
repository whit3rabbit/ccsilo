"""LiteLLM-specific model-list behavior for the local model proxy."""

from .base import ProxyProviderAdapter


class LiteLLMProxyProvider(ProxyProviderAdapter):
    key = "litellm"
