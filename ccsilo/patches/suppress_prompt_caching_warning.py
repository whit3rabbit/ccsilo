"""Suppress the prompt-caching-disabled startup warning."""

import re

from . import Patch, PatchContext, PatchOutcome


_MARKER = "ccsilo:suppress-prompt-caching-warning"
_WARNING_COMPONENT_RE = re.compile(
    r'(function\s+[$\w]+\(\)\{)'
    r'let\s+[$\w]+=[$\w]+\.c\(5\),[$\w]+;'
    r'(?=[\s\S]{0,1800}?"DISABLE_PROMPT_CACHING")'
    r'(?=[\s\S]{0,1800}?"Prompt caching disabled via ")'
    r'[\s\S]{0,2400}?return\s+[$\w]+;?\}'
)
_WARNING_NOTICE_RE = re.compile(
    r'(id:"prompt-caching-disabled",tier:"(?:critical|warning)",type:"warning",isActive:\(\)=>)'
    r'[$\w]+\(\)\.length>0'
    r'(?=,render:\(\)=>\{[\s\S]{0,1800}?"Prompt caching (?:disabled via |off \())'
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _MARKER in js:
        return PatchOutcome(js=js, status="skipped")

    match = _WARNING_COMPONENT_RE.search(js)
    if match:
        replacement = f"{match.group(1)}return null/*{_MARKER}*/}}"
        new_js = js[:match.start()] + replacement + js[match.end():]
        return PatchOutcome(js=new_js, status="applied")

    match = _WARNING_NOTICE_RE.search(js)
    if match:
        replacement = f"{match.group(1)}false/*{_MARKER}*/"
        new_js = js[:match.start()] + replacement + js[match.end():]
        return PatchOutcome(js=new_js, status="applied")

    return PatchOutcome(
        js=js,
        status="missed",
        notes=("missing prompt caching warning component",),
    )


PATCH = Patch(
    id="suppress-prompt-caching-warning",
    name="Suppress prompt caching warning",
    group="ui",
    versions_supported=">=2.1.0,<3",
    versions_tested=(">=2.1.0,<=2.1.186",),
    apply=_apply,
    on_miss="skip",
    description="Hide the startup warning shown when prompt caching is disabled by environment variables.",
)
