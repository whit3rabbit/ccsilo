"""Key handling and activation dispatch for the TUI."""

from ._const import SOURCE_ARTIFACT, SOURCE_LATEST, SOURCE_VERSION
from .options import setup_upgrade_status

import sys as _sys


def _tui():
    return _sys.modules["ccsilo.tui"]


def _proxy(name):
    def call(*args, **kwargs):
        return getattr(_tui(), name)(*args, **kwargs)
    return call


__all__ = ['_event_requests_quit', '_handle_backspace_key', '_handle_char_key', '_variant_accepts_name_text', '_toggle_selected', '_activate', '_activate_tweaks_source', '_activate_tweaks_edit', '_activate_models_edit', '_activate_setup_manager', '_activate_setup_detail', '_current_setup_id_for_action', '_start_setup_create', '_open_upgrade_preview', '_open_delete_confirm', '_open_inspect_delete_confirm', '_cancel_inspect_delete', '_open_tweak_editor', '_open_tweak_adder', '_open_model_editor', '_open_variant_create_preview', '_cycle_tweak_filter', '_cycle_variant_provider_filter', '_cycle_setup_provider_filter', '_cycle_setup_sort', '_clamp_setup_manager_selection', '_activate_dashboard', '_activate_variants', '_activate_patch_packages']


def _variant_provider_selector_mode(state):
    return state.mode in {"variants", "first-run-setup"} and state.variant_step == 0


def _variant_provider_search_active(state):
    return _variant_provider_selector_mode(state) and getattr(state, "variant_provider_search_active", False)

def _event_requests_quit(event, char_key_code):
    if event.get("kind") != "key":
        return False

    key_name = str(event.get("key") or event.get("name") or "").replace("-", "+").lower()
    if key_name in {"ctrl+c", "control+c"}:
        return True

    code = event.get("code")
    code_name = str(code).lower()
    code_is_char = code == int(char_key_code) or code_name == "char"
    if not code_is_char:
        return False

    ch = event.get("ch")
    if ch in {3, "\x03"}:
        return True

    if isinstance(ch, int):
        char = chr(ch) if 0 <= ch <= 0x10FFFF else ""
    else:
        char = str(ch or "")

    modifiers = event.get("modifiers") or event.get("mods") or event.get("modifier") or ""
    if isinstance(modifiers, (list, tuple, set)):
        modifier_text = " ".join(str(modifier).lower() for modifier in modifiers)
    else:
        modifier_text = str(modifiers).lower()
    has_control = "ctrl" in modifier_text or "control" in modifier_text
    return has_control and char.lower() == "c"

def _handle_backspace_key(state):
    if state.mode == "busy":
        return True
    if state.mode == "setup-manager" and state.setup_search_active:
        state.setup_search_text = state.setup_search_text[:-1]
        _tui()._clamp_setup_manager_selection(state)
        state.message = f"Search: {state.setup_search_text or 'none'}"
        _tui()._save_setup_list_preferences(state)
        return True
    if _variant_provider_search_active(state):
        state.variant_provider_search_text = state.variant_provider_search_text[:-1]
        state.selected_index = state._clamp(state.selected_index, state.item_count())
        state.message = f"Provider search: {state.variant_provider_search_text or 'none'}"
        return True
    if state.mode in {"tweaks-edit", "tweak-editor"} and state.tweak_search_active:
        state.tweak_search = state.tweak_search[:-1]
        state.selected_index = state._clamp(state.selected_index, state.item_count())
        state.message = f"Tweak search: {state.tweak_search or 'none'}"
        return True
    if state.mode == "delete-confirm":
        state.delete_confirm_text = state.delete_confirm_text[:-1]
        return True
    if state.mode == "dashboard":
        return _tui()._dashboard_backspace(state)
    if state.mode == "models-edit":
        return _tui()._models_backspace(state)
    if state.mode in {"variants", "first-run-setup"}:
        return _tui()._variant_backspace(state)
    return False

