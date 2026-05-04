"""Variant public lifecycle workflows."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..binary_patcher.bun_compat import has_bun_node_compat
from .._utils import safe_read_json as _safe_read_json, utc_now as _utc_now
from ..providers import build_provider_env, get_provider, normalize_mcp_ids, provider_default_variant_name
from ..workspace import NativeArtifact, read_json, workspace_root
from .builder import patch_refs_for_profile as _patch_refs_for_profile
from .constants import VARIANT_METADATA
from .model import (
    Variant,
    VariantBuildResult,
    default_bin_dir,
    validate_variant_manifest,
    variant_id_from_name,
    variant_root,
)
from .tweaks import default_tweak_ids_for_provider, env_for_tweaks, normalize_tweak_ids, sync_tweak_env
from .wrapper import (
    SECRETS_FILE,
    SECRETS_FILE_MODE,
    validate_secret_file as _validate_secret_file,
    write_secrets as _write_secrets,
)

import sys as _sys


def _variants():
    return _sys.modules["cc_extractor.variants"]


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
    root=None,
    source_artifact: Optional[NativeArtifact] = None,
) -> VariantBuildResult:
    provider = get_provider(provider_key)
    name = name or provider_default_variant_name(provider_key)
    variant_id = variant_id_from_name(name)
    path = variant_root(variant_id, root=root)
    if path.exists() and not force:
        raise ValueError(f"Variant {variant_id} already exists")

    provider_env = build_provider_env(
        provider_key,
        base_url=base_url,
        api_key=api_key,
        credential_env=credential_env,
        store_secret=store_secret,
        model_overrides=model_overrides,
        extra_env=extra_env,
    )
    tweak_ids = normalize_tweak_ids(tweaks or default_tweak_ids_for_provider(provider.key))
    selected_mcp_ids = normalize_mcp_ids(mcp_ids or [])
    safe_env = dict(provider_env.env)
    safe_env.update(env_for_tweaks(tweak_ids, tweak_options))
    now = _utc_now()
    existing = _safe_read_json(path / VARIANT_METADATA)
    patch_refs = _patch_refs_for_profile(patch_profile_id, root=root)

    manifest = {
        "schemaVersion": 1,
        "id": variant_id,
        "name": name.strip(),
        "provider": {
            "key": provider.key,
            "label": provider.label,
        },
        "source": {
            "version": claude_version or "latest",
        },
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
        "credential": provider_env.credential,
        "paths": {},
        "createdAt": existing.get("createdAt") if existing else now,
        "updatedAt": now,
    }
    validate_variant_manifest(manifest)

    path.mkdir(parents=True, exist_ok=True)
    if provider_env.secret_env:
        _write_secrets(path / SECRETS_FILE, provider_env.secret_env)
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

def apply_variant(variant_id: str, *, claude_version: Optional[str] = None, root=None) -> VariantBuildResult:
    variant = load_variant(variant_id, root=root)
    return _apply_variant_manifest(variant.manifest, claude_version=claude_version, root=root)

def _apply_variant_manifest(manifest: Dict, *, claude_version: Optional[str] = None, root=None) -> VariantBuildResult:
    manifest = dict(manifest)
    if claude_version:
        manifest["source"] = dict(manifest["source"])
        manifest["source"]["version"] = claude_version
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
    )

def update_variants(
    name: Optional[str] = None,
    *,
    all_variants: bool = False,
    claude_version: Optional[str] = None,
    root=None,
) -> List[VariantBuildResult]:
    if all_variants:
        return [
            _apply_variant_manifest(variant.manifest, claude_version=claude_version, root=root)
            for variant in scan_variants(root)
        ]
    if not name:
        raise ValueError("Pass a variant name or --all")
    return [apply_variant(variant_id_from_name(name), claude_version=claude_version, root=root)]

def remove_variant(name: str, *, yes: bool = False, root=None) -> bool:
    if not yes:
        raise ValueError("Pass --yes to remove a variant")
    variant_id = variant_id_from_name(name)
    try:
        variant = load_variant(variant_id, root=root)
    except ValueError:
        return False
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

def run_variant(name: str, args: Optional[List[str]] = None, root=None) -> int:
    variant_id = variant_id_from_name(name)
    load_variant(variant_id, root=root)
    wrapper = _canonical_wrapper_path(variant_id, root=root)
    if not wrapper.exists():
        raise ValueError(f"Variant wrapper is missing: {wrapper}")
    try:
        result = subprocess.run([str(wrapper), *(args or [])], check=False, timeout=300)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Variant '{name}' timed out after 300s") from exc
    return result.returncode
