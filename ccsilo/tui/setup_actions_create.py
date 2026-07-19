"""Setup creation action for the TUI."""

import os

from ..providers import find_anyllm_proxy_binary, get_provider
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
    "_run_variant_create",
]

def _run_variant_create(state):
    provider = _tui()._selected_variant_provider(state)
    if provider is None:
        state.message = "Select a provider first."
        return
    local_proxy = get_provider(provider["key"]).local_proxy
    if local_proxy and find_anyllm_proxy_binary() is None:
        binary = local_proxy.get("binary")
        state.message = (
            f"{provider['label']} needs the {binary} binary. Install it first: "
            "brew install whit3rabbit/tap/anyllm-proxy (or use the Integrations screen), then retry."
        )
        return
    name = state.variant_name.strip() or provider_default_variant_name(provider["key"])
    credential_env = _tui()._variant_credential_env_for_create(state, provider)
    api_key = _tui()._variant_api_key_for_create(state)
    store_secret = _tui()._variant_store_secret_for_create(state)
    if credential_env and not store_secret and not provider.get("credentialOptional") and credential_env not in os.environ:
        state.message = f"Credential env {credential_env} is not set."
        return
    try:
        expected_setup_id = variant_id_from_name(name)
    except Exception as exc:
        state.last_action_log = _stage_log_lines("Create failure", str(exc))
        state.last_action_summary = [
            "Create failed.",
            f"Setup: {name}",
            "Setup directory created: no",
            "Command created: no",
            "Setup config created: no",
            "Previous state changed: no",
            "Cleanup needed: no",
            f"Failed stage: validate setup id: {exc}",
        ]
        state.message = f"Setup create failed: {exc}"
        message = state.message
        _tui()._set_mode(state, "error")
        state.message = message
        return
    before = _expected_setup_snapshot(expected_setup_id)
    failed_stage = "create setup"
    install_plan = None
    install_alias = state.variant_install_alias.strip()
    if not install_alias and not state.variant_install_alias_customized:
        install_alias = expected_setup_id
    try:
        if state.variant_install_command:
            failed_stage = "validate install command"
            install_plan, _install_plan_output = _run_quiet(
                inspect_variant_command_install,
                expected_setup_id,
                target=workspace_root() / "bin" / expected_setup_id,
                alias=install_alias,
                yes=True,
            )
            if getattr(install_plan, "status", "") == "blocked":
                state.last_action_log = _stage_log_lines("Validate install command", install_plan.warning)
                state.last_action_summary = [
                    "Command install blocked.",
                    f"Setup: {expected_setup_id}",
                    f"Alias: {install_alias}",
                    f"Install path: {install_plan.path}",
                    f"Reason: {install_plan.warning}",
                    "Change the alias or turn install command off.",
                ]
                state.message = f"Command alias blocked: {install_plan.warning}"
                return
        failed_stage = "create setup"
        result, output = _run_quiet(
            create_variant,
            name=name,
            provider_key=provider["key"],
            claude_version=state.variant_claude_version or "latest",
            tweaks=state.selected_variant_tweaks,
            base_url=_tui()._variant_base_url_for_create(state, provider),
            credential_env=credential_env,
            api_key=api_key,
            store_secret=store_secret,
            model_overrides=_tui()._variant_model_overrides_for_create(state),
            mcp_ids=state.selected_variant_mcp_ids,
            integration_ids=state.selected_variant_integration_ids,
            **_tui()._variant_ccrouter_options_for_create(state, provider),
            **_tui()._variant_model_proxy_options_for_create(state, provider),
            force=False,
        )
        state.last_action_log = _stage_log_lines("Create setup", output)
        stage_lines = _build_stage_lines(getattr(result, "stages", []))
        setup_id = getattr(getattr(result, "variant", None), "variant_id", None) or variant_id_from_name(name)
        wrapper_path = getattr(result, "wrapper_path", None)
        config_path = workspace_root() / "variants" / setup_id / "variant.json"
        install_result = None
        install_output = ""
        result_variant = getattr(result, "variant", None)
        if state.variant_install_command and result_variant is not None:
            failed_stage = "install command"
            install_result, install_output = _run_quiet(
                install_variant_command,
                result_variant,
                alias=install_alias,
                yes=True,
            )
        state.selected_setup_id = setup_id
        health = _run_setup_health(state, setup_id, show_result=False)
        log_sections = [
            ("Create setup", output),
            ("Build stages", "\n".join(stage_lines)),
        ]
        if install_result is not None:
            log_sections.append(("Install command", install_output))
        log_sections.append(("Health", health.get("output", "")))
        run_command = str(wrapper_path) if wrapper_path else f"ccsilo variant run {setup_id} --"
        install_summary = "no"
        install_warning = ""
        if install_result is not None:
            if getattr(install_result, "status", "") == "blocked":
                install_summary = f"skipped, existing command preserved: {install_result.path}"
            else:
                run_command = install_result.alias
                install_summary = str(install_result.path)
            install_warning = install_result.warning
        summary = [
            "Setup created.",
            "",
            "Run it with:",
            f"  {run_command}",
            "",
            "Command:",
            f"  {wrapper_path or '(unknown)'}",
            "",
            f"Installed command: {install_summary}",
        ]
        if install_warning:
            summary.append(f"Install warning: {install_warning}")
        summary.extend([
            "",
            "Config:",
            f"  {config_path}",
            "",
            f"Health: {health.get('status', 'unknown')}",
        ])
        state.last_action_log = _stage_log_lines(
            *log_sections,
        )
        state.last_action_summary = _append_backend_stages(summary, stage_lines)
        if getattr(install_result, "status", "") == "blocked":
            state.message = f"Setup created; command install skipped: {install_result.warning}"
        else:
            state.message = f"Setup created: {wrapper_path or setup_id}"
        _tui()._reset_variant(state)
        message = state.message
        _tui()._set_mode(state, "health-result")
        state.message = message
    except Exception as exc:
        stage_lines = _exception_stage_lines(exc)
        state.last_action_log = _stage_log_lines(
            "Create failure",
            str(exc),
            "Build stages",
            "\n".join(stage_lines),
        )
        state.last_action_summary = _append_backend_stages(
            _create_failure_summary(expected_setup_id, before, exc, failed_stage=failed_stage),
            stage_lines,
        )
        state.message = f"Setup create failed: {exc}"
        message = state.message
        _tui()._set_mode(state, "error")
        state.message = message
