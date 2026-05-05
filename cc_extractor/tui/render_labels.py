"""Text labels, context, footer, and headless rendering helpers."""

import os

from ..variants.model import default_bin_dir, variant_id_from_name
from ..variants.install import default_install_dir
from ..workspace import short_sha, workspace_root
from ._const import DASHBOARD_STEPS, TABS, TAB_MODES, VARIANT_MODEL_FIELDS, VARIANT_STEPS
from .options import (
    dashboard_options,
    dashboard_source_label,
    dashboard_title,
    dashboard_tweak_ids,
    format_native_artifact,
    loaded_profile,
    models_edit_options,
    models_pending_diff,
    selected_dashboard_packages,
    selected_dashboard_tweaks,
    selected_setup_variant,
    selected_variant_provider,
    selected_tweaks_edit_patch,
    variant_model_display_value,
    setup_detail_lines,
    setup_detail_options,
    setup_manager_control_summary,
    setup_manager_empty_label,
    setup_manager_options,
    tweak_control_summary,
    tweak_diff,
    tweak_status,
    tweaks_edit_empty_label,
    tweaks_edit_groups,
    tweaks_edit_options,
    tweaks_source_options,
    unsupported_pending_tweaks,
    variant_provider_detail_lines,
    variant_provider_selector_labels,
    variant_options,
    variant_title,
)
from .themes import theme_name

__all__ = ['active_tab', 'active_tab_index', 'tab_bar', 'compact_tab_bar', 'panel_title', 'current_labels', 'create_preview_labels', '_create_preview_endpoint_lines', '_create_preview_credential', '_create_preview_api_key_storage', '_create_preview_mcp_lines', '_create_preview_model_lines', 'upgrade_preview_labels', 'delete_confirm_labels', 'inspect_delete_confirm_labels', 'help_labels', 'busy_labels', 'tweak_preview_labels', 'models_control_summary', '_tweaks_edit_labels', 'tweaks_detail_text', 'empty_text', 'selected_label_index', 'visible_items', 'clamp_ratio', 'ascii_progress', 'progress_specs', '_patch_progress_spec', '_dashboard_tweak_progress_spec', 'top_chrome_lines', 'context_line', 'context_hint', 'status_line', 'theme_line', 'workspace_line', 'footer_lines', 'footer_text', '_dashboard_key_line', '_variant_key_line', 'key_line', 'screen_text', 'body_text', '_variant_provider_selector_active', 'layout_heights']

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

def current_labels(state):
    if state.mode == "loading":
        return "Loading setups", ["Refreshing workspace state..."]
    if state.mode == "busy":
        return state.busy_title or "Working", busy_labels(state)
    if state.mode == "setup-manager":
        labels = [
            setup_manager_control_summary(state),
            "Name                 Provider     Claude Code  Health   Command",
        ]
        labels.extend(option.label for option in setup_manager_options(state))
        empty_label = setup_manager_empty_label(state)
        if empty_label:
            labels.append(empty_label)
        return "Setup manager", labels
    if state.mode == "setup-detail":
        labels = setup_detail_lines(state) + ["", "Actions"]
        labels.extend(option.label for option in setup_detail_options(state))
        return f"Manage setup: {state.selected_setup_id or 'none'}", labels
    if state.mode == "first-run-setup":
        title = "No Claude Code setups found"
        return f"{title}: {VARIANT_STEPS[state.variant_step]}", [option.label for option in variant_options(state)]
    if state.mode == "create-preview":
        return "Setup create preview", create_preview_labels(state)
    if state.mode == "upgrade-preview":
        return "Upgrade preview", upgrade_preview_labels(state)
    if state.mode == "delete-confirm":
        return "Delete setup", delete_confirm_labels(state)
    if state.mode == "inspect-delete-confirm":
        return "Delete native download", inspect_delete_confirm_labels(state)
    if state.mode == "health-result":
        return "Setup result", state.last_action_summary or ["No result available."]
    if state.mode == "logs":
        return "Logs", state.last_action_log or ["No logs available."]
    if state.mode == "help":
        return "Shortcuts", help_labels()
    if state.mode == "error":
        return "Error", state.last_action_summary or [state.message or "Unknown error."]
    if state.mode == "dashboard":
        return dashboard_title(state), [option.label for option in dashboard_options(state)]
    if state.mode == "inspect":
        return "Inspect", [format_native_artifact(artifact) for artifact in state.native_artifacts]
    if state.mode == "extract":
        return "Extract", [format_native_artifact(artifact) for artifact in state.native_artifacts]
    if state.mode == "patch-source":
        return "Patch source", [format_native_artifact(artifact) for artifact in state.native_artifacts]
    if state.mode == "patch-package":
        labels = []
        for index, package in enumerate(state.patch_packages):
            marker = "[x]" if index in state.selected_patch_indexes else "[ ]"
            labels.append(f"{marker} {package.patch_id}@{package.version}  {package.name}")
        return "Patch bundles", labels
    if state.mode == "variants":
        return variant_title(state), [option.label for option in variant_options(state)]
    if state.mode == "tweaks-source":
        return "Tweaks: pick setup", [option.label for option in tweaks_source_options(state)]
    if state.mode in {"tweaks-edit", "tweak-editor"}:
        if state.tweak_apply_preview:
            return "Tweak rebuild preview", tweak_preview_labels(state)
        labels = [tweak_control_summary(state)]
        labels.extend(_tweaks_edit_labels(state))
        empty_label = tweaks_edit_empty_label(state)
        if empty_label:
            labels.append(empty_label)
        title = f"Edit tweaks: {state.tweaks_variant_id or 'no setup'}"
        return title, labels
    if state.mode == "models-edit":
        labels = [models_control_summary(state)]
        labels.extend(option.label for option in models_edit_options(state))
        return f"Edit models: {state.models_variant_id or 'no setup'}", labels
    return "Status", []

