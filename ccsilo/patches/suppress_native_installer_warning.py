"""Suppress the native installer startup warning."""

import re

from . import Patch, PatchContext, PatchOutcome


_WARNING = (
    "Claude Code has switched from npm to native installer. Run `claude install` "
    "or see https://docs.anthropic.com/en/docs/claude-code/getting-started "
    "for more options."
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(re.escape(_WARNING), js)
    if not match:
        return PatchOutcome(
            js=js,
            status="skipped",
            notes=("native installer warning already absent",),
        )
    new_js = js[:match.start()] + js[match.end():]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="suppress-native-installer-warning",
    name="Suppress native installer warning",
    group="ui",
    versions_supported=">=2.1.0,<3",
    versions_tested=(">=2.1.0,<2.2",),
    apply=_apply,
    on_miss="skip",
    description="Remove the startup warning that prompts npm users to install the native Claude Code binary.",
)
