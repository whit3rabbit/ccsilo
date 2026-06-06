"""Remove the main prompt input border."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


_LINE = r'(?:"(?:\u2500|\\u2500)")'
_SAVE_EDITOR_TEXT = "Save and close editor"


def _hide_prompt_border_var(js: str):
    save_idx = js.find(_SAVE_EDITOR_TEXT)
    if save_idx == -1:
        return js, False
    window_start = max(0, save_idx - 2000)
    window = js[window_start:save_idx]
    matches = list(re.finditer(r",[$\w]+=[$\w]+\?\{\}:\{borderColor:", window))
    if not matches:
        return js, False
    start = window_start + matches[-1].start()
    tail = "borderLeft:!1,borderRight:!1,borderBottom:!0"
    tail_idx = js.find(tail, start, save_idx)
    if tail_idx == -1:
        return js, False
    segment = js[start:tail_idx + len(tail)]
    old = 'borderStyle:"round"'
    rel = segment.find(old)
    if rel == -1:
        return js, False
    style_start = start + rel
    return js[:style_start] + "borderStyle:undefined" + js[style_start + len(old):], True


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    new_js = js
    patched = False

    bottom = re.search(
        rf"createElement\(([$\w]+),\{{color:([$\w]+)\.bgColor\}},{_LINE}\.repeat\(([$\w]+)\)\)",
        new_js,
    )
    if bottom:
        text_component, style_var, width_var = bottom.groups()
        new_js = (
            new_js[:bottom.start()]
            + f'createElement({text_component},null,"")'
            + new_js[bottom.end():]
        )
        top_pattern = re.compile(
            rf"createElement\({re.escape(text_component)},\{{color:{re.escape(style_var)}\.bgColor\}},"
            rf"{re.escape(style_var)}\.text\?.+?{_LINE}\.repeat\({re.escape(width_var)}\)\)",
            re.DOTALL,
        )
        top = top_pattern.search(new_js)
        if top:
            new_js = (
                new_js[:top.start()]
                + f'createElement({text_component},null,"")'
                + new_js[top.end():]
            )
        patched = True

    main_input = re.search(
        r'(borderColor:[$\w]+\(\),)borderStyle:"round"'
        r'(,borderLeft:!1,borderRight:!1,borderBottom:!0,width:"100%",borderText:)',
        new_js,
    )
    if main_input:
        new_js = (
            new_js[:main_input.start()]
            + f"{main_input.group(1)}borderStyle:undefined{main_input.group(2)}"
            + new_js[main_input.end():]
        )
        patched = True

    new_js, new_main_input_patched = _hide_prompt_border_var(new_js)
    patched = patched or new_main_input_patched

    editor = re.search(
        r'borderStyle:"round"(,borderLeft:!1,borderRight:!1,borderBottom:!0,width:"100%"\}.+?Save and close editor)',
        new_js,
        re.DOTALL,
    )
    if editor:
        new_js = new_js[:editor.start()] + f"borderStyle:undefined{editor.group(1)}" + new_js[editor.end():]
        patched = True

    if not patched:
        return PatchOutcome(js=js, status="missed")
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="input-box-border",
    name="Input box border",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES + ("==2.1.167",),
    apply=_apply,
    description="Remove the rounded border around the main prompt input box.",
)
