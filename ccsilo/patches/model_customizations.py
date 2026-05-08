"""Add custom Claude model entries to the model picker.

Adapted from ccsilo/variants/tweaks.py::_model_customizations.
"""

import json
import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


CUSTOM_MODELS = [
    {"value": "claude-opus-4-6", "label": "Opus 4.6", "description": "Claude Opus 4.6"},
    {"value": "claude-sonnet-4-6", "label": "Sonnet 4.6", "description": "Claude Sonnet 4.6"},
    {"value": "claude-haiku-4-5-20251001", "label": "Haiku 4.5", "description": "Claude Haiku 4.5"},
    {"value": "claude-opus-4-5-20251101", "label": "Opus 4.5", "description": "Claude Opus 4.5"},
    {"value": "claude-sonnet-4-5-20250929", "label": "Sonnet 4.5", "description": "Claude Sonnet 4.5"},
    {"value": "claude-opus-4-20250514", "label": "Opus 4", "description": "Claude Opus 4"},
    {"value": "claude-sonnet-4-20250514", "label": "Sonnet 4", "description": "Claude Sonnet 4"},
    {"value": "claude-3-7-sonnet-20250219", "label": "Sonnet 3.7", "description": "Claude 3.7 Sonnet"},
    {"value": "claude-3-5-haiku-20241022", "label": "Haiku 3.5", "description": "Claude 3.5 Haiku"},
]


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(
        r" ([$\w]+)\.push\(\{value:[$\w]+,label:[$\w]+,description:\"Custom model\"\}\)", js
    )
    if not match:
        return PatchOutcome(js=js, status="missed")
    model_var = match.group(1)
    search_start = max(0, match.start() - 1500)
    chunk = js[search_start:match.start()]
    func_pattern = re.compile(
        rf"function [$\w]+\([^)]*\)\{{(?:let|var|const) {re.escape(model_var)}=.+?;"
    )
    last = None
    for found in func_pattern.finditer(chunk):
        last = found
    if last is None:
        return PatchOutcome(js=js, status="missed")
    insertion_index = search_start + last.end()
    marker = f"{model_var}.push({json.dumps(CUSTOM_MODELS[0], separators=(',', ':'))});"
    if js[insertion_index:insertion_index + len(marker)] == marker:
        return PatchOutcome(js=js, status="skipped")
    inject = "".join(
        f"{model_var}.push({json.dumps(model, separators=(',', ':'))});"
        for model in CUSTOM_MODELS
    )
    new_js = js[:insertion_index] + inject + js[insertion_index:]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="model-customizations",
    name="Custom Claude models in picker",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Add extended Claude model entries (Opus 4.6, Sonnet 4.6, Haiku 4.5, etc.) to the model picker.",
)
