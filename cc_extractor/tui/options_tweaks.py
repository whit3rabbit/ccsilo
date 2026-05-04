"""Curated tweak option, status, and selection helpers."""

from types import SimpleNamespace

from ..patches._registry import REGISTRY as PATCH_REGISTRY, patches_grouped
from ..patches._versions import SemverRangeError, version_in_range
from ..variant_tweaks import (
    BOOLEAN_ENV_TWEAKS,
    CURATED_TWEAK_IDS,
    DEFAULT_TWEAK_IDS,
    ENV_TWEAK_IDS,
    PROMPT_ONLY_TWEAK_IDS,
    SETUP_ONLY_TWEAK_IDS,
)
from ._const import MenuOption
from .options_setup import selected_setup_variant

ENV_TWEAK_META = {
    "context-limit": (
        "Context limit",
        "environment",
        "Sets CLAUDE_CODE_CONTEXT_LIMIT and disables automatic compaction.",
    ),
    "file-read-limit": (
        "File read limit",
        "environment",
        "Sets CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS.",
    ),
    "subagent-model": (
        "Subagent model",
        "environment",
        "Sets CLAUDE_CODE_SUBAGENT_MODEL.",
    ),
}
for _tweak_id, _meta in BOOLEAN_ENV_TWEAKS.items():
    ENV_TWEAK_META[_tweak_id] = (
        str(_meta["name"]),
        "environment",
        f"Sets {_meta['env']}={_meta['value']}. {str(_meta['description'])}",
    )

PROMPT_ONLY_TWEAK_META = {
    "rtk-shell-prefix": (
        "RTK shell prefix",
        "prompts",
        "Adds setup prompt guidance to prefix shell commands with rtk when available.",
    ),
}

SETUP_ONLY_TWEAK_META = {
    "dangerously-skip-permissions": (
        "Dangerous skip permissions",
        "system",
        "Always launches this setup with --dangerously-skip-permissions.",
    ),
}

def _tweak_display_name(tweak_id):
    patch = PATCH_REGISTRY.get(tweak_id)
    if patch is not None:
        return patch.name
    if tweak_id in ENV_TWEAK_META:
        return ENV_TWEAK_META[tweak_id][0]
    if tweak_id in PROMPT_ONLY_TWEAK_META:
        return PROMPT_ONLY_TWEAK_META[tweak_id][0]
    if tweak_id in SETUP_ONLY_TWEAK_META:
        return SETUP_ONLY_TWEAK_META[tweak_id][0]
    return tweak_id.replace("-", " ").title()

def tweaks_source_options(state):
    options = []
    if not state.variants:
        options.append(MenuOption("section", "No setups found - create one first"))
        return options
    for variant in state.variants:
        manifest = variant.manifest or {}
        tweak_count = len(manifest.get("tweaks", []) or [])
        provider = (manifest.get("provider") or {}).get("key") or "?"
        version = (manifest.get("source") or {}).get("version") or "?"
        label = f"{variant.variant_id}  ({provider}, claude {version}, {tweak_count} tweaks)"
        options.append(MenuOption("tweaks-pick-variant", label, variant.variant_id))
    return options

def tweaks_edit_options(state):
    """Curated tweaks grouped by category. Each item is a togglable row.

    `selected_index` walks only the togglable rows; group headers are returned
    via `tweaks_edit_groups()` for rendering, not as MenuOption entries.
    """
    options = []
    for group, tweaks in _filtered_patches_grouped(state):
        for tweak in tweaks:
            marker = "[x]" if tweak.id in state.tweaks_pending else "[ ]"
            status = tweak_status(state, tweak.id)
            label = f"{marker} {tweak.name}  ({tweak.id})  {status['label']}"
            options.append(MenuOption("tweak-toggle", label, tweak.id))
    return options

def tweaks_edit_groups(state):
    """Return a list of (group_label, [patch_id, ...]) preserving display order.

    The renderer walks options in order and inserts a group header before the
    first patch belonging to each new group.
    """
    return [(group, [patch.id for patch in patches]) for group, patches in _filtered_patches_grouped(state)]

def selected_tweaks_edit_option(state):
    options = tweaks_edit_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]

def selected_tweaks_edit_patch(state):
    """Return the Patch-like object currently selected in tweaks-edit mode, or None."""
    option = selected_tweaks_edit_option(state)
    if option is None:
        return None
    return _tweak_meta(str(option.value))

def tweak_control_summary(state):
    search = getattr(state, "tweak_search", "") or ""
    search_label = search if search else "none"
    if getattr(state, "tweak_search_active", False):
        search_label = f"{search_label} (typing)"
    return f"View: {getattr(state, 'tweak_filter', 'recommended') or 'recommended'} | Search: {search_label}"

def tweaks_edit_empty_label(state):
    if len(tweaks_edit_options(state)) == 0:
        return "No tweaks match current search/filter."
    return ""

def selected_setup_version(state):
    variant = selected_setup_variant(state)
    if variant is None:
        return None
    return ((variant.manifest or {}).get("source") or {}).get("version")

