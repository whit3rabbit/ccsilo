"""Setup, model, dashboard-build, and logging actions for the TUI."""

import os
from pathlib import Path

from ._const import VARIANT_MODEL_FIELDS

import sys as _sys


def _tui():
    return _sys.modules["ccsilo.tui"]


def _proxy(name):
    def call(*args, **kwargs):
        return getattr(_tui(), name)(*args, **kwargs)
    return call

load_tui_settings = _proxy('load_tui_settings')
save_tui_settings = _proxy('save_tui_settings')
workspace_root = _proxy('workspace_root')
default_bin_dir = _proxy('default_bin_dir')
doctor_variant = _proxy('doctor_variant')
update_variants = _proxy('update_variants')
load_variant = _proxy('load_variant')
remove_variant = _proxy('remove_variant')
delete_native_download = _proxy('delete_native_download')
short_sha = _proxy('short_sha')
_run_quiet = _proxy('_run_quiet')
apply_dashboard_tweaks_to_native = _proxy('apply_dashboard_tweaks_to_native')
fetch_provider_models = _proxy('fetch_provider_models')
stored_credential_value = _proxy('stored_credential_value')
update_variant_models = _proxy('update_variant_models')
provider_default_variant_name = _proxy('provider_default_variant_name')
variant_id_from_name = _proxy('variant_id_from_name')
create_variant = _proxy('create_variant')
inspect_variant_command_install = _proxy('inspect_variant_command_install')
install_variant_command = _proxy('install_variant_command')
run_ccrouter_command = _proxy('run_ccrouter_command')
variant_install_cleanup_paths = _proxy('variant_install_cleanup_paths')
_models_pending_diff = _proxy('_models_pending_diff')
download_versions = _proxy('download_versions')
refresh_download_index = _proxy('refresh_download_index')

__all__ = ['_refresh_state', '_refresh_startup_download_index', '_route_startup', '_load_saved_setup_list_preferences', '_save_setup_list_preferences', '_log_lines', '_stage_log_lines', '_build_stage_lines', '_exception_stage_lines', '_result_stage_lines', '_append_backend_stages', '_stage_lines_from_log', '_copy_text_to_clipboard', '_copy_setup_command', '_copy_setup_config', '_queue_setup_run', '_clear_terminal_for_external_command', '_run_pending_setup', '_copy_logs', '_open_logs', '_open_help', '_health_status_from_report', '_yes_no', '_path_snapshot', '_path_changed', '_expected_setup_snapshot', '_variant_setup_snapshot', '_create_failure_summary', '_target_version_for_summary', '_has_cached_native_artifact', '_base_download_status', '_post_variant_snapshot', '_command_replaced_status', '_active_setup_status', '_managed_install_paths', '_run_setup_health', '_run_setup_upgrade', '_run_setup_ccrouter_action', '_inspect_delete_artifact', '_run_inspect_delete', '_run_setup_delete', '_begin_tweak_apply_preview', '_run_tweak_apply', '_run_dashboard_build', '_refresh_variant_models', '_refresh_models_editor_models', '_models_editor_variant', '_models_editor_provider', '_models_editor_endpoint', '_models_editor_api_key', '_apply_models_choice', '_apply_models', '_discard_models', '_variant_model_discovery_api_key', '_run_variant_create']

def _refresh_state(state):
    try:
        state.refresh()
        return True
    except Exception as exc:
        prefix = f"{state.message} " if state.message else ""
        state.message = f"{prefix}Refresh failed: {exc}"
        return False

def _refresh_startup_download_index(state):
    if state.download_index_checked_live:
        return True
    state.download_index_checked_live = True
    try:
        index = refresh_download_index()
    except Exception as exc:
        prefix = f"{state.message} " if state.message else ""
        state.message = f"{prefix}Version check failed: {exc}"
        return False
    state.download_index = index
    state.download_versions = download_versions(index, "binary")
    state.download_index_loaded = True
    return True

def _route_startup(state):
    if state.variants:
        if state.selected_setup_id is None:
            state.selected_setup_id = state.variants[0].variant_id
        _tui()._set_mode(state, "setup-manager")
    else:
        _tui()._reset_variant(state)
        _tui()._set_mode(state, "first-run-setup")
        state.message = "No Claude Code setups found."

def _load_saved_setup_list_preferences(state):
    setup_list = load_tui_settings().get("setupList") or {}
    state.setup_search_text = str(setup_list.get("searchText") or "")
    state.setup_provider_filter = str(setup_list.get("providerFilter") or "all")
    sort_key = str(setup_list.get("sortKey") or "name")
    state.setup_sort_key = sort_key if sort_key in {"name", "provider", "health", "updated", "version"} else "name"
    state.setup_search_active = False

