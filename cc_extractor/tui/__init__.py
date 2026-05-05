"""Interactive TUI for cc-extractor.

The action layer (mode dispatchers, build runners, key handlers, monkey-patch
re-exports) lives in this ``__init__`` module so test fixtures can do
``monkeypatch.setattr(tui, "create_variant", fake)`` and have the patch propagate
to internal call sites.

Pure helpers live in submodules (``state``, ``themes``, ``options``,
``rendering``, ``nav``, ``keys``, ``dashboard``, ``variant_actions``) and are
re-exported below to keep the existing ``tui._foo`` test API stable.
"""

# ruff: noqa: F401

import subprocess
import sys

__all__ = [
    "TUI_THEMES", "TuiTheme",
    "apply_dashboard_tweaks_to_native", "apply_patch_packages_to_native", "apply_variant",
    "create_variant", "default_install_dir", "doctor_variant", "install_variant_command", "load_variant", "remove_variant", "update_variant_models", "update_variants",
    "download_binary", "download_versions", "extract_all",
    "load_download_index", "list_variant_providers", "parse_bun_binary",
    "provider_default_variant_name", "refresh_download_index", "scan_variants",
    "CURATED_TWEAK_IDS", "DASHBOARD_TWEAK_IDS", "DEFAULT_TWEAK_IDS",
    "DashboardTweakProfile", "NativeArtifact", "PatchPackage", "PatchProfile",
    "delete_dashboard_tweak_profile", "delete_native_download", "delete_patch_profile", "extraction_paths",
    "load_dashboard_tweak_profile", "load_patch_profile",
    "load_tui_settings", "native_artifact_from_path", "rename_dashboard_tweak_profile", "rename_patch_profile",
    "save_dashboard_tweak_profile", "save_patch_profile", "save_tui_settings", "scan_dashboard_tweak_profiles",
    "scan_extractions", "scan_native_downloads", "scan_npm_downloads", "scan_patch_packages",
    "scan_patch_profiles", "short_sha", "workspace_root",
    "DASHBOARD_STEPS", "DEFAULT_THEME_ID", "MenuOption", "SOURCE_ARTIFACT",
    "SOURCE_LATEST", "SOURCE_VERSION", "TABS", "TAB_MODES", "THEME_ORDER",
    "VARIANT_MODEL_FIELDS", "VARIANT_STEPS",
    "_active_tab", "_body_text", "_footer_lines", "_footer_text", "_gauge_widget",
    "_list_widget", "_tabs_widget", "_normalize_theme_id", "_theme_name",
    "_dashboard_options", "_dashboard_source_artifact", "_dashboard_tweak_ids", "_loaded_profile",
    "_dashboard_tweak_profile_by_id", "_dashboard_tweak_profile_missing_ids",
    "_profile_by_id", "_profile_missing_refs", "_profile_refs_by_key",
    "_selected_dashboard_tweaks", "_selected_patch_refs", "_selected_setup_option", "_selected_setup_variant",
    "_variant_model_display_value", "_variant_options",
    "_selected_artifact",
    "_run_quiet",
    "_advance_dashboard", "_create_dashboard_profile", "_dashboard_artifact_for_run",
    "_delete_dashboard_profile", "_load_dashboard_profile", "_overwrite_dashboard_profile",
    "_refresh_dashboard_index", "_rename_dashboard_profile", "_require_dashboard_patches",
    "_reset_dashboard", "_toggle_dashboard_patch", "_toggle_dashboard_tweak",
    "_dashboard_accepts_profile_text", "_dashboard_backspace",
    "_variant_accepts_text", "_variant_append_text", "_variant_backspace",
    "_models_accepts_text", "_models_append_text", "_models_backspace",
    "_activate_extract", "_activate_inspect", "_activate_patch_source",
    "_apply_tweaks", "_discard_tweaks", "_enter_tweaks_for_variant",
    "_go_back", "_move_tab", "_selected_tweaks_source_variant_id",
    "_set_mode", "_source_artifact", "_toggle_patch", "_toggle_tweak",
    "_tweaks_edit_options", "_tweaks_source_options",
    "_selected_dashboard_option", "_selected_dashboard_packages",
    "_selected_variant_option", "_selected_variant_provider",
    "_models_edit_options", "_models_pending_diff", "_selected_models_edit_option",
    "_active_theme", "_cycle_theme", "_load_saved_theme_id",
    "_advance_variant", "_require_variant_model_mapping", "_reset_variant",
    "_set_variant_provider_defaults", "_toggle_variant_mcp", "_toggle_variant_tweak",
    "_toggle_variant_store_secret", "_variant_api_key_for_create",
    "_variant_base_url_for_create", "_variant_credential_env_for_create",
    "_variant_model_overrides_for_create", "_variant_store_secret_for_create",
    "_refresh_startup_download_index",
    "_run_inspect_delete", "_run_setup_health", "_run_setup_upgrade", "_run_setup_delete", "_route_startup",
    "_queue_setup_run", "_run_pending_setup",
    "_start_busy_action", "_poll_busy_action",
    "_load_saved_setup_list_preferences", "_save_setup_list_preferences",
    "_copy_logs", "_copy_setup_config", "_copy_text_to_clipboard", "_open_help", "_open_logs", "_open_variant_create_preview",
    "_event_requests_quit", "_screen_text", "_style", "_render_frame",
    "run_tui",
]

