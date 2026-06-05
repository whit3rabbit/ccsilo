"""Suppress the native installer startup warning."""

import re

from . import Patch, PatchContext, PatchOutcome


_WARNING = (
    "Claude Code has switched from npm to native installer. Run `claude install` "
    "or see https://docs.anthropic.com/en/docs/claude-code/getting-started "
    "for more options."
)
_MARKER = "ccsilo:suppress-native-installer-warning"
_NPM_DEPRECATION_NOTICE_RE = re.compile(
    r'(id:"npm-deprecation",tier:"(?:critical|warning)",type:"warning",isActive:\([$\w]+\)=>)'
    r'[$\w]+\.npmInstallDeprecated'
    r'(?=,render:\(\)=>[\s\S]{0,1200}?"Installed via npm \(deprecated\)")'
    r'(?=,render:\(\)=>[\s\S]{0,1200}?claude install)'
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    new_js = js
    changed = False

    match = re.search(re.escape(_WARNING), new_js)
    if match:
        new_js = new_js[:match.start()] + new_js[match.end():]
        changed = True

    if _MARKER not in new_js:
        match = _NPM_DEPRECATION_NOTICE_RE.search(new_js)
        if match:
            replacement = f"{match.group(1)}false/*{_MARKER}*/"
            new_js = new_js[:match.start()] + replacement + new_js[match.end():]
            changed = True

    if changed:
        return PatchOutcome(js=new_js, status="applied")
    if _MARKER in new_js:
        return PatchOutcome(js=new_js, status="skipped")
    if "npm-deprecation" in js or "Installed via npm (deprecated)" in js:
        return PatchOutcome(
            js=js,
            status="missed",
            notes=("missing npm deprecation warning notice",),
        )
    return PatchOutcome(
        js=js,
        status="skipped",
        notes=("native installer warning already absent",),
    )


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
