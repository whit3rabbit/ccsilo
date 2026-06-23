import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.suppress_rate_limit_options import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("suppress-rate-limit-options")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "onOpenRateLimitOptions:()=>{}" in outcome.js


def test_jsx_runtime_synthetic_applies():
    js = (
        "No.jsxs(No.Fragment,{children:["
        "No.jsx(_We,{messages:Ip.messages,deferMessages:Ip.isMain&&!NH&&be,"
        'placeholderElement:!T?No.jsx(w6e,{param:{text:"x",type:"text"}}):null,'
        "commands:io,verbose:K,screen:ct,streamingToolUses:dr,"
        "showAllInTranscript:zt,agentDefinitions:te,onOpenRateLimitOptions:TVe,"
        "isLoading:be})]})"
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.186"))
    assert outcome.status == "applied"
    assert "onOpenRateLimitOptions:()=>{}" in outcome.js


def test_metadata():
    assert PATCH.id == "suppress-rate-limit-options"
    assert PATCH.group == "ui"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
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