def tweak_status(state, tweak_id):
    if tweak_id in ENV_TWEAK_IDS:
        return {"label": "env-backed", "selectable": True, "reason": "Sets environment only."}
    if tweak_id in PROMPT_ONLY_TWEAK_IDS:
        label = "ready" if tweak_id in DEFAULT_TWEAK_IDS else "advanced"
        return {"label": label, "selectable": True, "reason": "Adds prompt overlay instructions."}
    patch = PATCH_REGISTRY.get(tweak_id)
    if patch is None:
        if tweak_id in SETUP_ONLY_TWEAK_IDS:
            label = "ready" if tweak_id in DEFAULT_TWEAK_IDS else "advanced"
            return {"label": label, "selectable": True, "reason": "Changes setup wrapper behavior."}
        return {"label": "unknown", "selectable": False, "reason": "Tweak is not registered."}
    version = selected_setup_version(state)
    if not version or version == "latest":
        if patch.id in DEFAULT_TWEAK_IDS:
            return {"label": "ready", "selectable": True, "reason": "Version is not pinned yet."}
        return {"label": "advanced", "selectable": True, "reason": "Version is not pinned yet."}
    if version in patch.versions_blacklisted:
        return {
            "label": "blocked: blacklisted version",
            "selectable": False,
            "reason": f"Claude Code {version} is blacklisted for this tweak.",
        }
    try:
        supported = version_in_range(version, patch.versions_supported)
    except SemverRangeError as exc:
        return {"label": "unsupported", "selectable": False, "reason": str(exc)}
    if not supported:
        return {
            "label": f"unsupported for Claude Code {version}",
            "selectable": False,
            "reason": f"Supported range: {patch.versions_supported}",
        }
    if patch.id in DEFAULT_TWEAK_IDS:
        return {"label": "ready", "selectable": True, "reason": "Recommended setup tweak."}
    return {"label": "advanced", "selectable": True, "reason": "Advanced tweak. Review before enabling."}

def tweak_diff(state):
    pending = set(state.tweaks_pending or [])
    baseline = set(state.tweaks_baseline or ())
    return sorted(pending - baseline), sorted(baseline - pending)

def unsupported_pending_tweaks(state):
    return [
        tweak_id for tweak_id in sorted(set(state.tweaks_pending or []))
        if not tweak_status(state, tweak_id)["selectable"]
    ]

def _filtered_patches_grouped(state):
    grouped = []
    recommended = set(DEFAULT_TWEAK_IDS) | set(state.tweaks_baseline or ()) | set(state.tweaks_pending or [])
    curated = set(CURATED_TWEAK_IDS)
    for group, patches in patches_grouped().items():
        filtered = []
        for patch in patches:
            if patch.id not in curated:
                continue
            if not _tweak_passes_filter(state, patch.id, recommended):
                continue
            filtered.append(patch)
        if filtered:
            grouped.append((group, filtered))
    env_filtered = [
        _tweak_meta(tweak_id)
        for tweak_id in ENV_TWEAK_IDS
        if tweak_id in curated and _tweak_passes_filter(state, tweak_id, recommended)
    ]
    prompt_only_filtered = [
        _tweak_meta(tweak_id)
        for tweak_id in PROMPT_ONLY_TWEAK_IDS
        if tweak_id in curated and _tweak_passes_filter(state, tweak_id, recommended)
    ]
    setup_only_filtered = [
        _tweak_meta(tweak_id)
        for tweak_id in SETUP_ONLY_TWEAK_IDS
        if tweak_id in curated and tweak_id not in PATCH_REGISTRY and _tweak_passes_filter(state, tweak_id, recommended)
    ]
    if prompt_only_filtered:
        for index, (group, patches) in enumerate(grouped):
            if group == "prompts":
                grouped[index] = (group, [*patches, *prompt_only_filtered])
                break
        else:
            grouped.append(("prompts", prompt_only_filtered))
    if env_filtered:
        grouped.append(("environment", env_filtered))
    if setup_only_filtered:
        grouped.append(("setup", setup_only_filtered))
    return grouped

def _tweak_meta(tweak_id):
    patch = PATCH_REGISTRY.get(tweak_id)
    if patch is not None:
        return patch
    if tweak_id in PROMPT_ONLY_TWEAK_META:
        name, group, description = PROMPT_ONLY_TWEAK_META[tweak_id]
        return SimpleNamespace(
            id=tweak_id,
            name=name,
            group=group,
            versions_supported="prompt-only",
            versions_tested=("prompt-only",),
            versions_blacklisted=(),
            on_miss="skip",
            description=description,
        )
    if tweak_id in SETUP_ONLY_TWEAK_META:
        name, group, description = SETUP_ONLY_TWEAK_META[tweak_id]
        return SimpleNamespace(
            id=tweak_id,
            name=name,
            group=group,
            versions_supported="setup-wrapper",
            versions_tested=("setup-wrapper",),
            versions_blacklisted=(),
            on_miss="skip",
            description=description,
        )
    if tweak_id not in ENV_TWEAK_META:
        return None
    name, group, description = ENV_TWEAK_META[tweak_id]
    return SimpleNamespace(
        id=tweak_id,
        name=name,
        group=group,
        versions_supported="env-backed",
        versions_tested=("env-backed",),
        versions_blacklisted=(),
        on_miss="skip",
        description=description,
    )

def _tweak_passes_filter(state, tweak_id, recommended):
    status = tweak_status(state, tweak_id)
    if state.tweak_filter == "recommended" and tweak_id not in recommended:
        return False
    if state.tweak_filter == "advanced" and tweak_id in DEFAULT_TWEAK_IDS:
        return False
    if state.tweak_filter == "incompatible" and status["selectable"]:
        return False
    meta = _tweak_meta(tweak_id)
    if meta is None:
        return False
    search_text = f"{meta.id} {meta.name} {meta.group} {meta.description}".lower()
    if state.tweak_search and state.tweak_search.lower() not in search_text:
        return False
    return True

def selected_tweaks_source_variant_id(state):
    if not state.variants:
        return None
    index = max(0, min(state.selected_index, len(state.variants) - 1))
    return state.variants[index].variant_id
