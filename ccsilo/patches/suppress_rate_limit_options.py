"""Suppress the rate-limit options callback."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    # 2.1.232 reordered the messages-list props from
    # showAllInTranscript,agentDefinitions to
    # agentDefinitions,streamingToolUses,showAllInTranscript; 2.1.235 then
    # dropped agentDefinitions from the list. Accept all three shapes.
    match = re.search(
        r"\.(?:createElement|jsx|jsxs)\([.$\w]+,\{messages:.{0,900},"
        r"(?:showAllInTranscript:[$\w]+,agentDefinitions:[$\w]+,"
        r"|agentDefinitions:[$\w]+,streamingToolUses:[$\w]+,showAllInTranscript:[$\w]+,"
        r"|streamingToolUses:[$\w]+,showAllInTranscript:[$\w]+,)"
        r"onOpenRateLimitOptions:([$\w]+)",
        js,
        re.DOTALL,
    )
    if match:
        new_js = js[:match.start(1)] + "()=>{}" + js[match.end(1):]
        return PatchOutcome(js=new_js, status="applied")
    # 2.1.242+ splits the bundle: the callback is threaded through a props
    # object as `onOpenRateLimitOptions:m?.openRateLimitOptions` instead of a
    # JSX object literal. Neutralize the pass-through value.
    match = re.search(r"onOpenRateLimitOptions:[$\w]+\?\.openRateLimitOptions\b", js)
    if match:
        new_js = js[: match.start()] + "onOpenRateLimitOptions:()=>{}" + js[match.end() :]
        return PatchOutcome(js=new_js, status="applied")
    # 2.1.242-2.1.246 thread it through a compact message-item JSX call:
    # o(Vg,{text:$e,onOpenRateLimitOptions:vO,onRateLimitAutoQueueContinue:YO})
    match = re.search(
        r"onOpenRateLimitOptions:[$\w]+,(?=onRateLimitAutoQueueContinue:[$\w]+\})",
        js,
    )
    if match:
        new_js = js[: match.start()] + "onOpenRateLimitOptions:()=>{}," + js[match.end() :]
        return PatchOutcome(js=new_js, status="applied")
    return PatchOutcome(js=js, status="missed")


PATCH = Patch(
    id="suppress-rate-limit-options",
    name="Suppress rate limit options",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Disable the injected /rate-limit-options opener when rate limits are reached.",
)
