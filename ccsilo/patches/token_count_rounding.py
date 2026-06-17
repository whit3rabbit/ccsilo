"""Round displayed token counts."""

import re
from typing import Optional, Tuple

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


_STATUSLINE_TEMPLATE_RE = re.compile(
    r'(([$\w]+)=([$\w]+)\()'
    r'([$\w]+)'
    r'(\),[$\w]+=[$\w]+\?`\$\{\2\} tokens`:`[^`]*\$\{\2\} tokens`)'
)
_STATUSLINE_ARROW_TEMPLATE_RE = re.compile(
    r'(([$\w]+)=([$\w]+)\()'
    r'([$\w]+)'
    r'(\),[$\w]+=`\$\{[$\w]+\.arrowDown\} \$\{\2\} tokens`)'
)
_TOKEN_KEY_ANCHOR = 'key:"tokens"'
_TOKEN_SUFFIX_RE = re.compile(r',([$\w]+)," tokens"')
_OVERRIDE_CALL_RE = re.compile(
    r'(overrideMessage:.{0,10000},([$\w]+)=[$\w]+\()(.+?)(\),.{0,1000}key:"tokens".{0,200},\2," tokens")',
    re.DOTALL,
)
_OVERRIDE_ROUNDED_RE = re.compile(
    r'(overrideMessage:.{0,10000},key:"tokens".{0,200}[$\w]+\()(Math\.round\(.+?\))(\))',
    re.DOTALL,
)


def _rounding_base(ctx: PatchContext) -> int:
    settings = ((ctx.config or {}).get("settings") or {}).get("misc") or {}
    value = settings.get("tokenCountRounding") or (ctx.config or {}).get("token_count_rounding") or 1000
    return int(value)


def _round_expression(pre: str, part: str, post: str, base: int) -> str:
    return f"{pre}Math.round(({part})/{base})*{base}{post}"


def _search_token_windowed(js: str, pattern: re.Pattern, *, before: int, after: int, required: Optional[str]):
    if required is not None and required not in js:
        return None

    cursor = 0
    while True:
        anchor = js.find(_TOKEN_KEY_ANCHOR, cursor)
        if anchor == -1:
            return None
        cursor = anchor + len(_TOKEN_KEY_ANCHOR)
        start = max(0, anchor - before)
        end = min(len(js), anchor + len(_TOKEN_KEY_ANCHOR) + after)
        window = js[start:end]
        if required is not None and required not in window:
            continue
        match = pattern.search(window)
        if match:
            return start, match


def _search_call_key(js: str) -> Optional[Tuple[int, int, str, str, str]]:
    cursor = 0
    while True:
        anchor = js.find(_TOKEN_KEY_ANCHOR, cursor)
        if anchor == -1:
            return None
        cursor = anchor + len(_TOKEN_KEY_ANCHOR)

        suffix = _TOKEN_SUFFIX_RE.search(js[anchor: anchor + len(_TOKEN_KEY_ANCHOR) + 220])
        if suffix is None:
            continue
        display_var = suffix.group(1)
        suffix_end = anchor + suffix.end()

        assign_start = max(0, anchor - 2500)
        assign_window = js[assign_start:anchor]
        assign_pattern = re.compile(rf'{re.escape(display_var)}=[$\w]+\(')
        assignments = list(assign_pattern.finditer(assign_window))
        for assignment in reversed(assignments):
            start = assign_start + assignment.start()
            pre = assignment.group(0)
            part_start = assign_start + assignment.end()
            close_at = js.find(")", part_start, anchor)
            if close_at == -1 or anchor - close_at > 2000:
                continue
            part = js[part_start:close_at]
            post = js[close_at:suffix_end]
            if part:
                return start, suffix_end, pre, part, post


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    base = _rounding_base(ctx)
    if "`" in js:
        for statusline_pattern in (_STATUSLINE_TEMPLATE_RE, _STATUSLINE_ARROW_TEMPLATE_RE):
            statusline_match = statusline_pattern.search(js)
            if not statusline_match:
                continue
            pre, part, post = (
                statusline_match.group(1),
                statusline_match.group(4),
                statusline_match.group(5),
            )
            replacement = _round_expression(pre, part, post, base)
            new_js = js[:statusline_match.start()] + replacement + js[statusline_match.end():]
            return PatchOutcome(js=new_js, status="applied")

    override_call = _search_token_windowed(
        js,
        _OVERRIDE_CALL_RE,
        before=12_000,
        after=260,
        required="overrideMessage",
    )
    if override_call:
        window_start, match = override_call
        pre, part, post = match.group(1), match.group(3), match.group(4)
        if "Math.round((" in part:
            return PatchOutcome(js=js, status="skipped")
        replacement = _round_expression(pre, part, post, base)
        start = window_start + match.start()
        end = window_start + match.end()
        new_js = js[:start] + replacement + js[end:]
        return PatchOutcome(js=new_js, status="applied")

    call_key = _search_call_key(js)
    if call_key:
        start, end, pre, part, post = call_key
        if "Math.round((" in part:
            return PatchOutcome(js=js, status="skipped")
        replacement = _round_expression(pre, part, post, base)
        new_js = js[:start] + replacement + js[end:]
        return PatchOutcome(js=new_js, status="applied")

    override_rounded = _search_token_windowed(
        js,
        _OVERRIDE_ROUNDED_RE,
        before=10_500,
        after=260,
        required="overrideMessage",
    )
    if override_rounded:
        window_start, match = override_rounded
        pre, part, post = match.group(1), match.group(2), match.group(3)
        if "Math.round((" in part:
            return PatchOutcome(js=js, status="skipped")
        replacement = _round_expression(pre, part, post, base)
        start = window_start + match.start()
        end = window_start + match.end()
        new_js = js[:start] + replacement + js[end:]
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
