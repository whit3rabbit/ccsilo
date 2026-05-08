"""Variant public lifecycle workflows."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..binary_patcher.bun_compat import has_bun_node_compat
from .._utils import require_env_name, safe_read_json as _safe_read_json, utc_now as _utc_now
from ..providers import build_provider_env, get_provider, normalize_mcp_ids, provider_default_variant_name
from ..workspace import NativeArtifact, SEMVER_RE, import_local_native_binary, read_json, workspace_root
from .builder import patch_refs_for_profile as _patch_refs_for_profile
from .constants import VARIANT_METADATA
from .ccrouter import (
    ccrouter_doctor_checks,
    ccrouter_manifest_for_create,
)
from .model import (
    Variant,
    VariantBuildResult,
    default_bin_dir,
    validate_variant_manifest,
    variant_id_from_name,
    variant_root,
)
from .install import remove_variant_managed_installs
from .tweaks import default_tweak_ids_for_provider, env_for_tweaks, normalize_tweak_ids, sync_tweak_env
from .wrapper import (
    SECRETS_FILE,
    SECRETS_FILE_MODE,
    validate_secret_file as _validate_secret_file,
    write_secrets as _write_secrets,
)

import sys as _sys


def _variants():
    return _sys.modules["ccsilo.variants"]


def _proxy(name):
    def call(*args, **kwargs):
        return getattr(_variants(), name)(*args, **kwargs)
    return call

__all__ = ['_resolve_bin_dir', '_canonical_wrapper_path', 'scan_variants', 'load_variant', 'create_variant', 'apply_variant', '_apply_variant_manifest', 'update_variants', 'remove_variant', 'doctor_variant', 'run_variant']

def _resolve_bin_dir(bin_dir, root) -> Path:
    if bin_dir is None:
        return default_bin_dir(root)
    return Path(bin_dir)

def _canonical_wrapper_path(variant_id: str, root=None) -> Path:
    return default_bin_dir(root) / variant_id

def scan_variants(root=None) -> List[Variant]:
    base = workspace_root(root) / "variants"
    variants = []
    if not base.exists():
        return variants
    for metadata_path in base.glob(f"*/{VARIANT_METADATA}"):
        try:
            variants.append(load_variant(metadata_path.parent.name, root=root))
        except ValueError:
            continue
    return sorted(variants, key=lambda item: item.name.lower())

def load_variant(variant_id: str, root=None) -> Variant:
    path = variant_root(variant_id, root=root)
    metadata_path = path / VARIANT_METADATA
    if not metadata_path.exists():
        raise ValueError(f"No variant found for {variant_id}")
    manifest = read_json(metadata_path)
    validate_variant_manifest(manifest)
    if manifest["id"] != variant_id:
        raise ValueError("variant filename does not match id")
    return Variant(variant_id=manifest["id"], name=manifest["name"], path=path, manifest=manifest)

def create_variant(
    *,
    name: Optional[str] = None,
    provider_key: str,
    claude_version: str = "latest",
    patch_profile_id: Optional[str] = None,
    tweaks: Optional[Iterable[str]] = None,
    base_url: Optional[str] = None,
    credential_env: Optional[str] = None,
    api_key: Optional[str] = None,
    store_secret: bool = False,
    bin_dir: Optional[os.PathLike] = None,
    force: bool = False,
    model_overrides: Optional[Dict[str, str]] = None,
    extra_env: Optional[List[str]] = None,
    tweak_options: Optional[Dict[str, str]] = None,
    mcp_ids: Optional[Iterable[str]] = None,
    ccrouter_mode: Optional[str] = None,
    ccrouter_config: Optional[str] = None,
    ccrouter_package: Optional[str] = None,
    ccrouter_port: Optional[object] = None,
    ccrouter_autostart: Optional[bool] = None,
    model_proxy: Optional[str] = None,
    model_proxy_port: Optional[object] = None,
    source_binary: Optional[os.PathLike] = None,
    source_platform: Optional[str] = None,
    root=None,
    source_artifact: Optional[NativeArtifact] = None,
) -> VariantBuildResult:
    provider = get_provider(provider_key)
    name = name or provider_default_variant_name(provider_key)
    variant_id = variant_id_from_name(name)
    path = variant_root(variant_id, root=root)
    if path.exists() and not force:
        raise ValueError(f"Variant {variant_id} already exists")
    if source_binary is not None and source_artifact is not None:
        raise ValueError("Pass either source_binary or source_artifact, not both")
    if source_platform is not None and source_binary is None:
        raise ValueError("--source-platform requires --source-binary")
    if source_binary is not None:
        source_artifact = _import_source_binary_for_version(
            source_binary,
            claude_version,
            source_platform=source_platform,
            root=root,
        )

    provider_env = build_provider_env(
        provider_key,
        base_url=base_url,
        api_key=api_key,
        credential_env=credential_env,
        store_secret=store_secret,
        model_overrides=model_overrides,
        extra_env=extra_env,
    )
    model_proxy_payload, safe_env, credential, secret_env = _model_proxy_for_create(
        provider,
        provider_env,
        model_proxy=model_proxy,
        model_proxy_port=model_proxy_port,
        base_url=base_url,
        api_key=api_key,
        model_overrides=model_overrides or {},
    )
    tweak_ids = normalize_tweak_ids(tweaks or default_tweak_ids_for_provider(provider.key))
    selected_mcp_ids = normalize_mcp_ids(mcp_ids or [])
    safe_env.update(env_for_tweaks(tweak_ids, tweak_options))
    now = _utc_now()
    existing = _safe_read_json(path / VARIANT_METADATA)
    patch_refs = _patch_refs_for_profile(patch_profile_id, root=root)
    ccrouter_config_payload = ccrouter_manifest_for_create(
        provider.key,
        path,
        mode=ccrouter_mode,
        config_mode=ccrouter_config,
        package_spec=ccrouter_package,
        port=ccrouter_port,
        auto_start=ccrouter_autostart,
    )

    manifest = {
        "schemaVersion": 1,
        "id": variant_id,
        "name": name.strip(),
        "provider": {
            "key": provider.key,
            "label": provider.label,
        },
        "source": _source_manifest_for_create(source_artifact, claude_version),
        "patchProfile": patch_profile_id,
        "patches": patch_refs,
        "tweaks": tweak_ids,
        "tweakOptions": dict(tweak_options or {}),
        "mcp": {
            "selected": selected_mcp_ids,
        },
        "modelOverrides": dict(model_overrides or {}),
        "env": safe_env,
        "envUnset": list(provider_env.env_unset),
        "credential": credential,
        "paths": {},
        "createdAt": existing.get("createdAt") if existing else now,
        "updatedAt": now,
    }
    if ccrouter_config_payload is not None:
        manifest["ccrouter"] = ccrouter_config_payload
    if model_proxy_payload is not None:
        manifest["modelProxy"] = model_proxy_payload
    validate_variant_manifest(manifest)

    path.mkdir(parents=True, exist_ok=True)
    if secret_env:
        _write_secrets(path / SECRETS_FILE, secret_env)
        manifest["credential"] = dict(manifest["credential"])
        manifest["credential"]["secretsPath"] = str(path / SECRETS_FILE)
    elif (path / SECRETS_FILE).exists():
        (path / SECRETS_FILE).unlink()

    return _variants()._build_variant_from_manifest(
        manifest,
        root=root,
        bin_dir=_resolve_bin_dir(bin_dir, root),
        source_artifact=source_artifact,
    )

_MODEL_PROXY_AUTH_ENV = {"ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
_MODEL_PROXY_MAX_TIMEOUT_MS = 24 * 60 * 60 * 1000

def _model_proxy_for_create(
    provider,
    provider_env,
    *,
    model_proxy: Optional[str],
    model_proxy_port: Optional[object],
    base_url: Optional[str],
    api_key: Optional[str],
    model_overrides: Dict[str, str],
):
    if model_proxy in (None, ""):
        return None, dict(provider_env.env), dict(provider_env.credential), dict(provider_env.secret_env)
    if model_proxy != "architect":
        raise ValueError("model proxy must be architect; this proxy is only for Architect Mode setups")
    if provider.auth_mode == "none":
        raise ValueError(f"{provider.label} cannot use a model proxy because it has no backend credentials")

    backend_url = str(base_url if base_url is not None else provider.base_url).strip()
    if not backend_url:
        raise ValueError(f"{provider.label} model proxy requires ANTHROPIC_BASE_URL or --base-url")
    source_env = _model_proxy_credential_source(provider, provider_env)
    credential, secret_env = _model_proxy_credential(provider_env, source_env, api_key=api_key)
    safe_env = _model_proxy_safe_env(provider_env.env, model_overrides)
    payload = {
        "mode": "architect",
        "port": _model_proxy_port(model_proxy_port),
        "backendUrl": backend_url,
        "backendAuth": "bearer" if provider.auth_mode == "authToken" else "x-api-key",
        "credentialEnv": source_env,
        "anthropicUrl": "https://api.anthropic.com",
        "timeoutMs": _model_proxy_timeout_ms(safe_env.get("API_TIMEOUT_MS")),
        **_model_proxy_route_models(safe_env),
    }
    return payload, safe_env, credential, secret_env


def _model_proxy_credential_source(provider, provider_env) -> str:
    credential = provider_env.credential or {}
    if credential.get("mode") == "env" and credential.get("source"):
        return require_env_name(credential["source"], label="model proxy credential source")
    if provider.credential_env:
        return require_env_name(provider.credential_env, label="model proxy credential source")
    targets = [target for target in credential.get("targets", []) if target not in _MODEL_PROXY_AUTH_ENV]
    if targets:
        return require_env_name(targets[0], label="model proxy credential source")
    if provider.auth_mode == "apiKey":
        return "ANTHROPIC_API_KEY"
    raise ValueError(f"{provider.label} model proxy requires a provider credential env")


def _model_proxy_credential(provider_env, source_env: str, *, api_key: Optional[str]):
    source_env = require_env_name(source_env, label="model proxy credential source")
    mode = (provider_env.credential or {}).get("mode")
    if mode == "env":
        return {"mode": "env", "source": source_env, "targets": []}, {}
    if mode == "none" and source_env in (provider_env.env or {}):
        return dict(provider_env.credential or {"mode": "none", "targets": []}), {}
    if mode == "stored":
        value = (api_key or "").strip()
        if not value:
            for secret_value in (provider_env.secret_env or {}).values():
                if secret_value:
                    value = secret_value
                    break
        if not value:
            raise ValueError("model proxy stored credential is missing")
        return {"mode": "stored", "targets": [source_env]}, {source_env: value}
    raise ValueError("model proxy requires backend credentials or a credential env var")


def _model_proxy_safe_env(env: Dict[str, str], model_overrides: Dict[str, str]) -> Dict[str, str]:
    safe_env = {
        key: value
        for key, value in dict(env).items()
        if key not in _MODEL_PROXY_AUTH_ENV
    }
    opus_override = str(model_overrides.get("opus") or "").strip()
    if not opus_override:
        raise ValueError("--model-opus must be set to a claude-* planner model when --model-proxy architect is used")
    if not opus_override.startswith("claude-"):
        raise ValueError("--model-opus must be a claude-* model when --model-proxy architect is used")
    default_override = str(model_overrides.get("default") or "").strip()
    if not default_override:
        worker_default = safe_env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or safe_env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
        if worker_default:
            safe_env["ANTHROPIC_MODEL"] = worker_default
    return safe_env


def _model_proxy_route_models(env: Dict[str, str]) -> Dict[str, List[str]]:
    backend_models: List[str] = []
    anthropic_models: List[str] = []
    for key in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_SMALL_FAST_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    ):
        model = str(env.get(key) or "").strip()
        if not model:
            continue
        target = anthropic_models if model.startswith("claude-") else backend_models
        if model not in target:
            target.append(model)
    if not backend_models:
        raise ValueError("--model-proxy architect requires at least one non-claude worker model")
    if not anthropic_models:
        raise ValueError("--model-proxy architect requires at least one claude-* planner model")
    return {"backendModels": backend_models, "anthropicModels": anthropic_models}


def _model_proxy_port(value: Optional[object]):
    if value in (None, "", "auto"):
        return "auto"
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("model proxy port must be auto or an integer") from exc
    if port < 1 or port > 65535:
        raise ValueError("model proxy port must be between 1 and 65535")
    return port


def _model_proxy_timeout_ms(value: Optional[object]) -> int:
    if value in (None, ""):
        return 600_000
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("model proxy API_TIMEOUT_MS must be an integer") from exc
    if timeout < 1:
        raise ValueError("model proxy API_TIMEOUT_MS must be positive")
    if timeout > _MODEL_PROXY_MAX_TIMEOUT_MS:
        raise ValueError("model proxy API_TIMEOUT_MS exceeds maximum allowed timeout")
    return timeout


def apply_variant(
    variant_id: str,
    *,
    claude_version: Optional[str] = None,
    source_binary: Optional[os.PathLike] = None,
    source_platform: Optional[str] = None,
    root=None,
) -> VariantBuildResult:
    variant = load_variant(variant_id, root=root)
    return _apply_variant_manifest(
        variant.manifest,
        claude_version=claude_version,
        source_binary=source_binary,
        source_platform=source_platform,
        root=root,
    )

def _apply_variant_manifest(
    manifest: Dict,
    *,
    claude_version: Optional[str] = None,
    source_binary: Optional[os.PathLike] = None,
    source_platform: Optional[str] = None,
    root=None,
) -> VariantBuildResult:
    manifest = dict(manifest)
    source_artifact = None
    if source_platform is not None and source_binary is None:
        raise ValueError("--source-platform requires --source-binary")
    if source_binary is not None:
        source_artifact = _import_source_binary_for_version(
            source_binary,
            claude_version,
            source_platform=source_platform,
            root=root,
        )
        manifest["source"] = {
            "type": "local-binary",
            "version": source_artifact.version,
        }
    elif claude_version:
        manifest["source"] = {
            "type": "download",
            "version": claude_version,
        }
    manifest["env"] = sync_tweak_env(
        manifest.get("env", {}),
        manifest.get("tweaks", []),
        manifest.get("tweakOptions", {}),
    )
    manifest["updatedAt"] = _utc_now()
    return _variants()._build_variant_from_manifest(
        manifest,
        root=root,
        bin_dir=default_bin_dir(root),
        source_artifact=source_artifact,
    )

def update_variants(
    name: Optional[str] = None,
    *,
    all_variants: bool = False,
    claude_version: Optional[str] = None,
    source_binary: Optional[os.PathLike] = None,
    source_platform: Optional[str] = None,
    root=None,
) -> List[VariantBuildResult]:
    if source_platform is not None and source_binary is None:
        raise ValueError("--source-platform requires --source-binary")
    if all_variants and source_binary is not None:
        raise ValueError("--source-binary can only be used when updating one variant")
    if all_variants:
        return [
            _apply_variant_manifest(variant.manifest, claude_version=claude_version, root=root)
            for variant in scan_variants(root)
        ]
    if not name:
        raise ValueError("Pass a variant name or --all")
    return [
        apply_variant(
            variant_id_from_name(name),
            claude_version=claude_version,
            source_binary=source_binary,
            source_platform=source_platform,
            root=root,
        )
    ]

def _import_source_binary_for_version(
    source_binary: os.PathLike,
    claude_version: Optional[str],
    *,
    source_platform: Optional[str],
    root=None,
) -> NativeArtifact:
    if not isinstance(claude_version, str) or not SEMVER_RE.match(claude_version):
        raise ValueError("--source-binary requires --claude-version with a concrete semver")
    return import_local_native_binary(
        source_binary,
        claude_version,
        platform_key=source_platform,
        root=root,
    )

def _source_manifest_for_create(
    source_artifact: Optional[NativeArtifact],
    claude_version: Optional[str],
) -> Dict[str, str]:
    if source_artifact is None:
        return {
            "type": "download",
            "version": claude_version or "latest",
        }
    source_type = source_artifact.metadata.get("sourceType")
    if source_type != "local-binary":
        return {
            "type": "download",
            "version": source_artifact.version,
        }
    payload = {
        "type": "local-binary",
        "version": source_artifact.version,
        "platform": source_artifact.platform,
        "sha256": source_artifact.sha256,
        "path": str(source_artifact.path),
    }
    imported_from = source_artifact.metadata.get("importedFrom")
    if imported_from:
        payload["importedFrom"] = str(imported_from)
    return payload

def remove_variant(name: str, *, yes: bool = False, root=None) -> bool:
    if not yes:
        raise ValueError("Pass --yes to remove a variant")
    variant_id = variant_id_from_name(name)
    try:
        variant = load_variant(variant_id, root=root)
    except ValueError:
        return False
    remove_variant_managed_installs(variant)
    wrapper_path = _canonical_wrapper_path(variant_id, root=root)
    if wrapper_path.exists():
        wrapper_path.unlink()
    shutil.rmtree(variant.path)
    return True

def doctor_variant(name: Optional[str] = None, *, all_variants: bool = False, root=None) -> List[Dict[str, object]]:
    if all_variants or not name:
        variants = scan_variants(root)
    else:
        variants = [load_variant(variant_id_from_name(name), root=root)]
    reports = []
    for variant in variants:
        paths = variant.manifest.get("paths", {})
        runtime = variant.manifest.get("runtime", "native")
        binary = Path(paths.get("binary", ""))
        wrapper = Path(paths.get("wrapper", ""))
        config = Path(paths.get("configDir", "")) / "settings.json"
        secrets_path = variant.path / SECRETS_FILE
        checks = [
            {"name": "wrapper", "ok": wrapper.is_file(), "path": str(wrapper)},
            {"name": "settings", "ok": config.is_file(), "path": str(config)},
        ]
        if runtime == "node":
            entry = Path(paths.get("entryPath", ""))
            unpacked_dir = Path(paths.get("unpackedDir", ""))
            bun_compat_ok = _node_entry_bun_compat_ok(entry)
            checks.extend(
                [
                    {"name": "binary", "ok": binary.is_file(), "path": str(binary)},
                    {"name": "node-entry", "ok": entry.is_file(), "path": str(entry)},
                    {"name": "node-bun-compat", "ok": bun_compat_ok, "path": str(entry)},
                    {"name": "package-json", "ok": (unpacked_dir / "package.json").is_file(), "path": str(unpacked_dir / "package.json")},
                    {"name": "node-modules", "ok": (unpacked_dir / "node_modules").is_dir(), "path": str(unpacked_dir / "node_modules")},
                ]
            )
        else:
            checks.append({"name": "binary", "ok": binary.is_file(), "path": str(binary)})
        checks.extend(ccrouter_doctor_checks(variant.manifest))
        checks.extend(_model_proxy_doctor_checks(variant.manifest))
        credential = variant.manifest.get("credential", {})
        if credential.get("mode") == "stored":
            secrets_path = Path(credential.get("secretsPath") or secrets_path)
            checks.append({"name": "secrets", "ok": secrets_path.is_file() and not secrets_path.is_symlink(), "path": str(secrets_path)})
            if secrets_path.exists() and not secrets_path.is_symlink() and os.name != "nt":
                mode_ok = (secrets_path.stat().st_mode & 0o777) == SECRETS_FILE_MODE
                checks.append({"name": "secrets-mode", "ok": mode_ok, "path": str(secrets_path)})
            if secrets_path.exists():
                try:
                    _validate_secret_file(secrets_path)
                    secret_safe = True
                    secret_detail = ""
                except ValueError as exc:
                    secret_safe = False
                    secret_detail = str(exc)
                checks.append({"name": "secrets-safe", "ok": secret_safe, "path": str(secrets_path), "detail": secret_detail})
        ok = all(check["ok"] for check in checks)
        reports.append({"id": variant.variant_id, "name": variant.name, "ok": ok, "checks": checks})
    return reports

def _node_entry_bun_compat_ok(entry: Path) -> bool:
    try:
        js = entry.read_text(encoding="latin1")
    except OSError:
        return False
    return "Bun." not in js or has_bun_node_compat(js)


def _model_proxy_doctor_checks(manifest: Dict) -> List[Dict[str, object]]:
    config = manifest.get("modelProxy")
    if not isinstance(config, dict):
        return []
    config_path = Path(str(config.get("runtimeConfigPath") or ""))
    log_path = Path(str(config.get("logPath") or ""))
    python_path = Path(str(config.get("pythonExecutable") or ""))
    port = config.get("port", "auto")
    port_ok = port == "auto" or isinstance(port, int)
    return [
        {"name": "model-proxy-config", "ok": config_path.is_file(), "path": str(config_path)},
        {"name": "model-proxy-log-dir", "ok": bool(log_path.parent) and log_path.parent.is_dir(), "path": str(log_path.parent)},
        {"name": "model-proxy-python", "ok": python_path.is_file() and os.access(python_path, os.X_OK), "path": str(python_path)},
        {"name": "model-proxy-port", "ok": port_ok, "path": str(config_path), "detail": str(port)},
    ]

def run_variant(name: str, args: Optional[List[str]] = None, root=None) -> int:
    variant_id = variant_id_from_name(name)
    load_variant(variant_id, root=root)
    wrapper = _canonical_wrapper_path(variant_id, root=root)
    if not wrapper.exists():
        raise ValueError(f"Variant wrapper is missing: {wrapper}")
    result = subprocess.run([str(wrapper), *(args or [])], check=False)
    return result.returncode
