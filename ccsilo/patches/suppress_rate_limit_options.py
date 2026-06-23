"""Suppress the rate-limit options callback."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(
        r"\.(?:createElement|jsx|jsxs)\([.$\w]+,\{messages:.{0,900},"
        r"showAllInTranscript:[$\w]+,"
        r"agentDefinitions:[$\w]+,onOpenRateLimitOptions:([$\w]+)",
        js,
        re.DOTALL,
    )
    if not match:
        return PatchOutcome(js=js, status="missed")
    new_js = js[:match.start(1)] + "()=>{}" + js[match.end(1):]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="suppress-rate-limit-options",
    name="Suppress rate limit options",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Disable the injected /rate-limit-options opener when rate limits are reached.",
)
