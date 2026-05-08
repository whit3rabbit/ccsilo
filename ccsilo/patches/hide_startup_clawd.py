"""Hide the ASCII clawed-claw startup banner.

Adapted from ccsilo/variants/tweaks.py::_hide_startup_clawd.
"""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(r"▛███▜|\\u259B\\u2588\\u2588\\u2588\\u259C", js, re.IGNORECASE)
    if not match:
        return PatchOutcome(js=js, status="missed")
    lookback_start = max(0, match.start() - 2000)
    before = js[lookback_start:match.start()]
    funcs = list(re.finditer(r"function ([$\w]+)\([^)]*\)\{", before))
    if not funcs:
        return PatchOutcome(js=js, status="missed")
    inner_name = funcs[-1].group(1)
    for wrapper in re.finditer(r"function ([$\w]+)\([^)]*\)\{", js):
        body_start = wrapper.end()
        body = js[body_start:body_start + 500]
        elem_idx = body.find(f"createElement({inner_name},")
        if elem_idx == -1:
            continue
        if body.lstrip().startswith("return null;"):
            return PatchOutcome(js=js, status="skipped")
        next_func_idx = body.find("function ")
        if next_func_idx != -1 and next_func_idx < elem_idx:
            continue
        new_js = js[:body_start] + "return null;" + js[body_start:]
        return PatchOutcome(js=new_js, status="applied")
    inner_start = lookback_start + funcs[-1].end()
    if js[inner_start:inner_start + 32].lstrip().startswith("return null;"):
        return PatchOutcome(js=js, status="skipped")
    new_js = js[:inner_start] + "return null;" + js[inner_start:]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="hide-startup-clawd",
    name="Hide ASCII startup banner",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Hide the ASCII clawed-claw mascot shown at startup.",
)
