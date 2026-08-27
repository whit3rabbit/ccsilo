"""Inject custom themes into Claude Code's theme registry.

Adapter over ccsilo.binary_patcher.theme.
"""

from ..binary_patcher.theme import ThemeAnchorNotFound, apply_theme, apply_theme_to_modules, themes_from_config
from . import ModuleSetOutcome, Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _themes_for(ctx: PatchContext):
    return themes_from_config(dict(ctx.config) if ctx.config else None)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    themes = _themes_for(ctx)
    if not themes:
        return PatchOutcome(js=js, status="skipped")
    result = apply_theme(js, themes)
    if result.replaced:
        return PatchOutcome(js=result.js, status="applied")
    return PatchOutcome(js=result.js, status="skipped")


def _apply_modules(modules, ctx: PatchContext):
    themes = _themes_for(ctx)
    if not themes:
        return ModuleSetOutcome(js_by_path={}, status="skipped")
    try:
        changed, replaced = apply_theme_to_modules(modules, themes)
    except ThemeAnchorNotFound as exc:
        return ModuleSetOutcome(js_by_path={}, status="missed", notes=(str(exc),))
    if not replaced:
        return ModuleSetOutcome(js_by_path={}, status="skipped")
    return ModuleSetOutcome(js_by_path=changed, status="applied")


PATCH = Patch(
    id="themes",
    name="Custom themes",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    apply_modules=_apply_modules,
    description="Inject custom theme entries into Claude Code's theme registry.",
)