def _handle_char_key(state, char):
    if char == "\x03":
        return False
    if state.mode == "busy":
        return True

    if state.mode == "delete-confirm":
        if char.isprintable() and char not in "\r\n\t":
            state.delete_confirm_text += char
        return True

    if state.mode == "inspect-delete-confirm":
        if char.lower() == "y":
            _tui()._run_inspect_delete(state)
        elif char.lower() == "n":
            _tui()._cancel_inspect_delete(state)
        else:
            state.message = "Press y to delete, or n/Esc to cancel."
        return True

    if state.mode == "dashboard" and _tui()._dashboard_accepts_profile_text(state):
        if char.isprintable() and char not in "\r\n\t":
            state.dashboard_profile_name += char
            state.dashboard_delete_confirm_id = ""
        return True

    if _variant_provider_search_active(state):
        if char.isprintable() and char not in "\r\n\t":
            state.variant_provider_search_text += char
            state.selected_index = state._clamp(state.selected_index, state.item_count())
            state.message = f"Provider search: {state.variant_provider_search_text}"
        return True

    if state.mode in {"variants", "first-run-setup"} and _tui()._variant_accepts_text(state):
        if char.isprintable() and char not in "\r\n\t":
            _tui()._variant_append_text(state, char)
        return True

    if state.mode == "models-edit" and _tui()._models_accepts_text(state):
        if char.isprintable() and char not in "\r\n\t":
            _tui()._models_append_text(state, char)
        return True

    if state.mode == "setup-manager" and state.setup_search_active:
        if char.isprintable() and char not in "\r\n\t":
            state.setup_search_text += char
            _tui()._clamp_setup_manager_selection(state)
            state.message = f"Search: {state.setup_search_text}"
            _tui()._save_setup_list_preferences(state)
        return True

    if state.mode in {"tweaks-edit", "tweak-editor"} and state.tweak_search_active:
        if char.isprintable() and char not in "\r\n\t":
            state.tweak_search += char
            state.selected_index = state._clamp(state.selected_index, state.item_count())
            state.message = f"Tweak search: {state.tweak_search}"
        return True

    lowered = char.lower()
    if lowered == "q":
        return False
    if char == "?":
        _tui()._open_help(state)
        return True
    if state.mode == "upgrade-preview":
        if lowered == "y":
            _tui()._start_busy_action(
                state,
                "Upgrading setup",
                f"Rebuilding setup {state.selected_setup_id or 'selected setup'}",
                _tui()._busy_upgrade_action,
            )
        elif lowered == "n":
            _tui()._go_back(state)
        return True
    if state.mode == "create-preview":
        if lowered == "y":
            name = state.variant_name.strip() or "new setup"
            _tui()._start_busy_action(
                state,
                "Creating setup",
                f"Building custom Claude setup {name}",
                _tui()._busy_create_action,
            )
        elif lowered == "i":
            state.variant_install_command = not state.variant_install_command
            state.variant_install_choice_initialized = True
            state.message = "Install command: yes" if state.variant_install_command else "Install command: no"
        elif lowered == "n":
            _tui()._go_back(state)
        return True
    if state.mode in {"tweaks-edit", "tweak-editor"} and state.tweak_apply_preview:
        if lowered == "y":
            _tui()._start_busy_action(
                state,
                "Rebuilding tweaks",
                f"Applying tweak changes to setup {state.tweaks_variant_id or 'selected setup'}",
                _tui()._busy_tweak_apply_action,
            )
        elif lowered == "n":
            state.tweak_apply_preview = False
            state.message = "Tweak rebuild cancelled."
        return True
    handled_setup_key = False
    if char == "/" and _variant_provider_selector_mode(state):
        state.variant_provider_search_active = True
        state.message = "Search providers."
        return True
    if lowered == "f" and _variant_provider_selector_mode(state):
        _cycle_variant_provider_filter(state)
        return True
    if char == "/" and state.mode == "setup-manager":
        state.setup_search_active = True
        state.message = "Search setups."
        handled_setup_key = True
    elif char == "/" and state.mode in {"tweaks-edit", "tweak-editor"}:
        state.tweak_search_active = True
        state.message = "Search tweaks."
        return True
    elif lowered == "p" and state.mode == "setup-manager":
        _tui()._cycle_setup_provider_filter(state)
        handled_setup_key = True
    elif lowered == "s" and state.mode == "setup-manager":
        _tui()._cycle_setup_sort(state)
        handled_setup_key = True
    elif lowered == "n" and state.mode in {"setup-manager", "setup-detail", "health-result"}:
        _tui()._start_setup_create(state)
        handled_setup_key = True
    elif lowered == "u" and state.mode in {"setup-manager", "setup-detail"}:
        _tui()._open_upgrade_preview(state)
        handled_setup_key = True
    elif lowered == "h" and state.mode in {"setup-manager", "setup-detail"}:
        setup_id = _tui()._current_setup_id_for_action(state)
        if setup_id:
            _tui()._run_setup_health(state, setup_id, show_result=True)
        handled_setup_key = True
    elif lowered == "d" and state.mode in {"setup-manager", "setup-detail"}:
        _tui()._open_delete_confirm(state)
        handled_setup_key = True
    elif lowered == "x" and state.mode in {"setup-manager", "setup-detail"}:
        setup_id = _tui()._current_setup_id_for_action(state)
        if setup_id:
            _tui()._queue_setup_run(state, setup_id)
        handled_setup_key = True
    elif lowered == "t" and state.mode in {"setup-manager", "setup-detail"}:
        _tui()._open_tweak_editor(state)
        handled_setup_key = True
    elif lowered == "m" and state.mode in {"setup-manager", "setup-detail"}:
        _tui()._open_model_editor(state)
        handled_setup_key = True
    elif lowered == "r" and state.mode == "setup-manager":
        _tui()._refresh_state(state)
        state.message = "Setup list refreshed."
        handled_setup_key = True
    elif lowered == "c" and state.mode == "setup-detail":
        _tui()._copy_setup_command(state)
        handled_setup_key = True
    elif lowered == "g" and state.mode == "setup-detail":
        _tui()._copy_setup_config(state)
        handled_setup_key = True
    elif lowered == "c" and state.mode in {"health-result", "logs"}:
        _tui()._copy_logs(state)
        handled_setup_key = True
    elif lowered == "l" and state.mode in {"setup-detail", "health-result"}:
        _tui()._open_logs(state)
        handled_setup_key = True
    if handled_setup_key:
        return not state.pending_run_command
    if lowered == "b":
        _tui()._go_back(state)
    elif lowered == "t":
        if state.mode not in {"setup-manager", "setup-detail"}:
            _tui()._cycle_theme(state)
    elif lowered == "a" and state.mode in {"tweaks-edit", "tweak-editor"}:
        _tui()._begin_tweak_apply_preview(state)
    elif lowered == "d" and state.mode in {"tweaks-edit", "tweak-editor"}:
        _tui()._discard_tweaks(state)
    elif lowered == "a" and state.mode == "models-edit":
        _tui()._apply_models(state)
    elif lowered == "d" and state.mode == "models-edit":
        _tui()._discard_models(state)
    elif lowered == "d" and state.mode == "inspect":
        _tui()._open_inspect_delete_confirm(state)
    elif lowered == "v" and state.mode in {"tweaks-edit", "tweak-editor", "variants", "first-run-setup"}:
        _tui()._cycle_tweak_filter(state)
    elif char == " ":
        _tui()._toggle_selected(state)
    elif lowered == "r" and state.mode == "dashboard" and state.dashboard_step == 0:
        _tui()._refresh_dashboard_index(state)

    return True

