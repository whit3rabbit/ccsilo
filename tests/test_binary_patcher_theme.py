import json

import pytest

from ccsilo.binary_patcher.index import PatchInputs, apply_patches as apply_binary_patches
from ccsilo.bun_extract import parse_bun_binary
from ccsilo.binary_patcher.theme import ThemeAnchorNotFound, apply_theme, themes_from_config
from ccsilo.providers import provider_patch_config
from tests.helpers.bun_fixture import build_bun_fixture


THEMES = [
    {"id": "dark", "name": "Dark mode", "colors": {"bashBorder": "#fff", "autoAccept": "#0f0", "text": "#aaa"}},
    {"id": "zai-gold", "name": "Z.ai gold", "colors": {"bashBorder": "#daa", "autoAccept": "#fda", "text": "#bbb"}},
]

NEW_FORMAT_FIXTURE = "\n".join(
    [
        'function getNames(){return{"dark":"Dark mode","light":"Light mode","zaiGold":"Auto Z.ai gold"}}',
        'const themeOptions=[{label:"Dark mode",value:"dark"},{label:"Light mode",value:"light"}];',
        'function pickTheme(A){switch(A){case"light":return LX9;case"dark":return CX9;default:return CX9}}',
    ]
)

MEMOIZED_OPTIONS_FIXTURE = "\n".join(
    [
        'function getNames(){Ct5={auto:"Auto (match terminal)",dark:"Dark mode",light:"Light mode","dark-daltonized":"Dark mode (colorblind-friendly)","light-daltonized":"Light mode (colorblind-friendly)","dark-ansi":"Dark mode (ANSI colors only)","light-ansi":"Light mode (ANSI colors only)"}}',
        'function picker(){let r,e,JH,$H,s,o,HH;if(cache)r={label:"Auto (match terminal)",value:"auto"},e={label:"Dark mode",value:"dark"},JH={label:"Light mode",value:"light"},$H={label:"Dark mode (colorblind-friendly)",value:"dark-daltonized"},s={label:"Light mode (colorblind-friendly)",value:"light-daltonized"},o={label:"Dark mode (ANSI colors only)",value:"dark-ansi"},HH={label:"Light mode (ANSI colors only)",value:"light-ansi"};let NH=Y?[{label:"New custom theme\\u2026",value:jk8}]:[],_H=[r,e,JH,$H,s,o,HH,...p.map(es5),...NH]}',
        'function pickTheme(A){switch(A){case"light":return LX9;case"light-ansi":return AX9;case"dark-ansi":return BX9;case"light-daltonized":return DX9;case"dark-daltonized":return EX9;default:return CX9}}',
    ]
)

OLD_FORMAT_FIXTURE = "\n".join(
    [
        'function getNames(){return{"dark":"Dark mode","light":"Light mode"}}',
        'const themeOptions=[{label:"Dark mode",value:"dark"},{label:"Light mode",value:"light"}];',
        'function pickTheme(A){switch(A){case"dark":return{"autoAccept":"#0f0","bashBorder":"#fff","text":"#aaa"};default:return{"autoAccept":"#0f0","bashBorder":"#fff","text":"#aaa"}}}',
    ]
)


def test_apply_theme_rewrites_new_format_bundle():
    result = apply_theme(NEW_FORMAT_FIXTURE, THEMES)

    assert result.replaced == 3
    assert 'case"dark":return{"bashBorder":"#fff"' in result.js
    assert 'case"zai-gold":return{"bashBorder":"#daa"' in result.js
    assert '[{"label":"Dark mode","value":"dark"},{"label":"Z.ai gold","value":"zai-gold"}]' in result.js
    assert 'return{"dark":"Dark mode","zai-gold":"Z.ai gold"}' in result.js


def test_apply_theme_rewrites_memoized_object_options_bundle():
    result = apply_theme(MEMOIZED_OPTIONS_FIXTURE, THEMES)

    assert result.replaced == 3
    assert 'case"zai-gold":return{"bashBorder":"#daa"' in result.js
    assert '_H=[{"label":"Dark mode","value":"dark"},{"label":"Z.ai gold","value":"zai-gold"}]' in result.js
    assert 'Ct5={"dark":"Dark mode","zai-gold":"Z.ai gold"}' in result.js
    assert 'function getNames(){return{"dark":"Dark mode","zai-gold":"Z.ai gold"}' not in result.js


