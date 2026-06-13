"""Busy-state helpers for the TUI action layer."""

import copy
import concurrent.futures

import sys as _sys


def _tui():
    return _sys.modules["ccsilo.tui"]


def _proxy(name):
    def call(*args, **kwargs):
        return getattr(_tui(), name)(*args, **kwargs)
    return call

_BUSY_TICK_MS = 250
_BUSY_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="ccsilo-tui",
)

__all__ = [
    "_BUSY_TICK_MS",
    "_clear_busy_state",
    "_copy_completed_busy_state",
    "_run_busy_action",
    "_start_busy_action",
    "_poll_busy_action",
    "_busy_create_action",
    "_busy_integration_install_action",
    "_busy_upgrade_action",
    "_busy_tweak_apply_action",
]

def _clear_busy_state(state):
    state.busy_title = ""
    state.busy_detail = ""
    state.busy_ticks = 0
    state.busy_future = None

def _copy_completed_busy_state(state, completed_state):
    state.__dict__.clear()
    state.__dict__.update(copy.deepcopy(completed_state.__dict__))
    _clear_busy_state(state)

def _run_busy_action(worker_state, action):
    _clear_busy_state(worker_state)
    action(worker_state)
    return worker_state

def _start_busy_action(state, title, detail, action):
    if state.busy_future is not None:
        state.message = "Already working. Input is locked while this runs."
        return False
    worker_state = copy.deepcopy(state)
    future = _BUSY_EXECUTOR.submit(_run_busy_action, worker_state, action)
    state.busy_title = str(title)
    state.busy_detail = str(detail)
    state.busy_ticks = 0
    state.busy_future = future
    state.message = f"{title}..."
    _tui()._set_mode(state, "busy")
    state.message = f"{title}..."
    return True

def _poll_busy_action(state):
    if state.mode != "busy" or state.busy_future is None:
        return False
    state.busy_ticks += 1
    if not state.busy_future.done():
        return False
    future = state.busy_future
    try:
        completed_state = future.result()
    except Exception as exc:
        _clear_busy_state(state)
        state.last_action_log = _tui()._stage_log_lines("Busy action failure", str(exc))
        state.last_action_summary = [f"Action failed: {exc}"]
        state.message = f"Action failed: {exc}"
        _tui()._set_mode(state, "error")
        state.message = f"Action failed: {exc}"
        return True
    _copy_completed_busy_state(state, completed_state)
    return True

def _busy_create_action(worker_state):
    _tui()._run_variant_create(worker_state)
    _tui()._refresh_state(worker_state)

def _busy_integration_install_action(worker_state):
    _tui()._run_variant_integration_install(worker_state)
    _tui()._refresh_state(worker_state)

def _busy_upgrade_action(worker_state):
    _tui()._run_setup_upgrade(worker_state)

def _busy_tweak_apply_action(worker_state):
    _tui()._run_tweak_apply(worker_state)
    _tui()._refresh_state(worker_state)
