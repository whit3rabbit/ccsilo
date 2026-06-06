"""TUI chrome, footer, progress, and headless text helpers."""

from ..workspace import workspace_root
from ._const import DASHBOARD_STEPS, TABS, TAB_MODES, VARIANT_STEPS
from .options import (
    dashboard_source_label,
    dashboard_tweak_ids,
    loaded_profile,
    models_pending_diff,
    selected_dashboard_packages,
    selected_dashboard_tweaks,
    selected_variant_provider,
    setup_detail_lines,
    setup_manager_control_summary,
    tweak_control_summary,
    tweak_diff,
    tweaks_edit_groups,
    variant_provider_detail_lines,
    variant_provider_selected_label_index,
    variant_provider_selector_labels,
    variant_tweak_selected_label_index,
)
from .render_labels_details import dashboard_tweak_detail_text, tweaks_detail_text, variant_tweak_detail_text
from .render_labels_modes import current_labels
from .themes import theme_name

__all__ = [
    "active_tab",
    "active_tab_index",
    "tab_bar",
    "compact_tab_bar",
    "panel_title",
    "empty_text",
    "selected_label_index",
    "visible_items",
    "clamp_ratio",
    "ascii_progress",
    "progress_specs",
    "_patch_progress_spec",
    "_dashboard_tweak_progress_spec",
    "top_chrome_lines",
    "context_line",
    "context_hint",
    "status_line",
    "theme_line",
    "workspace_line",
    "footer_lines",
    "footer_text",
    "_dashboard_key_line",
    "_variant_key_line",
    "key_line",
    "screen_text",
    "body_text",
    "_variant_provider_selector_active",
    "_variant_tweak_selector_active",
    "_dashboard_tweak_selector_active",
    "layout_heights",
]

def active_tab(state):
    if state.mode == "patch-package":
        return "Patch"
    if state.mode == "inspect-delete-confirm":
        return "Inspect"
    if state.mode in {
        "loading",
        "busy",
        "create-preview",
        "first-run-setup",
        "setup-manager",
        "setup-detail",
        "upgrade-preview",
        "delete-confirm",
        "health-result",
        "logs",
        "help",
        "error",
        "variants",
        "models-edit",
        "tweaks-source",
        "tweaks-edit",
        "tweak-editor",
    }:
        return "Manage Setup"
    for tab, mode in zip(TABS, TAB_MODES):
        if state.mode == mode:
            return tab
    return "Manage Setup"

def active_tab_index(state):
    return TABS.index(active_tab(state))

def tab_bar(state):
    active = active_tab(state)
    parts = []
    for tab in TABS:
        if tab == active:
            parts.append(f"[{tab}]")
        else:
            parts.append(f" {tab} ")
    return "  ".join(parts)

def compact_tab_bar(state):
    active = active_tab(state)
    return " ".join(f"[{tab}]" if tab == active else tab for tab in TABS)

def panel_title(state, title):
    return f"{title} | {compact_tab_bar(state)}"

def empty_text(state):
    if state.mode in {"inspect", "extract", "patch-source"}:
        return "No centralized native downloads found."
    if state.mode == "patch-package":
        return "No patch bundles found."
    if state.mode == "dashboard" and state.dashboard_step == 1:
        return "No curated dashboard patches available."
    if state.mode in {"variants", "first-run-setup"}:
        return "No setup providers found."
    if state.mode == "tweaks-source":
        return "No setups found - create one first."
    if state.mode in {"tweaks-edit", "tweak-editor"}:
        return "No tweaks match current search/filter."
    if state.mode == "models-edit":
        return "No model fields available."
    return "Ready."

def selected_label_index(state):
    """Map state.selected_index (which walks selectable options) to the row
    index in `current_labels()`. Modes with non-selectable header rows (like
    tweaks-edit's group headers) need this offset.
    """
    if state.mode in {"tweaks-edit", "tweak-editor"} and state.tweak_apply_preview:
        return 0
    if state.mode in {"tweaks-edit", "tweak-editor"}:
        target = state.selected_index
        label_index = 1
        seen = 0
        for _, patch_ids in tweaks_edit_groups(state):
            label_index += 1  # group header
            for _ in patch_ids:
                if seen == target:
                    return label_index
                label_index += 1
                seen += 1
        return max(0, label_index - 1)
    if state.mode == "models-edit":
        return state.selected_index + 1
    if state.mode == "setup-manager":
        return state.selected_index + 2
    if state.mode == "setup-detail":
        return state.selected_index + len(setup_detail_lines(state)) + 2
    if _variant_provider_selector_active(state):
        return variant_provider_selected_label_index(state)
    if _variant_tweak_selector_active(state):
        return variant_tweak_selected_label_index(state)
    return state.selected_index