def _variant_accepts_name_text(state):
    if state.mode not in {"variants", "first-run-setup"} or state.variant_step != 1:
        return False
    option = _tui()._selected_variant_option(state)
    return option is not None and option.kind == "variant-name"

def _toggle_selected(state):
    if state.mode == "dashboard":
        option = _tui()._selected_dashboard_option(state)
        if option and option.kind == "dashboard-tweak-toggle":
            _tui()._toggle_dashboard_tweak(state, str(option.value))
    elif state.mode == "patch-package":
        _tui()._toggle_patch(state)
    elif state.mode in {"variants", "first-run-setup"}:
        option = _tui()._selected_variant_option(state)
        if option and option.kind == "variant-tweak":
            _tui()._toggle_variant_tweak(state, str(option.value))
        elif option and option.kind == "variant-architect-mode":
            _tui()._toggle_variant_tweak(state, str(option.value))
        elif option and option.kind == "variant-mcp":
            _tui()._toggle_variant_mcp(state, str(option.value))
        elif option and option.kind == "variant-store-secret":
            _tui()._toggle_variant_store_secret(state)
        elif option and option.kind == "variant-ccrouter-autostart":
            _tui()._toggle_variant_ccrouter_autostart(state)
        elif option and option.kind == "variant-model-proxy":
            _tui()._toggle_variant_model_proxy(state)
    elif state.mode in {"tweaks-edit", "tweak-editor"}:
        _tui()._toggle_tweak(state)

