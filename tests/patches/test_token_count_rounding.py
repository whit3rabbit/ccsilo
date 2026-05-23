import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.token_count_rounding import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies_default(cli_js_synthetic):
    js = cli_js_synthetic("token-count-rounding")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "Math.round((inputTokens+outputTokens)/1000)*1000" in outcome.js


def test_synthetic_applies_config(cli_js_synthetic):
    js = cli_js_synthetic("token-count-rounding")
    outcome = PATCH.apply(
        js,
        PatchContext(
            claude_version=None,
            config={"settings": {"misc": {"tokenCountRounding": 50}}},
        ),
    )
    assert outcome.status == "applied"
    assert "Math.round((inputTokens+outputTokens)/50)*50" in outcome.js


def test_statusline_template_applies_without_crossing_statements(parse_js):
    js = (
        'let ZH=L&&!L.isIdle?L.progress?.tokenCount??0:OH+X,'
        'RH=D9(ZH),hH=J?`${RH} tokens`:`${$$.arrowDown} ${RH} tokens`,'
        'UH=D8(hH),Y$=sr.useRef(0),QH=Z&&V!==null?Math.max(Y$.current,Wg7(C-V)):null;'
    )

    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.149"))

    assert outcome.status == "applied"
    assert "RH=D9(Math.round((ZH)/1000)*1000),hH=" in outcome.js
    assert "Y$=sr.useRef(0)/1000" not in outcome.js
    parse_js(outcome.js)


def test_metadata():
    assert PATCH.id == "token-count-rounding"
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
