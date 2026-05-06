"""Append the provider label to the (Claude Code) version banner."""

from . import Patch, PatchContext, PatchOutcome

def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    marker = " (Claude Code)"
    idx = js.find(marker)
    if idx == -1:
        return PatchOutcome(js=js, status="missed")
    replacement = f" (Claude Code, {ctx.provider_label} variant)"
    new_js = js[:idx] + replacement + js[idx + len(marker):]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="patches-applied-indication",
    name="Patches-applied indication",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=(">=2.0.20,<2.1", ">=2.1.0,<=2.1.131"),
    apply=_apply,
    description="Append the provider label after '(Claude Code)' in the version banner.",
)
