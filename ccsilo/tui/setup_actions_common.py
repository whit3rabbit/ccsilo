"""Shared proxy, logging, and status helpers for TUI setup actions."""

from pathlib import Path
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
replace_variant_command_alias = _proxy('replace_variant_command_alias')
run_ccrouter_command = _proxy('run_ccrouter_command')
variant_install_cleanup_paths = _proxy('variant_install_cleanup_paths')
_models_pending_diff = _proxy('_models_pending_diff')
download_versions = _proxy('download_versions')
effective_latest_download_version = _proxy('effective_latest_download_version')
refresh_download_index = _proxy('refresh_download_index')

__all__ = [
    "_tui",
    "_proxy",
    "_refresh_state",
    "_refresh_startup_download_index",
    "_route_startup",
    "_load_saved_setup_list_preferences",
    "_save_setup_list_preferences",
    "_log_lines",
    "_stage_log_lines",
    "_build_stage_lines",
    "_exception_stage_lines",
    "_result_stage_lines",
    "_append_backend_stages",
    "_stage_lines_from_log",
    "_copy_text_to_clipboard",
    "_health_status_from_report",
    "_yes_no",
    "_path_snapshot",
    "_path_changed",
    "_expected_setup_snapshot",
    "_variant_setup_snapshot",
    "_create_failure_summary",
    "_target_version_for_summary",
    "_has_cached_native_artifact",
    "_base_download_status",
    "_post_variant_snapshot",
    "_command_replaced_status",
    "_active_setup_status",
    "_managed_install_paths",
    "load_tui_settings",
    "save_tui_settings",
    "workspace_root",
    "default_bin_dir",
    "doctor_variant",
    "update_variants",
    "load_variant",
    "remove_variant",
    "delete_native_download",
    "short_sha",
    "_run_quiet",
    "apply_dashboard_tweaks_to_native",
    "fetch_provider_models",
    "stored_credential_value",
    "update_variant_models",
    "provider_default_variant_name",
    "variant_id_from_name",
    "create_variant",
    "inspect_variant_command_install",
    "install_variant_command",
    "replace_variant_command_alias",
    "run_ccrouter_command",
    "variant_install_cleanup_paths",
    "_models_pending_diff",
    "download_versions",
    "effective_latest_download_version",
    "refresh_download_index",
]

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
        return effective_latest_download_version(state.download_index)
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
