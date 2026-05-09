"""Model alias updates for existing variants."""

from typing import Dict

from .._utils import utc_now as _utc_now
from ..providers import get_provider
from ..providers.schema import MODEL_ENV_KEYS
from ..workspace import write_json
from .constants import VARIANT_METADATA
from .model import Variant, validate_variant_manifest
from .tweaks import (
    CURATED_TWEAK_IDS,
    GATEWAY_MODEL_DISCOVERY_TWEAK_ID,
    sync_tweak_env,
)
from .wrapper import write_wrapper as _write_wrapper

import sys as _sys


def _variants():
    return _sys.modules["ccsilo.variants"]


def _proxy(name):
    def call(*args, **kwargs):
        return getattr(_variants(), name)(*args, **kwargs)
    return call

__all__ = ['update_variant_models', '_normalize_model_overrides', '_model_env_for_existing_setup', '_sync_existing_compatibility_model_defaults', '_validate_existing_model_mapping']

def update_variant_models(
    variant_id: str,
    model_overrides: Dict[str, str],
    *,
    root=None,
) -> Variant:
    """Update saved model aliases for an existing setup without rebuilding it."""
    variant = _variants().load_variant(_variants().variant_id_from_name(variant_id), root=root)
    manifest = dict(variant.manifest)
    provider_key = str((manifest.get("provider") or {}).get("key") or "")
    provider = get_provider(provider_key)
    normalized = _normalize_model_overrides(model_overrides or {})
    env = _model_env_for_existing_setup(manifest.get("env", {}), provider.models, normalized)
    _validate_existing_model_mapping(provider, env)

    manifest["modelOverrides"] = normalized
    if isinstance(manifest.get("modelProxy"), dict):
        manifest["tweaks"] = _model_proxy_tweak_ids(manifest.get("tweaks", []))
    manifest["env"] = sync_tweak_env(
        env,
        manifest.get("tweaks", []),
        manifest.get("tweakOptions", {}),
    )
    manifest["updatedAt"] = _utc_now()
    validate_variant_manifest(manifest)
    _write_wrapper(manifest)
    write_json(variant.path / VARIANT_METADATA, manifest)
    return _variants().load_variant(variant.variant_id, root=root)

def _normalize_model_overrides(model_overrides: Dict[str, str]) -> Dict[str, str]:
    valid_keys = set(MODEL_ENV_KEYS)
    normalized = {}
    for key, value in model_overrides.items():
        if key not in valid_keys:
            continue
        text = str(value or "").strip()
        if text:
            normalized[key] = text
    return normalized

def _model_env_for_existing_setup(env: Dict[str, str], provider_models: Dict[str, str], model_overrides: Dict[str, str]) -> Dict[str, str]:
    model_env_keys = set(MODEL_ENV_KEYS.values())
    result = {
        key: str(value)
        for key, value in (env or {}).items()
        if key not in model_env_keys
    }
    for model_key, model_value in provider_models.items():
        if model_value:
            result[MODEL_ENV_KEYS[model_key]] = str(model_value)
    for model_key, model_value in model_overrides.items():
        result[MODEL_ENV_KEYS[model_key]] = model_value
    _sync_existing_compatibility_model_defaults(result, model_overrides)
    return result

def _sync_existing_compatibility_model_defaults(env: Dict[str, str], overrides: Dict[str, str]) -> None:
    if not str(overrides.get("default") or "").strip() and env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"):
        env["ANTHROPIC_MODEL"] = env["ANTHROPIC_DEFAULT_OPUS_MODEL"]
    if not str(overrides.get("small_fast") or "").strip() and env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        env["ANTHROPIC_SMALL_FAST_MODEL"] = env["ANTHROPIC_DEFAULT_HAIKU_MODEL"]

def _validate_existing_model_mapping(provider, env: Dict[str, str]) -> None:
    if not provider.requires_model_mapping:
        return
    missing = [
        name
        for name in (
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        )
        if not env.get(name)
    ]
    if missing:
        raise ValueError(f"{provider.label} requires model mapping for {', '.join(missing)}")


def _model_proxy_tweak_ids(tweak_ids):
    result = [str(tweak_id) for tweak_id in (tweak_ids or []) if str(tweak_id)]
    if GATEWAY_MODEL_DISCOVERY_TWEAK_ID not in result:
        result.append(GATEWAY_MODEL_DISCOVERY_TWEAK_ID)
    return sorted(result, key=_tweak_sort_index)


def _tweak_sort_index(tweak_id: str) -> int:
    try:
        return CURATED_TWEAK_IDS.index(tweak_id)
    except ValueError:
        return len(CURATED_TWEAK_IDS)
