"""Tests for the no-prompt-steganography patch."""

import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches._versions import version_in_range
from ccsilo.patches.no_prompt_steganography import PATCH, _STEGO_REMOVED_RANGE
from tests.patches.conftest import resolve_tested_versions

_STEGO_SUPPORTED = ">=2.1.97,<3"


_UNCLEAN_JS = (
    'function eca(e){let t=ddp(),n=pdp(t?.known??!1,t?.labKw??!1),'
    'r=t?.cnTZ?e.replaceAll("-","/"):e;'
    'return`Today${n}s date is ${r}.`}'
)


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("no-prompt-steganography")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "ccsilo:no-prompt-steganography" in outcome.js


def test_synthetic_output_is_clean():
    outcome = PATCH.apply(_UNCLEAN_JS, PatchContext(claude_version="2.1.197"))

    assert outcome.status == "applied"
    assert "ccsilo:no-prompt-steganography" in outcome.js
    # No Unicode apostrophe variants (U+2019, U+02BC, U+02B9)
    assert "’" not in outcome.js
    assert "ʼ" not in outcome.js
    assert "ʹ" not in outcome.js
    # No date-separator flip pattern
    assert '.replaceAll("-","/")' not in outcome.js
    # Normal apostrophe preserved
    assert "Today's date is" in outcome.js


def test_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("no-prompt-steganography")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_miss_has_detail():
    outcome = PATCH.apply("function unrelated(){return null}", PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert len(outcome.notes) > 0


def test_metadata():
    assert PATCH.id == "no-prompt-steganography"
    assert PATCH.group == "prompts"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    if not version_in_range(version, _STEGO_SUPPORTED):
        pytest.skip(f"{version} predates stego introduction ({_STEGO_SUPPORTED})")

    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))

    if version_in_range(version, _STEGO_REMOVED_RANGE):
        assert outcome.status == "skipped", (
            f"stego was removed upstream in {version}, expected skip"
        )
    else:
        assert outcome.status == "applied"
        assert "ccsilo:no-prompt-steganography" in outcome.js


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    if not version_in_range(version, _STEGO_SUPPORTED):
        pytest.skip(f"{version} predates stego introduction ({_STEGO_SUPPORTED})")

    js = cli_js_real(version)

    # L2 skip: stego removed upstream, no replacement to parse-validate
    if version_in_range(version, _STEGO_REMOVED_RANGE):
        pytest.skip(
            f"stego was removed upstream in {version}; "
            "no replacement function to parse-validate"
        )

    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")

    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
