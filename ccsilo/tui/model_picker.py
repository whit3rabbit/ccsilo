"""Shared helpers for TUI model-picker state and filtering."""

from ._const import MODEL_CHOICE_DISPLAY_LIMIT, VARIANT_MODEL_FIELDS


def model_field_keys():
    return [key for key, _label in VARIANT_MODEL_FIELDS]


def model_field_label(key: str) -> str:
    for field_key, label in VARIANT_MODEL_FIELDS:
        if field_key == key:
            return label
    return VARIANT_MODEL_FIELDS[0][1]


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
