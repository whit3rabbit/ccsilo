import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.input_border_box import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("input-box-border")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert 'createElement(T,null,"")' in outcome.js
    assert 'borderStyle:"round"' not in outcome.js
    assert "borderStyle:undefined" in outcome.js


def test_new_prompt_border_object_shape_applies():
    js = (
        'let te={value:q},dY=Pf?{}:{borderColor:(()=>{let S_={bash:"bashBorder"};'
        'if(S_[M])return S_[M];return"promptBorder"})(),borderStyle:"round",'
        'borderLeft:!1,borderRight:!1,borderBottom:!0};'
        'if(k5)return m9.createElement(p,{flexDirection:"row",alignItems:"center",'
        'justifyContent:"center",...dY,width:"100%"},'
        'm9.createElement(N,{dimColor:!0,italic:!0},"Save and close editor to continue..."));'
        'return m9.createElement(p,{flexDirection:"row",...dY,width:"100%",borderText:se})'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.167"))
    assert outcome.status == "applied"
    assert 'borderStyle:"round"' not in outcome.js
    assert "borderStyle:undefined" in outcome.js


def test_metadata():
    assert PATCH.id == "input-box-border"
    assert PATCH.group == "ui"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
    assert outcome.status == "applied"


def test_real_l1_2_1_167(cli_js_real):
    outcome = PATCH.apply(cli_js_real("2.1.167"), PatchContext(claude_version="2.1.167"))
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
