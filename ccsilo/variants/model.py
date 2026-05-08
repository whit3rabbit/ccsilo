"""Dataclasses and small helpers for the variants subsystem (no I/O)."""

from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Dict, List, Optional

from .._utils import make_kebab_id, require_env_name
from ..workspace import PATCH_ID_RE, workspace_root

MODEL_PROXY_MAX_TIMEOUT_MS = 24 * 60 * 60 * 1000


@dataclass
class Variant:
    variant_id: str
    name: str
    path: Path
    manifest: Dict


@dataclass
class VariantBuildStage:
    name: str
    status: str
    detail: str = ""


class VariantBuildError(RuntimeError):
    def __init__(self, variant_id: str, stage: str, cause: Exception, stages: List[VariantBuildStage]):
        self.variant_id = variant_id
        self.stage = stage
        self.cause = cause
        self.stages = list(stages)
        super().__init__(f"{stage} failed for {variant_id}: {cause}")


@dataclass
class VariantBuildResult:
    variant: Variant
    binary_path: Path
    wrapper_path: Path
    output_sha256: str
    applied_tweaks: List[str]
    skipped_tweaks: List[str]
    missing_prompt_keys: List[str]
    stages: List[VariantBuildStage] = dataclass_field(default_factory=list)


@dataclass
class _BinaryTweakResult:
    applied: List[str]
    skipped: List[str]
    missing: List[str]


@dataclass
class _RuntimePatchResult:
    tweaks: _BinaryTweakResult
    sign_result: object
    runtime: str = "native"
    entry_path: Optional[str] = None


@dataclass
class _AlreadySigned:
    signed: bool = True
    reason: Optional[str] = None
    detail: Optional[str] = None


def variant_id_from_name(name: str) -> str:
    return make_kebab_id(name, label="variant name")


def variant_root(variant_id: str, root=None) -> Path:
    if not isinstance(variant_id, str) or not PATCH_ID_RE.match(variant_id):
        raise ValueError("variant id must be lower-kebab-case")
    return workspace_root(root) / "variants" / variant_id


def default_bin_dir(root=None) -> Path:
    return workspace_root(root) / "bin"


