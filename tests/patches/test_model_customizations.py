import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.model_customizations import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("model-customizations")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "claude-sonnet-4-6" in outcome.js


def test_multi_declarator_entry_let_applies():
    # Claude Code >= 2.1.257 declares the models array as a later declarator
    # of the function-entry let statement instead of the first one.
    js = (
        'function wro(e,n){let r=_ro(e,n),o=r??gro(e),f=1;'
        'if(f)o.push({value:U,label:U,description:"Custom model"});return o}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.259"))
    assert outcome.status == "applied"
    assert "claude-sonnet-4-6" in outcome.js


def test_coalesced_push_and_grown_picker_applies(cli_js_synthetic):
    # Claude Code >= 2.1.261 pushes the fallback entry as
    # `s.push(h5(O)??{...})` and sits >2000 chars after the entry let
    # statement, past the old 1500-char lookback window.
    js = cli_js_synthetic("model-customizations-coalesced")
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.261"))
    assert outcome.status == "applied"
    assert "claude-sonnet-4-6" in outcome.js
    # Injection lands right after the entry let statement, before the padding.
    assert js.index("let r=grp") < outcome.js.index("claude-sonnet-4-6") < outcome.js.index("pad();")


def test_metadata():
    assert PATCH.id == "model-customizations"


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
