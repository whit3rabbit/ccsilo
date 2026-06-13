"""Mode-specific label builders for the TUI."""

import os

from ..variant_tweaks import GATEWAY_MODEL_DISCOVERY_ENV
from ..variants import CCR_PROVIDER_KEYS
from ..variants.install import default_install_dir, inspect_variant_command_install
from ..variants.model import default_bin_dir, variant_id_from_name
from ..workspace import short_sha, workspace_root
from ._const import VARIANT_MODEL_FIELDS, VARIANT_STEPS
from .options import (
    dashboard_options,
    dashboard_title,
    format_native_artifact,
    model_picker_summary,
    models_edit_options,
    models_pending_diff,
    selected_setup_variant,
    selected_variant_provider,
    setup_default_command_alias,
    setup_detail_lines,
    setup_detail_options,
    setup_upgrade_status,
    setup_manager_control_summary,
    setup_manager_empty_label,
    setup_manager_options,
    tweak_control_summary,
    tweak_diff,
    tweaks_edit_empty_label,
    tweaks_edit_groups,
    tweaks_edit_options,
    tweaks_source_options,
    unsupported_pending_tweaks,
    variant_model_display_value,
    variant_options,
    variant_provider_selector_labels,
    variant_title,
    variant_tweak_selector_labels,
)
from .model_picker import create_uses_architect_mode, model_field_label, visible_model_ids

__all__ = [
    "current_labels",
    "create_preview_labels",
    "_create_preview_install_lines",
    "_create_preview_ccrouter_lines",
    "_create_preview_model_proxy_lines",
    "_create_preview_endpoint_lines",
    "_create_preview_credential",
    "_create_preview_api_key_storage",
    "_create_preview_mcp_lines",
    "_create_preview_model_lines",
    "command_alias_labels",
    "upgrade_preview_labels",
    "delete_confirm_labels",
    "inspect_delete_confirm_labels",
    "help_labels",
    "busy_labels",
    "tweak_preview_labels",
    "models_control_summary",
    "_tweaks_edit_labels",
    "_variant_labels",
]

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
        labels = _variant_labels(state)
        return f"{title}: {VARIANT_STEPS[state.variant_step]}", labels
    if state.mode == "create-preview":
        return "Setup create preview", create_preview_labels(state)
    if state.mode == "upgrade-preview":
        return "Upgrade preview", upgrade_preview_labels(state)
    if state.mode == "delete-confirm":
        return "Delete setup", delete_confirm_labels(state)
    if state.mode == "command-alias":
        return "Install command", command_alias_labels(state)
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
        labels = _variant_labels(state)
        return variant_title(state), labels
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

    alias = _create_preview_alias(state, setup_id)
    mcp_lines = _create_preview_mcp_lines(state, provider)
    integration_lines = _create_preview_integration_lines(state)
    model_lines = _create_preview_model_lines(state, provider)
    tweak_lines = [f"  {tweak_id}" for tweak_id in state.selected_variant_tweaks] or ["  none"]
    return [
        f"Setup name: {name or '(type a setup name)'}",
        f"Command alias: {alias or '(type a command alias)'}",
        *_create_preview_install_lines(state, setup_id, alias),
        "Create setup",
        f"Setup id: {setup_id}",
        f"Provider: {provider.get('key') or '?'}",
        f"Claude Code: {state.variant_claude_version or 'latest'}",
        f"Wrapper command: {command}",
        *_create_preview_ccrouter_lines(state, provider),
        *_create_preview_model_proxy_lines(state),
        *_create_preview_endpoint_lines(state, provider),
        f"Credential env: {_create_preview_credential(state, provider)}",
        f"API key storage: {_create_preview_api_key_storage(state)}",
        *mcp_lines,
        *integration_lines,
        *model_lines,
        "Default tweaks:",
        *tweak_lines,
        validation,
        "",
        "Cancel: press N/Esc",
    ]


def _create_preview_alias(state, setup_id):
    alias = state.variant_install_alias.strip()
    if alias or state.variant_install_alias_customized:
        return alias
    if setup_id == "(invalid)":
        return ""
    return setup_id


def _create_preview_install_lines(state, setup_id, alias):
    if not state.variant_install_command:
        return ["Install command: no (select row or press I to toggle)"]
    if setup_id == "(invalid)":
        return ["Install command: yes (unavailable until setup id is valid)"]
    if not alias:
        return ["Install command: yes (type a command alias first)"]
    install_dir = default_install_dir(allow_create=True)
    if install_dir is None:
        return ["Install command: yes (no install directory found)"]
    target = workspace_root() / "bin" / setup_id
    try:
        plan = inspect_variant_command_install(setup_id, target=target, alias=alias, yes=True)
    except Exception as exc:
        return [f"Install command: blocked ({exc})"]
    if plan.status == "blocked":
        return [f"Install command: blocked ({plan.warning})", f"Install path: {plan.path}"]
    lines = [f"Install command: yes ({plan.path}, {plan.status})"]
    if plan.warning:
        lines.append(f"Install warning: {plan.warning}")
    return lines

def _create_preview_ccrouter_lines(state, provider):
    if provider.get("key") not in CCR_PROVIDER_KEYS:
        return []
    lines = [f"CCR mode: {state.variant_ccrouter_mode}"]
    if state.variant_ccrouter_mode == "managed":
        lines.extend(
            [
                f"CCR config: {state.variant_ccrouter_config}",
                f"CCR package: {state.variant_ccrouter_package}",
                f"CCR port: {state.variant_ccrouter_port or 'auto'}",
                f"CCR auto-start: {'yes' if state.variant_ccrouter_autostart else 'no'}",
            ]
        )
    return lines