def _activate(state):
    state.message = ""
    if state.mode == "setup-manager" and state.setup_search_active:
        state.setup_search_active = False
        state.message = f"Search filter kept: {state.setup_search_text or 'none'}"
        return True
    if _variant_provider_search_active(state):
        state.variant_provider_search_active = False
        state.message = f"Provider search kept: {state.variant_provider_search_text or 'none'}"
        return True
    if state.mode in {"tweaks-edit", "tweak-editor"} and state.tweak_search_active:
        state.tweak_search_active = False
        state.message = f"Tweak search kept: {state.tweak_search or 'none'}"
        return True
    if state.mode == "busy":
        return True
    try:
        if state.mode == "setup-manager":
            _tui()._activate_setup_manager(state)
        elif state.mode == "setup-detail":
            _tui()._activate_setup_detail(state)
        elif state.mode == "first-run-setup":
            _tui()._activate_variants(state)
        elif state.mode == "create-preview":
            state.message = "Press y to create this setup, or n/Esc to cancel."
        elif state.mode == "upgrade-preview":
            state.message = "Press y to proceed, or n/Esc to cancel."
        elif state.mode == "delete-confirm":
            _tui()._run_setup_delete(state)
        elif state.mode == "health-result":
            _tui()._set_mode(state, "setup-detail" if state.selected_setup_id else "setup-manager")
        elif state.mode == "dashboard":
            _tui()._activate_dashboard(state)
        elif state.mode == "inspect":
            _tui()._activate_inspect(state)
        elif state.mode == "inspect-delete-confirm":
            state.message = "Press y to delete, or n/Esc to cancel."
        elif state.mode == "extract":
            _tui()._activate_extract(state)
        elif state.mode == "patch-source":
            _tui()._activate_patch_source(state)
        elif state.mode == "patch-package":
            _tui()._activate_patch_packages(state)
        elif state.mode == "variants":
            _tui()._activate_variants(state)
        elif state.mode == "models-edit":
            _tui()._activate_models_edit(state)
        elif state.mode == "tweaks-source":
            _tui()._activate_tweaks_source(state)
        elif state.mode in {"tweaks-edit", "tweak-editor"}:
            _tui()._activate_tweaks_edit(state)
    except Exception as exc:
        state.message = f"Action failed: {exc}"

    _tui()._refresh_state(state)
    return not state.pending_run_command

def _activate_tweaks_source(state):
    """Enter tweak-editor scoped to the selected setup."""
    variant_id = _tui()._selected_tweaks_source_variant_id(state)
    if variant_id is None:
        state.message = "No setup available - create one first."
        return
    _tui()._enter_tweaks_for_variant(state, variant_id)