def _save_setup_list_preferences(state):
    settings = load_tui_settings()
    settings["themeId"] = settings.get("themeId") or state.theme_id
    settings["setupList"] = {
        "searchText": state.setup_search_text,
        "providerFilter": state.setup_provider_filter,
        "sortKey": state.setup_sort_key,
    }
    try:
        save_tui_settings(settings)
        return True
    except Exception as exc:
        state.message = f"Setup list preferences changed but save failed: {exc}"
        return False

def _log_lines(output, fallback="No backend output captured."):
    lines = str(output or "").splitlines()
    return lines if lines else [fallback]

def _stage_log_lines(*stages):
    if stages and all(isinstance(stage, tuple) and len(stage) == 2 for stage in stages):
        pairs = stages
    else:
        pairs = list(zip(stages[0::2], stages[1::2]))
    lines = []
    for label, output in pairs:
        lines.append(f"[{label}]")
        lines.extend(_log_lines(output))
    return lines or ["No backend output captured."]

def _build_stage_lines(stages):
    lines = []
    for stage in stages or []:
        name = getattr(stage, "name", None) or str(getattr(stage, "get", lambda _key, default=None: default)("name", "stage"))
        status = getattr(stage, "status", None) or str(getattr(stage, "get", lambda _key, default=None: default)("status", "unknown"))
        detail = getattr(stage, "detail", None) or getattr(stage, "get", lambda _key, default=None: default)("detail", "")
        line = f"{name}: {status}"
        if detail:
            line = f"{line} ({detail})"
        lines.append(line)
    return lines

def _exception_stage_lines(exc):
    return _build_stage_lines(getattr(exc, "stages", []))

def _result_stage_lines(results):
    lines = []
    for result in results or []:
        lines.extend(_build_stage_lines(getattr(result, "stages", [])))
    return lines

def _append_backend_stages(summary, stage_lines):
    if stage_lines:
        summary.extend(["", "Backend stages:", *stage_lines])
    return summary

def _stage_lines_from_log(log_lines):
    if "[Build stages]" not in (log_lines or []):
        return []
    index = log_lines.index("[Build stages]")
    return list(log_lines[index + 1:])

def _copy_text_to_clipboard(text):
    _tui().subprocess.run(["pbcopy"], input=str(text), text=True, check=True)

def _copy_setup_command(state):
    variant = _tui()._selected_setup_variant(state)
    if variant is None:
        state.message = "Select a setup first."
        return
    wrapper = ((variant.manifest or {}).get("paths") or {}).get("wrapper") or ""
    if not wrapper:
        state.message = f"Setup {variant.variant_id} has no command path to copy."
        return
    try:
        _tui()._copy_text_to_clipboard(wrapper)
    except Exception as exc:
        state.message = f"Copy failed: {exc}"
        return
    state.last_action_log = [f"Copied command path: {wrapper}"]
    state.message = f"Copied command path for setup {variant.variant_id}."

def _copy_setup_config(state):
    variant = _tui()._selected_setup_variant(state)
    if variant is None:
        state.message = "Select a setup first."
        return
    config_path = variant.path / "variant.json"
    try:
        _tui()._copy_text_to_clipboard(str(config_path))
    except Exception as exc:
        state.message = f"Copy failed: {exc}"
        return
    state.last_action_log = [f"Copied setup config path: {config_path}"]
    state.message = f"Copied setup config path for setup {variant.variant_id}."

def _queue_setup_run(state, setup_id):
    variant = next((item for item in state.variants if item.variant_id == setup_id), None)
    if variant is None:
        state.message = f"Setup {setup_id} not found."
        return
    wrapper_path = default_bin_dir() / setup_id
    if not wrapper_path.is_file():
        state.message = f"Setup command is missing: {wrapper_path}"
        return
    state.selected_setup_id = setup_id
    state.pending_run_setup_id = setup_id
    state.pending_run_command = [str(wrapper_path)]
    state.last_action_log = [f"Queued setup run: {wrapper_path}"]
    state.message = f"Running setup {setup_id} after setup manager exits."

def _clear_terminal_for_external_command():
    if not _tui().sys.stdout.isatty():
        return
    _tui().sys.stdout.write("\033[2J\033[H")
    _tui().sys.stdout.flush()