def create_preview_labels(state):
    provider = selected_variant_provider(state)
    if provider is None:
        return ["No provider selected."]
    name = state.variant_name.strip() or str(provider.get("defaultVariantName") or provider.get("key") or "")
    try:
        setup_id = variant_id_from_name(name)
        command = default_bin_dir() / setup_id
    except Exception as exc:
        setup_id = "(invalid)"
        command = "(unavailable)"
        validation = f"Validation: {exc}"
    else:
        validation = "Validation: ready"

    mcp_lines = _create_preview_mcp_lines(state, provider)
    model_lines = _create_preview_model_lines(state, provider)
    tweak_lines = [f"  {tweak_id}" for tweak_id in state.selected_variant_tweaks] or ["  none"]
    return [
        f"Setup: {name or '(unnamed)'}",
        f"Setup id: {setup_id}",
        f"Provider: {provider.get('key') or '?'}",
        f"Claude Code: {state.variant_claude_version or 'latest'}",
        f"Command: {command}",
        *_create_preview_install_lines(state, setup_id),
        *_create_preview_endpoint_lines(state, provider),
        f"Credential env: {_create_preview_credential(state, provider)}",
        f"API key storage: {_create_preview_api_key_storage(state)}",
        *mcp_lines,
        *model_lines,
        "Default tweaks:",
        *tweak_lines,
        validation,
        "",
        "Proceed? y/N",
    ]

def _create_preview_install_lines(state, setup_id):
    if not state.variant_install_command:
        return ["Install command: no (press I to toggle)"]
    if setup_id == "(invalid)":
        return ["Install command: yes (unavailable until setup id is valid)"]
    install_dir = default_install_dir(allow_create=True)
    if install_dir is None:
        return ["Install command: yes (no install directory found)"]
    return [f"Install command: yes ({install_dir / setup_id})"]

def _create_preview_endpoint_lines(state, provider):
    if provider.get("authMode") == "none":
        return []
    return [f"Endpoint: {state.variant_base_url.strip() or provider.get('baseUrl') or '(not set)'}"]

def _create_preview_credential(state, provider):
    if provider.get("authMode") == "none":
        return "not required"
    if state.variant_store_secret:
        return "not used, storing setup-local secret"
    value = state.variant_credential_env.strip()
    if not value:
        return "not set"
    suffix = "set" if value in os.environ else "missing"
    if provider.get("credentialOptional"):
        suffix = f"optional, {suffix}"
    return f"{value} ({suffix})"

def _create_preview_api_key_storage(state):
    if not state.variant_store_secret:
        return "off"
    return "on, key set" if state.variant_api_key.strip() else "on, key missing"