def _activate_tweaks_edit(state):
    """Enter on a patch row toggles it (mirrors Space)."""
    if state.tweak_apply_preview:
        state.message = "Press y to rebuild, or n/Esc to cancel."
        return
    _tui()._toggle_tweak(state)

def _activate_models_edit(state):
    option = _tui()._selected_models_edit_option(state)
    if option is None:
        return
    if option.kind == "section":
        return
    if option.kind == "models-refresh":
        _tui()._refresh_models_editor_models(state)
    elif option.kind == "models-choice":
        _tui()._apply_models_choice(state, str(option.value))
    elif option.kind == "models-field":
        state.message = f"Type the {option.value} model alias, or Backspace to clear it."
    elif option.kind == "models-apply":
        _tui()._apply_models(state)
    elif option.kind in {"models-discard", "models-back"}:
        _tui()._discard_models(state)

def _activate_setup_manager(state):
    option = _tui()._selected_setup_option(state)
    if option is None:
        return
    if option.kind == "setup-action-new":
        _tui()._start_setup_create(state)
    elif option.kind == "setup-row":
        state.selected_setup_id = str(option.value)
        _tui()._set_mode(state, "setup-detail")

def _activate_setup_detail(state):
    option = _tui()._selected_setup_option(state)
    if option is None:
        return
    setup_id = str(option.value) if option.value else _tui()._current_setup_id_for_action(state)
    if option.kind == "setup-action-new":
        _tui()._start_setup_create(state)
    elif option.kind == "setup-action-run" and setup_id:
        _tui()._queue_setup_run(state, setup_id)
    elif option.kind == "setup-action-health" and setup_id:
        _tui()._run_setup_health(state, setup_id, show_result=True)
    elif option.kind == "setup-action-upgrade":
        _tui()._open_upgrade_preview(state)
    elif option.kind == "setup-action-models":
        _tui()._open_model_editor(state)
    elif option.kind == "setup-action-tweaks":
        _tui()._open_tweak_editor(state)
    elif option.kind == "setup-action-add-tweaks":
        _tui()._open_tweak_adder(state)
    elif option.kind == "setup-action-delete":
        _tui()._open_delete_confirm(state)
    elif option.kind.startswith("setup-action-ccrouter-") and setup_id:
        action = option.kind.replace("setup-action-ccrouter-", "")
        _tui()._run_setup_ccrouter_action(state, setup_id, action)

def _current_setup_id_for_action(state):
    option = _tui()._selected_setup_option(state)
    if state.mode == "setup-manager":
        if option is None or option.kind != "setup-row":
            state.message = "Select a setup first."
            return None
        return str(option.value)
    setup_id = state.selected_setup_id
    if not setup_id:
        state.message = "Select a setup first."
        return None
    return setup_id

def _start_setup_create(state):
    _tui()._reset_variant(state)
    state.tweak_filter = "recommended"
    _tui()._set_mode(state, "variants" if state.variants else "first-run-setup")

def _open_upgrade_preview(state):
    setup_id = _tui()._current_setup_id_for_action(state)
    if setup_id is None:
        return
    version_check_message = ""
    if not _tui()._refresh_startup_download_index(state):
        version_check_message = state.message
    state.selected_setup_id = setup_id
    state.setup_upgrade_target = "latest"
    state.last_action_summary = []
    _tui()._set_mode(state, "upgrade-preview")
    variant = _tui()._selected_setup_variant(state)
    if version_check_message:
        state.message = version_check_message
    elif variant is not None:
        status = setup_upgrade_status(state, variant)
        if status["state"] == "available":
            state.message = f"Update available: {status['current']} -> {status['latest']}"
        elif status["state"] == "current":
            state.message = "No newer Claude Code version found. Rebuild will reapply patches."
        elif status["state"] == "ahead":
            state.message = "Current Claude Code is newer than the latest version index."
        elif status["latest"]:
            state.message = f"Latest Claude Code in version index: {status['latest']}"

