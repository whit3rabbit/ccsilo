"""Compatibility facade for TUI setup, model, dashboard, and logging actions."""

from .setup_actions_commands import (
    _clear_terminal_for_external_command,
    _copy_logs,
    _copy_setup_command,
    _copy_setup_config,
    _open_help,
    _open_logs,
    _queue_setup_run,
    _run_pending_setup,
)
from .setup_actions_common import (
    _refresh_state,
    _refresh_startup_download_index,
    _route_startup,
    _load_saved_setup_list_preferences,
    _save_setup_list_preferences,
    _log_lines,
    _stage_log_lines,
    _build_stage_lines,
    _exception_stage_lines,
    _result_stage_lines,
    _append_backend_stages,
    _stage_lines_from_log,
    _copy_text_to_clipboard,
    _health_status_from_report,
    _yes_no,
    _path_snapshot,
    _path_changed,
    _expected_setup_snapshot,
    _variant_setup_snapshot,
    _create_failure_summary,
    _target_version_for_summary,
    _has_cached_native_artifact,
    _base_download_status,
    _post_variant_snapshot,
    _command_replaced_status,
    _active_setup_status,
    _managed_install_paths,
)
from .setup_actions_create import _run_variant_create
from .setup_actions_models import (
    _refresh_variant_models,
    _refresh_models_editor_models,
    _models_editor_variant,
    _models_editor_provider,
    _models_editor_endpoint,
    _models_editor_api_key,
    _apply_models_choice,
    _skip_variant_model_list,
    _skip_models_editor_model_list,
    _apply_models,
    _discard_models,
    _variant_model_discovery_api_key,
)
from .setup_actions_setup import (
    _run_setup_health,
    _run_setup_ccrouter_action,
    _run_setup_command_alias,
    _run_setup_upgrade,
    _inspect_delete_artifact,
    _run_inspect_delete,
    _run_setup_delete,
)
from .setup_actions_tweaks import (
    _begin_tweak_apply_preview,
    _run_tweak_apply,
    _run_dashboard_build,
)

__all__ = ['_refresh_state', '_refresh_startup_download_index', '_route_startup', '_load_saved_setup_list_preferences', '_save_setup_list_preferences', '_log_lines', '_stage_log_lines', '_build_stage_lines', '_exception_stage_lines', '_result_stage_lines', '_append_backend_stages', '_stage_lines_from_log', '_copy_text_to_clipboard', '_copy_setup_command', '_copy_setup_config', '_queue_setup_run', '_clear_terminal_for_external_command', '_run_pending_setup', '_copy_logs', '_open_logs', '_open_help', '_health_status_from_report', '_yes_no', '_path_snapshot', '_path_changed', '_expected_setup_snapshot', '_variant_setup_snapshot', '_create_failure_summary', '_target_version_for_summary', '_has_cached_native_artifact', '_base_download_status', '_post_variant_snapshot', '_command_replaced_status', '_active_setup_status', '_managed_install_paths', '_run_setup_health', '_run_setup_upgrade', '_run_setup_ccrouter_action', '_run_setup_command_alias', '_inspect_delete_artifact', '_run_inspect_delete', '_run_setup_delete', '_begin_tweak_apply_preview', '_run_tweak_apply', '_run_dashboard_build', '_refresh_variant_models', '_refresh_models_editor_models', '_models_editor_variant', '_models_editor_provider', '_models_editor_endpoint', '_models_editor_api_key', '_apply_models_choice', '_skip_variant_model_list', '_skip_models_editor_model_list', '_apply_models', '_discard_models', '_variant_model_discovery_api_key', '_run_variant_create']