# Externally-supplied helpers that tests monkey-patch through ``tui.<name>``.
# Imports must stay in this module so internal callers resolve through the
# package globals that ``monkeypatch.setattr`` updates.
from ..bun_extract import parse_bun_binary
from ..download_index import download_versions, load_download_index, refresh_download_index
from ..downloader import download_binary
from ..extractor import extract_all
from ..patch_workflow import apply_dashboard_tweaks_to_native, apply_patch_packages_to_native
from ..providers import provider_default_variant_name
from ..providers import fetch_provider_models
from ..variant_tweaks import CURATED_TWEAK_IDS, DASHBOARD_TWEAK_IDS, DEFAULT_TWEAK_IDS
from ..variants import (
    apply_variant,
    create_variant,
    default_install_dir,
    doctor_variant,
    install_variant_command,
    list_variant_providers,
    load_variant,
    remove_variant,
    scan_variants,
    update_variant_models,
    update_variants,
)
from ..variants.model import default_bin_dir, variant_id_from_name
from ..variants.wrapper import stored_credential_value
from ..workspace import (
    DashboardTweakProfile,
    NativeArtifact,
    PatchPackage,
    PatchProfile,
    delete_dashboard_tweak_profile,
    delete_native_download,
    delete_patch_profile,
    extraction_paths,
    load_dashboard_tweak_profile,
    load_patch_profile,
    load_tui_settings,
    native_artifact_from_path,
    rename_dashboard_tweak_profile,
    rename_patch_profile,
    save_dashboard_tweak_profile,
    save_patch_profile,
    save_tui_settings,
    scan_dashboard_tweak_profiles,
    scan_extractions,
    scan_native_downloads,
    scan_npm_downloads,
    scan_patch_packages,
    scan_patch_profiles,
    short_sha,
    workspace_root,
)

