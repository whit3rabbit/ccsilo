import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.thinking_visibility import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("thinking-visibility")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "return null" not in outcome.js
    assert "isTranscriptMode:true," in outcome.js


def test_synthetic_applies_braced_gate():
    # 2.1.203 minifier emits `if(C){return null}` (braces, no semicolon)
    # instead of the older `if(C)return null;`. Both gates must anchor.
    js = (
        'case"thinking":{if(!lit&&!OY){return null}'
        'let TU;if(rkt[0]!==n)TU=Kd.jsx(ker,{addMargin:n,param:r,'
        'isTranscriptMode:lit,verbose:OY})}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "return null" not in outcome.js
    assert "isTranscriptMode:true," in outcome.js


def test_metadata():
    assert PATCH.id == "thinking-visibility"
    assert PATCH.group == "thinking"


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
