"""Suppress the model launch availability notice."""

import re

from . import Patch, PatchContext, PatchOutcome


_MARKER = "ccsilo:suppress-model-launch-notice"
_OPUS47_ELIGIBILITY_RE = re.compile(
    r'(function\s+[$\w]+\(\)\{)'
    r'if\([$\w]+\(\)!=="firstParty"\)return!1;'
    r'let\s+([$\w]+)=[$\w]+\(\);'
    r'if\(\2\.unpinOpus47LaunchEffort\)return!1;'
    r'if\(\(\2\.opus47LaunchSeenCount\?\?0\)>=[$\w]+\)return!1;'
    r'return!0\}'
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _MARKER in js:
        return PatchOutcome(js=js, status="skipped")

    match = _OPUS47_ELIGIBILITY_RE.search(js)
    if not match:
        return PatchOutcome(
            js=js,
            status="missed",
            notes=("missing Opus 4.7 launch eligibility gate",),
        )

    replacement = f"{match.group(1)}return!1/*{_MARKER}*/}}"
    new_js = js[:match.start()] + replacement + js[match.end():]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="suppress-model-launch-notice",
    name="Suppress model launch notice",
    group="ui",
    versions_supported=">=2.1.0,<3",
    versions_tested=(">=2.1.0,<=2.1.152",),
    apply=_apply,
    on_miss="skip",
    description="Hide the startup notice announcing newly available Claude model launches.",
)