def _run_pending_setup(state):
    command = list(state.pending_run_command or [])
    if not command:
        return 0
    setup_id = state.pending_run_setup_id or Path(command[0]).name
    _tui()._clear_terminal_for_external_command()
    print(f"Running setup {setup_id}: {command[0]}")
    try:
        result = _tui().subprocess.run(command, check=False)
    except KeyboardInterrupt:
        return 130
    return result.returncode

def _copy_logs(state):
    text = "\n".join(state.last_action_log or state.last_action_summary or ["No logs available."])
    try:
        _tui()._copy_text_to_clipboard(text)
    except Exception as exc:
        state.message = f"Copy failed: {exc}"
        return
    state.message = "Copied log text."

def _open_logs(state):
    if not state.last_action_log:
        state.last_action_log = ["No logs available."]
    _tui()._set_mode(state, "logs")

def _open_help(state):
    state.help_return_mode = state.mode if state.mode != "help" else (state.help_return_mode or "setup-manager")
    _tui()._set_mode(state, "help")

def _health_status_from_report(report):
    return "healthy" if report and report.get("ok") else "broken"

def _yes_no(value):
    return "yes" if value else "no"

def _path_snapshot(path):
    if not path:
        return {"path": "", "exists": False, "size": None, "mtime_ns": None}
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False, "size": None, "mtime_ns": None}
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }

def _path_changed(before, after):
    return (
        before.get("exists") != after.get("exists")
        or before.get("size") != after.get("size")
        or before.get("mtime_ns") != after.get("mtime_ns")
    )

def _expected_setup_snapshot(setup_id):
    setup_dir = workspace_root() / "variants" / setup_id
    wrapper = workspace_root() / "bin" / setup_id
    config = setup_dir / "variant.json"
    return {
        "setup_dir": _path_snapshot(setup_dir),
        "wrapper": _path_snapshot(wrapper),
        "config": _path_snapshot(config),
    }

def _variant_setup_snapshot(variant):
    manifest = variant.manifest or {}
    paths = manifest.get("paths") or {}
    wrapper = paths.get("wrapper") or ""
    binary = paths.get("binary") or ""
    return {
        "manifest": dict(manifest),
        "setup_dir": _path_snapshot(variant.path),
        "wrapper": _path_snapshot(wrapper),
        "binary": _path_snapshot(binary),
        "config": _path_snapshot(variant.path / "variant.json"),
    }

def _create_failure_summary(setup_id, before, exc, failed_stage="create setup"):
    after = _expected_setup_snapshot(setup_id)
    setup_created = not before["setup_dir"]["exists"] and after["setup_dir"]["exists"]
    command_created = not before["wrapper"]["exists"] and after["wrapper"]["exists"]
    config_created = not before["config"]["exists"] and after["config"]["exists"]
    changed = any(_path_changed(before[key], after[key]) for key in ("setup_dir", "wrapper", "config"))
    cleanup_needed = setup_created or command_created or config_created
    return [
        "Create failed.",
        f"Setup: {setup_id}",
        f"Setup directory created: {_yes_no(setup_created)}",
        f"Command created: {_yes_no(command_created)}",
        f"Setup config created: {_yes_no(config_created)}",
        f"Previous state changed: {_yes_no(changed)}",
        f"Cleanup needed: {_yes_no(cleanup_needed)}",
        f"Failed stage: {failed_stage}: {exc}",
    ]

def _target_version_for_summary(state, target):
    if target == "latest":
        return str((state.download_index.get("binary") or {}).get("latest") or "")
    return str(target or "")

def _has_cached_native_artifact(state, version):
    if not version:
        return False
    return any(getattr(artifact, "version", None) == version for artifact in state.native_artifacts)

def _base_download_status(state, target_version, cached_before):
    if not target_version:
        return "unknown"
    if cached_before:
        return "already cached"
    if _has_cached_native_artifact(state, target_version):
        return "verified"
    return "not found"

def _post_variant_snapshot(setup_id, fallback):
    try:
        variant = load_variant(setup_id)
    except Exception:
        return None, fallback
    return variant, _variant_setup_snapshot(variant)

def _command_replaced_status(before, after):
    if not before.get("path") or not after.get("path"):
        return "unknown"
    if not after.get("exists"):
        return "unknown, command missing"
    return "yes" if _path_changed(before, after) else "no"

def _active_setup_status(snapshot):
    if snapshot is None:
        return "unknown"
    wrapper_exists = snapshot["wrapper"]["exists"]
    binary_exists = snapshot["binary"]["exists"]
    return "yes" if wrapper_exists and binary_exists else "no"


