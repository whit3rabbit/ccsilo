import json
import shutil
import subprocess

import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.mid_conversation_system_fallback import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("mid-conversation-system-422-fallback")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "H.status!==400&&H.status!==422" in outcome.js
    assert "literal_error" in outcome.js
    assert "ccsilo:mid-conversation-system-422-fallback" in outcome.js


def test_synthetic_zai_422_rejection_falls_back(cli_js_synthetic, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; skipping runtime predicate check")

    js = cli_js_synthetic("mid-conversation-system-422-fallback")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    body = {
        "detail": [
            {
                "type": "literal_error",
                "loc": ["body", "messages", 1, "role"],
                "msg": "Input should be 'user' or 'assistant'",
                "input": "system",
            }
        ]
    }
    probe = (
        outcome.js
        + "\nconst err = new rq(" + json.dumps(json.dumps(body)) + ");"
        + "\nerr.status = 422;"
        + "\nif (!pP8(err)) process.exit(17);"
    )
    path = tmp_path / "probe.js"
    path.write_text(probe, encoding="utf-8")

    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr or result.stdout


def test_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("mid-conversation-system-422-fallback")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_miss_has_detail():
    outcome = PATCH.apply("function unrelated(){return!0}", PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert outcome.notes == ("missing mid-conversation system fallback predicate",)


def test_metadata():
    assert PATCH.id == "mid-conversation-system-422-fallback"
    assert PATCH.group == "system"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))

    assert outcome.status in {"applied", "missed"}
    if outcome.status == "applied":
        assert "ccsilo:mid-conversation-system-422-fallback" in outcome.js
    else:
        assert outcome.notes == ("missing mid-conversation system fallback predicate",)


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    if outcome.status == "applied":
        parse_js(outcome.js)
