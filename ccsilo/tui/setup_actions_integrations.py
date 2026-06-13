"""Setup wizard integration install/prep actions."""

from .setup_actions_common import (  # noqa: F401
    _run_quiet,
    _stage_log_lines,
    _tui,
    install_local_integration,
)

__all__ = [
    "_run_variant_integration_install",
]


def _run_variant_integration_install(state):
    integration_id = str(state.pending_variant_integration_install_id or "").strip()
    if not integration_id:
        state.message = "Select an integration install action first."
        return
    try:
        result, output = _run_quiet(install_local_integration, integration_id)
    except Exception as exc:
        state.last_action_log = _stage_log_lines("Integration install failure", str(exc))
        state.last_action_summary = [
            "Integration install failed.",
            f"Integration: {integration_id}",
            f"Failed stage: install/prep: {exc}",
        ]
        state.message = f"Integration install failed: {exc}"
        return
    summary = list(getattr(result, "summary", []) or [])
    changed = "yes" if getattr(result, "changed", False) else "no"
    state.last_action_log = _stage_log_lines("Integration install", output or getattr(result, "output", ""))
    state.last_action_summary = [
        "Integration install/prep completed.",
        f"Integration: {integration_id}",
        f"Changed global state: {changed}",
        "",
        *(summary or ["No installer summary returned."]),
    ]
    state.variant_integration_install_confirm = ""
    state.pending_variant_integration_install_id = ""
    state.message = f"Integration install/prep completed: {integration_id}"
