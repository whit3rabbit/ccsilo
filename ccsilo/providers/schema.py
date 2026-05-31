"""Provider template schema validation and deserialization."""

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .._utils import require_env_name


DEFAULT_TIMEOUT_MS = "3000000"

MODEL_ENV_KEYS = {
    "sonnet": "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "opus": "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "haiku": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "small_fast": "ANTHROPIC_SMALL_FAST_MODEL",
    "default": "ANTHROPIC_MODEL",
    "subagent": "CLAUDE_CODE_SUBAGENT_MODEL",
}

MODEL_JSON_KEYS = {
    "sonnet": "sonnet",
    "opus": "opus",
    "haiku": "haiku",
    "smallFast": "small_fast",
    "default": "default",
    "subagent": "subagent",
}


@dataclass(frozen=True)
class ProviderTemplate:
    key: str
    label: str
    description: str
    display_order: int
    base_url: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    env_unset: List[str] = field(default_factory=list)
    api_key_label: str = ""
    auth_mode: str = "apiKey"
    requires_model_mapping: bool = False
    credential_optional: bool = False
    no_prompt_pack: bool = False
    requires_empty_api_key: bool = False
    auth_token_also_sets_api_key: bool = False
    auth_token_fallback: Optional[str] = None
    default_variant_name: Optional[str] = None
    credential_env: Optional[str] = None
    models: Dict[str, str] = field(default_factory=dict)
    theme: Dict[str, object] = field(default_factory=dict)
    prompt_overlays: Dict[str, str] = field(default_factory=dict)
    settings_permissions_deny: List[str] = field(default_factory=list)
    mcp_servers: Dict[str, object] = field(default_factory=dict)
    tui: Dict[str, object] = field(default_factory=dict)
    model_proxy: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderEnv:
    env: Dict[str, str]
    env_unset: List[str]
    secret_env: Dict[str, str]
    credential: Dict[str, object]


class ProviderSchemaError(ValueError):
    pass


TOP_LEVEL_KEYS = {
    "schemaVersion",
    "key",
    "label",
    "description",
    "displayOrder",
    "baseUrl",
    "auth",
    "models",
    "env",
    "envUnset",
    "variant",
    "claudeConfig",
    "tui",
    "modelProxy",
}

AUTH_KEYS = {
    "mode",
    "apiKeyLabel",
    "credentialEnv",
    "credentialOptional",
    "authTokenFallback",
    "requiresEmptyApiKey",
    "authTokenAlsoSetsApiKey",
}

MODEL_KEYS = {"default", "smallFast", "opus", "sonnet", "haiku", "subagent", "requiresModelMapping"}
VARIANT_KEYS = {"defaultVariantName", "splashStyle", "theme", "noPromptPack", "promptOverlays"}
CLAUDE_CONFIG_KEYS = {"settingsPermissionsDeny", "mcpServers"}
TUI_KEYS = {"headline", "features", "setupLinks", "setupNote", "section", "modelDiscovery"}
MODEL_DISCOVERY_KEYS = {"enabled"}
MODEL_PROXY_KEYS = {"mode", "backendFormat", "backendAuth"}
MCP_SERVER_KEYS = {"type", "command", "args", "env", "url", "headers", "headersHelper", "oauth"}
MCP_SERVER_TYPES = {"http", "stdio", "sse"}


