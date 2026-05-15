"""Setup lifecycle, command, delete, and log actions for the TUI."""

from pathlib import Path

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

__all__ = [
    "_run_setup_health",
    "_run_setup_ccrouter_action",
    "_run_setup_upgrade",
    "_inspect_delete_artifact",
    "_run_inspect_delete",
    "_run_setup_delete",
]


def _run_setup_health(state, setup_id, *, show_result=False):
    try:
        reports, output = _run_quiet(doctor_variant, setup_id)
        report = reports[0] if reports else {"id": setup_id, "ok": False, "checks": []}
        status = _health_status_from_report(report)
        checks = report.get("checks", []) or []
        state.setup_health[setup_id] = {
            "status": status,
            "checks": checks,
            "message": f"Health: {status}",
            "output": output,
        }
        state.last_action_log = _stage_log_lines("Health", output)
        lines = [f"Setup: {setup_id}", f"Health: {status}"]
        for check in checks:
            check_status = "ok" if check.get("ok") else "failed"
            lines.append(f"{check.get('name', '?')}: {check_status} {check.get('path', '')}")
        state.message = f"Health for setup {setup_id}: {status}"
    except Exception as exc:
        status = "broken"
        state.setup_health[setup_id] = {
            "status": status,
            "checks": [],
            "message": str(exc),
            "output": str(exc),
        }
        state.last_action_log = _stage_log_lines("Health", str(exc))
        lines = [f"Setup: {setup_id}", "Health: broken", f"Doctor failed: {exc}"]
        state.message = f"Health for setup {setup_id}: broken"
    if show_result:
        state.selected_setup_id = setup_id
        state.last_action_summary = lines
        message = state.message
        _tui()._set_mode(state, "health-result")
        state.message = message
    return state.setup_health[setup_id]

def _run_setup_ccrouter_action(state, setup_id, action):
    variant = next((item for item in state.variants if item.variant_id == setup_id), None)
    if variant is None:
        state.message = f"Setup {setup_id} not found."
        return
    ccrouter = (variant.manifest or {}).get("ccrouter") or {}
    if ccrouter.get("mode") != "managed":
        state.message = f"Setup {setup_id} is not managed by ccsilo CCR."
        return
    if action == "copy-config":
        config_path = ccrouter.get("configPath") or str(Path(ccrouter.get("homeDir", "")) / ".claude-code-router" / "config.json")
        try:
            _tui()._copy_text_to_clipboard(config_path)
        except Exception as exc:
            state.message = f"Copy failed: {exc}"
            return
        state.last_action_log = [f"Copied CCR config path: {config_path}"]
        state.message = f"Copied CCR config path for setup {setup_id}."
        return

    command_args = {
        "status": ["status"],
        "start": ["start"],
        "stop": ["stop"],
        "restart": ["restart"],
        "ui": ["ui"],
    }.get(action)
    if command_args is None:
        state.message = f"Unknown CCR action: {action}"
        return
    try:
        result, output = _run_quiet(run_ccrouter_command, variant.manifest, command_args)
    except Exception as exc:
        state.last_action_log = _stage_log_lines("CCR action failure", str(exc))
        state.message = f"CCR {action} failed: {exc}"
        return
    combined = "\n".join(
        str(part)
        for part in (output, getattr(result, "stdout", ""), getattr(result, "stderr", ""))
        if str(part).strip()
    )
    state.last_action_log = _stage_log_lines(f"CCR {action}", combined)
    state.last_action_summary = [
        f"CCR {action}.",
        f"Setup: {setup_id}",
        f"Return code: {getattr(result, 'returncode', '?')}",
        "",
        *(combined.splitlines() or ["No CCR output captured."]),
    ]
    if getattr(result, "returncode", 1) == 0:
        state.message = f"CCR {action} completed for setup {setup_id}."
    else:
        state.message = f"CCR {action} exited {getattr(result, 'returncode', '?')} for setup {setup_id}."
    _tui()._set_mode(state, "health-result")