def visible_items(labels, selected_index, max_items):
    if not labels:
        return None
    max_items = max(1, max_items)
    if len(labels) <= max_items:
        return 0, labels
    half = max_items // 2
    start = max(0, selected_index - half)
    start = min(start, len(labels) - max_items)
    return start, labels[start:start + max_items]

def clamp_ratio(value):
    return max(0.0, min(float(value), 1.0))

def ascii_progress(title, ratio, label, width=24):
    ratio = clamp_ratio(ratio)
    filled = int(round(ratio * width))
    return f"{title}: [{'#' * filled}{'.' * (width - filled)}] {label}"

def progress_specs(state):
    specs = []
    if state.mode == "dashboard":
        specs.append((
            "Wizard",
            (state.dashboard_step + 1) / len(DASHBOARD_STEPS),
            f"{state.dashboard_step + 1}/{len(DASHBOARD_STEPS)} {DASHBOARD_STEPS[state.dashboard_step]}",
        ))
        if state.dashboard_step == 1:
            specs.append(_dashboard_tweak_progress_spec(state))
    elif state.mode == "patch-package":
        specs.append(_patch_progress_spec(state))
    elif state.mode in {"variants", "first-run-setup"}:
        specs.append((
            "Setup",
            (state.variant_step + 1) / len(VARIANT_STEPS),
            f"{state.variant_step + 1}/{len(VARIANT_STEPS)} {VARIANT_STEPS[state.variant_step]}",
        ))
    return specs

def _patch_progress_spec(state):
    selected = len(selected_dashboard_packages(state))
    total = len(state.patch_packages)
    ratio = selected / total if total else 0.0
    return ("Patch bundles", ratio, f"{selected}/{total} selected")

def _dashboard_tweak_progress_spec(state):
    selected = len(selected_dashboard_tweaks(state))
    available = len(dashboard_tweak_ids())
    ratio = selected / available if available else 0.0
    return ("Tweaks", ratio, f"{selected}/{available} selected")

def top_chrome_lines(state):
    return [context_line(state)]

def context_line(state):
    if state.mode == "loading":
        return "Loading | Refreshing setup state"
    if state.mode == "busy":
        return f"Working | {state.busy_title or 'Setup build'}"
    if state.mode == "setup-manager":
        return f"Home | Setups {len(state.variants)} | {setup_manager_control_summary(state)}"
    if state.mode == "setup-detail":
        return f"Home > {state.selected_setup_id or 'setup'}"
    if state.mode == "upgrade-preview":
        return f"Home > {state.selected_setup_id or 'setup'} > Upgrade"
    if state.mode == "create-preview":
        return "Create setup > Preview"
    if state.mode == "delete-confirm":
        return f"Home > {state.selected_setup_id or 'setup'} > Delete"
    if state.mode == "inspect-delete-confirm":
        return "Inspect > Delete native download"
    if state.mode == "health-result":
        return f"Home > {state.selected_setup_id or 'setup'} > Result"
    if state.mode == "help":
        return f"Help | Return {state.help_return_mode or 'setup-manager'}"
    if state.mode == "first-run-setup":
        provider = selected_variant_provider(state)
        name = state.variant_name or (provider.get("defaultVariantName") if provider else "")
        return (
            f"First run setup {VARIANT_STEPS[state.variant_step]} | "
            f"Step {state.variant_step + 1}/{len(VARIANT_STEPS)} | "
            f"Provider {provider.get('key') if provider else 'none'} | "
            f"Name {name or 'none'}"
        )
    if state.mode == "dashboard":
        step = DASHBOARD_STEPS[state.dashboard_step]
        profile = loaded_profile(state)
        profile_label = profile.name if profile else "none"
        return (
            f"Dashboard {step} | Step {state.dashboard_step + 1}/{len(DASHBOARD_STEPS)} | "
            f"Source {dashboard_source_label(state)} | "
            f"Patches {len(selected_dashboard_tweaks(state))} | Profile {profile_label}"
        )
    if state.mode == "variants":
        provider = selected_variant_provider(state)
        name = state.variant_name or (provider.get("defaultVariantName") if provider else "")
        credential = state.variant_credential_env or "none"
        return (
            f"Create setup {VARIANT_STEPS[state.variant_step]} | "
            f"Step {state.variant_step + 1}/{len(VARIANT_STEPS)} | "
            f"Provider {provider.get('key') if provider else 'none'} | "
            f"Name {name or 'none'} | Credential {credential}"
        )
    if state.mode == "patch-package":
        selected = len(selected_dashboard_packages(state))
        total = len(state.patch_packages)
        return f"Patch bundles | Bundles {selected}/{total} selected"
    if state.mode == "tweaks-source":
        return f"Tweaks | Setups {len(state.variants)}"
    if state.mode in {"tweaks-edit", "tweak-editor"}:
        pending = len(set(state.tweaks_pending) ^ set(state.tweaks_baseline))
        return (
            f"Home > {state.tweaks_variant_id or 'setup'} > Edit tweaks | "
            f"{tweak_control_summary(state)} | Pending changes {pending}"
        )
    if state.mode == "models-edit":
        diff = models_pending_diff(state)
        return (
            f"Home > {state.models_variant_id or 'setup'} > Edit models | "
            f"Pending fields {len(diff['changed'])}"
        )
    if state.mode in {"inspect", "extract", "patch-source"}:
        return f"{active_tab(state)} | Native artifacts {len(state.native_artifacts)}"
    return active_tab(state)

