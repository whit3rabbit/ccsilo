"""Module-set patch application for split bundles (Claude Code >= 2.1.242)."""

from ccsilo.patches import (
    ModuleSetOutcome,
    Patch,
    PatchContext,
    PatchOutcome,
    apply_patches_to_modules,
)
from ccsilo.patches.themes import PATCH as THEMES_PATCH
from ccsilo.variants.tweaks import (
    ENV_TWEAK_IDS,
    apply_variant_tweaks_to_modules,
)

VERSION = "2.1.247"


def _ctx(**overrides):
    base = {"claude_version": VERSION, "provider_label": "ccsilo"}
    base.update(overrides)
    return PatchContext(**base)


def _mk_patch(patch_id, marker, *, module_scope="any", on_miss="fatal"):
    def apply(js, ctx):
        if marker in js:
            return PatchOutcome(js=js + f"/*{patch_id}*/", status="applied")
        return PatchOutcome(js=js, status="missed", notes=(f"{patch_id} anchor",))

    return Patch(
        id=patch_id,
        name=patch_id,
        group="ui",
        versions_supported=">=2.1.0,<3",
        versions_tested=(">=2.1.242,<=2.1.247",),
        apply=apply,
        on_miss=on_miss,
        module_scope=module_scope,
    )


def test_apply_patches_to_modules_applies_per_anchor_module():
    patch = _mk_patch("demo", "ANCHOR_A")
    modules = {"cli": "entry;", "_7.js": "var x = 'ANCHOR_A';"}
    result = apply_patches_to_modules(
        modules, ["demo"], _ctx(), entry_path="cli", registry={"demo": patch}
    )
    assert result.applied == ("demo",)
    assert set(result.js_by_path) == {"_7.js"}
    assert result.js_by_path["_7.js"].endswith("/*demo*/")
    assert modules["_7.js"] == "var x = 'ANCHOR_A';"


def test_apply_patches_to_modules_keeps_entry_scoped_patch_on_entry():
    patch = _mk_patch("entry-only", "ANCHOR_A", module_scope="entry")
    modules = {"cli": "entry ANCHOR_A;", "_7.js": "var x = 'ANCHOR_A';"}
    result = apply_patches_to_modules(
        modules, ["entry-only"], _ctx(), entry_path="cli", registry={"entry-only": patch}
    )
    assert result.applied == ("entry-only",)
    assert set(result.js_by_path) == {"cli"}


def test_apply_patches_to_modules_missed_everywhere_keeps_notes():
    patch = _mk_patch("demo", "ANCHOR_A")
    result = apply_patches_to_modules(
        {"cli": "entry;"}, ["demo"], _ctx(), entry_path="cli", registry={"demo": patch}
    )
    assert result.applied == ()
    assert result.missed == ("demo",)
    assert result.notes == ("demo anchor",)


def test_apply_patches_to_modules_drops_miss_notes_when_applied_elsewhere():
    patch = _mk_patch("demo", "ANCHOR_A")
    modules = {"cli": "entry;", "_7.js": "var x = 'ANCHOR_A';"}
    result = apply_patches_to_modules(
        modules, ["demo"], _ctx(), entry_path="cli", registry={"demo": patch}
    )
    # The entry module missed but the patch applied in _7.js, so per-module
    # miss notes must not leak into the aggregate.
    assert result.notes == ()


def test_apply_patches_to_modules_runs_cross_module_hook():
    def apply_modules(modules, ctx):
        if any("NEEDS_BOTH" in js for js in modules.values()):
            return ModuleSetOutcome(
                js_by_path={"cli": modules["cli"] + "/*xmod*/"}, status="applied"
            )
        return ModuleSetOutcome(js_by_path={}, status="missed", notes=("xmod anchor",))

    patch = Patch(
        id="xmod",
        name="xmod",
        group="ui",
        versions_supported=">=2.1.0,<3",
        versions_tested=(">=2.1.242,<=2.1.247",),
        apply=lambda js, ctx: PatchOutcome(js=js, status="missed"),
        apply_modules=apply_modules,
    )
    modules = {"cli": "entry;", "_7.js": "var NEEDS_BOTH = 1;"}
    result = apply_patches_to_modules(
        modules, ["xmod"], _ctx(), entry_path="cli", registry={"xmod": patch}
    )
    assert result.applied == ("xmod",)
    assert result.js_by_path == {"cli": "entry;/*xmod*/"}


