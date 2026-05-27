import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.suppress_prompt_caching_warning import PATCH
from tests.patches.conftest import resolve_tested_versions


_NOTICE_OBJECT_JS = (
    'x$z={id:"prompt-caching-disabled",tier:"critical",type:"warning",'
    'isActive:()=>qu4().length>0,render:()=>{let H=qu4();return '
    'e4.createElement(p,{flexDirection:"row"},e4.createElement(k,{color:"error"},'
    '"\\u25CF "),e4.createElement(p,{flexDirection:"column"},'
    'e4.createElement(k,{color:"error"},"Prompt caching disabled via ",H.join(", "),'
    '". This will impact latency and token costs."),e4.createElement(k,{dimColor:!0},'
    '"We highly recommend disabling"," ",H.length===1?"this environment variable":'
    '"these environment variables")))}}'
)


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("suppress-prompt-caching-warning")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "Prompt caching disabled via" not in outcome.js
    assert "ccsilo:suppress-prompt-caching-warning" in outcome.js


def test_notice_object_anchor_disables_warning():
    outcome = PATCH.apply(_NOTICE_OBJECT_JS, PatchContext(claude_version="2.1.152"))

    assert outcome.status == "applied"
    assert 'isActive:()=>false/*ccsilo:suppress-prompt-caching-warning*/' in outcome.js
    assert "Prompt caching disabled via" in outcome.js


def test_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("suppress-prompt-caching-warning")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_miss_has_detail():
    outcome = PATCH.apply("function unrelated(){return null}", PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert outcome.notes == ("missing prompt caching warning component",)


def test_metadata():
    assert PATCH.id == "suppress-prompt-caching-warning"
    assert PATCH.group == "ui"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))

    assert outcome.status == "applied"
    assert "ccsilo:suppress-prompt-caching-warning" in outcome.js


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
