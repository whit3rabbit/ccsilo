"""Model discovery and model editor actions for the TUI."""

import os
from .model_picker import (
    models_editor_uses_architect_mode,
    model_field_label,
    next_model_target,
    normalize_model_target,
    sorted_unique_model_ids,
    sync_architect_worker_default,
)
from .setup_actions_common import (  # noqa: F401
    _active_setup_status,
    _append_backend_stages,
    _base_download_status,
    _build_stage_lines,
    _command_replaced_status,
    _copy_text_to_clipboard,
    _create_failure_summary,
    _exception_stage_lines,
    _expected_setup_snapshot,
    _has_cached_native_artifact,
    _health_status_from_report,
    _log_lines,
    _managed_install_paths,
    _models_pending_diff,
    _path_changed,
    _path_snapshot,
    _post_variant_snapshot,
    _result_stage_lines,
    _run_quiet,
    _stage_lines_from_log,
    _stage_log_lines,
    _target_version_for_summary,
    _tui,
    _variant_setup_snapshot,
    _yes_no,
    apply_dashboard_tweaks_to_native,
    create_variant,
    default_bin_dir,
    delete_native_download,
    doctor_variant,
    download_versions,
    fetch_provider_models,
    inspect_variant_command_install,
    install_variant_command,
    load_tui_settings,
    load_variant,
    provider_default_variant_name,
    refresh_download_index,
    remove_variant,
    run_ccrouter_command,
    save_tui_settings,
    short_sha,
    stored_credential_value,
    update_variant_models,
    update_variants,
    variant_id_from_name,
    variant_install_cleanup_paths,
    workspace_root,
)
from .setup_actions_setup import _run_setup_health

__all__ = [
    "_refresh_variant_models",
    "_refresh_models_editor_models",
    "_models_editor_variant",
    "_models_editor_provider",
    "_models_editor_endpoint",
    "_models_editor_api_key",
    "_apply_models_choice",
    "_skip_variant_model_list",
    "_skip_models_editor_model_list",
    "_apply_models",
    "_discard_models",
    "_variant_model_discovery_api_key",
]

def _refresh_variant_models(state):
    provider = _tui()._selected_variant_provider(state)
    if not provider or not ((provider.get("modelDiscovery") or {}).get("enabled")):
        state.message = "This provider does not support model refresh."
        return
    if not _tui()._validate_variant_endpoint(state, provider):
        return
    endpoint = state.variant_base_url.strip() or str(provider.get("baseUrl") or "").strip()
    try:
        models = fetch_provider_models(endpoint, api_key=_variant_model_discovery_api_key(state))
    except Exception as exc:
        state.variant_model_choices = []
        state.message = f"Model refresh failed: {exc}"
        return
    state.variant_model_choices = sorted_unique_model_ids(models)
    if not state.variant_model_choices:
        state.message = "Model refresh returned no models. Type aliases manually."
        return
    _select_first_option_kind(state, _tui()._variant_options, "variant-model-choice")
    state.message = f"Loaded {len(state.variant_model_choices)} models. Target: {model_field_label(state.variant_model_target)}."

def _refresh_models_editor_models(state):
    variant = _models_editor_variant(state)
    if variant is None:
        state.message = "No setup selected."
        return
    provider = _models_editor_provider(state, variant)
    if not ((provider.get("modelDiscovery") or {}).get("enabled")):
        state.message = "This provider does not support model refresh."
        return
    endpoint = _models_editor_endpoint(variant, provider)
    if not endpoint:
        state.message = "Endpoint is not configured for this setup."
        return
    try:
        models = fetch_provider_models(endpoint, api_key=_models_editor_api_key(variant))
    except Exception as exc:
        state.models_choices = []
        state.message = f"Model refresh failed: {exc}"
        return
    state.models_choices = sorted_unique_model_ids(models)
    if not state.models_choices:
        state.message = "Model refresh returned no models. Type aliases manually."
        return
    _select_first_option_kind(state, _tui()._models_edit_options, "models-choice")
    state.message = f"Loaded {len(state.models_choices)} models. Target: {model_field_label(state.models_target)}."

def _models_editor_variant(state):
    if not state.models_variant_id:
        return None
    for variant in state.variants:
        if variant.variant_id == state.models_variant_id:
            return variant
    return None

def _models_editor_provider(state, variant):
    provider_key = str(((variant.manifest or {}).get("provider") or {}).get("key") or "")
    for provider in state.variant_providers:
        if provider.get("key") == provider_key:
            return provider
    return {"key": provider_key, "label": provider_key or "?", "baseUrl": "", "models": {}, "modelDiscovery": {}}

def _models_editor_endpoint(variant, provider):
    env = (variant.manifest or {}).get("env") or {}
    return str(env.get("ANTHROPIC_BASE_URL") or provider.get("baseUrl") or "").strip()

