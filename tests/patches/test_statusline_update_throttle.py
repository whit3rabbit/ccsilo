import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.statusline_update_throttle import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies_throttle_default(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "lastCall=Pc.useRef(0)" in outcome.js
    assert "now-lastCall.current>=300" in outcome.js
    assert "X=Pc.useCallback" in outcome.js


def test_synthetic_v2_applies_throttle_default(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v2")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "lastCall=xj.useRef(0)" in outcome.js
    assert "now-lastCall.current>=300" in outcome.js
    assert "u=xj.useCallback" in outcome.js


def test_synthetic_v2_applies_fixed_interval_config(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v2")
    outcome = PATCH.apply(
        js,
        PatchContext(
            claude_version=None,
            config={
                "settings": {
                    "misc": {
                        "statuslineThrottleMs": 750,
                        "statuslineUseFixedInterval": True,
                    }
                }
            },
        ),
    )
    assert outcome.status == "applied"
    assert "setInterval(()=>I(),750)" in outcome.js
    assert "u=xj.useCallback(()=>{},[])" in outcome.js


def test_synthetic_applies_fixed_interval_config(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle")
    outcome = PATCH.apply(
        js,
        PatchContext(
            claude_version=None,
            config={
                "settings": {
                    "misc": {
                        "statuslineThrottleMs": 750,
                        "statuslineUseFixedInterval": True,
                    }
                }
            },
        ),
    )
    assert outcome.status == "applied"
    assert "setInterval(()=>O(argRef.current),750)" in outcome.js
    assert "X=Pc.useCallback(()=>{},[])" in outcome.js


def test_synthetic_v3_default_config_skips(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v3")
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.259"))
    assert outcome.status == "skipped"
    assert outcome.js == js


def test_synthetic_v3_applies_throttle_config(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v3")
    outcome = PATCH.apply(
        js,
        PatchContext(
            claude_version="2.1.259",
            config={"settings": {"misc": {"statuslineThrottleMs": 750}}},
        ),
    )
    assert outcome.status == "applied"
    assert "var N1e=750,L1e=1000;" in outcome.js
    assert "lastCall" not in outcome.js
    assert "setInterval" not in outcome.js


def test_synthetic_v3_fixed_interval_notes_native_setting(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v3")
    outcome = PATCH.apply(
        js,
        PatchContext(
            claude_version="2.1.259",
            config={
                "settings": {
                    "misc": {
                        "statuslineThrottleMs": 750,
                        "statuslineUseFixedInterval": True,
                    }
                }
            },
        ),
    )
    assert outcome.status == "applied"
    assert "var N1e=750,L1e=1000;" in outcome.js
    assert "setInterval" not in outcome.js
    assert any("statusLine.refreshInterval" in note for note in outcome.notes)


def test_synthetic_v3_fixed_interval_default_skips_with_note(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v3")
    outcome = PATCH.apply(
        js,
        PatchContext(
            claude_version="2.1.259",
            config={"settings": {"misc": {"statuslineUseFixedInterval": True}}},
        ),
    )
    assert outcome.status == "skipped"
    assert outcome.js == js
    assert any("statusLine.refreshInterval" in note for note in outcome.notes)


def test_synthetic_v3_ambiguous_anchor_misses(cli_js_synthetic):
    js = cli_js_synthetic("statusline-update-throttle-v3") * 2
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.259"))
    assert outcome.status == "missed"
    assert outcome.notes and "ambiguous" in outcome.notes[0]


def test_metadata():
    assert PATCH.id == "statusline-update-throttle"
    assert PATCH.group == "ui"


_THROTTLE_750 = {"settings": {"misc": {"statuslineThrottleMs": 750}}}


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(
        cli_js_real(version), PatchContext(claude_version=version, config=_THROTTLE_750)
    )
    assert outcome.status == "applied"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1_default_config(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
    assert outcome.status in ("applied", "skipped")
    if outcome.status == "skipped":
        assert outcome.js == cli_js_real(version)


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version, config=_THROTTLE_750))
    parse_js(outcome.js)