def _open_delete_confirm(state):
    setup_id = _tui()._current_setup_id_for_action(state)
    if setup_id is None:
        return
    state.selected_setup_id = setup_id
    state.delete_confirm_text = ""
    _tui()._set_mode(state, "delete-confirm")

def _open_inspect_delete_confirm(state):
    artifact = _tui()._selected_artifact(state)
    if artifact is None:
        return
    state.inspect_delete_confirm_path = str(artifact.path)
    _tui()._set_mode(state, "inspect-delete-confirm")
    state.message = "Confirm deleting this downloaded native artifact."

def _cancel_inspect_delete(state):
    state.inspect_delete_confirm_path = ""
    _tui()._set_mode(state, "inspect")
    state.message = "Delete cancelled."

def _open_tweak_editor(state):
    setup_id = _tui()._current_setup_id_for_action(state)
    if setup_id is None:
        return
    _tui()._enter_tweaks_for_variant(state, setup_id)

def _open_tweak_adder(state):
    setup_id = _tui()._current_setup_id_for_action(state)
    if setup_id is None:
        return
    _tui()._enter_tweaks_for_variant(state, setup_id)
    state.tweak_filter = "all"
    state.selected_index = 0
    state.message = "Showing all available tweaks for this setup."

def _open_model_editor(state):
    setup_id = _tui()._current_setup_id_for_action(state)
    if setup_id is None:
        return
    variant = next((item for item in state.variants if item.variant_id == setup_id), None)
    if variant is None:
        state.message = f"Setup not found: {setup_id}"
        return
    baseline = {
        key: str(value).strip()
        for key, value in ((variant.manifest or {}).get("modelOverrides") or {}).items()
        if str(value).strip()
    }
    state.selected_setup_id = setup_id
    state.models_variant_id = setup_id
    state.models_baseline = dict(baseline)
    state.models_pending = dict(baseline)
    state.models_choices = []
    _tui()._set_mode(state, "models-edit")

def _open_variant_create_preview(state):
    provider = _tui()._selected_variant_provider(state)
    if provider is None:
        state.message = "Select a provider first."
        return
    if not state.variant_name.strip():
        state.message = "Type a setup name first."
        return
    if not _tui()._validate_variant_endpoint(state, provider):
        return
    if not _tui()._validate_variant_secret(state):
        return
    if not state.variant_install_choice_initialized:
        state.variant_install_command = _tui().default_install_dir() is not None
        state.variant_install_choice_initialized = True
    state.last_action_summary = []
    _tui()._set_mode(state, "create-preview")

def _cycle_tweak_filter(state):
    order = ["recommended", "all", "advanced", "incompatible"]
    current = state.tweak_filter if state.tweak_filter in order else "recommended"
    state.tweak_filter = order[(order.index(current) + 1) % len(order)]
    state.selected_index = 0
    state.message = f"Tweak view: {state.tweak_filter}"

def _cycle_variant_provider_filter(state):
    order = ["all", "recommended", "cloud", "local", "model-map", "mcp"]
    current = state.variant_provider_filter if state.variant_provider_filter in order else "all"
    state.variant_provider_filter = order[(order.index(current) + 1) % len(order)]
    state.selected_index = 0
    state.message = f"Provider filter: {state.variant_provider_filter}"

def _cycle_setup_provider_filter(state):
    options = ["all", *_tui()._setup_provider_keys(state)]
    current = state.setup_provider_filter if state.setup_provider_filter in options else "all"
    state.setup_provider_filter = options[(options.index(current) + 1) % len(options)]
    state.selected_index = 0
    state.message = f"Provider filter: {state.setup_provider_filter}"
    _tui()._save_setup_list_preferences(state)