def _create_preview_mcp_lines(state, provider):
    provider_mcp = list(provider.get("mcpServers") or [])
    selected = list(state.selected_variant_mcp_ids)
    lines = ["MCP servers:"]
    if provider_mcp:
        lines.extend(f"  {name} (auto-enabled for this provider)" for name in provider_mcp)
    if selected:
        lines.extend(f"  {mcp_id} (optional)" for mcp_id in selected)
    if not provider_mcp and not selected:
        lines.append("  none")
    return lines

def _create_preview_model_lines(state, provider):
    if not provider.get("requiresModelMapping"):
        return ["Models: provider defaults"]
    lines = ["Models:"]
    for key, label in VARIANT_MODEL_FIELDS:
        value = variant_model_display_value(state, provider, key)
        source = "override" if state.variant_model_overrides.get(key, "").strip() else "default"
        lines.append(f"  {label}: {value or '(not set)'} ({source})")
    return lines

def upgrade_preview_labels(state):
    variant = selected_setup_variant(state)
    if variant is None:
        return ["No setup selected."]
    manifest = variant.manifest or {}
    current = (manifest.get("source") or {}).get("version") or "?"
    target = state.setup_upgrade_target or "latest"
    tweaks = manifest.get("tweaks", []) or []
    paths = manifest.get("paths") or {}
    return [
        f"Setup: {variant.variant_id}",
        f"Current Claude Code: {current}",
        f"Target Claude Code: {target}",
        f"Tweak count: {len(tweaks)}",
        f"Command path: {paths.get('wrapper') or '(no command)'}",
        "Rebuild: yes",
        "",
        "Proceed? y/N",
    ]

def delete_confirm_labels(state):
    variant = selected_setup_variant(state)
    if variant is None:
        return ["No setup selected."]
    paths = (variant.manifest or {}).get("paths") or {}
    return [
        f"Type setup id to delete: {variant.variant_id}",
        f"Typed: {state.delete_confirm_text or '(empty)'}",
        "",
        "Will remove:",
        f"Setup directory: {variant.path}",
        f"Command: {paths.get('wrapper') or '(no command)'}",
        "",
        "Shared downloads and caches are not removed.",
    ]

def inspect_delete_confirm_labels(state):
    artifact = next(
        (item for item in state.native_artifacts if str(item.path) == state.inspect_delete_confirm_path),
        None,
    )
    if artifact is None:
        return [
            "Selected native artifact is no longer available.",
            "",
            "Press n or Esc to return to Inspect.",
        ]
    return [
        "Delete this downloaded native artifact?",
        f"Version: {artifact.version}",
        f"Platform: {artifact.platform}",
        f"SHA: {short_sha(artifact.sha256)}",
        f"Path: {artifact.path}",
        "",
        "Proceed? y/N",
    ]

def help_labels():
    return [
        "Global",
        "Up/Down: move",
        "Enter: select or confirm current screen",
        "Esc/B: back",
        "Q or Ctrl+C: quit",
        "?: shortcuts",
        "T: cycle theme outside setup manager/detail",
        "",
        "Setup manager",
        "/: search setups",
        "P: cycle provider filter",
        "S: cycle sort",
        "N: new setup",
        "X: run selected setup",
        "U: upgrade selected setup",
        "T: edit tweaks for selected setup",
        "H: run health check",
        "D: delete selected setup",
        "R: refresh setups",
        "",
        "Setup detail and results",
        "C: copy command path",
        "G: copy setup config path",
        "L: view logs",
        "",
        "Logs",
        "C: copy log text",
        "",
        "Inspect",
        "Enter: inspect selected native download",
        "D: delete selected native download",
        "",
        "Dashboard",
        "R: refresh source list",
        "Space: toggle tweak or package selections",
        "A: apply tweak profile changes when shown",
        "D: delete or discard profile changes when shown",
        "V: view selection details when shown",
        "",
        "Setup creation",
        "Space: toggle MCP servers or tweaks",
        "I: toggle command install on preview",
        "V: view tweak details",
        "",
        "Tweaks editor",
        "/: search tweaks",
        "Space: toggle selected tweak",
        "A: apply pending changes",
        "D: discard pending changes",
        "V: view tweak details",
    ]

