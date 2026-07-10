"""Auto-accept the 'Ready to code?' plan-mode prompt."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    ready_idx = js.find('title:"Ready to code?"')
    if ready_idx == -1:
        return PatchOutcome(js=js, status="missed")
    if re.search(r"[$\w]+(?:\.current)?\(\"yes-accept-edits\"\);return null;", js):
        return PatchOutcome(js=js, status="skipped")

    # Legacy structure (<=2.1.205): the select's onChange is a bare/memoized
    # wrapper handler sitting near the title, with either a `return` just before
    # the title or an `else <handler>=<cache>[N];` memo assignment to inject
    # after. Insert the auto-accept there.
    legacy = _apply_legacy(js, ready_idx)
    if legacy is not None:
        return legacy

    # 2.1.206+ structure: the proceed branch inlines the handler as
    # `onChange:(v)=>void <handler>(v)` (the earlier bare `onChange:<ident>` now
    # belongs to the review branch), and React-compiler memoization leaves the
    # component with a single terminal `return <ident>}`. Call the underlying
    # handler and short-circuit that return.
    inline = _apply_inline(js, ready_idx)
    if inline is not None:
        return inline

    return PatchOutcome(js=js, status="missed")


def _apply_legacy(js: str, ready_idx: int):
    after = js[ready_idx:ready_idx + 3000]
    accept_func = None
    match = None
    for pattern in (
        r"onChange:\([$\w]+\)=>([$\w]+)\([$\w]+\),onCancel",
        r"onChange:([$\w]+),onCancel",
        r"onChange:\([$\w]+\)=>void ([$\w]+)\.current\([$\w]+\),onCancel",
    ):
        match = re.search(pattern, after)
        if match:
            accept_func = match.group(1)
            if ".current" not in accept_func and "current" in pattern:
                accept_func += ".current"
            break
    if not accept_func:
        return None
    insertion = f'{accept_func}("yes-accept-edits");return null;'
    before_start = max(0, ready_idx - 500)
    before = js[before_start:ready_idx]
    return_idx = before.rfind("return ")
    if return_idx == -1:
        fallback = re.search(
            rf"else {re.escape(accept_func)}=[$\w]+\[\d+\];",
            after[: match.start()],
        )
        if not fallback:
            return None
        insert_at = ready_idx + fallback.end()
        new_js = js[:insert_at] + insertion + js[insert_at:]
        return PatchOutcome(js=new_js, status="applied")
    insert_at = before_start + return_idx
    new_js = js[:insert_at] + insertion + js[insert_at:]
    return PatchOutcome(js=new_js, status="applied")


def _apply_inline(js: str, ready_idx: int):
    after = js[ready_idx:ready_idx + 4000]
    # Underlying handler from the proceed branch: onChange:(v)=>void FUNC(v)
    handler = re.search(
        r"onChange:\([$\w]+\)=>void ([$\w]+)\([$\w]+\),onCancel", after
    )
    if not handler:
        return None
    accept_func = handler.group(1)
    # Component's terminal return; it is the first `return <ident>}` after the
    # title in the memoized render output.
    ret = re.search(r"return [$\w]+\}", after[handler.end():])
    if not ret:
        return None
    insert_at = ready_idx + handler.end() + ret.start()
    insertion = f'{accept_func}("yes-accept-edits");return null;'
    new_js = js[:insert_at] + insertion + js[insert_at:]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="auto-accept-plan-mode",
    name="Auto-accept plan mode",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Auto-accept the 'Ready to code?' plan-mode prompt without prompting the user.",
)
