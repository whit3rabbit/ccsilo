"""Shared variant lifecycle constants."""

from .tweaks import (
    ENV_TWEAK_IDS,
    PROMPT_ONLY_TWEAK_IDS,
    SETUP_CONFIG_TWEAK_IDS,
    SETUP_ENV_ONLY_TWEAK_IDS,
)

VARIANT_METADATA = "variant.json"

_THEME_PROMPT_TWEAKS = ("themes", "prompt-overlays")
_PROMPT_ONLY_TWEAKS = tuple(PROMPT_ONLY_TWEAK_IDS)
_NATIVE_REGEX_TWEAKS = (
    "hide-startup-banner",
    "hide-startup-clawd",
    "suppress-native-installer-warning",
    "suppress-prompt-caching-warning",
    "suppress-model-launch-notice",
    "mid-conversation-system-422-fallback",
    "mcp-non-blocking",
)
_SETUP_ENV_ONLY_TWEAKS = tuple(SETUP_ENV_ONLY_TWEAK_IDS)
_SETUP_CONFIG_TWEAKS = tuple(SETUP_CONFIG_TWEAK_IDS)
_IN_PLACE_TWEAKS = (
    *_THEME_PROMPT_TWEAKS,
    *_NATIVE_REGEX_TWEAKS,
    *_SETUP_ENV_ONLY_TWEAKS,
    *_SETUP_CONFIG_TWEAKS,
    *_PROMPT_ONLY_TWEAKS,
    *ENV_TWEAK_IDS,
)