def provider_from_json(payload: Dict[str, object]) -> ProviderTemplate:
    _require_keys(payload, TOP_LEVEL_KEYS, "provider")
    if payload.get("schemaVersion") != 1:
        raise ProviderSchemaError("provider schemaVersion must be 1")

    key = _string(payload, "key", required=True)
    label = _string(payload, "label", required=True)
    description = _string(payload, "description", required=True)
    display_order = _int(payload, "displayOrder", required=True)
    base_url = _string(payload, "baseUrl")

    auth = _object(payload, "auth")
    _require_keys(auth, AUTH_KEYS, f"{key}.auth")
    auth_mode = _string(auth, "mode") or "apiKey"
    if auth_mode not in {"apiKey", "authToken", "none"}:
        raise ProviderSchemaError(f"{key}.auth.mode must be apiKey, authToken, or none")

    models_payload = _object(payload, "models")
    _require_keys(models_payload, MODEL_KEYS, f"{key}.models")
    models = _models(models_payload, key)

    env = _string_map(_object(payload, "env"), f"{key}.env")
    for env_key in env:
        _env_name(env_key, f"{key}.env key")
    env_unset = _string_list(payload, "envUnset")
    for env_key in env_unset:
        _env_name(env_key, f"{key}.envUnset item")
    for model_key, model_value in models.items():
        env_key = MODEL_ENV_KEYS[model_key]
        if model_value:
            env.setdefault(env_key, model_value)

    variant = _object(payload, "variant")
    _require_keys(variant, VARIANT_KEYS, f"{key}.variant")
    splash_style = _string(variant, "splashStyle")
    if splash_style:
        env.setdefault("CCSILO_SPLASH", "1")
        env.setdefault("CCSILO_SPLASH_STYLE", splash_style)
    env.setdefault("CCSILO_PROVIDER_LABEL", label)

    claude_config = _object(payload, "claudeConfig")
    _require_keys(claude_config, CLAUDE_CONFIG_KEYS, f"{key}.claudeConfig")
    _validate_mcp_servers(_object(claude_config, "mcpServers"), f"{key}.claudeConfig.mcpServers")

    tui = _object(payload, "tui")
    _require_keys(tui, TUI_KEYS, f"{key}.tui")
    if "features" in tui and not _is_string_list(tui["features"]):
        raise ProviderSchemaError(f"{key}.tui.features must be a list of strings")
    if "setupLinks" in tui:
        _string_map(_object(tui, "setupLinks"), f"{key}.tui.setupLinks")
    if "section" in tui:
        section = _string(tui, "section")
        if section and section not in {"pinned", "cloud", "local"}:
            raise ProviderSchemaError(f"{key}.tui.section must be pinned, cloud, or local")
    if "modelDiscovery" in tui:
        discovery = _object(tui, "modelDiscovery")
        _require_keys(discovery, MODEL_DISCOVERY_KEYS, f"{key}.tui.modelDiscovery")
        if _bool(discovery, "enabled"):
            env.setdefault("CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY", "1")

    model_proxy = _object(payload, "modelProxy")
    _require_keys(model_proxy, MODEL_PROXY_KEYS, f"{key}.modelProxy")
    if model_proxy:
        mode = _string(model_proxy, "mode", required=True)
        if mode not in {"architect", "openai"}:
            raise ProviderSchemaError(f"{key}.modelProxy.mode must be architect or openai")
        backend_format = _string(model_proxy, "backendFormat")
        if backend_format and backend_format not in {"anthropic", "openai-chat"}:
            raise ProviderSchemaError(f"{key}.modelProxy.backendFormat must be anthropic or openai-chat")
        backend_auth = _string(model_proxy, "backendAuth")
        if backend_auth and backend_auth not in {"x-api-key", "bearer"}:
            raise ProviderSchemaError(f"{key}.modelProxy.backendAuth must be x-api-key or bearer")

    credential_env = _optional_string(auth, "credentialEnv")
    if credential_env:
        _env_name(credential_env, f"{key}.auth.credentialEnv")

    return ProviderTemplate(
        key=key,
        label=label,
        description=description,
        display_order=display_order,
        base_url=base_url,
        env=env,
        env_unset=env_unset,
        api_key_label=_string(auth, "apiKeyLabel"),
        auth_mode=auth_mode,
        requires_model_mapping=_bool(models_payload, "requiresModelMapping"),
        credential_optional=_bool(auth, "credentialOptional"),
        no_prompt_pack=_bool(variant, "noPromptPack"),
        requires_empty_api_key=_bool(auth, "requiresEmptyApiKey"),
        auth_token_also_sets_api_key=_bool(auth, "authTokenAlsoSetsApiKey"),
        auth_token_fallback=_optional_string(auth, "authTokenFallback"),
        default_variant_name=_optional_string(variant, "defaultVariantName"),
        credential_env=credential_env,
        models=models,
        theme=copy.deepcopy(_object(variant, "theme")),
        prompt_overlays=_string_map(_object(variant, "promptOverlays"), f"{key}.variant.promptOverlays"),
        settings_permissions_deny=_string_list(claude_config, "settingsPermissionsDeny"),
        mcp_servers=copy.deepcopy(_object(claude_config, "mcpServers")),
        tui=copy.deepcopy(tui),
        model_proxy=copy.deepcopy(model_proxy),
    )


