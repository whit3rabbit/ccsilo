"""Explicit registry of `ccsilo.patches` Patch objects."""

from typing import Dict, List, Tuple

from . import Patch
from . import (
    agents_md,
    allow_custom_agent_models,
    anthropic_sse_error_surfacing,
    auto_accept_plan_mode,
    filter_scroll_escape_sequences,
    hide_ctrl_g,
    hide_startup_banner,
    hide_startup_clawd,
    input_border_box,
    mid_conversation_system_fallback,
    mcp_startup,
    model_customizations,
    no_prompt_steganography,
    opencode_gateway_discovery,
    opusplan1m,
    patches_applied_indication,
    prompt_overlays,
    remember_skill,
    session_memory,
    show_more_items,
    statusline_update_throttle,
    suppress_model_launch_notice,
    suppress_line_numbers,
    suppress_native_installer_warning,
    suppress_prompt_caching_warning,
    suppress_rate_limit_options,
    themes,
    thinking_visibility,
    token_count_rounding,
)

REGISTRY: Dict[str, Patch] = {
    agents_md.PATCH.id: agents_md.PATCH,
    allow_custom_agent_models.PATCH.id: allow_custom_agent_models.PATCH,
    anthropic_sse_error_surfacing.PATCH.id: anthropic_sse_error_surfacing.PATCH,
    auto_accept_plan_mode.PATCH.id: auto_accept_plan_mode.PATCH,
    filter_scroll_escape_sequences.PATCH.id: filter_scroll_escape_sequences.PATCH,
    hide_ctrl_g.PATCH.id: hide_ctrl_g.PATCH,
    hide_startup_banner.PATCH.id: hide_startup_banner.PATCH,
    hide_startup_clawd.PATCH.id: hide_startup_clawd.PATCH,
    input_border_box.PATCH.id: input_border_box.PATCH,
    mid_conversation_system_fallback.PATCH.id: mid_conversation_system_fallback.PATCH,
    mcp_startup.MCP_NON_BLOCKING_PATCH.id: mcp_startup.MCP_NON_BLOCKING_PATCH,
    mcp_startup.MCP_BATCH_SIZE_PATCH.id: mcp_startup.MCP_BATCH_SIZE_PATCH,
    model_customizations.PATCH.id: model_customizations.PATCH,
    no_prompt_steganography.PATCH.id: no_prompt_steganography.PATCH,
    opencode_gateway_discovery.PATCH.id: opencode_gateway_discovery.PATCH,
    opusplan1m.PATCH.id: opusplan1m.PATCH,
    patches_applied_indication.PATCH.id: patches_applied_indication.PATCH,
    prompt_overlays.PATCH.id: prompt_overlays.PATCH,
    remember_skill.PATCH.id: remember_skill.PATCH,
    session_memory.PATCH.id: session_memory.PATCH,
    show_more_items.PATCH.id: show_more_items.PATCH,
    statusline_update_throttle.PATCH.id: statusline_update_throttle.PATCH,
    suppress_model_launch_notice.PATCH.id: suppress_model_launch_notice.PATCH,
    suppress_line_numbers.PATCH.id: suppress_line_numbers.PATCH,
    suppress_native_installer_warning.PATCH.id: suppress_native_installer_warning.PATCH,
    suppress_prompt_caching_warning.PATCH.id: suppress_prompt_caching_warning.PATCH,
    suppress_rate_limit_options.PATCH.id: suppress_rate_limit_options.PATCH,
    themes.PATCH.id: themes.PATCH,
    thinking_visibility.PATCH.id: thinking_visibility.PATCH,
    token_count_rounding.PATCH.id: token_count_rounding.PATCH,
}


def get_patch(patch_id: str) -> Patch:
    if patch_id not in REGISTRY:
        raise KeyError(f"unknown patch: {patch_id!r}")
    return REGISTRY[patch_id]


def registered_ids() -> tuple:
    return tuple(REGISTRY.keys())


GROUP_ORDER: Tuple[str, ...] = ("ui", "thinking", "prompts", "tools", "system")


def patches_grouped() -> Dict[str, List[Patch]]:
    """Return registered patches grouped by `Patch.group`.

    Group keys appear in `GROUP_ORDER` first, then any unknown group keys
    in lexicographic order. Within each group, patches keep registry insertion
    order (the order they appear in REGISTRY).
    """
    grouped: Dict[str, List[Patch]] = {}
    for patch in REGISTRY.values():
        grouped.setdefault(patch.group, []).append(patch)
    ordered: Dict[str, List[Patch]] = {}
    for group in GROUP_ORDER:
        if group in grouped:
            ordered[group] = grouped.pop(group)
    for group in sorted(grouped):
        ordered[group] = grouped[group]
    return ordered