def busy_labels(state):
    tick = int(getattr(state, "busy_ticks", 0) or 0)
    spinner = "|/-\\"[tick % 4]
    width = 18
    window = 5
    start = tick % (width - window + 1)
    bar = "." * start + "#" * window + "." * (width - start - window)
    detail = state.busy_detail or "Running setup build"
    return [
        f"{spinner} {detail}",
        f"Progress: [{bar}] working",
        "Input locked while this runs.",
        "Backend stages will appear when complete.",
    ]

def tweak_preview_labels(state):
    variant = selected_setup_variant(state)
    added, removed = tweak_diff(state)
    unsupported = unsupported_pending_tweaks(state)
    command = ""
    if variant is not None:
        command = ((variant.manifest or {}).get("paths") or {}).get("wrapper") or ""
    labels = [
        f"Setup: {state.tweaks_variant_id or state.selected_setup_id or '(none)'}",
        "",
        "Add:",
        *(f"  {item}" for item in (added or ["none"])),
        "",
        "Remove:",
        *(f"  {item}" for item in (removed or ["none"])),
        "",
        f"Will rebuild command: {command or '(no command)'}",
    ]
    if unsupported:
        labels.extend(["", f"Blocked unsupported tweaks: {', '.join(unsupported)}"])
    labels.extend(["", "Proceed? y/N"])
    return labels

def models_control_summary(state):
    diff = models_pending_diff(state)
    changed = ", ".join(diff["changed"]) if diff["changed"] else "none"
    return f"Loaded models: {len(state.models_choices or [])} | Changed aliases: {changed}"

def _tweaks_edit_labels(state):
    """Build the left-pane label list for tweaks-edit mode.

    Walks `tweaks_edit_options(state)` (one entry per togglable patch) and
    inserts a non-selectable group header (rendered with leading "-- ") above
    the first patch in each group. Group headers are visual-only and do not
    affect `selected_index`.
    """
    options = tweaks_edit_options(state)
    by_id = {opt.value: opt.label for opt in options}
    labels = []
    for group, patch_ids in tweaks_edit_groups(state):
        labels.append(f"-- {group} --")
        for patch_id in patch_ids:
            label = by_id.get(patch_id)
            if label is not None:
                labels.append(label)
    return labels

def tweaks_detail_text(state) -> str:
    """Right-pane content describing the currently selected patch."""
    patch = selected_tweaks_edit_patch(state)
    if patch is None:
        return "No patch selected."
    applied = "yes" if patch.id in (state.tweaks_baseline or ()) else "no"
    pending = "yes" if patch.id in (state.tweaks_pending or ()) else "no"
    blacklist = ", ".join(patch.versions_blacklisted) if patch.versions_blacklisted else "(none)"
    tested = ", ".join(patch.versions_tested) if patch.versions_tested else "(none)"
    description = patch.description or "(no description)"
    return "\n".join([
        patch.name,
        f"Group: {patch.group}",
        f"Status: {tweak_status(state, patch.id)['label']}",
        f"Reason: {tweak_status(state, patch.id)['reason']}",
        "",
        description,
        "",
        f"Versions supported: {patch.versions_supported}",
        f"Tested ranges: {tested}",
        f"Blacklisted: {blacklist}",
        f"On miss: {patch.on_miss}",
        "",
        f"Enabled in setup {state.tweaks_variant_id or '(no setup)'}: {applied}",
        f"Pending after apply: {pending}",
    ])

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
        return "Models: refresh local list, select one, edit aliases manually, then apply."
    if state.mode == "dashboard" and state.dashboard_step == 2:
        return "Profile names: select Name, then type or Backspace."
    if state.mode in {"variants", "first-run-setup"}:
        if state.variant_step == 1:
            return "Setup names: select Name, then type or Backspace. Choose a Claude Code version if needed."
        if state.variant_step == 2:
            return "Credentials: edit endpoint/env, toggle local API key storage with Space."
        if state.variant_step == 3:
            return "MCP servers: provider servers are automatic. Space toggles optional servers."
        if state.variant_step == 4:
            return "Models: refresh local model list, select one, or edit aliases manually."
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
        return "Keys: Q quit | Space toggle | A apply | D discard | / search | ? more"
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

def layout_heights(height):
    height = max(1, height)
    if height >= 16:
        return 0, 6
    if height >= 12:
        return 0, 5
    footer_height = min(2, max(0, height - 1))
    return 0, footer_height