def test_apply_variant_tweaks_to_modules_skips_env_only_and_reports_fatal_miss():
    env_only = sorted(ENV_TWEAK_IDS)[0]
    # hide-startup-banner is a real fatal-anchor tweak; nothing anchors in
    # this synthetic module set, so the module-set application must raise.
    import pytest
    from ccsilo.variants.tweaks import TweakPatchError

    result = apply_variant_tweaks_to_modules(
        {"cli": "entry;"},
        entry_path="cli",
        tweak_ids=[env_only],
        claude_version=VERSION,
    )
    assert result.applied == []
    assert env_only in result.skipped

    with pytest.raises(TweakPatchError, match="hide-startup-banner"):
        apply_variant_tweaks_to_modules(
            {"cli": "entry;"},
            entry_path="cli",
            tweak_ids=["hide-startup-banner"],
            claude_version=VERSION,
        )


def test_themes_apply_modules_spans_three_modules():
    obj_module = 'var uu={auto:"Auto (match terminal)",dark:"Dark mode",light:"Light mode"};'
    options_module = (
        'var a={label:"Auto (match terminal)",value:"auto"},'
        'b={label:"Dark mode",value:"dark"},'
        'c={label:"Light mode",value:"light"};'
        'var opts=[a,b,c,...x.map(f),...y];'
    )
    # 2.1.247-style resolver: variable-return cases still match the legacy
    # switch matcher, so the whole switch is replaced like the monolithic era.
    switch_module = 'function ur(r){switch(r){case"light":return D;case"dark-ansi":return H;default:return R}}'
    config = {"themes": [{"id": "zai-dark", "name": "Zai Dark", "colors": {"bashBorder": "#ff0000"}}]}
    outcome = THEMES_PATCH.apply_modules(
        {
            "_154.js": obj_module,
            "_159.js": options_module,
            "_637.js": switch_module,
        },
        _ctx(config=config),
    )
    assert outcome.status == "applied"
    assert set(outcome.js_by_path) == {"_154.js", "_159.js", "_637.js"}
    assert '"zai-dark":"Zai Dark"' in outcome.js_by_path["_154.js"]
    assert '"value":"zai-dark"' in outcome.js_by_path["_159.js"]
    assert 'case"zai-dark":return{"bashBorder":"#ff0000"};' in outcome.js_by_path["_637.js"]
    assert 'default:return{"bashBorder":"#ff0000"};' in outcome.js_by_path["_637.js"]


def test_themes_apply_modules_injects_into_resolver_without_legacy_switch():
    obj_module = 'var uu={auto:"Auto (match terminal)",dark:"Dark mode",light:"Light mode"};'
    options_module = (
        'var a={label:"Auto (match terminal)",value:"auto"},'
        'b={label:"Dark mode",value:"dark"},'
        'c={label:"Light mode",value:"light"};'
        'var opts=[a,b,c,...x.map(f),...y];'
    )
    # No leading case"light"/case"dark" arm: the legacy literal-switch matcher
    # must reject it and the resolver fallback must inject cases instead.
    switch_module = 'function ur(r){switch(r){case"light-ansi":return P;case"dark-ansi":return H;default:return R}}'
    config = {"themes": [{"id": "zai-dark", "name": "Zai Dark", "colors": {"bashBorder": "#ff0000"}}]}
    outcome = THEMES_PATCH.apply_modules(
        {
            "_154.js": obj_module,
            "_159.js": options_module,
            "_637.js": switch_module,
        },
        _ctx(config=config),
    )
    assert outcome.status == "applied"
    patched_switch = outcome.js_by_path["_637.js"]
    assert patched_switch.startswith('function ur(r){switch(r){case"zai-dark":return{"bashBorder":"#ff0000"};case"light-ansi"')
    # Built-in arms survive injection.
    assert 'case"dark-ansi":return H;' in patched_switch
