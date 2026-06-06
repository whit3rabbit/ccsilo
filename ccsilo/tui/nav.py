"""Tab/mode navigation, simple toggles, and inspect/extract activators.

None of these helpers reference monkey-patched names. The action-layer in
:mod:`ccsilo.tui` re-exports them for tests that reach in via
``tui._move_tab`` / ``tui._activate_extract``.
"""

from ..bun_extract import parse_bun_binary
from ..extractor import extract_all
from ..workspace import (
    extraction_paths,
    short_sha,
    workspace_root,
)
from ._const import TABS, TAB_MODES
from ._runtime import run_quiet
from .rendering import active_tab


def set_mode(state, mode: str) -> None:
    if state.mode != mode:
        state.message = ""
    state.mode = mode
    state.selected_index = 0


def move_tab(state, offset: int) -> None:
    active = active_tab(state)
    current = TABS.index(active)
    next_index = (current + offset) % len(TABS)
    set_mode(state, TAB_MODES[next_index])


def go_back(state) -> None:
    if state.mode == "setup-manager" and getattr(state, "setup_search_active", False):
        state.setup_search_active = False
        state.message = "Search filter kept."
    elif state.mode == "setup-detail":
        set_mode(state, "setup-manager")
    elif state.mode == "help":
        set_mode(state, state.help_return_mode or "setup-manager")
    elif state.mode in {"upgrade-preview", "delete-confirm", "logs", "error"}:
        set_mode(state, "setup-detail" if state.selected_setup_id else "setup-manager")
    elif state.mode == "inspect-delete-confirm":
        state.inspect_delete_confirm_path = ""
        set_mode(state, "inspect")
        state.message = "Delete cancelled."
    elif state.mode == "create-preview":
        set_mode(state, "variants" if state.variants else "first-run-setup")
    elif state.mode == "health-result":
        set_mode(state, "setup-detail" if state.selected_setup_id else "setup-manager")
    elif state.mode == "first-run-setup":
        if state.variant_step == 0 and getattr(state, "variant_provider_search_active", False):
            state.variant_provider_search_active = False
            state.message = "Provider search kept."
            return
        if state.variant_step == 4 and getattr(state, "variant_model_search_active", False):
            state.variant_model_search_active = False
            state.message = "Model search kept."
            return
        if state.variant_step > 0:
            state.variant_step -= 1
            state.selected_index = 0
    elif state.mode == "dashboard":
        if state.dashboard_delete_confirm_id:
            state.dashboard_delete_confirm_id = ""
            state.message = "Delete cancelled."
            return
        if state.dashboard_step > 0:
            state.dashboard_step -= 1
            state.selected_index = 0
    elif state.mode == "patch-package":
        set_mode(state, "patch-source")
    elif state.mode == "variants":
        if state.variant_step == 0 and getattr(state, "variant_provider_search_active", False):
            state.variant_provider_search_active = False
            state.message = "Provider search kept."
            return
        if state.variant_step == 4 and getattr(state, "variant_model_search_active", False):
            state.variant_model_search_active = False
            state.message = "Model search kept."
            return
        if state.variant_step > 0:
            state.variant_step -= 1
            state.selected_index = 0
        else:
            set_mode(state, "setup-manager")
    elif state.mode in {"tweaks-edit", "tweak-editor"}:
        if getattr(state, "tweak_search_active", False):
            state.tweak_search_active = False
            state.message = "Tweak search kept."
            return
        if state.tweak_apply_preview:
            state.tweak_apply_preview = False
            state.message = "Tweak rebuild cancelled."
            return
        if list(state.tweaks_pending) != list(state.tweaks_baseline):
            discard_tweaks(state)
        else:
            state.tweaks_variant_id = None
            state.tweaks_pending = []
            state.tweaks_baseline = ()
            state.tweak_search = ""
            state.tweak_search_active = False
            set_mode(state, "setup-detail" if state.selected_setup_id else "setup-manager")
    elif state.mode == "models-edit":
        if getattr(state, "models_search_active", False):
            state.models_search_active = False
            state.message = "Model search kept."
            return
        state.models_variant_id = None
        state.models_baseline = {}
        state.models_pending = {}
        state.models_choices = []
        state.models_search_text = ""
        state.models_search_active = False
        state.models_target = "opus"
        set_mode(state, "setup-detail" if state.selected_setup_id else "setup-manager")


def toggle_patch(state) -> None:
    if not state.patch_packages:
        return
    index = state.selected_index
    if index in state.selected_patch_indexes:
        state.selected_patch_indexes.remove(index)
    else:
        state.selected_patch_indexes.append(index)
        state.selected_patch_indexes.sort()


def selected_artifact(state):
    if not state.native_artifacts:
        state.message = "No centralized native downloads found."
        return None
    return state.native_artifacts[state.selected_index]


def source_artifact(state):
    if not state.native_artifacts:
        return None
    index = max(0, min(state.selected_source_index, len(state.native_artifacts) - 1))
    return state.native_artifacts[index]


def activate_inspect(state):
    artifact = selected_artifact(state)
    if artifact is None:
        return
    try:
        data = artifact.path.read_bytes()
        info = parse_bun_binary(data)
        entry = info.modules[info.entry_point_id].name if 0 <= info.entry_point_id < len(info.modules) else "unknown"
        state.message = (
            f"{artifact.version} {artifact.platform} {short_sha(artifact.sha256)}: "
            f"{info.platform}, {len(info.modules)} modules, entry {entry}"
        )
    except Exception as exc:
        state.message = f"Inspect failed: {exc}"