def _models_editor_api_key(variant):
    credential = (variant.manifest or {}).get("credential") or {}
    if credential.get("mode") == "stored":
        try:
            return stored_credential_value(variant.manifest)
        except Exception:
            return None
    if credential.get("mode") == "env":
        source = str(credential.get("source") or "").strip()
        if source and source in os.environ:
            return os.environ[source]
    return None

def _apply_models_choice(state, model_id: str):
    value = model_id.strip()
    if not value:
        return
    key = normalize_model_target(getattr(state, "models_target", ""))
    state.models_pending[key] = value
    architect_mode = models_editor_uses_architect_mode(state)
    if architect_mode:
        sync_architect_worker_default(state.models_pending, key)
    next_key = next_model_target(key)
    state.models_target = next_key
    state.message = (
        f"{model_field_label(key, architect_mode=architect_mode)} model set to {value}. "
        f"Next target: {model_field_label(next_key, architect_mode=architect_mode)}."
    )

def _skip_variant_model_list(state):
    state.variant_model_choices = []
    state.variant_model_search_text = ""
    state.variant_model_search_active = False
    target = normalize_model_target(getattr(state, "variant_model_target", ""))
    state.variant_model_target = target
    _select_option_value(state, _tui()._variant_options, "variant-model", target)
    state.message = f"Skipped model list. Type aliases manually, or edit {_variant_model_config_path_hint(state)} modelOverrides after create."

def _skip_models_editor_model_list(state):
    state.models_choices = []
    state.models_search_text = ""
    state.models_search_active = False
    target = normalize_model_target(getattr(state, "models_target", ""))
    state.models_target = target
    _select_option_value(state, _tui()._models_edit_options, "models-field", target)
    variant = _models_editor_variant(state)
    config_path = variant.path / "variant.json" if variant is not None else "<setup-dir>/variant.json"
    state.message = f"Skipped model list. Type aliases manually, or edit {config_path} modelOverrides."

def _apply_models(state):
    if not state.models_variant_id:
        state.message = "No setup selected."
        return
    diff = _models_pending_diff(state)
    if not diff["changed"]:
        state.message = "No model changes to apply."
        return
    setup_id = state.models_variant_id
    try:
        updated, output = _run_quiet(update_variant_models, setup_id, diff["pending"])
        _tui()._refresh_state(state)
        state.selected_setup_id = setup_id
        state.models_baseline = dict(diff["pending"])
        state.models_pending = dict(diff["pending"])
        health = _run_setup_health(state, setup_id, show_result=False)
        wrapper = str(((getattr(updated, "manifest", {}) or {}).get("paths") or {}).get("wrapper") or "")
        state.last_action_log = _stage_log_lines(
            "Model update",
            output,
            "Health",
            health.get("output", ""),
        )
        changed = ", ".join(diff["changed"])
        state.last_action_summary = [
            f"Models updated: {setup_id}",
            f"Aliases changed: {changed}",
            "Binary rebuilt: no",
            f"Command updated: {wrapper or '(unknown)'}",
            f"Health: {health.get('status', 'unknown')}",
        ]
        state.message = f"Models updated for setup {setup_id}: {health.get('status', 'unknown')}"
        message = state.message
        _tui()._set_mode(state, "health-result")
        state.message = message
    except Exception as exc:
        state.last_action_log = _stage_log_lines("Model update failure", str(exc))
        state.last_action_summary = [
            f"Model update failed: {setup_id}",
            f"Failed stage: {exc}",
            "Binary rebuilt: no",
        ]
        state.message = f"Model update failed: {exc}"
        message = state.message
        _tui()._set_mode(state, "error")
        state.message = message

def _discard_models(state):
    state.models_pending = dict(state.models_baseline or {})
    state.models_choices = []
    state.models_search_text = ""
    state.models_search_active = False
    state.message = "Discarded model changes."

def _variant_model_discovery_api_key(state):
    if state.variant_store_secret and state.variant_api_key.strip():
        return state.variant_api_key.strip()
    credential_env = state.variant_credential_env.strip()
    if credential_env and credential_env in os.environ:
        return os.environ[credential_env]
    return None


def _select_first_option_kind(state, options_func, kind: str) -> None:
    for index, option in enumerate(options_func(state)):
        if option.kind == kind:
            state.selected_index = index
            return


def _select_option_value(state, options_func, kind: str, value: str) -> None:
    for index, option in enumerate(options_func(state)):
        if option.kind == kind and option.value == value:
            state.selected_index = index
            return


def _variant_model_config_path_hint(state):
    provider = _tui()._selected_variant_provider(state)
    name = state.variant_name.strip() or str((provider or {}).get("defaultVariantName") or (provider or {}).get("key") or "")
    try:
        setup_id = variant_id_from_name(name)
    except Exception:
        setup_id = "<setup-id>"
    return workspace_root() / "variants" / setup_id / "variant.json"
