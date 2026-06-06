"""Model editor option helpers for setup variants."""

from ._const import MenuOption, VARIANT_MODEL_FIELDS
from .model_picker import (
    model_field_label,
    model_search_label,
    normalize_model_target,
    visible_model_ids,
)
from .options_variant_state import _provider_model_discovery_enabled

__all__ = [
    "provider_for_setup",
    "models_edit_options",
    "models_edit_variant",
    "selected_models_edit_option",
    "models_display_value",
    "models_pending_diff",
    "model_picker_summary",
    "_models_choice_selected",
]

def provider_for_setup(state, variant):
    provider_key = str(((variant.manifest or {}).get("provider") or {}).get("key") or "")
    for provider in state.variant_providers:
        if provider.get("key") == provider_key:
            return provider
    return {
        "key": provider_key,
        "label": provider_key or "?",
        "models": {},
        "modelDiscovery": {},
        "requiresModelMapping": bool((variant.manifest or {}).get("modelOverrides")),
    }

def models_edit_options(state):
    variant = models_edit_variant(state)
    if variant is None:
        return [MenuOption("models-back", "Back to setup")]
    provider = provider_for_setup(state, variant)
    options = []
    target = normalize_model_target(getattr(state, "models_target", ""))
    for key, label in VARIANT_MODEL_FIELDS:
        value = models_display_value(state, provider, key)
        source = "override" if state.models_pending.get(key, "").strip() else "default"
        marker = ">" if key == target else " "
        options.append(MenuOption("models-field", f"{marker} {label} -> {value or '(not set)'} ({source})", key))
    if _provider_model_discovery_enabled(provider):
        options.append(MenuOption("models-refresh", "Refresh model list"))
        options.append(MenuOption("models-skip", "Skip model list / type aliases manually"))
        if state.models_choices:
            search_text = getattr(state, "models_search_text", "")
            visible, match_count = visible_model_ids(state.models_choices, search_text)
            options.append(MenuOption("section", model_picker_summary(
                len(state.models_choices),
                match_count,
                len(visible),
                search_text,
                getattr(state, "models_search_active", False),
                target,
            )))
            for model_id in visible:
                marker = "*" if _models_choice_selected(state, model_id) else " "
                options.append(MenuOption("models-choice", f"{marker} {model_id}", model_id))
            if not visible:
                options.append(MenuOption("section", "No models match current search. Backspace or clear search to widen."))
            elif match_count > len(visible):
                options.append(MenuOption(
                    "section",
                    f"Showing {len(visible)}/{match_count} matching models; keep typing to narrow.",
                ))
        else:
            options.append(MenuOption(
                "section",
                "No models loaded. Refresh, skip the list, or type aliases manually.",
            ))
    options.append(MenuOption("models-apply", "Apply model changes"))
    options.append(MenuOption("models-discard", "Discard model changes"))
    return options

def models_edit_variant(state):
    if not state.models_variant_id:
        return None
    for variant in state.variants:
        if variant.variant_id == state.models_variant_id:
            return variant
    return None

def selected_models_edit_option(state):
    options = models_edit_options(state)
    if not options:
        return None
    index = max(0, min(state.selected_index, len(options) - 1))
    return options[index]

def models_display_value(state, provider, key):
    override = state.models_pending.get(key, "").strip()
    if override:
        return override
    return str((provider or {}).get("models", {}).get(key) or "")

def models_pending_diff(state):
    baseline = {
        key: value
        for key, value in (state.models_baseline or {}).items()
        if str(value or "").strip()
    }
    pending = {
        key: value
        for key, value in (state.models_pending or {}).items()
        if str(value or "").strip()
    }
    return {
        "changed": sorted(key for key in set(baseline) | set(pending) if baseline.get(key) != pending.get(key)),
        "pending": pending,
    }

def model_picker_summary(total, match_count, visible_count, search_text, active, target):
    search = model_search_label(search_text, active)
    target_label = model_field_label(normalize_model_target(target))
    if total:
        return (
            f"Target: {target_label} | Search: {search} | "
            f"Showing {visible_count}/{match_count} matches from {total} loaded"
        )
    return (
        f"Target: {target_label} | Search: {search} | "
        f"Showing 0/0 matches from 0 loaded"
    )

def _models_choice_selected(state, model_id):
    pending = state.models_pending or {}
    key = normalize_model_target(getattr(state, "models_target", ""))
    return pending.get(key) == model_id
