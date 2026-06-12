"""Tweak and selector detail text for the TUI."""

from ..variant_tweaks import (
    GATEWAY_MODEL_DISCOVERY_ENV,
    GATEWAY_MODEL_DISCOVERY_TWEAK_ID,
    default_tweak_ids_for_provider,
)
from ..variants.model import variant_id_from_name
from ..workspace import workspace_root
from ._const import ARCHITECT_MODE_TWEAK_ID
from .options import (
    dashboard_source_label,
    selected_dashboard_option,
    selected_tweaks_edit_patch,
    selected_variant_option,
    selected_variant_provider,
    tweak_meta,
    tweak_status,
    tweak_status_for_version,
    variant_setup_tweak_ids,
)

__all__ = [
    "tweaks_detail_text",
    "variant_tweak_detail_text",
    "dashboard_tweak_detail_text",
    "_format_tweak_detail_text",
    "_variant_model_proxy_detail_text",
    "_variant_tweak_summary_text",
]

def tweaks_detail_text(state) -> str:
    """Right-pane content describing the currently selected patch."""
    patch = selected_tweaks_edit_patch(state)
    if patch is None:
        return "No patch selected."
    status = tweak_status(state, patch.id)
    applied = "yes" if patch.id in (state.tweaks_baseline or ()) else "no"
    pending = "yes" if patch.id in (state.tweaks_pending or ()) else "no"
    return _format_tweak_detail_text(
        patch,
        status,
        [
            f"Enabled in setup {state.tweaks_variant_id or '(no setup)'}: {applied}",
            f"Pending after apply: {pending}",
        ],
    )

def variant_tweak_detail_text(state) -> str:
    option = selected_variant_option(state)
    if option is None:
        return "No tweak selected."
    if option.kind in {"variant-model-proxy", "variant-model-proxy-port"}:
        return _variant_model_proxy_detail_text(state)
    if option.kind == "variant-architect-mode":
        tweak_id = ARCHITECT_MODE_TWEAK_ID
    elif option.kind == "variant-tweak":
        tweak_id = str(option.value)
    else:
        return _variant_tweak_summary_text(state)
    patch = tweak_meta(tweak_id)
    if patch is None:
        return "No tweak metadata available."
    provider = selected_variant_provider(state)
    recommended = default_tweak_ids_for_provider(provider.get("key") if provider else None)
    status = tweak_status_for_version(
        tweak_id,
        state.variant_claude_version,
        recommended_ids=recommended,
    )
    enabled = "yes" if tweak_id in (state.selected_variant_tweaks or []) else "no"
    trailing = [
        f"Selected for new setup: {enabled}",
        f"Claude Code version: {state.variant_claude_version or 'latest'}",
    ]
    if tweak_id == ARCHITECT_MODE_TWEAK_ID:
        trailing.extend(_architect_mode_edit_lines(state))
    return _format_tweak_detail_text(
        patch,
        status,
        trailing,
    )

def dashboard_tweak_detail_text(state) -> str:
    option = selected_dashboard_option(state)
    if option is None or option.kind != "dashboard-tweak-toggle":
        return "Select a dashboard tweak to see details."
    tweak_id = str(option.value)
    patch = tweak_meta(tweak_id)
    if patch is None:
        return "No tweak metadata available."
    selected = "yes" if tweak_id in (state.selected_dashboard_tweak_ids or []) else "no"
    return _format_tweak_detail_text(
        patch,
        {"label": "dashboard", "reason": "Available for native dashboard builds."},
        [
            f"Selected for build: {selected}",
            f"Dashboard source: {dashboard_source_label(state)}",
        ],
    )

def _format_tweak_detail_text(patch, status, trailing_lines):
    blacklist = ", ".join(patch.versions_blacklisted) if patch.versions_blacklisted else "(none)"
    tested = ", ".join(patch.versions_tested) if patch.versions_tested else "(none)"
    description = patch.description or "(no description)"
    return "\n".join([
        patch.name,
        f"Group: {patch.group}",
        f"Status: {status['label']}",
        f"Reason: {status['reason']}",
        "",
        description,
        "",
        f"Versions supported: {patch.versions_supported}",
        f"Tested ranges: {tested}",
        f"Blacklisted: {blacklist}",
        f"On miss: {patch.on_miss}",
        "",
        *trailing_lines,
    ])

def _variant_model_proxy_detail_text(state) -> str:
    enabled = "yes" if state.variant_model_proxy == "architect" else "no"
    architect_mode = "yes" if ARCHITECT_MODE_TWEAK_ID in (state.selected_variant_tweaks or []) else "no"
    gateway_discovery = "yes" if GATEWAY_MODEL_DISCOVERY_TWEAK_ID in (state.selected_variant_tweaks or []) else "no"
    return "\n".join([
        "OAuth architect proxy",
        "Group: setup",
        f"Status: {'ready' if enabled == 'yes' else 'disabled'}",
        "Reason: Requires Claude Code account/login and routes planner and worker model calls through different auth paths.",
        "",
        "Requires Claude Code account/login. Starts a setup-local proxy. claude-* calls use Claude Code OAuth/session auth. Non-Claude model aliases are sent to the selected provider backend.",
        "",
        "Versions supported: setup-wrapper",
        "Tested ranges: setup-wrapper",
        "Blacklisted: (none)",
        "On miss: skip",
        "",
        f"Selected for new setup: {enabled}",
        f"Port: {state.variant_model_proxy_port or 'auto'}",
        f"Architect Mode tweak selected: {architect_mode}",
        f"Gateway model discovery tweak selected: {gateway_discovery}",
        f"Required env: {GATEWAY_MODEL_DISCOVERY_ENV}=1",
        "Dependency: unchecking Gateway model discovery disables this proxy.",
    ])

def _architect_mode_edit_lines(state):
    setup_name = state.variant_name.strip() or "<setup-name>"
    try:
        setup_id = variant_id_from_name(setup_name)
    except Exception:
        setup_id = "<setup-id>"
    setup_root = workspace_root() / "variants" / setup_id
    return [
        "",
        "Auth note: normal Claude Code login/session can still be used. This alias does not start the setup-local OAuth architect proxy.",
        f"Selected alias file: {setup_root / 'config' / 'settings.json'} -> model=opusplan",
        f"Planner/worker aliases: {setup_root / 'variant.json'} -> modelOverrides",
        f"Generated wrapper: {workspace_root() / 'bin' / setup_id} exports model override env vars",
    ]

def _variant_tweak_summary_text(state) -> str:
    selected = len(state.selected_variant_tweaks or [])
    available = len(variant_setup_tweak_ids(state))
    return "\n".join([
        "Tweak selection",
        "Group: setup",
        "Status: ready",
        "Reason: Review each tweak before creating the setup.",
        "",
        f"Selected tweaks: {selected}",
        f"Visible tweaks: {available}",
        f"View: {state.tweak_filter or 'recommended'}",
    ])