def test_apply_theme_keeps_provider_theme_tables_in_sync():
    themes = themes_from_config(provider_patch_config("zai"))
    result = apply_theme(MEMOIZED_OPTIONS_FIXTURE, themes)
    name_table = result.js.split("function picker()", 1)[0]

    assert themes
    for theme in themes:
        theme_id = json.dumps(theme["id"])
        theme_name = json.dumps(theme["name"])
        assert f"{theme_id}:{theme_name}" in name_table
        assert f'"value":{theme_id}' in result.js
        assert f"case{theme_id}:return" in result.js


def test_apply_theme_rewrites_old_format_bundle():
    result = apply_theme(OLD_FORMAT_FIXTURE, THEMES)

    assert result.replaced == 3
    assert 'case"zai-gold":return{"bashBorder":"#daa"' in result.js


def test_apply_theme_noop_for_empty_theme_list():
    result = apply_theme(NEW_FORMAT_FIXTURE, [])

    assert result.replaced == 0
    assert result.js == NEW_FORMAT_FIXTURE


@pytest.mark.parametrize(
    ("broken", "anchor"),
    [
        (NEW_FORMAT_FIXTURE.replace('function pickTheme(A){switch(A){case"light":return LX9;case"dark":return CX9;default:return CX9}}', "/* removed */"), "switch"),
        (NEW_FORMAT_FIXTURE.replace('const themeOptions=[{label:"Dark mode",value:"dark"},{label:"Light mode",value:"light"}];', "/* removed */"), "objArr"),
        (NEW_FORMAT_FIXTURE.replace('function getNames(){return{"dark":"Dark mode","light":"Light mode","zaiGold":"Auto Z.ai gold"}}', "/* removed */"), "obj"),
    ],
)
def test_apply_theme_throws_anchor_not_found(broken, anchor):
    with pytest.raises(ThemeAnchorNotFound) as exc:
        apply_theme(broken, THEMES)

    assert exc.value.anchor == anchor


def test_binary_patcher_applies_native_startup_hide_tweaks(tmp_path):
    js = "\n".join(
        [
            ',R.createElement(B,{isBeforeFirstMessage:!1}),',
            'function banner(){return"Welcome to Claude Code"}',
            'function inner(){return"\\u259B\\u2588\\u2588\\u2588\\u259C"}function wrapper(){return R.createElement(inner,{})}',
        ]
    )
    fixture = build_bun_fixture(
        platform="macho",
        module_struct_size=52,
        modules=[{"name": "src/cli.js", "content": js}],
        entry_point_id=0,
    )
    binary = tmp_path / "claude"
    binary.write_bytes(fixture["buf"])

    result = apply_binary_patches(
        PatchInputs(
            binary_path=str(binary),
            config={},
            regex_tweaks=["hide-startup-banner", "hide-startup-clawd"],
            provider_label="Zai Cloud",
        )
    )

    assert result.ok is True
    assert result.curated_applied == ["hide-startup-banner", "hide-startup-clawd"]
    data = binary.read_bytes()
    info = parse_bun_binary(data)
    entry = info.modules[info.entry_point_id]
    entry_js = data[info.data_start + entry.cont_off : info.data_start + entry.cont_off + entry.cont_len].decode("utf-8")
    assert "isBeforeFirstMessage" not in entry_js
    assert "return null;" in entry_js


def test_binary_patcher_rejects_unsupported_native_regex_tweak(tmp_path):
    fixture = build_bun_fixture(
        platform="macho",
        module_struct_size=52,
        modules=[{"name": "src/cli.js", "content": "const version='x';"}],
        entry_point_id=0,
    )
    binary = tmp_path / "claude"
    binary.write_bytes(fixture["buf"])

    result = apply_binary_patches(
        PatchInputs(
            binary_path=str(binary),
            config={},
            regex_tweaks=["patches-applied-indication"],
        )
    )

    assert result.ok is False
    assert result.reason == "tweak-failed"
    assert "unsupported native regex tweak" in result.detail
