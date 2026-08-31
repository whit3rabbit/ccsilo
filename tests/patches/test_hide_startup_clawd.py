import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.hide_startup_clawd import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("hide-startup-clawd")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "return null;" in outcome.js


def test_new_head_art_synthetic_applies(cli_js_synthetic):
    # 2.1.236+ head row art gained a trailing arm block character.
    js = cli_js_synthetic("hide-startup-clawd-v2")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "return null;" in outcome.js


def test_table_above_functions_synthetic_applies(cli_js_synthetic):
    # 2.1.248+ hoists the glyph tables above the render functions, so no
    # function precedes the anchor anymore.
    js = cli_js_synthetic("hide-startup-clawd-v3")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "function sq(R){return null;" in outcome.js


def test_banner_adjacent_function_without_clawd_is_not_patched():
    # The OAuth page handler follows the clawd banner glyphs without
    # referencing the clawd color token; it must stay untouched.
    js = (
        'var banner=` \\u2590\\u259B\\u2588\\u2588\\u2588\\u259B\\u2588`;'
        'function cs(e,t){return new Response("<html>Claude Code</html>")}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "missed"
    assert outcome.js == js


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    js = cli_js_real(version)
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    assert outcome.status == "applied"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
