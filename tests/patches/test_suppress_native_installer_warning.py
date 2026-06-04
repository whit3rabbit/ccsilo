import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.suppress_native_installer_warning import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("suppress-native-installer-warning")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "Claude Code has switched from npm to native installer" not in outcome.js


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
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
    assert outcome.status in {"applied", "skipped"}


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
