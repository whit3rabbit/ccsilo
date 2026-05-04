import warnings
import pytest

from cc_extractor.patches import (
    Patch,
    PatchAnchorMissError,
    PatchBlacklistedError,
    PatchContext,
    PatchOutcome,
    PatchUnsupportedVersionError,
    apply_patches,
)


def _make_patch(id_, *, status="applied", on_miss="fatal", supported=">=0.0.0,<99",
                tested=(">=0.0.0,<99",), blacklisted=()):
    def _apply(js, ctx):
        return PatchOutcome(js=js + f":{id_}" if status == "applied" else js, status=status)
    return Patch(
        id=id_, name=id_, group="ui",
        versions_supported=supported,
        versions_tested=tested,
        versions_blacklisted=blacklisted,
        on_miss=on_miss,
        apply=_apply,
    )


def test_apply_patches_runs_in_registry_order():
    registry = {"a": _make_patch("a"), "b": _make_patch("b")}
    ctx = PatchContext(claude_version=None)
    result = apply_patches("js", ["a", "b"], ctx, registry=registry)
    assert result.js == "js:a:b"
    assert result.applied == ("a", "b")


def test_apply_patches_skips_when_outcome_is_skipped():
    registry = {"a": _make_patch("a", status="skipped")}
    ctx = PatchContext(claude_version=None)
    result = apply_patches("js", ["a"], ctx, registry=registry)
    assert result.js == "js"
    assert result.applied == ()
    assert result.skipped == ("a",)


def test_apply_patches_fatal_miss_raises():
    registry = {"a": _make_patch("a", status="missed", on_miss="fatal")}
    ctx = PatchContext(claude_version=None)
    with pytest.raises(PatchAnchorMissError):
        apply_patches("js", ["a"], ctx, registry=registry)


def test_apply_patches_fatal_miss_preserves_notes():
    def _apply(js, ctx):
        return PatchOutcome(js=js, status="missed", notes=("missing nested gate",))

    registry = {
        "a": Patch(
            id="a",
            name="a",
            group="ui",
            versions_supported=">=0.0.0,<99",
            versions_tested=(">=0.0.0,<99",),
            apply=_apply,
        )
    }
    ctx = PatchContext(claude_version=None)

    with pytest.raises(PatchAnchorMissError, match="missing nested gate"):
        apply_patches("js", ["a"], ctx, registry=registry)


def test_apply_patches_warn_miss_warns_and_continues():
    registry = {"a": _make_patch("a", status="missed", on_miss="warn"),
                "b": _make_patch("b")}
    ctx = PatchContext(claude_version=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = apply_patches("js", ["a", "b"], ctx, registry=registry)
    assert result.applied == ("b",)
    assert result.missed == ("a",)
    assert any("a" in str(w.message) for w in caught)


def test_apply_patches_skip_miss_silent():
    registry = {"a": _make_patch("a", status="missed", on_miss="skip")}
    ctx = PatchContext(claude_version=None)
    result = apply_patches("js", ["a"], ctx, registry=registry)
    assert result.missed == ("a",)
    assert result.applied == ()
    assert result.skipped == ()


def test_apply_patches_blacklist_blocks():
    registry = {"a": _make_patch("a", blacklisted=("2.0.40",))}
    ctx = PatchContext(claude_version="2.0.40")
    with pytest.raises(PatchBlacklistedError):
        apply_patches("js", ["a"], ctx, registry=registry)


def test_apply_patches_unsupported_version_blocks():
    registry = {"a": _make_patch("a", supported=">=3.0.0,<4")}
    ctx = PatchContext(claude_version="2.0.40")
    with pytest.raises(PatchUnsupportedVersionError):
        apply_patches("js", ["a"], ctx, registry=registry)


def test_apply_patches_force_bypasses_blacklist():
    registry = {"a": _make_patch("a", blacklisted=("2.0.40",))}
    ctx = PatchContext(claude_version="2.0.40", force=True)
    result = apply_patches("js", ["a"], ctx, registry=registry)
    assert result.applied == ("a",)


def test_apply_patches_warns_when_version_supported_but_not_tested():
    registry = {"a": _make_patch("a", supported=">=2.0.0,<3", tested=(">=2.0.0,<2.1",))}
    ctx = PatchContext(claude_version="2.5.0")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = apply_patches("js", ["a"], ctx, registry=registry)
    assert result.applied == ("a",)
    assert any("2.5.0" in str(w.message) for w in caught)


def test_apply_patches_unknown_id_raises():
    with pytest.raises(KeyError):
        apply_patches("js", ["nope"], PatchContext(claude_version=None), registry={})