def _managed_install_paths(variant):
    return list(variant_install_cleanup_paths(variant))


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
            "Tweaks reapplied: yes",
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

def _begin_tweak_apply_preview(state):
    if list(state.tweaks_pending) == list(state.tweaks_baseline):
        state.message = "No tweak changes to apply."
        return
    unsupported = _tui()._unsupported_pending_tweaks(state)
    if unsupported:
        state.message = f"Unsupported tweaks selected: {', '.join(unsupported)}"
        return
    state.tweak_apply_preview = True
    state.message = "Review tweak diff, then press y to rebuild."

def _run_tweak_apply(state):
    setup_id = state.tweaks_variant_id
    if setup_id is None:
        state.message = "No setup selected."
        return
    added, removed = _tui()._tweak_diff(state)
    state.tweak_apply_preview = False
    _tui()._apply_tweaks(state)
    rebuild_log = list(state.last_action_log)
    if not state.message.startswith("Applied tweaks"):
        state.last_action_summary = _append_backend_stages([state.message], _stage_lines_from_log(rebuild_log))
        message = state.message
        _tui()._set_mode(state, "health-result")
        state.message = message
        return
    state.selected_setup_id = setup_id
    health = _run_setup_health(state, setup_id, show_result=False)
    state.last_action_log = _stage_log_lines(
        "Tweak rebuild",
        "\n".join(rebuild_log),
        "Health",
        health.get("output", ""),
    )
    state.last_tweak_result = {
        "added": added,
        "removed": removed,
        "health": health.get("status", "unknown"),
    }
    state.last_action_summary = _append_backend_stages([
        "Tweaks updated:",
        f"Added: {', '.join(added) if added else 'none'}",
        f"Removed: {', '.join(removed) if removed else 'none'}",
        "Rebuild: successful",
        f"Health: {health.get('status', 'unknown')}",
    ], _stage_lines_from_log(rebuild_log))
    state.message = f"Tweaks updated for setup {setup_id}: {health.get('status', 'unknown')}"
    message = state.message
    _tui()._set_mode(state, "health-result")
    state.message = message

def _run_dashboard_build(state):
    if not _tui()._require_dashboard_patches(state):
        return

    loaded_profile = _tui()._loaded_profile(state)
    if loaded_profile is not None:
        missing = _tui()._dashboard_tweak_profile_missing_ids(state, loaded_profile)
        if missing:
            state.message = f"Loaded profile is invalid, missing {', '.join(missing)}"
            return

    tweak_ids = _tui()._selected_dashboard_tweaks(state)
    try:
        artifact = _tui()._dashboard_artifact_for_run(state)
        if artifact is None:
            return
        result, _output = _run_quiet(apply_dashboard_tweaks_to_native, artifact, tweak_ids)
        state.message = f"Dashboard build complete: {result.output_path}"
    except Exception as exc:
        state.message = f"Dashboard build failed: {exc}"

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
    state.variant_model_choices = list(models)
    if not state.variant_model_choices:
        state.message = "Model refresh returned no models. Type aliases manually."
        return
    state.selected_index = 1
    state.message = f"Loaded {len(state.variant_model_choices)} models. Select one to apply aliases."

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
    state.models_choices = list(models)
    if not state.models_choices:
        state.message = "Model refresh returned no models. Type aliases manually."
        return
    state.selected_index = 1
    state.message = f"Loaded {len(state.models_choices)} models. Select one to apply aliases."

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
    for key, _label in VARIANT_MODEL_FIELDS:
        state.models_pending[key] = value
    state.message = f"Model aliases set to {value}"

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
    state.message = "Discarded model changes."

def _variant_model_discovery_api_key(state):
    if state.variant_store_secret and state.variant_api_key.strip():
        return state.variant_api_key.strip()
    credential_env = state.variant_credential_env.strip()
    if credential_env and credential_env in os.environ:
        return os.environ[credential_env]
    return None

def _run_variant_create(state):
    provider = _tui()._selected_variant_provider(state)
    if provider is None:
        state.message = "Select a provider first."
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
    try:
        if state.variant_install_command:
            failed_stage = "validate install command"
            install_plan, _install_plan_output = _run_quiet(
                inspect_variant_command_install,
                expected_setup_id,
                target=workspace_root() / "bin" / expected_setup_id,
                yes=True,
            )
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
            if getattr(install_plan, "status", "") == "blocked":
                install_result = install_plan
                install_output = f"Skipped command install: {install_plan.warning}"
            else:
                failed_stage = "install command"
                install_result, install_output = _run_quiet(install_variant_command, result_variant, yes=True)
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