def validate_variant_manifest(manifest: Dict) -> None:
    if manifest.get("schemaVersion") != 1:
        raise ValueError("variant schemaVersion must be 1")
    variant_id = manifest.get("id")
    if not isinstance(variant_id, str) or not PATCH_ID_RE.match(variant_id):
        raise ValueError("variant id must be lower-kebab-case")
    if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
        raise ValueError("variant name must be a non-empty string")
    provider = manifest.get("provider")
    if not isinstance(provider, dict) or not isinstance(provider.get("key"), str):
        raise ValueError("variant provider must include key")
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("version"), str):
        raise ValueError("variant source must include version")
    source_type = source.get("type", "download")
    if source_type not in {"download", "local-binary"}:
        raise ValueError("variant source.type must be download or local-binary")
    if source_type == "local-binary":
        for field in ("platform", "sha256", "path"):
            if not isinstance(source.get(field), str) or not source[field]:
                raise ValueError(f"local-binary variant source must include {field}")
        imported_from = source.get("importedFrom")
        if imported_from is not None and not isinstance(imported_from, str):
            raise ValueError("local-binary variant source importedFrom must be a string")
    paths = manifest.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("variant paths must be an object")
    runtime = manifest.get("runtime", "native")
    if runtime not in ("native", "node"):
        raise ValueError("variant runtime must be native or node")
    if runtime == "node" and paths and not isinstance(paths.get("entryPath"), str):
        raise ValueError("node variant paths must include entryPath")
    mcp = manifest.get("mcp", {})
    if mcp is None:
        mcp = {}
    if not isinstance(mcp, dict):
        raise ValueError("variant mcp must be an object")
    selected_mcp = mcp.get("selected", [])
    if selected_mcp is None:
        selected_mcp = []
    if not isinstance(selected_mcp, list) or not all(isinstance(item, str) for item in selected_mcp):
        raise ValueError("variant mcp.selected must be a list of strings")
    if selected_mcp:
        from ..providers import normalize_mcp_ids

        normalize_mcp_ids(selected_mcp)
    ccrouter = manifest.get("ccrouter")
    if ccrouter is not None:
        if not isinstance(ccrouter, dict):
            raise ValueError("variant ccrouter must be an object")
        mode = ccrouter.get("mode")
        if mode not in {"managed", "external"}:
            raise ValueError("variant ccrouter.mode must be managed or external")
        if mode == "managed":
            config_mode = ccrouter.get("configMode")
            if config_mode not in {"copy-global", "empty", "shared-home"}:
                raise ValueError("variant ccrouter.configMode must be copy-global, empty, or shared-home")
            if not isinstance(ccrouter.get("packageSpec"), str) or not ccrouter["packageSpec"].strip():
                raise ValueError("variant ccrouter.packageSpec must be a non-empty string")
            if not isinstance(ccrouter.get("homeDir"), str) or not ccrouter["homeDir"].strip():
                raise ValueError("variant ccrouter.homeDir must be a non-empty string")
            if not isinstance(ccrouter.get("runtimeDir"), str) or not ccrouter["runtimeDir"].strip():
                raise ValueError("variant ccrouter.runtimeDir must be a non-empty string")
            if "tmpDir" in ccrouter and (not isinstance(ccrouter.get("tmpDir"), str) or not ccrouter["tmpDir"].strip()):
                raise ValueError("variant ccrouter.tmpDir must be a non-empty string")
            port = ccrouter.get("port")
            if not isinstance(port, int) or port < 1 or port > 65535:
                raise ValueError("variant ccrouter.port must be an integer between 1 and 65535")
            if not isinstance(ccrouter.get("autoStart", True), bool):
                raise ValueError("variant ccrouter.autoStart must be a boolean")
    model_proxy = manifest.get("modelProxy")
    if model_proxy is not None:
        if not isinstance(model_proxy, dict):
            raise ValueError("variant modelProxy must be an object")
        if model_proxy.get("mode") != "architect":
            raise ValueError("variant modelProxy.mode must be architect")
        port = model_proxy.get("port", "auto")
        if port != "auto" and (not isinstance(port, int) or port < 1 or port > 65535):
            raise ValueError("variant modelProxy.port must be auto or an integer between 1 and 65535")
        if not isinstance(model_proxy.get("backendUrl"), str) or not model_proxy["backendUrl"].strip():
            raise ValueError("variant modelProxy.backendUrl must be a non-empty string")
        if model_proxy.get("backendAuth") not in {"x-api-key", "bearer"}:
            raise ValueError("variant modelProxy.backendAuth must be x-api-key or bearer")
        timeout_ms = model_proxy.get("timeoutMs")
        if timeout_ms is not None and (not isinstance(timeout_ms, int) or timeout_ms < 1):
            raise ValueError("variant modelProxy.timeoutMs must be a positive integer")
        if isinstance(timeout_ms, int) and timeout_ms > MODEL_PROXY_MAX_TIMEOUT_MS:
            raise ValueError("variant modelProxy.timeoutMs exceeds maximum allowed timeout")
        if not isinstance(model_proxy.get("credentialEnv"), str) or not model_proxy["credentialEnv"].strip():
            raise ValueError("variant modelProxy.credentialEnv must be a non-empty string")
        require_env_name(model_proxy["credentialEnv"], label="variant modelProxy.credentialEnv")
        for field in ("backendModels", "anthropicModels"):
            values = model_proxy.get(field)
            if not isinstance(values, list) or not values:
                raise ValueError(f"variant modelProxy.{field} must be a non-empty list")
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"variant modelProxy.{field} must contain non-empty strings")
        if set(model_proxy["backendModels"]) & set(model_proxy["anthropicModels"]):
            raise ValueError("variant modelProxy backendModels and anthropicModels must not overlap")
        for value in model_proxy["anthropicModels"]:
            if not value.startswith("claude-"):
                raise ValueError("variant modelProxy.anthropicModels must contain claude-* models")
        for field in ("runtimeConfigPath", "logPath", "portFilePath", "pythonExecutable"):
            value = model_proxy.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"variant modelProxy.{field} must be a string")
    env_unset = manifest.get("envUnset", [])
    if env_unset is None:
        env_unset = []
    if not isinstance(env_unset, list):
        raise ValueError("variant envUnset must be a list of strings")
    for name in env_unset:
        if not isinstance(name, str):
            raise ValueError("variant envUnset must be a list of strings")
        require_env_name(name, label="variant envUnset item")
    for field in ("createdAt", "updatedAt"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise ValueError(f"variant {field} must be a non-empty string")


def list_variant_providers() -> List[Dict[str, object]]:
    from ..providers import list_providers
    from .splash import splash_ascii_art, splash_quote_block

    providers = []
    for provider in list_providers():
        section = str(provider.tui.get("section") or _default_provider_section(provider.key))
        model_discovery = provider.tui.get("modelDiscovery") or {}
        if not isinstance(model_discovery, dict):
            model_discovery = {}
        splash_style = str(provider.env.get("CCSILO_SPLASH_STYLE") or "default")
        providers.append(
            {
                "key": provider.key,
                "label": provider.label,
                "description": provider.description,
                "section": section,
                "baseUrl": provider.base_url,
                "authMode": provider.auth_mode,
                "requiresModelMapping": provider.requires_model_mapping,
                "credentialOptional": provider.credential_optional,
                "credentialEnv": provider.credential_env or "",
                "authTokenFallback": provider.auth_token_fallback or "",
                "noPromptPack": provider.no_prompt_pack,
                "models": dict(provider.models),
                "envUnset": list(provider.env_unset),
                "mcpServers": sorted(provider.mcp_servers),
                "settingsPermissionsDeny": list(provider.settings_permissions_deny),
                "modelDiscovery": dict(model_discovery),
                "tui": dict(provider.tui),
                "defaultVariantName": provider.default_variant_name or provider.key,
                "splashStyle": splash_style,
                "asciiArt": splash_ascii_art(splash_style),
                "asciiArtQuoteBlock": splash_quote_block(splash_style),
            }
        )
    return providers


def _default_provider_section(provider_key: str) -> str:
    if provider_key in {"mirror", "ccrouter"}:
        return "pinned"
    if provider_key in {"ollama", "lmstudio", "omlx", "local-custom"}:
        return "local"
    return "cloud"
