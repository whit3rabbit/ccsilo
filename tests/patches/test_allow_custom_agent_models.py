import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.allow_custom_agent_models import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("allow-custom-agent-models")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert ",model:z.string().optional()" in outcome.js


def test_synthetic_zod_mini_applies(cli_js_synthetic):
    js = cli_js_synthetic("allow-custom-agent-models-mini")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "model:N().optional().describe(" in outcome.js
    assert "Nr([" not in outcome.js


def test_metadata():
    assert PATCH.id == "allow-custom-agent-models"
    assert PATCH.group == "ui"
    assert PATCH.versions_tested  # non-empty


@pytest.fixture
def real_js_versions():
    return resolve_tested_versions(PATCH)


def test_real_l1_anchor_matches(cli_js_real, real_js_versions):
    if not real_js_versions:
        pytest.skip("no resolved versions")
    for version in real_js_versions:
        js = cli_js_real(version)
        outcome = PATCH.apply(js, PatchContext(claude_version=version))
        assert outcome.status == "applied", (
            f"allow-custom-agent-models did not apply against {version}"
        )


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
