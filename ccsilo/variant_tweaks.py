"""Backwards-compatible shim for the legacy ``ccsilo.variant_tweaks``
import path. The implementation lives in :mod:`ccsilo.variants.tweaks`.
"""

from .variants.tweaks import (  # noqa: F401
    CURATED_TWEAK_IDS,
    DASHBOARD_EXCLUDED_TWEAK_IDS,
    DASHBOARD_TWEAK_IDS,
    BOOLEAN_ENV_TWEAKS,
    BOOLEAN_ENV_TWEAK_IDS,
    CUSTOM_MODELS,
    DEFAULT_TWEAK_IDS,
    ENV_TWEAK_IDS,
    GATEWAY_MODEL_DISCOVERY_ENV,
    GATEWAY_MODEL_DISCOVERY_TWEAK_ID,
    MCP_BATCH_SIZE_DEFAULT,
    MCP_BATCH_SIZE_ENV,
    PROMPT_ONLY_TWEAK_IDS,
    RTK_SHELL_PREFIX_TEXT,
    SETUP_ONLY_TWEAK_IDS,
    SETUP_ENV_ONLY_TWEAK_IDS,
    VALUE_ENV_TWEAK_IDS,
    TweakPatchError,
    TweakResult,
    apply_variant_tweaks,
    available_tweaks,
    compose_prompt_overlays,
    default_tweak_ids_for_provider,
    env_for_tweaks,
    normalize_tweak_ids,
    sync_tweak_env,
)
