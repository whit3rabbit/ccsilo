import json

import pytest

from cc_extractor.binary_patcher.js_patch import UnpackedManifestError, patch_unpacked_entry, resolve_entry_path
from cc_extractor.binary_patcher.bun_compat import BUN_NODE_COMPAT_MARKER
from cc_extractor.binary_patcher.prompts import OVERLAY_MARKERS
from cc_extractor.binary_patcher.theme import ThemeAnchorNotFound


THEMES = [
    {"id": "dark", "name": "Dark mode", "colors": {"bashBorder": "#fff", "autoAccept": "#0f0", "text": "#aaa"}},
    {"id": "zai-gold", "name": "Z.ai gold", "colors": {"bashBorder": "#daa", "autoAccept": "#fda", "text": "#bbb"}},
]

CONFIG = {"settings": {"themes": THEMES}}

ENTRY_BODY = "\n".join(
    [
        'function getNames(){return{"dark":"Dark mode","light":"Light mode"}}',
        'const themeOptions=[{label:"Dark mode",value:"dark"},{label:"Light mode",value:"light"}];',
        'function pickTheme(A){switch(A){case"light":return LX9;case"dark":return CX9;default:return CX9}}',
        "const explorePrompt=`...lots of text...\nComplete the user's search request efficiently and report your findings clearly.`",
    ]
)


def wrap_bun_cjs(body):
    return f"// @bun @bytecode @bun-cjs\n(function(exports, require, module, __filename, __dirname) {{{body}}})"


def setup_unpacked(tmp_path, entry_body=ENTRY_BODY, *, wrap=True, manifest_name=".bundle_manifest.json"):
    entry_rel = "src/entrypoints/cli.js"
    entry_path = tmp_path / entry_rel
    entry_path.parent.mkdir(parents=True)
    entry_path.write_text(wrap_bun_cjs(entry_body) if wrap else entry_body, encoding="latin1")
    (tmp_path / manifest_name).write_text(
        json.dumps({"entryPoint": entry_rel, "entryPointId": 0, "modules": [{"name": entry_rel, "isEntry": True}]}),
        encoding="utf-8",
    )
    return tmp_path


def test_resolve_entry_path_supports_bundle_manifest(tmp_path):
    setup_unpacked(tmp_path)

    assert resolve_entry_path(str(tmp_path)).endswith("src/entrypoints/cli.js")


def test_resolve_entry_path_supports_ts_manifest_name(tmp_path):
    setup_unpacked(tmp_path, manifest_name="manifest.json")

    assert resolve_entry_path(str(tmp_path)).endswith("src/entrypoints/cli.js")


def test_patch_unpacked_entry_strips_wrapper_applies_theme_and_writes_back(tmp_path):
    setup_unpacked(tmp_path)

    result = patch_unpacked_entry(str(tmp_path), CONFIG)

    assert result.theme_replaced == 3
    written = (tmp_path / "src/entrypoints/cli.js").read_text(encoding="latin1")
    assert not written.startswith("// @bun")
    assert not written.startswith("(function(")
    assert written.count(BUN_NODE_COMPAT_MARKER) == 1
    assert 'case"zai-gold":return{"bashBorder":"#daa"' in written


def test_patch_unpacked_entry_applies_prompt_overlay(tmp_path):
    setup_unpacked(tmp_path)

    result = patch_unpacked_entry(str(tmp_path), CONFIG, {"explore": "Z.ai routing rule: prefer search via zai-cli."})

    assert result.prompt_replaced == ["explore"]
    written = (tmp_path / "src/entrypoints/cli.js").read_text(encoding="latin1")
    assert OVERLAY_MARKERS["start"] in written
    assert "Z.ai routing rule" in written


def test_patch_unpacked_entry_replaces_existing_overlay_block(tmp_path):
    tail = "Complete the user's search request efficiently and report your findings clearly."
    seeded = ENTRY_BODY.replace(tail, f"{tail}\n\n{OVERLAY_MARKERS['start']}\nOverlay v1\n{OVERLAY_MARKERS['end']}\n")
    setup_unpacked(tmp_path, seeded)

    result = patch_unpacked_entry(str(tmp_path), CONFIG, {"explore": "Overlay v2"})

    assert result.prompt_replaced == ["explore"]
    written = (tmp_path / "src/entrypoints/cli.js").read_text(encoding="latin1")
    assert written.count(OVERLAY_MARKERS["start"]) == 1
    assert "Overlay v2" in written
    assert "Overlay v1" not in written


def test_patch_unpacked_entry_throws_theme_anchor_not_found(tmp_path):
    broken = ENTRY_BODY.replace(
        'function pickTheme(A){switch(A){case"light":return LX9;case"dark":return CX9;default:return CX9}}',
        "/* removed */",
    )
    setup_unpacked(tmp_path, broken)

    with pytest.raises(ThemeAnchorNotFound):
        patch_unpacked_entry(str(tmp_path), CONFIG)


def test_resolve_entry_path_throws_when_manifest_missing(tmp_path):
    with pytest.raises(UnpackedManifestError):
        resolve_entry_path(str(tmp_path))


@pytest.mark.parametrize("entry_name", ["../outside.js", "C:/Users/alice/evil.js"])
def test_resolve_entry_path_rejects_unsafe_manifest_paths(tmp_path, entry_name):
    (tmp_path / ".bundle_manifest.json").write_text(
        json.dumps({"entryPoint": entry_name, "entryPointId": 0, "modules": [{"name": entry_name, "isEntry": True}]}),
        encoding="utf-8",
    )

    with pytest.raises(UnpackedManifestError, match="unsafe entry module path"):
        resolve_entry_path(str(tmp_path))