def _cycle_setup_sort(state):
    order = ["name", "provider", "health", "updated", "version"]
    current = state.setup_sort_key if state.setup_sort_key in order else "name"
    state.setup_sort_key = order[(order.index(current) + 1) % len(order)]
    state.selected_index = 0
    state.message = f"Setup sort: {state.setup_sort_key}"
    _tui()._save_setup_list_preferences(state)

def _clamp_setup_manager_selection(state):
    count = state.item_count()
    if count < 1:
        state.selected_index = 0
    else:
        state.selected_index = max(0, min(state.selected_index, count - 1))

def _activate_dashboard(state):
    option = _tui()._selected_dashboard_option(state)
    if option is None:
        return

    if option.kind != "profile-delete":
        state.dashboard_delete_confirm_id = ""

    if option.kind == "section":
        return
    if option.kind == "source-latest":
        state.dashboard_source_kind = SOURCE_LATEST
        state.dashboard_source_version = ""
        _tui()._advance_dashboard(state)
    elif option.kind == "source-version":
        state.dashboard_source_kind = SOURCE_VERSION
        state.dashboard_source_version = option.value
        _tui()._advance_dashboard(state)
    elif option.kind == "source-artifact":
        state.dashboard_source_kind = SOURCE_ARTIFACT
        state.dashboard_source_artifact_index = int(option.value)
        _tui()._advance_dashboard(state)
    elif option.kind == "refresh-index":
        _tui()._refresh_dashboard_index(state)
    elif option.kind == "dashboard-tweak-toggle":
        _tui()._toggle_dashboard_tweak(state, str(option.value))
    elif option.kind == "profile-load":
        _tui()._load_dashboard_profile(state, str(option.value))
    elif option.kind == "patch-continue":
        if _tui()._require_dashboard_patches(state):
            _tui()._advance_dashboard(state)
    elif option.kind == "profile-name":
        state.message = "Type a profile name here, then choose a profile action."
    elif option.kind == "profile-create":
        _tui()._create_dashboard_profile(state)
    elif option.kind == "profile-rename":
        _tui()._rename_dashboard_profile(state, str(option.value))
    elif option.kind == "profile-overwrite":
        _tui()._overwrite_dashboard_profile(state, str(option.value))
    elif option.kind == "profile-delete":
        _tui()._delete_dashboard_profile(state, str(option.value))
    elif option.kind == "review-continue":
        if _tui()._require_dashboard_patches(state):
            _tui()._advance_dashboard(state)
    elif option.kind == "review-run":
        _tui()._run_dashboard_build(state)
    elif option.kind == "review-back":
        state.dashboard_step = 2
        state.selected_index = 0
    elif option.kind == "review-reset":
        _tui()._reset_dashboard(state)

