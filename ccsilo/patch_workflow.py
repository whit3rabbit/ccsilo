"""Extract, patch, and repack a native Claude Code binary in one pass."""

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

from ._utils import atomic_write_text_no_symlink, safe_child_path, utc_now as _utc_now
from .bundler import pack_bundle
from .bun_extract import read_js_modules
from .extractor import extract_all
from .patcher import apply_patch
from .patches._registry import REGISTRY as PATCH_REGISTRY
from .variant_tweaks import DASHBOARD_TWEAK_IDS, apply_variant_tweaks_to_modules
from .workspace import (
    NativeArtifact,
    PATCHED_METADATA,
    PatchPackage,
    ensure_workspace,
    file_sha256,
    native_binary_filename,
    patched_output_path,
    patchset_slug,
    write_patched_metadata,
    write_json,
)


@dataclass
class PatchWorkflowResult:
    output_path: Path
    metadata_path: Path
    output_sha256: str
    patchset: str


@dataclass
class DashboardTweakWorkflowResult:
    output_path: Path
    metadata_path: Path
    output_sha256: str
    patchset: str
    applied_tweaks: List[str]
    skipped_tweaks: List[str]
    missing_prompt_keys: List[str]


def apply_patch_packages_to_native(
    source_artifact: NativeArtifact,
    patch_packages: Sequence[PatchPackage],
    root=None,
) -> PatchWorkflowResult:
    if not patch_packages:
        raise ValueError("Select at least one patch package")

    workspace = ensure_workspace(root)
    tmp_root = workspace / "tmp"
    patchset = patchset_slug(patch_packages)

    with tempfile.TemporaryDirectory(prefix="patch-", dir=str(tmp_root)) as temp_dir:
        temp_root = Path(temp_dir)
        extract_dir = temp_root / "bundle"
        staged_output = temp_root / native_binary_filename(source_artifact.platform)

        extract_all(
            str(source_artifact.path),
            str(extract_dir),
            source_version=source_artifact.version,
        )

        for package in patch_packages:
            apply_patch(
                package.path,
                extract_dir,
                binary_path=source_artifact.path,
                source_version=source_artifact.version,
                source_platform=source_artifact.platform,
            )

        pack_bundle(str(extract_dir), str(staged_output), str(source_artifact.path))
        output_sha256 = file_sha256(staged_output)
        final_path = patched_output_path(
            source_artifact.version,
            source_artifact.platform,
            source_artifact.sha256,
            patchset,
            output_sha256,
            root=root,
            filename=source_artifact.path.name,
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_output), str(final_path))
        if os.name != "nt":
            os.chmod(final_path, 0o755)

    metadata_path = write_patched_metadata(
        final_path,
        source_artifact,
        patch_packages,
        output_sha256,
        patchset,
    )
    return PatchWorkflowResult(
        output_path=final_path,
        metadata_path=metadata_path,
        output_sha256=output_sha256,
        patchset=patchset,
    )


