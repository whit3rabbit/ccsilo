"""Shared helpers for TUI model-picker state and filtering."""

from ._const import ARCHITECT_MODE_TWEAK_ID, MODEL_CHOICE_DISPLAY_LIMIT, VARIANT_MODEL_FIELDS


ARCHITECT_MODEL_LABELS = {
    "opus": "Planner",
    "sonnet": "Worker",
    "default": "Default worker",
}


def model_field_keys():
    return [key for key, _label in VARIANT_MODEL_FIELDS]


def model_field_label(key: str, *, architect_mode: bool = False) -> str:
    if architect_mode and key in ARCHITECT_MODEL_LABELS:
        return ARCHITECT_MODEL_LABELS[key]
    for field_key, label in VARIANT_MODEL_FIELDS:
        if field_key == key:
            return label
    return VARIANT_MODEL_FIELDS[0][1]


def create_uses_architect_mode(state) -> bool:
    return ARCHITECT_MODE_TWEAK_ID in (getattr(state, "selected_variant_tweaks", None) or [])


def setup_uses_architect_mode(variant) -> bool:
    manifest = getattr(variant, "manifest", None) or {}
    return ARCHITECT_MODE_TWEAK_ID in (manifest.get("tweaks") or [])


def models_editor_uses_architect_mode(state, variant=None) -> bool:
    if variant is None:
        setup_id = getattr(state, "models_variant_id", None)
        for candidate in getattr(state, "variants", []) or []:
            if candidate.variant_id == setup_id:
                variant = candidate
                break
    return setup_uses_architect_mode(variant) if variant is not None else False


def sync_architect_worker_default(model_overrides, key: str) -> None:
    if key == "sonnet":
        model_overrides["default"] = str(model_overrides.get("sonnet") or "")


def normalize_model_target(key: str) -> str:
    keys = model_field_keys()
    return key if key in keys else keys[0]


def next_model_target(key: str) -> str:
    keys = model_field_keys()
    current = normalize_model_target(key)
    index = keys.index(current)
    return keys[(index + 1) % len(keys)]


def sorted_unique_model_ids(model_ids):
    seen = set()
    result = []
    for model_id in model_ids or []:
        value = str(model_id or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return sorted(result, key=lambda item: item.casefold())


def filtered_model_ids(model_ids, search_text: str):
    choices = list(model_ids or [])
    terms = [term.casefold() for term in str(search_text or "").split() if term]
    if not terms:
        return choices
    return [
        model_id
        for model_id in choices
        if all(term in model_id.casefold() for term in terms)
    ]


def visible_model_ids(model_ids, search_text: str, limit: int = MODEL_CHOICE_DISPLAY_LIMIT):
    matches = filtered_model_ids(model_ids, search_text)
    return matches[:limit], len(matches)


def model_search_label(search_text: str, active: bool) -> str:
    value = str(search_text or "").strip() or "none"
    return f"{value} (typing)" if active else value
