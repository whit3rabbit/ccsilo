import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.suppress_native_installer_warning import PATCH
from tests.patches.conftest import resolve_tested_versions


_MARKER = "ccsilo:suppress-native-installer-warning"
_OLD_WARNING = "Claude Code has switched from npm to native installer"
_LATEST_WARNING = "Installed via npm (deprecated)"


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("suppress-native-installer-warning")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert _OLD_WARNING not in outcome.js


def test_latest_notice_object_anchor_disables_warning(cli_js_synthetic):
    js = cli_js_synthetic("suppress-native-installer-warning-v2")
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.165"))

    assert outcome.status == "applied"
    assert _LATEST_WARNING in outcome.js
    assert f"isActive:(H)=>false/*{_MARKER}*/" in outcome.js
    assert "isActive:(H)=>H.npmInstallDeprecated" not in outcome.js


def test_latest_notice_object_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("suppress-native-installer-warning-v2")
    once = PATCH.apply(js, PatchContext(claude_version="2.1.165"))
    twice = PATCH.apply(once.js, PatchContext(claude_version="2.1.165"))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_visible_latest_notice_without_anchor_is_missed():
    js = 'x={id:"npm-deprecation",render:()=>kK.createElement(uS,null,"Installed via npm (deprecated)")}'
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.165"))

    assert outcome.status == "missed"
    assert outcome.notes == ("missing npm deprecation warning notice",)


def test_absent_warning_skips():
    js = "function startup(){return null}"
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "skipped"
    assert outcome.js == js
    assert outcome.notes == ("native installer warning already absent",)


def test_metadata():
    assert PATCH.id == "suppress-native-installer-warning"
    assert PATCH.group == "ui"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    js = cli_js_real(version)
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    if _OLD_WARNING in js:
        assert outcome.status == "applied"
        assert _OLD_WARNING not in outcome.js
    elif "npm-deprecation" in js or _LATEST_WARNING in js:
        assert outcome.status == "applied"
        assert _MARKER in outcome.js
    else:
        assert outcome.status == "skipped"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