def _run_setup_upgrade(state):
    setup_id = state.selected_setup_id
    variant = _tui()._selected_setup_variant(state)
    if not setup_id or variant is None:
        state.message = "Select a setup first."
        return
    old_version = ((variant.manifest or {}).get("source") or {}).get("version") or "?"
    target = state.setup_upgrade_target or "latest"
    before = _variant_setup_snapshot(variant)
    target_version = _target_version_for_summary(state, target)
    cached_before = _has_cached_native_artifact(state, target_version)
    try:
        results, update_output = _run_quiet(update_variants, setup_id, claude_version=target)
        _tui()._refresh_state(state)
        state.selected_setup_id = setup_id
        refreshed = _tui()._selected_setup_variant(state)
        new_version = ((refreshed.manifest or {}).get("source") or {}).get("version") if refreshed else "?"
        health = _run_setup_health(state, setup_id, show_result=False)
        stage_lines = _result_stage_lines(results)
        state.last_action_log = _stage_log_lines(
            "Upgrade",
            update_output,
            "Build stages",
            "\n".join(stage_lines),
            "Health",
            health.get("output", ""),
        )
        wrapper = ""
        if results:
            wrapper = str(getattr(results[0], "wrapper_path", "") or "")
        if not wrapper and refreshed is not None:
            wrapper = str(((refreshed.manifest or {}).get("paths") or {}).get("wrapper") or "")
        status = health.get("status", "unknown")
        state.last_action_summary = _append_backend_stages([
            f"Setup upgraded: {setup_id}",
            f"Claude Code: {old_version} -> {new_version or target}",
            "Patches/tweaks reapplied: yes",
            f"Command rebuilt path: {wrapper or '(unknown)'}",
            f"Health: {status}",
        ], stage_lines)
        state.message = f"Upgrade complete for setup {setup_id}: {status}"
    except Exception as exc:
        refresh_message = ""
        try:
            _tui()._refresh_state(state)
            state.selected_setup_id = setup_id
        except Exception as refresh_exc:
            refresh_message = f" Refresh failed after error: {refresh_exc}"
        post_variant, after = _post_variant_snapshot(setup_id, before)
        base_status = _base_download_status(state, target_version, cached_before)
        command_replaced = _command_replaced_status(before["wrapper"], after["wrapper"])
        active = "unknown" if post_variant is None else _active_setup_status(after)
        stage_lines = _exception_stage_lines(exc)
        state.last_action_log = _stage_log_lines(
            "Upgrade failure",
            str(exc),
            "Build stages",
            "\n".join(stage_lines),
        )
        state.last_action_summary = _append_backend_stages([
            f"Upgrade failed: {setup_id}",
            f"Claude Code: {old_version} -> {target}",
            f"Base download succeeded: {base_status}",
            f"Command replaced: {command_replaced}",
            f"Previous setup remains active: {active}",
            f"Failed stage: update/rebuild: {exc}",
        ], stage_lines)
        if refresh_message:
            state.last_action_summary.append(refresh_message.strip())
        state.message = f"Upgrade failed: {exc}"
    message = state.message
    _tui()._set_mode(state, "health-result")
    state.message = message

def _inspect_delete_artifact(state):
    target = state.inspect_delete_confirm_path
    if not target:
        return None
    for artifact in state.native_artifacts:
        if str(artifact.path) == target:
            return artifact
    return None

def _run_inspect_delete(state):
    artifact = _inspect_delete_artifact(state)
    if artifact is None:
        state.inspect_delete_confirm_path = ""
        _tui()._set_mode(state, "inspect")
        state.message = "Selected native artifact is no longer available."
        return

    label = f"{artifact.version} {artifact.platform} {short_sha(artifact.sha256)}"
    try:
        removed = delete_native_download(artifact)
    except Exception as exc:
        state.last_action_log = _stage_log_lines("Native artifact delete failure", str(exc))
        _tui()._set_mode(state, "inspect")
        state.message = f"Delete failed: {exc}"
        return

    state.inspect_delete_confirm_path = ""
    _tui()._refresh_state(state)
    state.message = f"Deleted native artifact: {label}" if removed else f"Native artifact already missing: {label}"
    _tui()._set_mode(state, "inspect")
    state.message = f"Deleted native artifact: {label}" if removed else f"Native artifact already missing: {label}"

def _run_setup_delete(state):
    variant = _tui()._selected_setup_variant(state)
    if variant is None:
        state.message = "Select a setup first."
        return
    setup_id = variant.variant_id
    if state.delete_confirm_text != setup_id:
        state.message = f"Type {setup_id} exactly to delete."
        return
    paths = (variant.manifest or {}).get("paths") or {}
    setup_dir = variant.path
    wrapper_text = paths.get("wrapper") or ""
    wrapper_path = Path(wrapper_text) if wrapper_text else None
    managed_install_paths = _managed_install_paths(variant)
    delete_failed = False
    removed = False
    try:
        removed, output = _run_quiet(remove_variant, setup_id, yes=True)
        setup_removed = not setup_dir.exists()
        command_removed = True if wrapper_path is None else not wrapper_path.exists()
        managed_commands_removed = all(not path.exists() and not path.is_symlink() for path in managed_install_paths)
        state.last_action_log = _stage_log_lines("Delete", output)
        state.message = f"Deleted setup {setup_id}." if removed else f"Setup {setup_id} was not found."
    except Exception as exc:
        delete_failed = True
        setup_removed = not setup_dir.exists()
        command_removed = True if wrapper_path is None else not wrapper_path.exists()
        managed_commands_removed = all(not path.exists() and not path.is_symlink() for path in managed_install_paths)
        state.last_action_log = _stage_log_lines("Delete failure", str(exc))
        state.message = f"Delete failed: {exc}"
    title = f"Deleted setup: {setup_id}"
    if delete_failed:
        title = f"Delete failed: {setup_id}"
    elif not removed:
        title = f"Setup not found: {setup_id}"
    state.last_action_summary = [
        title,
        f"Setup directory removed: {'yes' if setup_removed else 'no'}",
        f"Command removed: {'yes' if command_removed else 'no'}",
        f"Installed commands removed: {_install_removed_summary(managed_install_paths, managed_commands_removed)}",
        "Shared downloads untouched: yes",
        "Next: fix the reported issue, refresh setup list, or retry delete.",
    ]
    state.delete_confirm_text = ""
    _tui()._refresh_state(state)
    if setup_removed:
        state.selected_setup_id = None
    else:
        state.selected_setup_id = setup_id
    message = state.message
    _tui()._set_mode(state, "setup-manager")
    state.message = message

def _install_removed_summary(paths, removed):
    if not paths:
        return "none"
    return "yes" if removed else "no"