def _create_preview_model_proxy_lines(state):
    if state.variant_model_proxy != "architect":
        return ["Model proxy: off"]
    return [
        "Model proxy: OAuth architect proxy",
        f"Model proxy port: {state.variant_model_proxy_port or 'auto'}",
        "Model proxy requirement: Requires Claude Code account/login",
        "Model proxy auth: claude-* calls use Claude Code OAuth/session",
        "Model proxy routing: non-Claude aliases use the provider backend",
        f"Model proxy discovery: sets {GATEWAY_MODEL_DISCOVERY_ENV}=1",
    ]

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

def _create_preview_integration_lines(state):
    selected = list(state.selected_variant_integration_ids or [])
    lines = ["Local integrations:"]
    if selected:
        lines.extend(f"  {integration_id}" for integration_id in selected)
    else:
        lines.append("  none")
    return lines

def _create_preview_model_lines(state, provider):
    architect_mode = create_uses_architect_mode(state)
    if not provider.get("requiresModelMapping") and not architect_mode:
        return ["Models: provider defaults"]
    lines = ["Architect Mode models:" if architect_mode else "Models:"]
    for key, label in VARIANT_MODEL_FIELDS:
        label = model_field_label(key, architect_mode=architect_mode)
        value = variant_model_display_value(state, provider, key)
        source = "override" if state.variant_model_overrides.get(key, "").strip() else "default"
        lines.append(f"  {label}: {value or '(not set)'} ({source})")
    name = state.variant_name.strip() or str(provider.get("defaultVariantName") or provider.get("key") or "")
    try:
        setup_id = variant_id_from_name(name)
    except Exception:
        setup_id = "<setup-id>"
    setup_root = workspace_root() / 'variants' / setup_id
    if architect_mode:
        lines.append(f"Selected alias: {setup_root / 'config' / 'settings.json'} -> model=opusplan")
        lines.append(f"Planner/worker aliases: {setup_root / 'variant.json'} -> modelOverrides")
    else:
        lines.append(f"Manual model edit: {setup_root / 'variant.json'} -> modelOverrides")
    return lines

def upgrade_preview_labels(state):
    variant = selected_setup_variant(state)
    if variant is None:
        return ["No setup selected."]
    manifest = variant.manifest or {}
    current = (manifest.get("source") or {}).get("version") or "?"
    target = state.setup_upgrade_target or "latest"
    status = setup_upgrade_status(state, variant)
    latest = status["latest"] or "unknown"
    target_label = target
    if target == "latest" and status["latest"]:
        target_label = f"{target} ({status['latest']})"
    tweaks = manifest.get("tweaks", []) or []
    patch_refs = manifest.get("patches", []) or []
    paths = manifest.get("paths") or {}
    return [
        f"Setup: {variant.variant_id}",
        f"Current Claude Code: {current}",
        f"Latest available: {latest}",
        f"Update available: {_upgrade_available_label(status)}",
        f"Target Claude Code: {target_label}",
        f"Tweak count: {len(tweaks)}",
        f"Patch package refs: {len(patch_refs)}",
        f"Command path: {paths.get('wrapper') or '(no command)'}",
        "Rebuild: yes",
        "Reapply patches/tweaks: yes",
        "",
        "Proceed? y/N",
    ]

def _upgrade_available_label(status):
    state_name = status["state"]
    if state_name == "available":
        return "yes"
    if state_name == "current":
        return "no"
    if state_name == "ahead":
        return "no (current is newer than latest)"
    return "unknown"

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

def command_alias_labels(state):
    variant = selected_setup_variant(state)
    if variant is None:
        return ["No setup selected."]
    paths = (variant.manifest or {}).get("paths") or {}
    target = paths.get("wrapper") or ""
    alias = state.setup_command_alias.strip() or setup_default_command_alias(variant)
    lines = [
        f"Setup: {variant.variant_id}",
        f"Command alias: {alias or '(type a command alias)'}",
        f"Target wrapper: {target or '(no command)'}",
    ]
    if not target:
        lines.append("Status: blocked, setup wrapper is missing")
        return lines
    if not alias:
        lines.append("Status: blocked, command alias is empty")
        return lines
    try:
        plan = inspect_variant_command_install(variant.variant_id, target=target, alias=alias, yes=True)
    except Exception as exc:
        lines.append(f"Status: blocked, {exc}")
        return lines
    lines.extend([
        f"Install path: {plan.path}",
        f"Status: {plan.status}",
    ])
    if plan.warning:
        lines.append(f"Warning: {plan.warning}")
    lines.extend(["", "Enter applies. Esc cancels."])
    return lines

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
        "/: search loaded models when a model-list row is selected",
        "I: toggle command install on preview",
        "V: view tweak details",
        "",
        "Tweaks editor",
        "/: search tweaks",
        "Space: toggle selected tweak",
        "A: apply pending changes",
        "D: discard pending changes",
        "V: view tweak details",
        "",
        "Models editor",
        "/: search loaded models when a model-list row is selected",
        "A: apply pending model changes",
        "D: discard pending model changes",
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
    visible, match_count = visible_model_ids(
        state.models_choices or [],
        getattr(state, "models_search_text", ""),
    )
    summary = model_picker_summary(
        len(state.models_choices or []),
        match_count,
        len(visible),
        getattr(state, "models_search_text", ""),
        getattr(state, "models_search_active", False),
        getattr(state, "models_target", ""),
    )
    return f"{summary} | Changed aliases: {changed}"

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

def _variant_labels(state):
    if state.variant_step == 0:
        return variant_provider_selector_labels(state)
    if state.variant_step == 5:
        return variant_tweak_selector_labels(state)
    return [option.label for option in variant_options(state)]
