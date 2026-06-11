import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.suppress_model_launch_notice import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_opus47_applies(cli_js_synthetic):
    js = cli_js_synthetic("suppress-model-launch-notice")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "opus47LaunchSeenCount" not in outcome.js
    assert "ccsilo:suppress-model-launch-notice" in outcome.js


def test_synthetic_opus48_applies(cli_js_synthetic):
    js = cli_js_synthetic("suppress-model-launch-notice-v2")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "opus48LaunchSeenCount" not in outcome.js
    assert "ccsilo:suppress-model-launch-notice" in outcome.js


def test_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("suppress-model-launch-notice")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_miss_has_detail():
    outcome = PATCH.apply("function unrelated(){return!0}", PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert outcome.notes == ("missing Opus 4.7/4.8 launch eligibility gate",)


def test_legacy_counter_cleanup_without_notice_skips():
    js = (
        "function clean(H){"
        "if(H.opus1mMergeNoticeSeenCount===void 0&&H.voiceNoticeSeenCount===void 0"
        "&&H.opus47LaunchSeenCount===void 0&&H.opus48LaunchSeenCount===void 0)return H;"
        "let{opus1mMergeNoticeSeenCount:q,voiceNoticeSeenCount:K,"
        "opus47LaunchSeenCount:_,opus48LaunchSeenCount:f,...A}=H;return A}"
        "const defaults={unpinOpus47LaunchEffort:!1,unpinOpus48LaunchEffort:!1,unpinFable5LaunchEffort:!1}"
    )

    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "skipped"
    assert outcome.notes == ("model launch notice already absent",)


def test_metadata():
    assert PATCH.id == "suppress-model-launch-notice"
    assert PATCH.group == "ui"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))

    assert outcome.status == "applied"
    assert "ccsilo:suppress-model-launch-notice" in outcome.js


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