def _activate_variants(state):
    option = _tui()._selected_variant_option(state)
    if option is None:
        return
    if option.kind == "section":
        return
    if option.kind == "variant-status":
        try:
            report = _tui().doctor_variant(str(option.value))
            ok = report[0]["ok"] if report else False
            state.message = f"Setup {option.value}: {'healthy' if ok else 'broken'}"
        except Exception as exc:
            state.message = f"Setup status failed: {exc}"
    elif option.kind == "variant-provider":
        state.variant_provider_index = int(option.value)
        provider = _tui()._selected_variant_provider(state)
        _tui()._set_variant_provider_defaults(state, provider)
        _tui()._advance_variant(state)
    elif option.kind == "variant-name":
        state.message = "Type a setup name here, then continue."
    elif option.kind == "variant-name-continue":
        if not state.variant_name.strip():
            state.message = "Type a setup name first."
            return
        _tui()._advance_variant(state)
    elif option.kind == "variant-version-latest":
        state.variant_claude_version = "latest"
        state.message = "Claude Code version: latest"
    elif option.kind == "variant-version":
        state.variant_claude_version = str(option.value)
        state.message = f"Claude Code version: {state.variant_claude_version}"
    elif option.kind == "variant-version-refresh":
        _tui()._refresh_dashboard_index(state)
    elif option.kind == "variant-credential-env":
        state.message = "Type a credential environment variable name."
    elif option.kind == "variant-endpoint":
        state.message = "Type the provider endpoint URL, including http:// or https://."
    elif option.kind == "variant-api-key":
        state.message = "Type the API key. It will be stored only in this setup's secrets.env."
    elif option.kind == "variant-credentials-continue":
        provider = _tui()._selected_variant_provider(state)
        if not _tui()._validate_variant_endpoint(state, provider):
            return
        if not _tui()._validate_variant_secret(state):
            return
        state.variant_step = 3
        state.selected_index = 0
    elif option.kind == "variant-store-secret":
        _tui()._toggle_variant_store_secret(state)
        state.message = "Local API key storage enabled." if state.variant_store_secret else "Local API key storage disabled."
    elif option.kind == "variant-ccrouter-mode":
        _tui()._cycle_variant_ccrouter_mode(state)
    elif option.kind == "variant-ccrouter-config":
        _tui()._cycle_variant_ccrouter_config(state)
    elif option.kind == "variant-ccrouter-package":
        state.message = "Type the CCR npm package spec."
    elif option.kind == "variant-ccrouter-port":
        state.message = "Type a CCR port, or auto."
    elif option.kind == "variant-ccrouter-autostart":
        _tui()._toggle_variant_ccrouter_autostart(state)
    elif option.kind == "variant-model-proxy":
        _tui()._toggle_variant_model_proxy(state)
    elif option.kind == "variant-model-proxy-port":
        state.message = "Type a model proxy port, or auto."
    elif option.kind == "variant-mcp":
        _tui()._toggle_variant_mcp(state, str(option.value))
    elif option.kind == "variant-mcp-continue":
        provider = _tui()._selected_variant_provider(state)
        if provider and not provider.get("requiresModelMapping"):
            state.variant_step = 5
            state.selected_index = 0
        else:
            _tui()._advance_variant(state)
    elif option.kind == "variant-model":
        state.message = f"Type the {option.value} model alias, or clear it to use the provider default."
    elif option.kind == "variant-model-refresh":
        _tui()._refresh_variant_models(state)
    elif option.kind == "variant-model-choice":
        _tui()._apply_variant_model_choice(state, str(option.value))
    elif option.kind == "variant-models-continue":
        if _tui()._require_variant_model_mapping(state):
            _tui()._advance_variant(state)
    elif option.kind == "variant-architect-mode":
        _tui()._toggle_variant_tweak(state, str(option.value))
    elif option.kind == "variant-tweak":
        _tui()._toggle_variant_tweak(state, str(option.value))
    elif option.kind == "variant-tweak-view":
        state.tweak_filter = str(option.value)
        state.selected_index = 0
    elif option.kind == "variant-tweaks-continue":
        _tui()._advance_variant(state)
    elif option.kind == "variant-create":
        _tui()._open_variant_create_preview(state)
    elif option.kind == "variant-review-back":
        state.variant_step = 5
        state.selected_index = 0
    elif option.kind == "variant-reset":
        _tui()._reset_variant(state)

def _activate_patch_packages(state):
    artifact = _tui()._source_artifact(state)
    if artifact is None:
        _tui()._set_mode(state, "patch-source")
        return
    if not state.selected_patch_indexes:
        state.message = "Select at least one patch package with Space."
        return

    packages = [
        state.patch_packages[index]
        for index in state.selected_patch_indexes
        if 0 <= index < len(state.patch_packages)
    ]
    if not packages:
        state.message = "Selected patch packages are unavailable."
        return
    try:
        result, _output = _tui()._run_quiet(_tui().apply_patch_packages_to_native, artifact, packages)
        state.message = f"Patched binary: {result.output_path}"
        _tui()._set_mode(state, "patch-source")
    except Exception as exc:
        state.message = f"Patch failed: {exc}"
