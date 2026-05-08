"""Hide the startup banner / welcome screen.

Adapted from ccsilo/variants/tweaks.py::_hide_startup_banner.
Original tweakcc source: vendor/tweakcc/src/patches/hideStartupBanner.ts.
"""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    changed = False
    match = re.search(r",[$\w]+\.createElement\([$\w]+,\{isBeforeFirstMessage:!1\}\),", js)
    if match:
        js = js[:match.start()] + "," + js[match.end():]
        changed = True

    for match in re.finditer(r"(function ([$\w]+)\(\)\{)(?=[^}]{0,500}Apple_Terminal)", js):
        body_start = match.end()
        chunk = js[body_start:body_start + 5000]
        if "Welcome to Claude Code" in chunk:
            if js[body_start:body_start + 32].lstrip().startswith("return null;"):
                return PatchOutcome(js=js, status="applied" if changed else "skipped")
            # Find the closing brace of this function
            brace_depth = 1
            pos = body_start
            while pos < len(js) and brace_depth > 0:
                if js[pos] == '{':
                    brace_depth += 1
                elif js[pos] == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        break
                pos += 1
            if brace_depth == 0:
                # Replace the function body with just "return null;"
                # pos now points to the closing brace
                new_js = js[:body_start] + "return null;" + js[pos:]
                return PatchOutcome(js=new_js, status="applied")
    if changed:
        return PatchOutcome(js=js, status="applied")
    return PatchOutcome(js=js, status="missed")


PATCH = Patch(
    id="hide-startup-banner",
    name="Hide startup banner",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Hide the welcome banner shown before the first message.",
)
