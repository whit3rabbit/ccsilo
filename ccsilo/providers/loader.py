"""Provider registry loading and env builder."""

import copy
from pathlib import Path
from typing import Dict, List, Optional

from .._utils import read_json_strict, require_env_name
from .schema import (
    MODEL_ENV_KEYS,
    ProviderEnv,
    ProviderSchemaError,
    ProviderTemplate,
    provider_from_json,
)


REGISTRY_DIR = Path(__file__).parent / "registry"


def list_providers() -> List[ProviderTemplate]:
    return sorted(_providers().values(), key=lambda provider: (provider.display_order, provider.label))


def get_provider(key: str) -> ProviderTemplate:
    provider = _providers().get(key)
    if provider is None:
        raise ValueError(f"Unknown provider: {key}")
    return provider


def provider_default_variant_name(provider_key: str) -> str:
    provider = get_provider(provider_key)
    return provider.default_variant_name or provider.key


def build_provider_env(
    provider_key: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    credential_env: Optional[str] = None,
    store_secret: bool = False,
    model_overrides: Optional[Dict[str, str]] = None,
    extra_env: Optional[List[str]] = None,
) -> ProviderEnv:
    provider = get_provider(provider_key)
    env = {key: str(value) for key, value in provider.env.items()}
    secret_env: Dict[str, str] = {}
    credential = {"mode": "none", "targets": []}

    auth_mode = provider.auth_mode
    if auth_mode != "none":
        env.setdefault("DISABLE_AUTOUPDATER", "1")
        env.setdefault("DISABLE_AUTO_MIGRATE_TO_NATIVE", "1")
        env.setdefault("CLAUDE_CODE_ENABLE_PROMPT_SUGGESTION", "1")
        effective_base_url = base_url if base_url is not None else provider.base_url
        if effective_base_url:
            env["ANTHROPIC_BASE_URL"] = effective_base_url

        targets = _credential_targets(provider)
        credential_value = (api_key or "").strip()
        source_env = (credential_env or provider.credential_env or _default_credential_env(provider)).strip()
        if source_env:
            source_env = require_env_name(source_env, label="credential env")

        if credential_value:
            if not store_secret:
                raise ValueError("Pass --store-secret when providing --api-key")
            for target in targets:
                secret_env[target] = credential_value
            credential = {"mode": "stored", "targets": targets}
        elif source_env and not provider.credential_optional:
            credential = {"mode": "env", "source": source_env, "targets": targets}
        elif source_env and provider.credential_optional and credential_env:
            credential = {"mode": "env", "source": source_env, "targets": targets}
        elif provider.credential_optional:
            _apply_auth_token_fallback(provider, env)
            credential = {"mode": "none", "targets": []}
        else:
            raise ValueError(f"{provider.label} requires credentials or a credential env var")

        if provider.requires_empty_api_key:
            env["ANTHROPIC_API_KEY"] = ""
        elif auth_mode == "authToken" and not provider.auth_token_also_sets_api_key:
            env.pop("ANTHROPIC_API_KEY", None)
        if auth_mode != "authToken":
            env.pop("ANTHROPIC_AUTH_TOKEN", None)

    _apply_model_overrides(env, model_overrides or {})
    _sync_compatibility_model_defaults(env, model_overrides or {})
    _validate_model_mapping(provider, env)
    _apply_extra_env(env, extra_env or [])
    return ProviderEnv(env=env, env_unset=list(provider.env_unset), secret_env=secret_env, credential=credential)


def provider_theme(provider_key: str) -> Dict:
    """Return the brand theme dict for a provider.

    If the provider defines a ``palette`` (compact hex colours), it is expanded
    to the full ~60-key colour map via :mod:`ccsilo.providers.palette`.
    Providers that already ship a full ``colors`` dict pass through unchanged.
    """
    from .palette import build_theme_colors

    provider = get_provider(provider_key)
    if provider.theme:
        theme = copy.deepcopy(provider.theme)
        # Expand compact hex palette → full rgb colour map.
        palette = theme.get("palette")
        if palette and isinstance(palette, dict):
            theme["colors"] = build_theme_colors(palette)
            theme.pop("palette", None)
        # Ensure the brand theme overrides the built-in "dark" entry.
        if not theme.get("id"):
            theme["id"] = "dark"
        return theme
    return {
        "id": "dark",
        "name": provider.label,
        "colors": {"bashBorder": "rgb(177,185,249)", "claude": "rgb(177,185,249)"},
    }