def context_hint(state):
    if state.mode == "busy":
        return "Input locked while this runs."
    if state.mode == "setup-manager":
        if getattr(state, "setup_search_active", False):
            return "Type to search setups. Enter or Esc keeps the current filter."
        return "Pick a setup, run it, or use a lifecycle action."
    if state.mode == "delete-confirm":
        return "Type the exact setup id, then press Enter."
    if state.mode == "inspect-delete-confirm":
        return "Confirm with y, or cancel with n/Esc."
    if state.mode == "upgrade-preview":
        return "Press y to proceed or n to cancel."
    if state.mode == "create-preview":
        return "Press y to create this setup, i toggles PATH install, or n to return to review."
    if state.mode in {"tweaks-edit", "tweak-editor"} and state.tweak_apply_preview:
        return "Review the diff, then press y to rebuild or n to cancel."
    if state.mode in {"tweaks-edit", "tweak-editor"} and getattr(state, "tweak_search_active", False):
        return "Type to search tweaks. Enter or Esc keeps the current filter."
    if state.mode == "models-edit":
        if getattr(state, "models_search_active", False):
            return "Type to search loaded models. Enter or Esc keeps the current filter."
        return "Models: select an alias target, refresh/search models, or type aliases manually."
    if state.mode == "dashboard" and state.dashboard_step == 2:
        return "Profile names: select Name, then type or Backspace."
    if state.mode in {"variants", "first-run-setup"}:
        if state.variant_step == 0:
            if getattr(state, "variant_provider_search_active", False):
                return "Type to search providers. Enter or Esc keeps the current filter."
            return "Providers: / searches, F cycles filters, Enter selects."
        if state.variant_step == 1:
            return "Setup names: select Name, then type or Backspace. Choose a Claude Code version if needed."
        if state.variant_step == 2:
            return "Credentials: edit endpoint/env, toggle local API key storage with Space."
        if state.variant_step == 3:
            return "MCP servers: provider servers are automatic. Space toggles optional servers."
        if state.variant_step == 4:
            if getattr(state, "variant_model_search_active", False):
                return "Type to search loaded models. Enter or Esc keeps the current filter."
            return "Models: select an alias target, refresh/search models, or type aliases manually."
        if state.variant_step == 5:
            return "Tweaks: Space toggles selected rows. Review details on the right."
    return "Ready"

def status_line(state):
    message = state.message.strip() if state.message else context_hint(state)
    return f"Status: {message}"

def theme_line(state):
    counts = f" | {state.counts}" if state.counts else ""
    return f"Theme: {theme_name(state.theme_id)}{counts}"

def workspace_line(_state):
    return f"Workspace: {workspace_root()}"

def footer_lines(state):
    return [status_line(state), key_line(state), theme_line(state), workspace_line(state)]

def footer_text(state):
    return " ".join(line for line in footer_lines(state) if line)

def _dashboard_key_line(state):
    if state.dashboard_step == 0:
        action = "Enter | R refresh"
    elif state.dashboard_step == 1:
        action = "Space toggle"
    elif state.dashboard_step == 3:
        action = "Enter run"
    else:
        action = "Enter"
    return f"Keys: Q quit | Up/Down | {action} | Theme T | ? more"

def _variant_key_line(state):
    if state.variant_step == 3:
        action = "Space MCP"
    elif state.variant_step == 5:
        action = "Space tweak | V view"
    elif state.variant_step == 6:
        action = "Enter"
    elif state.variant_step in {1, 2, 4}:
        action = "Type text | Enter choose | Space toggle"
    elif state.variant_step == 0:
        action = "Enter select | / search | F filter"
    else:
        action = "Enter"
    return f"Keys: Q quit | Up/Down | {action} | B/Esc | ? more"

