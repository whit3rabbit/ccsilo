import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.session_memory import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("session-memory")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert 'function enabled(){return true;return gate("tengu_session_memory",!1)}' in outcome.js
    assert "if(true){searchPastSessions()}" in outcome.js
    assert "Number(process.env.CC_SM_PER_SECTION_TOKENS??2000)" in outcome.js
    assert "Number(process.env.CM_SM_TOTAL_FILE_LIMIT??12000)" in outcome.js
    assert "CC_SM_MINIMUM_MESSAGE_TOKENS_TO_INIT" in outcome.js
    assert "CC_SM_MINIMUM_TOKENS_BETWEEN_UPDATE" in outcome.js
    assert "CC_SM_TOOL_CALLS_BETWEEN_UPDATES" in outcome.js


def test_new_file_memory_without_past_sessions_skips_obsolete_gate():
    js = (
        "function enabled(){if(simple())return!1;"
        "let flag=process.env.CLAUDE_CODE_DISABLE_AUTO_MEMORY;return!0}"
        'const marker="CLAUDE_COWORK_MEMORY_GUIDELINES";'
    )

    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "function enabled(){return true;if(simple())return!1;" in outcome.js
    assert "skipped obsolete past sessions gate" in outcome.notes


def test_new_file_memory_with_multiple_pre_gates_applies():
    js = (
        "function enabled(){if(one())return!1;if(two())return!1;"
        "let flag=process.env.CLAUDE_CODE_DISABLE_AUTO_MEMORY;return!0}"
        'const marker="CLAUDE_COWORK_MEMORY_GUIDELINES";'
    )

    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "function enabled(){return true;if(one())return!1;if(two())return!1;" in outcome.js
    assert "skipped obsolete past sessions gate" in outcome.notes


def test_metadata():
    assert PATCH.id == "session-memory"
    assert PATCH.group == "prompts"


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