def provider_patch_config(provider_key: str) -> Dict:
    """Build a tweakcc-style config with the brand theme + fallback themes."""
    from .palette import FALLBACK_THEMES

    brand = provider_theme(provider_key)
    # Merge: brand theme first (it overrides "dark" if id matches), then
    # fallback themes excluding any whose id collides with the brand.
    brand_id = brand.get("id", "dark")
    fallbacks = [t for t in FALLBACK_THEMES if t.get("id") != brand_id]
    return {"settings": {"themes": [brand] + fallbacks}}


def provider_prompt_overlays(provider_key: str) -> Dict[str, str]:
    provider = get_provider(provider_key)
    if provider.no_prompt_pack:
        return {}
    if provider.prompt_overlays:
        return dict(provider.prompt_overlays)
    label = provider.label
    return {
        "webfetch": f"When provider-specific docs or tools are needed, prefer {label} configuration from this isolated variant.",
        "explore": f"This Claude Code variant is configured for {label}. Keep model and provider assumptions consistent with that endpoint.",
        "planEnhanced": f"Plan with the active {label} provider in mind. Do not assume first-party Claude-only model names unless configured.",
    }


def provider_claude_config(provider_key: str) -> Dict[str, object]:
    provider = get_provider(provider_key)
    return {
        "settingsPermissionsDeny": list(provider.settings_permissions_deny),
        "mcpServers": copy.deepcopy(provider.mcp_servers),
    }


def _credential_targets(provider: ProviderTemplate) -> List[str]:
    if provider.auth_mode == "authToken":
        targets = ["ANTHROPIC_AUTH_TOKEN"]
        if provider.auth_token_also_sets_api_key:
            targets.append("ANTHROPIC_API_KEY")
        return _require_env_names(targets, label="credential target")
    targets = ["ANTHROPIC_API_KEY"]
    if provider.credential_env and provider.credential_env not in targets:
        targets.append(provider.credential_env)
    return _require_env_names(targets, label="credential target")


def _default_credential_env(provider: ProviderTemplate) -> str:
    return provider.credential_env or (
        "ANTHROPIC_AUTH_TOKEN" if provider.auth_mode == "authToken" else "ANTHROPIC_API_KEY"
    )


def _apply_auth_token_fallback(provider: ProviderTemplate, env: Dict[str, str]) -> None:
    if provider.auth_mode != "authToken" or not provider.auth_token_fallback:
        return
    for target in _credential_targets(provider):
        env[target] = provider.auth_token_fallback


def _apply_model_overrides(env: Dict[str, str], overrides: Dict[str, str]) -> None:
    for key, env_key in MODEL_ENV_KEYS.items():
        value = str(overrides.get(key) or "").strip()
        if value:
            env[env_key] = value


def _sync_compatibility_model_defaults(env: Dict[str, str], overrides: Dict[str, str]) -> None:
    if not str(overrides.get("default") or "").strip() and env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"):
        env["ANTHROPIC_MODEL"] = env["ANTHROPIC_DEFAULT_OPUS_MODEL"]
    if not str(overrides.get("small_fast") or "").strip() and env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"):
        env["ANTHROPIC_SMALL_FAST_MODEL"] = env["ANTHROPIC_DEFAULT_HAIKU_MODEL"]


def _validate_model_mapping(provider: ProviderTemplate, env: Dict[str, str]) -> None:
    if not provider.requires_model_mapping:
        return
    missing = [
        key
        for key in (
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        )
        if not env.get(key)
    ]
    if missing:
        names = ", ".join(missing)
        raise ValueError(f"{provider.label} requires model mapping for {names}")


def _apply_extra_env(env: Dict[str, str], entries: List[str]) -> None:
    for entry in entries:
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        if key:
            env[require_env_name(key, label="--extra-env key")] = value.strip()


def _require_env_names(names: List[str], *, label: str) -> List[str]:
    return [require_env_name(name, label=label) for name in names]


def _providers() -> Dict[str, ProviderTemplate]:
    providers = {}
    for path in _provider_manifest_paths():
        payload = read_json_strict(path)
        provider = provider_from_json(payload)
        expected_key = _expected_provider_key(path)
        if expected_key != provider.key:
            raise ProviderSchemaError(f"{path} does not match provider key {provider.key}")
        if provider.key in providers:
            raise ProviderSchemaError(f"Duplicate provider key: {provider.key}")
        providers[provider.key] = provider
    return providers


def _provider_manifest_paths() -> List[Path]:
    return sorted(
        path
        for path in REGISTRY_DIR.rglob("*.json")
        if path.is_file()
    )


def _expected_provider_key(path: Path) -> str:
    if path.parent == REGISTRY_DIR:
        return path.stem
    return path.parent.name