def apply_dashboard_tweaks_to_native(
    source_artifact: NativeArtifact,
    tweak_ids: Iterable[str],
    root=None,
) -> DashboardTweakWorkflowResult:
    normalized_ids = normalize_dashboard_tweak_ids(tweak_ids)

    workspace = ensure_workspace(root)
    tmp_root = workspace / "tmp"
    patchset = tweakset_slug(normalized_ids)

    with tempfile.TemporaryDirectory(prefix="dashboard-tweaks-", dir=str(tmp_root)) as temp_dir:
        temp_root = Path(temp_dir)
        extract_dir = temp_root / "bundle"
        staged_output = temp_root / native_binary_filename(source_artifact.platform)

        manifest_data = extract_all(
            str(source_artifact.path),
            str(extract_dir),
            source_version=source_artifact.version,
        )
        entry_rel, js_modules = read_js_modules(extract_dir, manifest_data)
        tweak_result = apply_variant_tweaks_to_modules(
            js_modules,
            entry_path=entry_rel,
            tweak_ids=normalized_ids,
            config={},
            overlays={},
            provider_label="ccsilo",
            claude_version=source_artifact.version,
        )
        for rel_path, patched_js in tweak_result.js_by_path.items():
            module_path = safe_child_path(extract_dir, rel_path, label="module path")
            atomic_write_text_no_symlink(module_path, patched_js)

        pack_bundle(str(extract_dir), str(staged_output), str(source_artifact.path))
        output_sha256 = file_sha256(staged_output)
        final_path = patched_output_path(
            source_artifact.version,
            source_artifact.platform,
            source_artifact.sha256,
            patchset,
            output_sha256,
            root=root,
            filename=source_artifact.path.name,
        )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged_output), str(final_path))
        if os.name != "nt":
            os.chmod(final_path, 0o755)

    metadata_path = write_dashboard_tweak_metadata(
        final_path,
        source_artifact,
        normalized_ids,
        tweak_result.applied,
        tweak_result.skipped,
        tweak_result.missing,
        output_sha256,
        patchset,
    )
    return DashboardTweakWorkflowResult(
        output_path=final_path,
        metadata_path=metadata_path,
        output_sha256=output_sha256,
        patchset=patchset,
        applied_tweaks=tweak_result.applied,
        skipped_tweaks=tweak_result.skipped,
        missing_prompt_keys=tweak_result.missing,
    )


def normalize_dashboard_tweak_ids(tweak_ids: Iterable[str]) -> List[str]:
    allowed = set(DASHBOARD_TWEAK_IDS)
    normalized: List[str] = []
    for tweak_id in tweak_ids:
        if tweak_id not in allowed:
            raise ValueError(f"Unsupported dashboard tweak: {tweak_id}")
        if tweak_id not in normalized:
            normalized.append(tweak_id)
    if not normalized:
        raise ValueError("Select at least one dashboard patch")
    return normalized


def tweakset_slug(tweak_ids: Sequence[str]) -> str:
    if not tweak_ids:
        return "none"

    raw = "__".join(tweak_ids)
    slug = re.sub(r"[^A-Za-z0-9_.@-]+", "-", raw).strip("-")
    if len(slug) <= 96:
        return slug
    return f"{slug[:64]}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def write_dashboard_tweak_metadata(
    output_path: os.PathLike,
    source_artifact: NativeArtifact,
    tweak_ids: Sequence[str],
    applied_tweaks: Sequence[str],
    skipped_tweaks: Sequence[str],
    missing_prompt_keys: Sequence[str],
    output_sha256: str,
    patchset: str,
) -> Path:
    payload = {
        "kind": "native-dashboard-tweaked",
        "version": source_artifact.version,
        "platform": source_artifact.platform,
        "sourceSha256": source_artifact.sha256,
        "sourcePath": str(source_artifact.path),
        "outputSha256": output_sha256,
        "outputPath": str(output_path),
        "patchset": patchset,
        "tweakIds": list(tweak_ids),
        "tweaks": [
            {
                "id": tweak_id,
                "name": PATCH_REGISTRY[tweak_id].name,
            }
            for tweak_id in tweak_ids
        ],
        "appliedTweaks": list(applied_tweaks),
        "skippedTweaks": list(skipped_tweaks),
        "missingPromptKeys": list(missing_prompt_keys),
        "createdAt": _utc_now(),
    }
    metadata_path = Path(output_path).parent / PATCHED_METADATA
    write_json(metadata_path, payload)
    return metadata_path


def _entry_path(extract_dir: Path, manifest_data: dict) -> Path:
    entry = manifest_data.get("entryPoint")
    if not entry:
        raise ValueError("Extracted bundle manifest did not include entryPoint")
    try:
        path = safe_child_path(extract_dir, entry, label="entryPoint")
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    if not path.exists():
        raise ValueError(f"Entry JS not found in extracted bundle: {entry}")
    return path
