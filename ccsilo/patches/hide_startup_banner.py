"""Hide the startup banner / welcome screen.

Adapted from ccsilo/variants/tweaks.py::_hide_startup_banner.
Original tweakcc source: vendor/tweakcc/src/patches/hideStartupBanner.ts.
"""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES

_FUNCTION_START_RE = re.compile(r"function ([$\w]+)\(\)\{")
_WELCOME = "Welcome to Claude Code"
_IDE_WELCOME = "Welcome to Claude Code for "
_PACKAGE_ANCHOR = 'PACKAGE_URL:"@anthropic-ai/claude-code"'


def _function_body_end(js: str, body_start: int) -> int:
    brace_depth = 1
    pos = body_start
    quote = None
    escape = False
    while pos < len(js) and brace_depth > 0:
        ch = js[pos]
        if quote is not None:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == quote:
                quote = None
        elif ch in ("'", '"', "`"):
            quote = ch
        elif ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0:
                return pos
        pos += 1
    return -1


def _startup_banner_function(js: str):
    start = 0
    while True:
        welcome_idx = js.find(_WELCOME, start)
        if welcome_idx == -1:
            return None
        start = welcome_idx + len(_WELCOME)
        if js.startswith(_IDE_WELCOME, welcome_idx):
            continue
        window_start = max(0, welcome_idx - 12000)
        matches = list(_FUNCTION_START_RE.finditer(js, window_start, welcome_idx))
        if not matches:
            continue
        match = matches[-1]
        body_start = match.end()
        body_end = _function_body_end(js, body_start)
        if body_end == -1 or welcome_idx > body_end:
            continue
        body = js[body_start:body_end]
        if _IDE_WELCOME in body:
            continue
        if "Apple_Terminal" not in body and _PACKAGE_ANCHOR not in body:
            continue
        return body_start, body_end


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    changed = False
    match = re.search(r",[$\w]+\.createElement\([$\w]+,\{isBeforeFirstMessage:!1\}\),", js)
    if match:
        js = js[:match.start()] + "," + js[match.end():]
        changed = True

    banner_function = _startup_banner_function(js)
    if banner_function is not None:
        body_start, body_end = banner_function
        if js[body_start:body_start + 32].lstrip().startswith("return null;"):
            return PatchOutcome(js=js, status="applied" if changed else "skipped")
        new_js = js[:body_start] + "return null;" + js[body_end:]
        return PatchOutcome(js=new_js, status="applied")
    if changed:
        return PatchOutcome(js=js, status="applied")
    return PatchOutcome(js=js, status="missed")


PATCH = Patch(
    id="hide-startup-banner",
    name="Hide startup banner",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES + ("==2.1.167",),
    apply=_apply,
    description="Hide the welcome banner shown before the first message.",
)
