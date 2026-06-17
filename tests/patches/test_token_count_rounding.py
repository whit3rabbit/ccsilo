import signal

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


def test_arrow_statusline_template_applies_without_crossing_statements(parse_js):
    js = (
        'let jH=$?b:OH.current,DH=i7(S),fH=f8(DH),MH=_H,'
        'YH=K_(MH),XH=`${eH.arrowDown} ${YH} tokens`,GH=f8(XH),'
        'wH=R.kind==="thinking"?L5f(R.thinkingMs):"thinking",AH;'
        'switch(R.kind){case"thinking":AH=`${wH}${X}`;break}'
        'let D8=[...N$?[p5.createElement(B,{flexDirection:"row",key:"tokens"},'
        'p5.createElement(Z5f,{mode:H}),p5.createElement(y,{dimColor:!0},YH," tokens"))]:[]];'
    )

    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.179"))

    assert outcome.status == "applied"
    assert "YH=K_(Math.round((MH)/1000)*1000),XH=" in outcome.js
    assert "AH;switch" not in outcome.js.split("Math.round(", 1)[1].split(")*1000", 1)[0]
    parse_js(outcome.js)


@pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="requires SIGALRM")
def test_no_match_token_windows_do_not_backtrack_catastrophically():
    chunk = (
        "aa=bb("
        + ("x" * 40)
        + "),"
        + ("y" * 2100)
        + 'key:"tokens"'
        + ("z" * 220)
        + ',cc," tokens";'
    )
    js = chunk * 120

    class Timeout(BaseException):
        pass

    def fail_on_alarm(_signum, _frame):
        raise Timeout()

    previous_handler = signal.signal(signal.SIGALRM, fail_on_alarm)
    signal.setitimer(signal.ITIMER_REAL, 3)
    try:
        outcome = PATCH.apply(js, PatchContext(claude_version="2.1.179"))
    except Timeout:
        pytest.fail("token-count-rounding did not finish on a bounded no-match input")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert outcome.status == "missed"


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
