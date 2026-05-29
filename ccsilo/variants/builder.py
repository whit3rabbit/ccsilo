"""Internal builder helpers used by the variant action layer.

These functions don't reference any monkey-patched name (the patched
``apply_patches``/``unpack_and_patch``/``_download_source_artifact`` symbols
all live in :mod:`ccsilo.variants` next to their callers), so they can
sit in their own module without breaking test fixtures.
"""

import contextlib
import os
from pathlib import Path
from typing import Dict, List, Optional

from .._utils import atomic_write_text_no_symlink, safe_child_path, safe_read_json as _safe_read_json
from ..patcher import apply_patch
from ..providers import (
    get_provider,
    provider_patch_config,
    provider_prompt_overlays,
)
from ..workspace import (
    NativeArtifact,
    load_patch_profile,
    read_json,
    scan_patch_packages,
    workspace_root,
)
from .tweaks import (
    ENV_TWEAK_IDS,
    PROMPT_ONLY_TWEAK_IDS,
    SETUP_CONFIG_TWEAK_IDS,
    SETUP_ONLY_TWEAK_IDS,
    SETUP_ENV_ONLY_TWEAK_IDS,
    TweakResult,
    apply_variant_tweaks,
    compose_prompt_overlays,
)


IN_PLACE_TWEAK_IDS = {
    "themes",
    "prompt-overlays",
    "hide-startup-banner",
    "hide-startup-clawd",
    "suppress-native-installer-warning",
    "suppress-prompt-caching-warning",
    "suppress-model-launch-notice",
    "mid-conversation-system-422-fallback",
    "mcp-non-blocking",
    "mcp-batch-size",
    *PROMPT_ONLY_TWEAK_IDS,
    *ENV_TWEAK_IDS,
    *SETUP_ONLY_TWEAK_IDS,
}


def resolve_source_version(version: str, root=None) -> str:
    version = version or "latest"
    if version != "stable":
        return version
    index_path = workspace_root(root) / "download-index.json"
    index = _safe_read_json(index_path)
    stable = index.get("binary", {}).get("stable")
    if isinstance(stable, str) and stable:
        return stable
    raise ValueError("stable channel is not available in the download index")


def patch_refs_for_profile(profile_id: Optional[str], root=None) -> List[Dict[str, str]]:
    if not profile_id:
        return []
    profile = load_patch_profile(profile_id, root=root)
    return list(profile.patches)


def apply_patch_refs(
    extract_dir: Path,
    refs: List[Dict[str, str]],
    source_artifact: NativeArtifact,
    root=None,
) -> None:
    if not refs:
        return
    packages = {(package.patch_id, package.version): package for package in scan_patch_packages(root)}
    for ref in refs:
        package = packages.get((ref["id"], ref["version"]))
        if package is None:
            raise ValueError(f"Missing patch package {ref['id']}@{ref['version']}")
        apply_patch(
            package.path,
            extract_dir,
            binary_path=source_artifact.path,
            source_version=source_artifact.version,
            source_platform=source_artifact.platform,
        )


def patch_entry_js(extract_dir: Path, manifest_data: Dict, *, provider_key: str, tweak_ids: List[str], claude_version: Optional[str] = None):
    entry = manifest_data.get("entryPoint")
    if not entry:
        manifest_path = extract_dir / ".bundle_manifest.json"
        if manifest_path.exists():
            entry = read_json(manifest_path).get("entryPoint")
    if not entry:
        raise ValueError("Extracted bundle manifest did not include entryPoint")
    try:
        entry_path = safe_child_path(extract_dir, entry, label="entryPoint")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not entry_path.exists():
        raise ValueError(f"Entry JS not found in extracted bundle: {entry}")
    js = entry_path.read_text(encoding="utf-8")
    provider = get_provider(provider_key)
    provider_overlays = provider_prompt_overlays(provider_key) if "prompt-overlays" in tweak_ids else {}
    setup_only_ids = {*SETUP_ENV_ONLY_TWEAK_IDS, *SETUP_CONFIG_TWEAK_IDS}
    setup_only_tweaks = [tweak_id for tweak_id in tweak_ids if tweak_id in setup_only_ids]
    patch_tweak_ids = [tweak_id for tweak_id in tweak_ids if tweak_id not in setup_only_ids]
    if patch_tweak_ids:
        result = apply_variant_tweaks(
            js,
            tweak_ids=patch_tweak_ids,
            config=provider_patch_config(provider_key),
            overlays=compose_prompt_overlays(provider_overlays, tweak_ids),
            provider_label=provider.label,
            claude_version=claude_version,
        )
    else:
        result = TweakResult(js=js, applied=[], skipped=[], missing=[])
    atomic_write_text_no_symlink(entry_path, result.js)
    if setup_only_tweaks:
        return TweakResult(
            js=result.js,
            applied=[*result.applied, *setup_only_tweaks],
            skipped=result.skipped,
            missing=result.missing,
        )
    return result


def can_use_in_place_variant_patch(source_artifact: NativeArtifact, manifest: Dict) -> bool:
    requested_tweaks = set(manifest.get("tweaks") or [])
    return (
        source_artifact.platform.startswith("darwin")
        and not manifest.get("patches")
        and requested_tweaks.issubset(IN_PLACE_TWEAK_IDS)
    )


@contextlib.contextmanager
def workspace_env(root):
    if root is None:
        yield
        return
    old_value = os.environ.get("CCSILO_WORKSPACE")
    os.environ["CCSILO_WORKSPACE"] = str(workspace_root(root))
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("CCSILO_WORKSPACE", None)
        else:
            os.environ["CCSILO_WORKSPACE"] = old_value
