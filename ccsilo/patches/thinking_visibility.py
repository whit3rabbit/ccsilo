"""Show thinking blocks without the transcript visibility gate."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(
        r'(case"thinking":\{?)(if\(.+?\)\{?return null[;}])(.{0,400}isTranscriptMode:).+?,',
        js,
        re.DOTALL,
    )
    if not match:
        return PatchOutcome(js=js, status="missed")
    replacement = f"{match.group(1)}{match.group(3)}true,"
    new_js = js[:match.start()] + replacement + js[match.end():]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="thinking-visibility",
    name="Thinking block visibility",
    group="thinking",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Show model thinking blocks without requiring the transcript-mode visibility toggle.",
)
