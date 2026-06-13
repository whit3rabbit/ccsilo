"""TuiState dataclass and refresh logic."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..download_index import download_versions, load_download_index
from ..providers import RTK_ID, detect_local_integrations, normalize_integration_ids, normalize_mcp_ids
from ..variant_tweaks import DEFAULT_TWEAK_IDS
from ..variant_tweaks import DASHBOARD_TWEAK_IDS
from ..variants import CCR_PACKAGE_DEFAULT
from ..variants import list_variant_providers, scan_variants
from ..variants.model import Variant
from ..workspace import (
    DashboardTweakProfile,
    NativeArtifact,
    PatchPackage,
    PatchProfile,
    scan_extractions,
    scan_native_downloads,
    scan_npm_downloads,
    scan_dashboard_tweak_profiles,
    scan_patch_packages,
    scan_patch_profiles,
)
from ._const import DEFAULT_THEME_ID, SOURCE_LATEST
from .model_picker import normalize_model_target
from .themes import normalize_theme_id


@dataclass
class TuiState:
    mode: str = "dashboard"
    selected_index: int = 0
    message: str = ""
    theme_id: str = DEFAULT_THEME_ID
    native_artifacts: List[NativeArtifact] = field(default_factory=list)
    patch_packages: List[PatchPackage] = field(default_factory=list)
    patch_profiles: List[PatchProfile] = field(default_factory=list)
    dashboard_tweak_profiles: List[DashboardTweakProfile] = field(default_factory=list)
    variants: List[Variant] = field(default_factory=list)
    variant_providers: List[Dict[str, Any]] = field(default_factory=list)
    download_index: dict = field(default_factory=dict)
    download_versions: List[str] = field(default_factory=list)
    download_index_loaded: bool = False
    download_index_checked_live: bool = False
    selected_source_index: int = 0
    selected_patch_indexes: List[int] = field(default_factory=list)
    selected_dashboard_tweak_ids: List[str] = field(default_factory=list)
    counts: str = ""
    dashboard_step: int = 0
    dashboard_source_kind: str = SOURCE_LATEST
    dashboard_source_version: str = ""
    dashboard_source_artifact_index: int = 0
    dashboard_profile_name: str = ""
    dashboard_loaded_profile_id: str = ""
    dashboard_delete_confirm_id: str = ""
    variant_step: int = 0
    variant_provider_index: int = 0
    variant_provider_search_text: str = ""
    variant_provider_search_active: bool = False
    variant_provider_filter: str = "all"
    variant_name: str = ""
    variant_claude_version: str = "latest"
    variant_base_url: str = ""
    variant_credential_env: str = ""
    variant_api_key: str = ""
    variant_store_secret: bool = False
    variant_ccrouter_mode: str = "managed"
    variant_ccrouter_config: str = "empty"
    variant_ccrouter_package: str = CCR_PACKAGE_DEFAULT
    variant_ccrouter_port: str = "auto"
    variant_ccrouter_autostart: bool = True
    variant_model_proxy: str = ""
    variant_model_proxy_port: str = "auto"
    variant_model_overrides: Dict[str, str] = field(default_factory=dict)
    variant_model_choices: List[str] = field(default_factory=list)
    variant_model_search_text: str = ""
    variant_model_search_active: bool = False
    variant_model_target: str = "opus"
    variant_install_command: bool = False
    variant_install_choice_initialized: bool = False
    variant_install_alias: str = ""
    variant_install_alias_customized: bool = False
    selected_variant_mcp_ids: List[str] = field(default_factory=list)
    selected_variant_integration_ids: List[str] = field(
        default_factory=lambda: [RTK_ID] if "rtk-shell-prefix" in DEFAULT_TWEAK_IDS else []
    )
    variant_integration_status: Dict[str, Any] = field(default_factory=dict)
    variant_integration_install_confirm: str = ""
    pending_variant_integration_install_id: str = ""
    selected_variant_tweaks: List[str] = field(default_factory=lambda: list(DEFAULT_TWEAK_IDS))
    selected_setup_id: Optional[str] = None
    setup_health: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    setup_search_text: str = ""
    setup_search_active: bool = False
    setup_provider_filter: str = "all"
    setup_sort_key: str = "name"
    setup_command_alias: str = ""
    help_return_mode: str = "setup-manager"
    delete_confirm_text: str = ""
    setup_upgrade_target: str = "latest"
    pending_run_setup_id: Optional[str] = None
    pending_run_command: List[str] = field(default_factory=list)
    busy_title: str = ""
    busy_detail: str = ""
    busy_ticks: int = 0
    busy_future: Any = None
    last_action_summary: List[str] = field(default_factory=list)
    last_action_log: List[str] = field(default_factory=list)
    tweaks_variant_id: Optional[str] = None
    tweaks_baseline: Tuple[str, ...] = ()
    tweaks_pending: List[str] = field(default_factory=list)
    tweak_filter: str = "recommended"
    tweak_search: str = ""
    tweak_search_active: bool = False
    tweak_apply_preview: bool = False
    last_tweak_result: Optional[Dict[str, Any]] = None
    models_variant_id: Optional[str] = None
    models_baseline: Dict[str, str] = field(default_factory=dict)
    models_pending: Dict[str, str] = field(default_factory=dict)
    models_choices: List[str] = field(default_factory=list)
    models_search_text: str = ""
    models_search_active: bool = False
    models_target: str = "opus"
    inspect_delete_confirm_path: str = ""

    def __post_init__(self):
        if not self.download_index_loaded and (self.download_index or self.download_versions):
            self.download_index_loaded = True

    def refresh(self):
        self.theme_id = normalize_theme_id(self.theme_id)
        self.native_artifacts = scan_native_downloads()
        npm_count = len(scan_npm_downloads())
        extraction_count = len(scan_extractions())
        self.patch_packages = scan_patch_packages()
        self.patch_profiles = scan_patch_profiles()
        self.dashboard_tweak_profiles = scan_dashboard_tweak_profiles()
        self.variants = scan_variants()
        self.variant_providers = list_variant_providers()
        if not self.download_index_loaded:
            self.download_index = load_download_index()
            self.download_versions = download_versions(self.download_index, "binary")
            self.download_index_loaded = True
        self.counts = (
            f"Native: {len(self.native_artifacts)}  "
            f"NPM: {npm_count}  "
            f"Extractions: {extraction_count}  "
            f"Patch bundles: {len(self.patch_packages)}  "
            f"Profiles: {len(self.dashboard_tweak_profiles)}  "
            f"Setups: {len(self.variants)}"
        )
        setup_ids = {variant.variant_id for variant in self.variants}
        self.setup_health = {
            setup_id: summary
            for setup_id, summary in self.setup_health.items()
            if setup_id in setup_ids
        }
        provider_keys = {
            str((variant.manifest.get("provider") or {}).get("key") or "")
            for variant in self.variants
            if variant.manifest
        }
        if self.setup_provider_filter != "all" and self.setup_provider_filter not in provider_keys:
            self.setup_provider_filter = "all"
        if self.setup_sort_key not in {"name", "provider", "health", "updated", "version"}:
            self.setup_sort_key = "name"
        if self.variant_provider_filter not in {"all", "recommended", "cloud", "local", "model-map", "mcp"}:
            self.variant_provider_filter = "all"
        self.variant_model_target = normalize_model_target(self.variant_model_target)
        self.models_target = normalize_model_target(self.models_target)
        if self.selected_setup_id not in setup_ids:
            self.selected_setup_id = self.variants[0].variant_id if self.variants else None
        if self.tweaks_variant_id not in setup_ids and self.mode not in {"tweaks-edit", "tweak-editor"}:
            self.tweaks_variant_id = None
            self.tweaks_baseline = ()
            self.tweaks_pending = []
            self.tweak_search_active = False
            self.tweak_apply_preview = False
        if self.models_variant_id not in setup_ids and self.mode != "models-edit":
            self.models_variant_id = None
            self.models_baseline = {}
            self.models_pending = {}
            self.models_choices = []
            self.models_search_text = ""
            self.models_search_active = False
            self.models_target = "opus"
        self.selected_patch_indexes = [
            index for index in self.selected_patch_indexes
            if 0 <= index < len(self.patch_packages)
        ]
        available_dashboard_tweaks = set(DASHBOARD_TWEAK_IDS)
        self.selected_dashboard_tweak_ids = [
            tweak_id for tweak_id in self.selected_dashboard_tweak_ids
            if tweak_id in available_dashboard_tweaks
        ]
        try:
            self.selected_variant_mcp_ids = normalize_mcp_ids(self.selected_variant_mcp_ids)
        except ValueError:
            self.selected_variant_mcp_ids = []
        try:
            self.selected_variant_integration_ids = normalize_integration_ids(self.selected_variant_integration_ids)
        except ValueError:
            self.selected_variant_integration_ids = []
        self.variant_integration_status = detect_local_integrations()
        self.selected_index = self._clamp(self.selected_index, self.item_count())
        self.selected_source_index = self._clamp(self.selected_source_index, len(self.native_artifacts))
        self.dashboard_source_artifact_index = self._clamp(
            self.dashboard_source_artifact_index,
            len(self.native_artifacts),
        )
        self.variant_provider_index = self._clamp(
            self.variant_provider_index,
            len(self.variant_providers),
        )

    def item_count(self):
        # Local import avoids a circular module-load on package init.
        from .options import (
            dashboard_options,
            setup_detail_options,
            setup_manager_options,
            tweaks_edit_options,
            models_edit_options,
            variant_options,
        )

        if self.mode == "setup-manager":
            return len(setup_manager_options(self))
        if self.mode == "setup-detail":
            return len(setup_detail_options(self))
        if self.mode == "create-preview":
            return 4
        if self.mode in {"loading", "busy", "upgrade-preview", "delete-confirm", "command-alias", "inspect-delete-confirm", "health-result", "logs", "help", "error"}:
            return 1
        if self.mode == "dashboard":
            return len(dashboard_options(self))
        if self.mode in {"inspect", "extract", "patch-source"}:
            return len(self.native_artifacts)
        if self.mode == "patch-package":
            return len(self.patch_packages)
        if self.mode in {"variants", "first-run-setup"}:
            return len(variant_options(self))
        if self.mode == "tweaks-source":
            return len(self.variants)
        if self.mode in {"tweaks-edit", "tweak-editor"}:
            return len(tweaks_edit_options(self))
        if self.mode == "models-edit":
            return len(models_edit_options(self))
        return 1

    def move(self, offset):
        count = self.item_count()
        if count < 1:
            self.selected_index = 0
            return
        self.selected_index = max(0, min(self.selected_index + offset, count - 1))

    def _clamp(self, value, count):
        if count < 1:
            return 0
        return max(0, min(value, count - 1))
