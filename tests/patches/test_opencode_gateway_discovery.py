import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches._registry import REGISTRY
from ccsilo.patches.opencode_gateway_discovery import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("opencode-gateway-discovery")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "ccsiloOpenCodeGatewayModels" in outcome.js
    assert "https://opencode.ai/zen/go/v1" in outcome.js
    assert "https://opencode.ai/zen/v1" in outcome.js
    assert "ccsiloLocalModelProxy" in outcome.js
    assert "id:j.id" in outcome.js
    assert '"opencode-go/"' not in outcome.js
    assert '"opencode/"' not in outcome.js
    assert "display_name:j.display_name||j.id" in outcome.js
    assert "filter((j)=>/^(claude|anthropic)/i.test(j.id))" in outcome.js


def test_synthetic_is_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("opencode-gateway-discovery")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_synthetic_applies_namespace_base_url(cli_js_synthetic):
    # 2.1.212+ reads env vars through a minified namespace (e.g. `Z.`)
    # instead of `process.env.`. The base-URL lookback must match both.
    js = cli_js_synthetic("opencode-gateway-discovery-v2")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "ccsiloOpenCodeGatewayModels" in outcome.js
    assert "Z.ANTHROPIC_BASE_URL" in outcome.js


def test_skips_when_gateway_discovery_unavailable():
    outcome = PATCH.apply("function old(){return null}", PatchContext(claude_version=None))

    assert outcome.status == "skipped"
    assert outcome.notes == ("gateway discovery unavailable",)


def test_miss_when_filter_anchor_absent():
    outcome = PATCH.apply(
        "process.env.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY;function unrelated(){return null}",
        PatchContext(claude_version=None),
    )

    assert outcome.status == "missed"
    assert outcome.notes


def test_metadata():
    assert PATCH.id == "opencode-gateway-discovery"
    assert PATCH.name == "OpenCode gateway discovery"
    assert PATCH.group == "ui"
    assert REGISTRY["opencode-gateway-discovery"] is PATCH


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    js = cli_js_real(version)
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    if "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY" in js:
        assert outcome.status == "applied"
        assert "ccsiloOpenCodeGatewayModels" in outcome.js
    else:
        assert outcome.status == "skipped"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
