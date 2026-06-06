import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.hide_startup_banner import PATCH


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("hide-startup-banner")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "isBeforeFirstMessage" not in outcome.js or "return null;" in outcome.js


def test_realistic_function_anchor_skips_terminal_helper_false_positive():
    js = (
        'function abH(){return terminal==="Apple_Terminal"}'
        + ("x" * 6000)
        + 'function qDH(){let terminal="Apple_Terminal";return "Welcome to Claude Code"}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.123"))
    assert outcome.status == "applied"
    assert 'function abH(){return terminal==="Apple_Terminal"}' in outcome.js
    assert 'function qDH(){return null;}' in outcome.js


def test_new_startup_banner_shape_with_pre_terminal_branch_applies():
    js = (
        'function kZH(){let H=uzq.c(36),[_]=d7();'
        'if(WA()){let G;if(H[0]===Symbol.for("react.memo_cache_sentinel"))'
        'G=Pq.default.createElement(N,null,'
        'Pq.default.createElement(N,{color:"claude"},"Welcome to Claude Code"," "),'
        'Pq.default.createElement(N,{dimColor:!0},"v",'
        '{PACKAGE_URL:"@anthropic-ai/claude-code",VERSION:"2.1.167"}.VERSION)),'
        'H[0]=G;else G=H[0];return G}'
        'if(Z_.terminal==="Apple_Terminal")return Pq.default.createElement(Ki3,'
        '{theme:_,welcomeMessage:"Welcome to Claude Code"});'
        'return Pq.default.createElement(N,null,"banner")}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.167"))
    assert outcome.status == "applied"
    assert outcome.js == "function kZH(){return null;}"


def test_ide_onboarding_welcome_is_not_banner_anchor():
    js = (
        'function OC8(H){let _=sL7.c(22),{onDone:q,installationStatus:K}=H;'
        'let w="VS Code",M=GZ.default.createElement(GZ.default.Fragment,null,'
        'GZ.default.createElement(N,{color:"claude"},"\\u273B "),'
        'GZ.default.createElement(N,null,"Welcome to Claude Code for ",w));'
        'return GZ.default.createElement(Q6,{title:M,onCancel:q},null)}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.167"))
    assert outcome.status == "missed"
    assert outcome.js == js


def test_metadata():
    assert PATCH.id == "hide-startup-banner"
    assert PATCH.group == "ui"
    assert PATCH.versions_tested  # non-empty


@pytest.fixture
def real_js_versions():
    from tests.patches.conftest import resolve_tested_versions
    return resolve_tested_versions(PATCH)


def test_real_l1_anchor_matches(cli_js_real, real_js_versions):
    if not real_js_versions:
        pytest.skip("no resolved versions")
    for version in real_js_versions:
        js = cli_js_real(version)
        outcome = PATCH.apply(js, PatchContext(claude_version=version))
        assert outcome.status == "applied", (
            f"hide-startup-banner did not apply against {version}"
        )


def test_real_l1_anchor_matches_2_1_167(cli_js_real):
    js = cli_js_real("2.1.167")
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.167"))
    assert outcome.status == "applied"


def test_real_l2_patched_js_parses(cli_js_real, real_js_versions, parse_js):
    if not real_js_versions:
        pytest.skip("no resolved versions")
    for version in real_js_versions:
        js = cli_js_real(version)
        # Skip L2 test if the original JS doesn't parse (extraction issue, not patch issue)
        try:
            parse_js(js)
        except AssertionError:
            pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
        outcome = PATCH.apply(js, PatchContext(claude_version=version))
        parse_js(outcome.js)
