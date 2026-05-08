"""Round displayed token counts."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _rounding_base(ctx: PatchContext) -> int:
    settings = ((ctx.config or {}).get("settings") or {}).get("misc") or {}
    value = settings.get("tokenCountRounding") or (ctx.config or {}).get("token_count_rounding") or 1000
    return int(value)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    patterns = (
        re.compile(r'(overrideMessage:.{0,10000},([$\w]+)=[$\w]+\()(.+?)(\),.{0,1000}key:"tokens".{0,200},\2," tokens")', re.DOTALL),
        re.compile(r'(([$\w]+)=([$\w]+)\()(.+?)(\),.{0,2000}key:"tokens".{0,200},\2," tokens")', re.DOTALL),
        re.compile(r'(overrideMessage:.{0,10000},key:"tokens".{0,200}[$\w]+\()(Math\.round\(.+?\))(\))', re.DOTALL),
    )
    for index, pattern in enumerate(patterns):
        match = pattern.search(js)
        if not match:
            continue
        if index == 0:
            pre, part, post = match.group(1), match.group(3), match.group(4)
        elif index == 1:
            pre, part, post = match.group(1), match.group(4), match.group(5)
        else:
            pre, part, post = match.group(1), match.group(2), match.group(3)
        if "Math.round((" in part:
            return PatchOutcome(js=js, status="skipped")
        base = _rounding_base(ctx)
        replacement = f"{pre}Math.round(({part})/{base})*{base}{post}"
        new_js = js[:match.start()] + replacement + js[match.end():]
        return PatchOutcome(js=new_js, status="applied")
    return PatchOutcome(js=js, status="missed")


PATCH = Patch(
    id="token-count-rounding",
    name="Token count rounding",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Round displayed token counts to the nearest configured base. Defaults to 1000.",
)