def _require_keys(payload: Dict[str, object], allowed: set, context: str) -> None:
    extra = sorted(set(payload) - allowed)
    if extra:
        raise ProviderSchemaError(f"{context} has unknown keys: {', '.join(extra)}")


def _object(payload: Dict[str, object], key: str) -> Dict[str, object]:
    value = payload.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProviderSchemaError(f"{key} must be an object")
    return value


def _string(payload: Dict[str, object], key: str, *, required: bool = False) -> str:
    value = payload.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ProviderSchemaError(f"{key} must be a string")
    if required and not value.strip():
        raise ProviderSchemaError(f"{key} must be a non-empty string")
    return value


def _optional_string(payload: Dict[str, object], key: str) -> Optional[str]:
    value = _string(payload, key)
    return value or None


def _int(payload: Dict[str, object], key: str, *, required: bool = False) -> int:
    value = payload.get(key)
    if required and value is None:
        raise ProviderSchemaError(f"{key} must be an integer")
    if value is None:
        return 0
    if not isinstance(value, int):
        raise ProviderSchemaError(f"{key} must be an integer")
    return value


def _bool(payload: Dict[str, object], key: str) -> bool:
    value = payload.get(key, False)
    if not isinstance(value, bool):
        raise ProviderSchemaError(f"{key} must be a boolean")
    return value


def _models(payload: Dict[str, object], provider_key: str) -> Dict[str, str]:
    models = {}
    for json_key, model_key in MODEL_JSON_KEYS.items():
        value = payload.get(json_key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ProviderSchemaError(f"{provider_key}.models.{json_key} must be a string")
        if value:
            models[model_key] = value
    return models


def _string_map(payload: Dict[str, object], context: str) -> Dict[str, str]:
    result = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
            raise ProviderSchemaError(f"{context} must map strings to scalar values")
        result[key] = str(value)
    return result


def _string_list(payload: Dict[str, object], key: str) -> List[str]:
    value = payload.get(key, [])
    if value is None:
        return []
    if not _is_string_list(value):
        raise ProviderSchemaError(f"{key} must be a list of strings")
    return list(value)


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _env_name(value: str, context: str) -> str:
    try:
        return require_env_name(value, label=context)
    except ValueError as exc:
        raise ProviderSchemaError(str(exc)) from exc


def _validate_mcp_env_keys(value: object, context: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "env":
                if isinstance(item, dict):
                    for env_key in item:
                        _env_name(env_key, f"{context}.env key")
                continue
            _validate_mcp_env_keys(item, f"{context}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_mcp_env_keys(item, f"{context}[{index}]")


def _validate_mcp_servers(servers: Dict[str, object], context: str) -> None:
    for name, server in servers.items():
        if not isinstance(name, str) or not name:
            raise ProviderSchemaError(f"{context} keys must be non-empty strings")
        if not isinstance(server, dict):
            raise ProviderSchemaError(f"{context}.{name} must be an object")
        extra = sorted(set(server) - MCP_SERVER_KEYS)
        if extra:
            raise ProviderSchemaError(f"{context}.{name} has unknown keys: {', '.join(extra)}")
        server_type = server.get("type")
        if server_type not in MCP_SERVER_TYPES:
            raise ProviderSchemaError(f"{context}.{name}.type must be http, stdio, or sse")
        if server_type == "stdio":
            if not isinstance(server.get("command"), str) or not str(server.get("command")).strip():
                raise ProviderSchemaError(f"{context}.{name}.command must be a non-empty string")
            if "args" in server and not _is_string_list(server["args"]):
                raise ProviderSchemaError(f"{context}.{name}.args must be a list of strings")
        else:
            if not isinstance(server.get("url"), str) or not str(server.get("url")).strip():
                raise ProviderSchemaError(f"{context}.{name}.url must be a non-empty string")
        if "headers" in server and not _is_string_map(server["headers"]):
            raise ProviderSchemaError(f"{context}.{name}.headers must be an object of strings")
        if "env" in server and not _is_string_map(server["env"]):
            raise ProviderSchemaError(f"{context}.{name}.env must be an object of strings")
        _validate_mcp_env_keys(server, f"{context}.{name}")


def _is_string_map(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in value.items()
    )
