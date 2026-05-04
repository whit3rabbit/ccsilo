"""Variant build and runtime patch helpers."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from .._utils import atomic_write_text_no_symlink, utc_now as _utc_now
from ..binary_patcher.bun_compat import ensure_bun_node_compat
from ..binary_patcher import PatchInputs
from ..binary_patcher.codesign import try_adhoc_sign
from ..providers import get_provider, provider_patch_config, provider_prompt_overlays
from ..workspace import NativeArtifact, file_sha256, native_artifact_from_path, native_binary_filename, write_json
from .builder import (
    apply_patch_refs as _apply_patch_refs,
    can_use_in_place_variant_patch as _can_use_in_place_variant_patch,
    patch_entry_js as _patch_entry_js,
    resolve_source_version as _resolve_source_version,
    workspace_env as _workspace_env,
)
from .constants import (
    VARIANT_METADATA,
    _IN_PLACE_TWEAKS,
    _NATIVE_REGEX_TWEAKS,
    _PROMPT_ONLY_TWEAKS,
    _SETUP_ENV_ONLY_TWEAKS,
    _THEME_PROMPT_TWEAKS,
)
from .model import (
    VariantBuildError,
    VariantBuildResult,
    VariantBuildStage,
    _AlreadySigned,
    _BinaryTweakResult,
    _RuntimePatchResult,
    variant_root,
)
from .tweaks import apply_variant_tweaks, compose_prompt_overlays
from .wrapper import write_variant_config as _write_variant_config, write_wrapper as _write_wrapper

import sys as _sys


def _variants():
    return _sys.modules["cc_extractor.variants"]


def _proxy(name):
    def call(*args, **kwargs):
        return getattr(_variants(), name)(*args, **kwargs)
    return call

__all__ = ['_BuildStageRecorder', '_join_stage_detail', '_classify_theme_prompt_tweaks', '_selected_setup_env_tweaks', '_order_selected_tweaks', '_build_variant_from_manifest', '_download_source_artifact', '_copy_patch_or_unpack_variant_binary', '_should_use_unpacked_node_runtime', '_copy_unpack_node_runtime_variant', '_unpack_node_runtime_variant']

class _BuildStageRecorder:
    def __init__(self, variant_id: str):
        self.variant_id = variant_id
        self.stages: List[VariantBuildStage] = []

    def run(self, name: str, func, *, detail: str = ""):
        stage = VariantBuildStage(name=name, status="running", detail=detail)
        self.stages.append(stage)
        try:
            result = func()
        except VariantBuildError:
            raise
        except Exception as exc:
            stage.status = "failed"
            stage.detail = _join_stage_detail(detail, str(exc))
            raise VariantBuildError(self.variant_id, name, exc, self.stages) from exc
        stage.status = "ok"
        return result

def _join_stage_detail(prefix: str, suffix: str) -> str:
    if prefix and suffix:
        return f"{prefix}: {suffix}"
    return prefix or suffix

def _classify_theme_prompt_tweaks(tweak_ids, *, theme_done: bool, prompt_done: bool):
    applied: List[str] = []
    skipped: List[str] = []
    if "themes" in tweak_ids:
        (applied if theme_done else skipped).append("themes")
    if "prompt-overlays" in tweak_ids:
        (applied if prompt_done else skipped).append("prompt-overlays")
    for tweak_id in _PROMPT_ONLY_TWEAKS:
        if tweak_id in tweak_ids:
            (applied if prompt_done else skipped).append(tweak_id)
    return applied, skipped

def _selected_setup_env_tweaks(tweak_ids):
    return [tweak_id for tweak_id in _SETUP_ENV_ONLY_TWEAKS if tweak_id in tweak_ids]

def _order_selected_tweaks(tweak_ids, values):
    selected = list(tweak_ids)
    return [tweak_id for tweak_id in selected if tweak_id in values]

def _build_variant_from_manifest(
    manifest: Dict,
    *,
    root=None,
    bin_dir: Path,
    source_artifact: Optional[NativeArtifact] = None,
) -> VariantBuildResult:
    variant_id = manifest["id"]
    stages = _BuildStageRecorder(variant_id)
    variant_dir = variant_root(variant_id, root=root)
    native_dir = variant_dir / "native"
    unpacked_dir = variant_dir / "unpacked"
    config_dir = variant_dir / "config"
    tweakcc_dir = variant_dir / "tweakcc"
    tmp_dir = variant_dir / "tmp"
    def prepare_dirs():
        for path in (native_dir, config_dir, tweakcc_dir, tmp_dir, bin_dir):
            path.mkdir(parents=True, exist_ok=True)

    stages.run("prepare directories", prepare_dirs, detail=str(variant_dir))

    if source_artifact is None:
        source_artifact = stages.run(
            "download source",
            lambda: _variants()._download_source_artifact(manifest["source"]["version"], root=root),
            detail=str(manifest["source"]["version"]),
        )
    binary_name = native_binary_filename(source_artifact.platform)
    output_binary = native_dir / binary_name
    runtime = "native"
    entry_path = None

    if _can_use_in_place_variant_patch(source_artifact, manifest):
        runtime_result = stages.run(
            "patch binary",
            lambda: _copy_patch_or_unpack_variant_binary(
                source_artifact,
                output_binary,
                unpacked_dir,
                provider_key=manifest["provider"]["key"],
                tweak_ids=manifest.get("tweaks", []),
            ),
            detail=str(output_binary),
        )
        tweak_result = runtime_result.tweaks
        sign_result = runtime_result.sign_result
        runtime = runtime_result.runtime
        entry_path = runtime_result.entry_path
    elif _should_use_unpacked_node_runtime(source_artifact, manifest):
        runtime_result = stages.run(
            "unpack node runtime",
            lambda: _copy_unpack_node_runtime_variant(
                source_artifact,
                output_binary,
                unpacked_dir,
                provider_key=manifest["provider"]["key"],
                tweak_ids=manifest.get("tweaks", []),
            ),
            detail=str(unpacked_dir),
        )
        tweak_result = runtime_result.tweaks
        sign_result = runtime_result.sign_result
        runtime = runtime_result.runtime
        entry_path = runtime_result.entry_path
    else:
        def rebuild_from_extract():
            with tempfile.TemporaryDirectory(prefix="variant-build-", dir=str(tmp_dir)) as temp_name:
                temp_root = Path(temp_name)
                extract_dir = temp_root / "bundle"
                staged_output = temp_root / binary_name
                manifest_data = _variants().extract_all(
                    str(source_artifact.path),
                    str(extract_dir),
                    source_version=source_artifact.version,
                )
                _apply_patch_refs(extract_dir, manifest.get("patches", []), source_artifact, root=root)
                local_tweak_result = _patch_entry_js(
                    extract_dir,
                    manifest_data,
                    provider_key=manifest["provider"]["key"],
                    tweak_ids=manifest.get("tweaks", []),
                    claude_version=source_artifact.version,
                )
                _variants().pack_bundle(str(extract_dir), str(staged_output), str(source_artifact.path))
                shutil.move(str(staged_output), str(output_binary))
                if os.name != "nt":
                    os.chmod(output_binary, 0o755)
                return local_tweak_result, try_adhoc_sign(str(output_binary))

        tweak_result, sign_result = stages.run(
            "extract patch repack",
            rebuild_from_extract,
            detail=str(output_binary),
        )

    output_sha256 = stages.run("hash output", lambda: file_sha256(output_binary), detail=str(output_binary))
    manifest = dict(manifest)
    manifest["runtime"] = runtime
    manifest["source"] = {
        "version": source_artifact.version,
        "platform": source_artifact.platform,
        "sha256": source_artifact.sha256,
        "path": str(source_artifact.path),
    }
    manifest["outputSha256"] = output_sha256
    manifest["paths"] = {
        "root": str(variant_dir),
        "binary": str(output_binary),
        "unpackedDir": str(unpacked_dir),
        "configDir": str(config_dir),
        "tweakccDir": str(tweakcc_dir),
        "tmpDir": str(tmp_dir),
        "binDir": str(bin_dir),
        "wrapper": str(bin_dir / variant_id),
    }
    if entry_path:
        manifest["paths"]["entryPath"] = str(entry_path)
        manifest["entrySha256"] = file_sha256(Path(entry_path))
    else:
        manifest.pop("entrySha256", None)
    manifest["patchResults"] = {
        "appliedTweaks": tweak_result.applied,
        "skippedTweaks": tweak_result.skipped,
        "missingPromptKeys": tweak_result.missing,
    }
    manifest["codesign"] = {
        "signed": sign_result.signed,
        "reason": sign_result.reason,
        "detail": sign_result.detail,
    }
    stages.run("write runtime config", lambda: _write_variant_config(manifest), detail=str(config_dir))
    wrapper_path = stages.run("write command", lambda: _write_wrapper(manifest), detail=str(bin_dir / variant_id))
    manifest["paths"]["wrapper"] = str(wrapper_path)
    manifest["updatedAt"] = _utc_now()
    stages.run("write setup config", lambda: write_json(variant_dir / VARIANT_METADATA, manifest), detail=str(variant_dir / VARIANT_METADATA))
    variant = stages.run("load setup", lambda: _variants().load_variant(variant_id, root=root), detail=str(variant_dir / VARIANT_METADATA))
    return VariantBuildResult(
        variant=variant,
        binary_path=output_binary,
        wrapper_path=wrapper_path,
        output_sha256=output_sha256,
        applied_tweaks=tweak_result.applied,
        skipped_tweaks=tweak_result.skipped,
        missing_prompt_keys=tweak_result.missing,
        stages=stages.stages,
    )

def _download_source_artifact(version: str, root=None) -> NativeArtifact:
    requested = _resolve_source_version(version, root=root)
    with _workspace_env(root):
        path = _variants().download_binary(requested)
    artifact = native_artifact_from_path(path, root=root)
    if artifact is None:
        raise ValueError(f"Downloaded binary was not found in workspace: {path}")
    return artifact

def _copy_patch_or_unpack_variant_binary(
    source_artifact: NativeArtifact,
    output_binary: Path,
    unpacked_dir: Path,
    *,
    provider_key: str,
    tweak_ids: List[str],
) -> _RuntimePatchResult:
    output_binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_artifact.path, output_binary)
    if os.name != "nt":
        os.chmod(output_binary, 0o755)

    config = provider_patch_config(provider_key) if "themes" in tweak_ids else {}
    provider_overlays = provider_prompt_overlays(provider_key) if "prompt-overlays" in tweak_ids else {}
    overlays = compose_prompt_overlays(provider_overlays, tweak_ids)
    native_regex_tweaks = [tweak_id for tweak_id in tweak_ids if tweak_id in _NATIVE_REGEX_TWEAKS]
    provider = get_provider(provider_key)
    result = _variants().apply_patches(
        PatchInputs(
            binary_path=str(output_binary),
            config=config,
            overlays=overlays,
            regex_tweaks=native_regex_tweaks,
            provider_label=provider.label,
            claude_version=source_artifact.version,
        )
    )
    if result.ok and result.skipped_reason == "macho-grow-not-supported" and (config or overlays or native_regex_tweaks):
        return _unpack_node_runtime_variant(
            source_artifact,
            output_binary,
            unpacked_dir,
            provider_key=provider_key,
            tweak_ids=tweak_ids,
            config=config,
            overlays=overlays,
        )
    if not result.ok:
        raise ValueError(f"binary patch failed: {result.reason}: {result.detail}")

    missing = list(getattr(result, "missing_prompt_keys", []) or [])
    if result.skipped_reason:
        applied, skipped = _classify_theme_prompt_tweaks(tweak_ids, theme_done=False, prompt_done=False)
    else:
        applied, skipped = _classify_theme_prompt_tweaks(
            tweak_ids,
            theme_done=bool(config),
            prompt_done=bool(overlays),
        )
        applied.extend(getattr(result, "curated_applied", []) or [])
        skipped.extend(getattr(result, "curated_skipped", []) or [])
        applied.extend(_selected_setup_env_tweaks(tweak_ids))
    skipped.extend(
        tweak_id for tweak_id in tweak_ids
        if tweak_id not in _THEME_PROMPT_TWEAKS
        and tweak_id not in _NATIVE_REGEX_TWEAKS
        and tweak_id not in _SETUP_ENV_ONLY_TWEAKS
        and tweak_id not in _PROMPT_ONLY_TWEAKS
        and tweak_id not in skipped
    )
    applied = _order_selected_tweaks(tweak_ids, applied)
    skipped = _order_selected_tweaks(tweak_ids, skipped)
    sign_result = try_adhoc_sign(str(output_binary)) if not result.resigned else _AlreadySigned()
    return _RuntimePatchResult(
        tweaks=_BinaryTweakResult(applied, skipped, missing),
        sign_result=sign_result,
    )

def _should_use_unpacked_node_runtime(source_artifact: NativeArtifact, manifest: Dict) -> bool:
    tweak_ids = set(manifest.get("tweaks") or [])
    return (
        source_artifact.platform.startswith("darwin")
        and not manifest.get("patches")
        and not tweak_ids.issubset(_IN_PLACE_TWEAKS)
    )

def _copy_unpack_node_runtime_variant(
    source_artifact: NativeArtifact,
    output_binary: Path,
    unpacked_dir: Path,
    *,
    provider_key: str,
    tweak_ids: List[str],
) -> _RuntimePatchResult:
    output_binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_artifact.path, output_binary)
    if os.name != "nt":
        os.chmod(output_binary, 0o755)

    config = provider_patch_config(provider_key) if "themes" in tweak_ids else {}
    provider_overlays = provider_prompt_overlays(provider_key) if "prompt-overlays" in tweak_ids else {}
    overlays = compose_prompt_overlays(provider_overlays, tweak_ids)
    return _unpack_node_runtime_variant(
        source_artifact,
        output_binary,
        unpacked_dir,
        provider_key=provider_key,
        tweak_ids=tweak_ids,
        config=config,
        overlays=overlays,
    )

def _unpack_node_runtime_variant(
    source_artifact: NativeArtifact,
    output_binary: Path,
    unpacked_dir: Path,
    *,
    provider_key: str,
    tweak_ids: List[str],
    config: Dict,
    overlays: Optional[Dict[str, str]],
) -> _RuntimePatchResult:
    provider = get_provider(provider_key)
    result = _variants().unpack_and_patch(
        pristine_binary_path=str(source_artifact.path),
        unpacked_dir=str(unpacked_dir),
        managed_root=str(unpacked_dir.parent),
        config=config,
        overlays=overlays,
    )
    missing = list(result.patch.prompt_missing or [])
    applied, skipped = _classify_theme_prompt_tweaks(
        tweak_ids,
        theme_done=bool(result.patch.theme_replaced),
        prompt_done=bool(result.patch.prompt_replaced),
    )
    applied.extend(_selected_setup_env_tweaks(tweak_ids))

    remaining_tweaks = [
        tweak_id for tweak_id in tweak_ids
        if tweak_id not in _THEME_PROMPT_TWEAKS
        and tweak_id not in _PROMPT_ONLY_TWEAKS
        and tweak_id not in _SETUP_ENV_ONLY_TWEAKS
    ]
    if remaining_tweaks:
        entry_path = Path(result.entry_path)
        js = entry_path.read_text(encoding="latin1")
        extra = apply_variant_tweaks(
            js,
            tweak_ids=remaining_tweaks,
            config={},
            overlays={},
            provider_label=provider.label,
            claude_version=source_artifact.version,
        )
        atomic_write_text_no_symlink(entry_path, ensure_bun_node_compat(extra.js), encoding="latin1")
        applied.extend(extra.applied)
        skipped.extend(extra.skipped)
        missing.extend(extra.missing)
    applied = _order_selected_tweaks(tweak_ids, applied)
    skipped = _order_selected_tweaks(tweak_ids, skipped)

    return _RuntimePatchResult(
        tweaks=_BinaryTweakResult(applied, skipped, missing),
        sign_result=_AlreadySigned(),
        runtime="node",
        entry_path=result.entry_path,
    )