def key_line(state):
    if state.mode == "busy":
        return "Keys: input locked while this runs"
    if state.mode == "setup-manager":
        return "Keys: Q/Ctrl+C quit | Enter manage | Up/Down | X run | ? more"
    if state.mode == "setup-detail":
        return "Keys: Q quit | Enter select | M models | Esc | Up/Down | ?"
    if state.mode == "delete-confirm":
        return "Keys: Type setup name | Enter delete | Esc cancel"
    if state.mode == "inspect-delete-confirm":
        return "Keys: Y delete | N/Esc cancel"
    if state.mode == "upgrade-preview":
        return "Keys: Y proceed | N/Esc cancel"
    if state.mode == "create-preview":
        return "Keys: Y create | I install | N/Esc cancel"
    if state.mode == "health-result":
        return "Keys: Q quit | Esc back | Enter manage | C copy logs | ? more"
    if state.mode == "logs":
        return "Keys: Q quit | C copy logs | Esc back | ? more"
    if state.mode == "models-edit":
        return "Keys: Q quit | Up/Down | Enter edit/select | Type text | A apply | D discard | Esc back"
    if state.mode == "help":
        return "Keys: Esc back | Q quit"
    if state.mode == "first-run-setup":
        return _variant_key_line(state)
    if state.mode == "dashboard":
        return _dashboard_key_line(state)
    if state.mode == "patch-package":
        return "Keys: Q quit | Space toggle | Enter apply | B/Esc | ? more"
    if state.mode == "variants":
        return _variant_key_line(state)
    if state.mode == "tweaks-source":
        return "Keys: Q quit | Enter pick setup | Up/Down | B/Esc | ? more"
    if state.mode in {"tweaks-edit", "tweak-editor"}:
        if state.tweak_apply_preview:
            return "Keys: Y proceed | N/Esc cancel"
        return "Keys: Q quit | Space toggle | A apply | D discard | V view | / search | ? more"
    if state.mode == "inspect":
        return "Keys: Q quit | Up/Down | Enter inspect | D delete | Tab tabs | ? more"
    return "Keys: Q quit | Up/Down | Enter run | Tab tabs | ? more"

def screen_text(state, height=24):
    top_height, footer_height = layout_heights(height)
    body_height = max(3, height - top_height - footer_height)

    title, labels = current_labels(state)
    if _variant_provider_selector_active(state):
        labels = variant_provider_selector_labels(state)
    lines = [panel_title(state, title), context_line(state), ""]
    cursor = selected_label_index(state)
    visible = visible_items(labels, cursor, max(1, body_height - 4))
    if visible:
        start_index, visible_labels = visible
        for offset, label in enumerate(visible_labels):
            index = start_index + offset
            prefix = "> " if index == cursor else "  "
            lines.append(prefix + label)
    else:
        lines.append("  " + empty_text(state))

    if _variant_provider_selector_active(state):
        lines.append("")
        lines.append("Provider details")
        for line in variant_provider_detail_lines(state):
            lines.append("  " + line)

    if _variant_tweak_selector_active(state):
        lines.append("")
        lines.append("Tweak details")
        for line in variant_tweak_detail_text(state).splitlines():
            lines.append("  " + line)

    if _dashboard_tweak_selector_active(state):
        lines.append("")
        lines.append("Tweak details")
        for line in dashboard_tweak_detail_text(state).splitlines():
            lines.append("  " + line)

    if state.mode in {"tweaks-edit", "tweak-editor"} and not state.tweak_apply_preview:
        added, removed = tweak_diff(state)
        lines.append("")
        lines.append("Pending changes")
        lines.append("  Add: " + (", ".join(added) if added else "none"))
        lines.append("  Remove: " + (", ".join(removed) if removed else "none"))
        lines.append("")
        lines.append("Tweak details")
        for line in tweaks_detail_text(state).splitlines():
            lines.append("  " + line)

    lines.append("")
    lines.extend(footer_lines(state))
    return "\n".join(lines)

def body_text(state, height):
    title, labels = current_labels(state)
    lines = [panel_title(state, title), context_line(state), ""]
    cursor = selected_label_index(state)
    visible = visible_items(labels, cursor, max(1, height - 5))
    if visible:
        start_index, visible_labels = visible
        for offset, label in enumerate(visible_labels):
            index = start_index + offset
            prefix = "> " if index == cursor else "  "
            lines.append(prefix + label)
    else:
        lines.append("  " + empty_text(state))
    return "\n".join(lines)

def _variant_provider_selector_active(state):
    return state.mode in {"variants", "first-run-setup"} and state.variant_step == 0

def _variant_tweak_selector_active(state):
    return state.mode in {"variants", "first-run-setup"} and state.variant_step == 5

def _dashboard_tweak_selector_active(state):
    return state.mode == "dashboard" and state.dashboard_step == 1

def layout_heights(height):
    height = max(1, height)
    if height >= 16:
        return 0, 6
    if height >= 12:
        return 0, 5
    footer_height = min(2, max(0, height - 1))
    return 0, footer_height
