"""Variant-tab action helpers (no monkey-patched dependencies)."""

from urllib.parse import urlparse

from ..providers import normalize_mcp_ids, provider_default_variant_name
from ..variant_tweaks import CURATED_TWEAK_IDS, DEFAULT_TWEAK_IDS, default_tweak_ids_for_provider
from ._const import VARIANT_MODEL_FIELDS, VARIANT_STEPS
from .options import (
    selected_variant_provider,
    variant_model_display_value,
)


def advance_variant(state):
    state.variant_step = min(state.variant_step + 1, len(VARIANT_STEPS) - 1)
    state.selected_index = 0


def reset_variant(state):
    state.variant_step = 0
    state.selected_index = 0
    state.variant_name = ""
    state.variant_claude_version = "latest"
    state.variant_base_url = ""
    state.variant_credential_env = ""
    state.variant_api_key = ""
    state.variant_store_secret = False
    state.variant_model_overrides = {}
    state.variant_model_choices = []
    state.variant_install_command = False
    state.variant_install_choice_initialized = False
    state.selected_variant_mcp_ids = []
    state.selected_variant_tweaks = list(DEFAULT_TWEAK_IDS)
    state.tweak_filter = "recommended"


def set_variant_provider_defaults(state, provider):
    state.variant_name = provider_default_variant_name(provider["key"]) if provider else ""
    state.variant_base_url = str(provider.get("baseUrl") or "") if provider else ""
    state.variant_credential_env = str(provider.get("credentialEnv") or "") if provider else ""
    state.variant_api_key = ""
    state.variant_store_secret = False
    state.variant_model_overrides = {}
    state.variant_model_choices = []
    state.variant_install_command = False
    state.variant_install_choice_initialized = False
    state.selected_variant_mcp_ids = []
    provider_key = str(provider.get("key") or "") if provider else ""
    state.selected_variant_tweaks = default_tweak_ids_for_provider(provider_key)


def toggle_variant_tweak(state, tweak_id: str):
    if tweak_id in state.selected_variant_tweaks:
        state.selected_variant_tweaks.remove(tweak_id)
    else:
        state.selected_variant_tweaks.append(tweak_id)
        state.selected_variant_tweaks.sort(key=lambda item: CURATED_TWEAK_IDS.index(item))


def toggle_variant_mcp(state, mcp_id: str):
    if mcp_id in state.selected_variant_mcp_ids:
        state.selected_variant_mcp_ids.remove(mcp_id)
        return
    state.selected_variant_mcp_ids.append(mcp_id)
    state.selected_variant_mcp_ids = normalize_mcp_ids(state.selected_variant_mcp_ids)


def require_variant_model_mapping(state) -> bool:
    provider = selected_variant_provider(state)
    if not provider or not provider.get("requiresModelMapping"):
        return True
    missing = [
        label
        for key, label in VARIANT_MODEL_FIELDS[:3]
        if not variant_model_display_value(state, provider, key)
    ]
    if missing:
        state.message = f"Set model aliases for: {', '.join(missing)}"
        return False
    return True


def variant_credential_env_for_create(state, provider):
    if state.variant_store_secret:
        return None
    value = state.variant_credential_env.strip()
    if not value:
        return None
    if (
        provider.get("credentialOptional")
        and value == provider.get("credentialEnv")
        and provider.get("authTokenFallback")
    ):
        return None
    if provider.get("authMode") == "none":
        return None
    return value


def variant_base_url_for_create(state, provider):
    if not provider or provider.get("authMode") == "none":
        return None
    value = state.variant_base_url.strip()
    return value or None


def variant_api_key_for_create(state):
    if not state.variant_store_secret:
        return None
    return state.variant_api_key.strip() or None


def variant_store_secret_for_create(state):
    return bool(state.variant_store_secret)


def variant_model_overrides_for_create(state):
    return {
        key: value.strip()
        for key, value in state.variant_model_overrides.items()
        if value.strip()
    }


def toggle_variant_store_secret(state):
    state.variant_store_secret = not state.variant_store_secret
    if not state.variant_store_secret:
        state.variant_api_key = ""


def apply_variant_model_choice(state, model_id: str):
    value = model_id.strip()
    if not value:
        return
    for key, _label in VARIANT_MODEL_FIELDS:
        state.variant_model_overrides[key] = value
    state.message = f"Model aliases set to {value}"


def validate_variant_endpoint(state, provider) -> bool:
    if not provider or provider.get("authMode") == "none":
        return True
    value = state.variant_base_url.strip()
    if not value:
        state.message = "Endpoint is required for this provider."
        return False
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        state.message = "Endpoint must be an http:// or https:// URL."
        return False
    return True


def validate_variant_secret(state) -> bool:
    if state.variant_store_secret and not state.variant_api_key.strip():
        state.message = "Enter an API key or turn off local secret storage."
        return False
    return True