from ._const import (
    DASHBOARD_STEPS,
    DEFAULT_THEME_ID,
    MenuOption,
    SOURCE_ARTIFACT,
    SOURCE_LATEST,
    SOURCE_VERSION,
    TABS,
    TAB_MODES,
    THEME_ORDER,
    VARIANT_MODEL_FIELDS,
    VARIANT_STEPS,
)
from ._runtime import run_quiet as _run_quiet
from .dashboard import (
    advance_dashboard as _advance_dashboard,
    create_dashboard_profile as _create_dashboard_profile,
    dashboard_artifact_for_run as _dashboard_artifact_for_run,
    delete_dashboard_profile as _delete_dashboard_profile,
    load_dashboard_profile as _load_dashboard_profile,
    overwrite_dashboard_profile as _overwrite_dashboard_profile,
    refresh_dashboard_index as _refresh_dashboard_index,
    rename_dashboard_profile as _rename_dashboard_profile,
    require_dashboard_patches as _require_dashboard_patches,
    reset_dashboard as _reset_dashboard,
    toggle_dashboard_patch as _toggle_dashboard_patch,
    toggle_dashboard_tweak as _toggle_dashboard_tweak,
)
from .keys import (
    dashboard_accepts_profile_text as _dashboard_accepts_profile_text,
    dashboard_backspace as _dashboard_backspace,
    models_accepts_text as _models_accepts_text,
    models_append_text as _models_append_text,
    models_backspace as _models_backspace,
    variant_accepts_text as _variant_accepts_text,
    variant_append_text as _variant_append_text,
    variant_backspace as _variant_backspace,
)
from .nav import (
    activate_extract as _activate_extract,
    activate_inspect as _activate_inspect,
    activate_patch_source as _activate_patch_source,
    apply_tweaks as _apply_tweaks,
    discard_tweaks as _discard_tweaks,
    enter_tweaks_for_variant as _enter_tweaks_for_variant,
    go_back as _go_back,
    move_tab as _move_tab,
    selected_artifact as _selected_artifact,
    set_mode as _set_mode,
    source_artifact as _source_artifact,
    toggle_patch as _toggle_patch,
    toggle_tweak as _toggle_tweak,
)
from .options import (
    dashboard_tweak_ids as _dashboard_tweak_ids,
    dashboard_options as _dashboard_options,
    dashboard_source_artifact as _dashboard_source_artifact,
    dashboard_tweak_profile_by_id as _dashboard_tweak_profile_by_id,
    dashboard_tweak_profile_missing_ids as _dashboard_tweak_profile_missing_ids,
    loaded_profile as _loaded_profile,
    profile_by_id as _profile_by_id,
    profile_missing_refs as _profile_missing_refs,
    profile_refs_by_key as _profile_refs_by_key,
    selected_dashboard_option as _selected_dashboard_option,
    selected_dashboard_packages as _selected_dashboard_packages,
    selected_dashboard_tweaks as _selected_dashboard_tweaks,
    selected_patch_refs as _selected_patch_refs,
    selected_setup_option as _selected_setup_option,
    selected_setup_variant as _selected_setup_variant,
    selected_models_edit_option as _selected_models_edit_option,
    selected_tweaks_source_variant_id as _selected_tweaks_source_variant_id,
    selected_variant_option as _selected_variant_option,
    selected_variant_provider as _selected_variant_provider,
    setup_provider_keys as _setup_provider_keys,
    models_edit_options as _models_edit_options,
    models_pending_diff as _models_pending_diff,
    tweak_diff as _tweak_diff,
    unsupported_pending_tweaks as _unsupported_pending_tweaks,
    tweaks_edit_options as _tweaks_edit_options,
    tweaks_source_options as _tweaks_source_options,
    variant_model_display_value as _variant_model_display_value,
    variant_options as _variant_options,
)
from .rendering import (
    active_tab as _active_tab,
    body_text as _body_text,
    footer_lines as _footer_lines,
    footer_text as _footer_text,
    gauge_widget as _gauge_widget,
    list_widget as _list_widget,
    render_frame as _render_frame,
    screen_text as _screen_text,
    style as _style,
    tabs_widget as _tabs_widget,
)
from .state import TuiState
from .themes import (
    TUI_THEMES,
    TuiTheme,
    active_theme as _active_theme,
    cycle_theme as _cycle_theme,
    load_saved_theme_id as _load_saved_theme_id,
    normalize_theme_id as _normalize_theme_id,
    theme_name as _theme_name,
)
from .variant_actions import (
    advance_variant as _advance_variant,
    require_variant_model_mapping as _require_variant_model_mapping,
    reset_variant as _reset_variant,
    apply_variant_model_choice as _apply_variant_model_choice,
    set_variant_provider_defaults as _set_variant_provider_defaults,
    toggle_variant_mcp as _toggle_variant_mcp,
    toggle_variant_store_secret as _toggle_variant_store_secret,
    toggle_variant_tweak as _toggle_variant_tweak,
    validate_variant_endpoint as _validate_variant_endpoint,
    validate_variant_secret as _validate_variant_secret,
    variant_api_key_for_create as _variant_api_key_for_create,
    variant_base_url_for_create as _variant_base_url_for_create,
    variant_credential_env_for_create as _variant_credential_env_for_create,
    variant_model_overrides_for_create as _variant_model_overrides_for_create,
    variant_store_secret_for_create as _variant_store_secret_for_create,
)
from .busy import (
    _BUSY_TICK_MS,
    _busy_create_action,
    _busy_tweak_apply_action,
    _busy_upgrade_action,
    _clear_busy_state,
    _copy_completed_busy_state,
    _poll_busy_action,
    _run_busy_action,
    _start_busy_action,
)
from .dispatch import (
    _activate,
    _activate_dashboard,
    _activate_models_edit,
    _activate_patch_packages,
    _activate_setup_detail,
    _activate_setup_manager,
    _activate_tweaks_edit,
    _activate_tweaks_source,
    _activate_variants,
    _cancel_inspect_delete,
    _clamp_setup_manager_selection,
    _current_setup_id_for_action,
    _cycle_setup_provider_filter,
    _cycle_setup_sort,
    _cycle_tweak_filter,
    _event_requests_quit,
    _handle_backspace_key,
    _handle_char_key,
    _open_delete_confirm,
    _open_inspect_delete_confirm,
    _open_model_editor,
    _open_tweak_editor,
    _open_upgrade_preview,
    _open_variant_create_preview,
    _start_setup_create,
    _toggle_selected,
    _variant_accepts_name_text,
)
from .setup_actions import (
    _active_setup_status,
    _append_backend_stages,
    _apply_models,
    _apply_models_choice,
    _base_download_status,
    _begin_tweak_apply_preview,
    _build_stage_lines,
    _clear_terminal_for_external_command,
    _command_replaced_status,
    _copy_logs,
    _copy_setup_command,
    _copy_setup_config,
    _copy_text_to_clipboard,
    _create_failure_summary,
    _discard_models,
    _exception_stage_lines,
    _expected_setup_snapshot,
    _has_cached_native_artifact,
    _health_status_from_report,
    _inspect_delete_artifact,
    _load_saved_setup_list_preferences,
    _log_lines,
    _models_editor_api_key,
    _models_editor_endpoint,
    _models_editor_provider,
    _models_editor_variant,
    _open_help,
    _open_logs,
    _path_changed,
    _path_snapshot,
    _post_variant_snapshot,
    _queue_setup_run,
    _refresh_models_editor_models,
    _refresh_state,
    _refresh_startup_download_index,
    _refresh_variant_models,
    _result_stage_lines,
    _route_startup,
    _run_dashboard_build,
    _run_inspect_delete,
    _run_pending_setup,
    _run_setup_delete,
    _run_setup_health,
    _run_setup_upgrade,
    _run_tweak_apply,
    _run_variant_create,
    _save_setup_list_preferences,
    _stage_lines_from_log,
    _stage_log_lines,
    _target_version_for_summary,
    _variant_model_discovery_api_key,
    _variant_setup_snapshot,
    _yes_no,
)




