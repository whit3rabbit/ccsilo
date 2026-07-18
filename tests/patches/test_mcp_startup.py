import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.mcp_startup import MCP_BATCH_SIZE_PATCH, MCP_NON_BLOCKING_PATCH
from tests.patches.conftest import resolve_tested_versions


def test_non_blocking_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("mcp-non-blocking")
    outcome = MCP_NON_BLOCKING_PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "if(false)" in outcome.js
    assert "MCP_CONNECTION_NONBLOCKING" not in outcome.js


def test_non_blocking_skips_when_modern_anchor_absent():
    outcome = MCP_NON_BLOCKING_PATCH.apply("no env gate", PatchContext(claude_version=None))
    assert outcome.status == "skipped"
    assert "already default" in outcome.notes[0]


def test_batch_size_synthetic_applies_default(cli_js_synthetic):
    js = cli_js_synthetic("mcp-batch-size")
    outcome = MCP_BATCH_SIZE_PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert 'MCP_SERVER_CONNECTION_BATCH_SIZE||"",10)||10' in outcome.js


def test_batch_size_synthetic_applies_config(cli_js_synthetic):
    js = cli_js_synthetic("mcp-batch-size")
    outcome = MCP_BATCH_SIZE_PATCH.apply(
        js,
        PatchContext(
            claude_version=None,
            config={"settings": {"misc": {"mcpServerBatchSize": 8}}},
        ),
    )
    assert outcome.status == "applied"
    assert 'MCP_SERVER_CONNECTION_BATCH_SIZE||"",10)||8' in outcome.js


def test_batch_size_synthetic_applies_helper_shape(cli_js_synthetic):
    # 2.1.211+ routes the env value through a minified int helper
    # (e.g. `zl(process.env.MCP_SERVER_CONNECTION_BATCH_SIZE)`) instead of
    # inline `parseInt(...||"",10)`. The ternary default is rewritten.
    js = cli_js_synthetic("mcp-batch-size-v2")
    outcome = MCP_BATCH_SIZE_PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "return e>0?e:10" in outcome.js
    assert "return e>0?e:3" not in outcome.js


def test_batch_size_synthetic_helper_shape_respects_config(cli_js_synthetic):
    js = cli_js_synthetic("mcp-batch-size-v2")
    outcome = MCP_BATCH_SIZE_PATCH.apply(
        js,
        PatchContext(
            claude_version=None,
            config={"settings": {"misc": {"mcpServerBatchSize": 7}}},
        ),
    )
    assert outcome.status == "applied"
    assert "return e>0?e:7" in outcome.js


def test_metadata():
    assert MCP_NON_BLOCKING_PATCH.id == "mcp-non-blocking"
    assert MCP_BATCH_SIZE_PATCH.id == "mcp-batch-size"
    assert MCP_NON_BLOCKING_PATCH.group == "tools"
    assert MCP_BATCH_SIZE_PATCH.group == "tools"


@pytest.mark.parametrize("version", resolve_tested_versions(MCP_NON_BLOCKING_PATCH))
def test_non_blocking_real_l1(cli_js_real, version):
    outcome = MCP_NON_BLOCKING_PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
    assert outcome.status in {"applied", "skipped"}


@pytest.mark.parametrize("version", resolve_tested_versions(MCP_BATCH_SIZE_PATCH))
def test_batch_size_real_l1(cli_js_real, version):
    outcome = MCP_BATCH_SIZE_PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
    assert outcome.status == "applied"


@pytest.mark.parametrize("version", resolve_tested_versions(MCP_BATCH_SIZE_PATCH))
def test_batch_size_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = MCP_BATCH_SIZE_PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)


@pytest.mark.parametrize("version", resolve_tested_versions(MCP_NON_BLOCKING_PATCH))
def test_non_blocking_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = MCP_NON_BLOCKING_PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
