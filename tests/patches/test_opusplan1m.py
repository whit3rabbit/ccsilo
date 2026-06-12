import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches._registry import REGISTRY
from ccsilo.patches.opusplan1m import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("opusplan1m")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert 'if((currentModel()==="opusplan"||currentModel()==="opusplan[1m]")&&mode==="plan"' in outcome.js
    assert 'currentModel()==="opusplan[1m]"' in outcome.js
    assert '"opusplan","opusplan[1m]"' in outcome.js
    assert 'if(A==="opusplan[1m]")return"Architect mode: planner model in plan mode, worker model otherwise"' in outcome.js
    assert 'if(A==="opusplan[1m]")return"Architect Mode"' in outcome.js
    assert 'value:"opusplan[1m]"' in outcome.js
    assert 'label:"Architect Mode"' in outcome.js


def test_synthetic_is_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("opusplan1m")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))
    assert twice.status == "skipped"
    assert twice.js == once.js
    assert twice.js.count('"opusplan[1m]"') == once.js.count('"opusplan[1m]"')


def test_synthetic_v2_applies_when_mode_switch_already_supports_1m(cli_js_synthetic):
    js = cli_js_synthetic("opusplan1m-v2")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert '"fable[1m]","opusplan","opusplan[1m]"' in outcome.js
    assert 'current==="opusplan[1m]"' in outcome.js
    assert 'if(A==="opusplan[1m]")return"Architect mode: planner model in plan mode, worker model otherwise"' in outcome.js
    assert 'if(A==="opusplan[1m]")return"Architect Mode"' in outcome.js
    assert 'selected==="opusplan[1m]"' in outcome.js
    assert outcome.js.count('value:"opusplan[1m]"') == 2


def test_synthetic_v3_applies_when_supported_mode_switch_uses_block(cli_js_synthetic):
    js = cli_js_synthetic("opusplan1m-v3")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert 'let plan=current==="opusplan[1m]"?oneM(opusModel()):opusModel();' in outcome.js
    assert '"fable[1m]","opusplan","opusplan[1m]"' in outcome.js
    assert 'if(A==="opusplan[1m]")return"Architect mode: planner model in plan mode, worker model otherwise"' in outcome.js
    assert 'if(A==="opusplan[1m]")return"Architect Mode"' in outcome.js
    assert 'selected==="opusplan[1m]"' in outcome.js
    assert outcome.js.count('value:"opusplan[1m]"') == 2


def test_miss_when_anchor_absent():
    outcome = PATCH.apply("function unrelated(){return null}", PatchContext(claude_version=None))
    assert outcome.status == "missed"
    assert outcome.notes


def test_metadata():
    assert PATCH.id == "opusplan1m"
    assert PATCH.name == "Architect Mode"
    assert PATCH.group == "ui"
    assert REGISTRY["opusplan1m"] is PATCH


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