# -- Top-level event loop ----------------------------------------------------

def run_tui():
    try:
        from ratatui_py import (
            App,
            Color,
            DrawCmd,
            Gauge,
            KeyCode,
            List as TuiList,
            Paragraph,
            Style,
            Tabs,
        )
    except (ImportError, OSError, RuntimeError) as exc:
        raise RuntimeError(f"ratatui is unavailable: {exc}") from exc

    state = TuiState(theme_id=_load_saved_theme_id())
    _load_saved_setup_list_preferences(state)
    if _refresh_state(state):
        _route_startup(state)
        _refresh_startup_download_index(state)

    def render(term, app_state):
        width, height = term.size()
        try:
            _render_frame(
                term, app_state, width, height,
                Paragraph, Style, Color, DrawCmd, Tabs, TuiList, Gauge,
            )
        except Exception:
            theme = _active_theme(app_state)
            screen = Paragraph.from_text(_screen_text(app_state, height=max(1, height - 1)))
            screen.set_block_title("cc-extractor", True)
            screen.set_style(_style(Style, Color, theme.body_fg, theme.body_bg, bold=True))
            screen.set_wrap(True)
            term.draw_paragraph(screen, (0, 0, max(1, width - 1), max(1, height - 1)))

    def on_event(term, event, app_state):
        if event.get("kind") != "key":
            return True
        if _event_requests_quit(event, KeyCode.Char):
            return False
        if app_state.mode == "busy":
            return True

        code = event.get("code")
        char_code = event.get("ch") or 0

        if code == int(KeyCode.Up):
            app_state.move(-1)
        elif code == int(KeyCode.Down):
            app_state.move(1)
        elif code == int(KeyCode.Left):
            _move_tab(app_state, -1)
        elif code == int(KeyCode.Right) or code == int(KeyCode.Tab):
            _move_tab(app_state, 1)
        elif code == int(KeyCode.Home):
            app_state.selected_index = 0
        elif code == int(KeyCode.End):
            app_state.selected_index = max(0, app_state.item_count() - 1)
        elif code == int(KeyCode.Backspace):
            if not _handle_backspace_key(app_state):
                _go_back(app_state)
        elif code == int(KeyCode.Esc):
            _go_back(app_state)
        elif code == int(KeyCode.Enter):
            return _activate(app_state)
        elif code == int(KeyCode.Char) and char_code:
            return _handle_char_key(app_state, chr(char_code))

        return True

    def on_tick(term, app_state):
        _poll_busy_action(app_state)

    def on_start(term, app_state):
        term.enter_alt()
        term.enable_raw()
        term.clear()

    def on_stop(exc, term, app_state):
        term.show_cursor()
        term.disable_raw()
        term.leave_alt()

    app = App(
        render=render,
        on_event=on_event,
        on_tick=on_tick,
        on_start=on_start,
        on_stop=on_stop,
        tick_ms=_BUSY_TICK_MS,
        clear_each_frame=False,
    )
    app.run(state)
    if state.pending_run_command:
        code = _run_pending_setup(state)
        if code:
            raise SystemExit(code)


# -- Busy action helpers ------------------------------------------------------

# -- Key handlers ------------------------------------------------------------

# -- Activate dispatchers ----------------------------------------------------