def activate_extract(state):
    artifact = selected_artifact(state)
    if artifact is None:
        return
    try:
        run_quiet(extract_all, str(artifact.path), source_version=artifact.version)
        _, bundle_path = extraction_paths(artifact.version, artifact.platform, artifact.sha256)
        state.message = f"Extraction ready: {bundle_path}"
    except Exception as exc:
        state.message = f"Extract failed: {exc}"


def activate_patch_source(state):
    artifact = selected_artifact(state)
    if artifact is None:
        return
    if not state.patch_packages:
        state.message = f"No patch packages found under {workspace_root() / 'patches' / 'packages'}"
        return
    state.selected_source_index = state.selected_index
    state.selected_patch_indexes = []
    set_mode(state, "patch-package")


def enter_tweaks_for_variant(state, variant_id: str) -> None:
    """Enter tweak-editor mode scoped to the given setup."""
    variant = next((v for v in state.variants if v.variant_id == variant_id), None)
    if variant is None:
        state.message = f"Setup {variant_id!r} not found"
        return
    manifest = variant.manifest or {}
    baseline = tuple(manifest.get("tweaks", []) or [])
    state.tweaks_variant_id = variant_id
    state.tweaks_baseline = baseline
    state.tweaks_pending = list(baseline)
    state.selected_setup_id = variant_id
    state.tweak_search = ""
    state.tweak_search_active = False
    state.tweak_apply_preview = False
    state.message = ""
    set_mode(state, "tweak-editor")


def toggle_tweak(state) -> None:
    """Toggle the patch under the cursor in `state.tweaks_pending`."""
    from .options import selected_tweaks_edit_option, tweak_status

    option = selected_tweaks_edit_option(state)
    if option is None or option.kind != "tweak-toggle":
        return
    patch_id = option.value
    status = tweak_status(state, str(patch_id))
    if not status["selectable"] and patch_id not in state.tweaks_pending:
        state.message = f"Tweak not selectable: {status['reason']}"
        return
    if patch_id in state.tweaks_pending:
        state.tweaks_pending = [pid for pid in state.tweaks_pending if pid != patch_id]
    else:
        state.tweaks_pending = list(state.tweaks_pending) + [patch_id]
    _refresh_tweaks_pending_message(state)


def discard_tweaks(state) -> None:
    """Reset pending changes back to the baseline."""
    if state.tweaks_variant_id is None:
        return
    state.tweaks_pending = list(state.tweaks_baseline)
    state.tweak_apply_preview = False
    state.message = "Discarded pending tweak changes."


def apply_tweaks(state) -> None:
    """Persist `tweaks_pending` to the setup config and rebuild."""
    if state.tweaks_variant_id is None:
        state.message = "No setup selected."
        return
    if list(state.tweaks_pending) == list(state.tweaks_baseline):
        state.message = "No tweak changes to apply."
        return

    # Local imports avoid circular imports + let tests monkey-patch them via
    # ccsilo.tui.nav (or via ccsilo.variants directly).
    from .. import variants as variants_module
    from ..variants.model import validate_variant_manifest
    from ..workspace import write_json

    variant_id = state.tweaks_variant_id
    pending = sorted(set(state.tweaks_pending))
    baseline_set = set(state.tweaks_baseline)
    pending_set = set(pending)
    added = sorted(pending_set - baseline_set)
    removed = sorted(baseline_set - pending_set)

    try:
        variant = variants_module.load_variant(variant_id)
    except Exception as exc:
        state.message = f"Failed to load setup: {exc}"
        return

    manifest = dict(variant.manifest or {})
    manifest["tweaks"] = pending

    try:
        validate_variant_manifest(manifest)
        write_json(variant.path / "variant.json", manifest)
    except Exception as exc:
        state.message = f"Failed to update setup config: {exc}"
        return

    claude_version = (manifest.get("source") or {}).get("version")
    try:
        result, output = run_quiet(variants_module.apply_variant, variant_id, claude_version=claude_version)
        log_lines = output.splitlines() if output else ["No rebuild output captured."]
        stage_lines = _build_stage_lines(getattr(result, "stages", []))
        if stage_lines:
            log_lines.extend(["[Build stages]", *stage_lines])
        state.last_action_log = log_lines
    except Exception as exc:
        stage_lines = _build_stage_lines(getattr(exc, "stages", []))
        state.last_action_log = [f"Apply failed: {exc}"]
        if stage_lines:
            state.last_action_log.extend(["[Build stages]", *stage_lines])
        state.message = f"Apply failed: {exc}"
        return

    # Refresh state from the now-rebuilt setup.
    state.refresh()
    refreshed = next((v for v in state.variants if v.variant_id == variant_id), None)
    if refreshed is not None:
        new_baseline = tuple((refreshed.manifest or {}).get("tweaks", []) or [])
        state.tweaks_baseline = new_baseline
        state.tweaks_pending = list(new_baseline)
    state.message = (
        f"Applied tweaks to setup {variant_id} "
        f"(+{len(added)} added, -{len(removed)} removed)."
    )


def _refresh_tweaks_pending_message(state) -> None:
    pending = set(state.tweaks_pending)
    baseline = set(state.tweaks_baseline)
    diff = (pending - baseline) | (baseline - pending)
    if not diff:
        state.message = ""
    else:
        state.message = (
            f"{len(diff)} pending change{'s' if len(diff) != 1 else ''} - "
            "press 'a' to apply, 'b' to discard"
        )


def _build_stage_lines(stages):
    lines = []
    for stage in stages or []:
        if isinstance(stage, dict):
            name = stage.get("name", "stage")
            status = stage.get("status", "unknown")
            detail = stage.get("detail", "")
        else:
            name = getattr(stage, "name", "stage")
            status = getattr(stage, "status", "unknown")
            detail = getattr(stage, "detail", "")
        line = f"{name}: {status}"
        if detail:
            line = f"{line} ({detail})"
        lines.append(line)
    return lines
