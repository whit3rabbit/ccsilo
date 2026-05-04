"""Variant lifecycle facade with monkey-patch-compatible build globals."""

# ruff: noqa: F401

from ..binary_patcher import PatchInputs, apply_patches
from ..binary_patcher.unpack_and_patch import unpack_and_patch
from ..bundler import pack_bundle
from ..downloader import download_binary
from ..extractor import extract_all
from ..providers import normalize_mcp_ids
from .build import (
    _BuildStageRecorder,
    _build_variant_from_manifest,
    _classify_theme_prompt_tweaks,
    _copy_patch_or_unpack_variant_binary,
    _copy_unpack_node_runtime_variant,
    _download_source_artifact,
    _join_stage_detail,
    _order_selected_tweaks,
    _selected_setup_env_tweaks,
    _should_use_unpacked_node_runtime,
    _unpack_node_runtime_variant,
)
from .constants import VARIANT_METADATA
from .lifecycle import (
    _apply_variant_manifest,
    _canonical_wrapper_path,
    _resolve_bin_dir,
    apply_variant,
    create_variant,
    doctor_variant,
    load_variant,
    remove_variant,
    run_variant,
    scan_variants,
    update_variants,
)
from .model import (
    Variant,
    VariantBuildError,
    VariantBuildResult,
    VariantBuildStage,
    default_bin_dir,
    list_variant_providers,
    validate_variant_manifest,
    variant_id_from_name,
    variant_root,
)
from .model_updates import (
    _model_env_for_existing_setup,
    _normalize_model_overrides,
    _sync_existing_compatibility_model_defaults,
    _validate_existing_model_mapping,
    update_variant_models,
)
from .tweaks import DEFAULT_TWEAK_IDS, apply_variant_tweaks, default_tweak_ids_for_provider, env_for_tweaks, normalize_tweak_ids
from .wrapper import SECRETS_FILE

__all__ = [
    "DEFAULT_TWEAK_IDS",
    "SECRETS_FILE",
    "VARIANT_METADATA",
    "Variant",
    "VariantBuildError",
    "VariantBuildResult",
    "VariantBuildStage",
    "apply_variant",
    "apply_variant_tweaks",
    "create_variant",
    "default_bin_dir",
    "default_tweak_ids_for_provider",
    "doctor_variant",
    "env_for_tweaks",
    "list_variant_providers",
    "load_variant",
    "normalize_tweak_ids",
    "normalize_mcp_ids",
    "remove_variant",
    "run_variant",
    "scan_variants",
    "update_variants",
    "update_variant_models",
    "validate_variant_manifest",
    "variant_id_from_name",
    "variant_root",
]
