"""Add Architect Mode model alias support."""

import re

from . import Patch, PatchContext, PatchOutcome


def _replace_first(js: str, pattern: str, replacement_fn) -> str:
    match = re.search(pattern, js)
    if not match:
        raise ValueError(pattern)
    replacement = replacement_fn(match)
    return js[:match.start()] + replacement + js[match.end():]


def _patch_mode_switch(js: str) -> str:
    if _mode_switch_has_1m(js):
        return js
    return _replace_first(
        js,
        r'if\s*\(\s*([$\w]+)\(\)\s*===\s*"opusplan"\s*&&\s*([$\w]+)\s*===\s*"plan"\s*&&\s*!([$\w]+)\s*\)\s*return\s*([$\w]+)\(\);',
        lambda m: f'if(({m.group(1)}()==="opusplan"||{m.group(1)}()==="opusplan[1m]")&&{m.group(2)}==="plan"&&!{m.group(3)})return {m.group(4)}();',
    )


def _patch_alias_list(js: str) -> str:
    return _replace_first(
        js,
        r'(\["sonnet","opus","haiku"(?:,"fable")?(?:,"best")?,"sonnet\[1m\]"(?:,"opus\[1m\]")?(?:,"fable\[1m\]")?,"opusplan")(?=\])',
        lambda m: m.group(0) + ',"opusplan[1m]"',
    )


def _patch_description(js: str) -> str:
    return _replace_first(
        js,
        r'(if\s*\(\s*([$\w]+)\s*===\s*"opusplan"\s*\)\s*return\s*"Opus((?: [^"]{0,20})?) in plan mode, else Sonnet((?: [^"]{0,20})?)";)',
        lambda m: (
            m.group(1)
            + f'if({m.group(2)}==="opusplan[1m]")return"Architect mode: planner model in plan mode, worker model otherwise";'
        ),
    )


def _patch_label(js: str) -> str:
    return _replace_first(
        js,
        r'(if\s*\(\s*([$\w]+)\s*===\s*"opusplan"\s*\)\s*return\s*"Opus Plan";)',
        lambda m: m.group(1) + f'if({m.group(2)}==="opusplan[1m]")return"Architect Mode";',
    )


def _patch_selector_options(js: str) -> str:
    match = re.search(
        r'((?<!else )if\s*\(\s*([$\w]+)\s*===\s*"opusplan"\s*\)\s*return\s*(?:[$\w]+\()?\[\s*\.\.\.([$\w]+)\s*,\s*([$\w]+)\(\)\s*\]\)?;)',
        js,
    )
    if not match:
        return _patch_selected_option_fallback(js)
    full_match, var_name, list_var = match.group(1), match.group(2), match.group(3)
    wrapper = re.search(rf"return\s*([$\w]+)\(\s*\[\.\.\.{re.escape(list_var)}", full_match)
    new_entry = '{value:"opusplan[1m]",label:"Architect Mode",description:"Use planner model in plan mode, worker model otherwise"}'
    return_expr = f"{wrapper.group(1)}([...{list_var},{new_entry}])" if wrapper else f"[...{list_var},{new_entry}]"
    replacement = full_match + f'if({var_name}==="opusplan[1m]")return {return_expr};'
    return js[:match.start()] + replacement + js[match.end():]


def _patch_selected_option_fallback(js: str) -> str:
    # 2.1.227+ passes extra arguments to the option-list wrapper
    # (`return W([...opts,factory()],ctx);`), so tolerate and replay any
    # trailing identifier arguments instead of assuming a single argument.
    match = re.search(
        r'(else if\(([$\w]+)==="opusplan"\)return ([$\w]+)\(\[\.\.\.([$\w]+),([$\w]+)\(\)\]((?:,[$\w]+)*)\);)',
        js,
    )
    if not match:
        raise ValueError("selector options")
    full_match, var_name, wrapper, list_var = match.group(1), match.group(2), match.group(3), match.group(4)
    extra_args = match.group(6)
    new_entry = '{value:"opusplan[1m]",label:"Architect Mode",description:"Use planner model in plan mode, worker model otherwise"}'
    replacement = full_match + (
        f'else if({var_name}==="opusplan[1m]")return {wrapper}([...{list_var},{new_entry}]{extra_args});'
    )
    return js[:match.start()] + replacement + js[match.end():]


def _patch_always_show(js: str) -> str:
    match = re.search(
        # The wrapper call gained trailing arguments in 2.1.227
        # (`return W(opts,ctx);`); only the match start is used, so the regex
        # just has to keep recognizing the guard.
        r'(if\s*\(\s*[$\w]+\s*===\s*null\s*\|\|\s*([$\w]+)\.some\s*\(\s*\(\s*[$\w]+\s*\)\s*=>\s*[$\w]+\.value\s*===\s*[$\w]+\s*\)\s*\)'
        r'\s*return\s*(?:[$\w]+\()?[$\w]+(?:\s*,\s*[$\w]+)*\)?\s*;)',
        js,
    )
    if not match:
        raise ValueError("always show")
    list_var = match.group(2)
    inject = (
        f'{list_var}.push({{value:"opusplan",label:"Architect Mode",description:"Use planner model in plan mode, worker model otherwise"}});'
        f'{list_var}.push({{value:"opusplan[1m]",label:"Architect Mode",description:"Use planner model in plan mode, worker model otherwise"}});'
    )
    return js[:match.start()] + inject + js[match.start():]


def _mode_switch_has_1m(js: str) -> bool:
    return bool(
        re.search(
            r'if\s*\(\s*\(\s*([$\w]+)\(\)\s*===\s*"opusplan"\s*\|\|\s*\1\(\)\s*===\s*"opusplan\[1m\]"\s*\)'
            r'\s*&&\s*[$\w]+\s*===\s*"plan"\s*&&\s*![$\w]+\s*\)\s*return\s*[$\w]+\(\);',
            js,
        )
        or re.search(
            r'if\s*\(\s*\(\s*([$\w]+)\s*===\s*"opusplan"\s*\|\|\s*\1\s*===\s*"opusplan\[1m\]"\s*\)'
            r'\s*&&\s*[$\w]+\s*===\s*"plan"\s*&&\s*![$\w]+\s*\)\s*return',
            js,
        )
        or re.search(
            r'if\s*\(\s*\(\s*([$\w]+)\s*===\s*"opusplan"\s*\|\|\s*\1\s*===\s*"opusplan\[1m\]"\s*\)'
            r'\s*&&\s*[$\w]+\s*===\s*"plan"\s*&&\s*![$\w]+\s*\)\s*\{(?=[\s\S]{0,1200}?return)',
            js,
        )
    )


def _already_patched(js: str) -> bool:
    return bool(
        _mode_switch_has_1m(js)
        and re.search(r'"opusplan"\s*,\s*"opusplan\[1m\]"', js)
        and '==="opusplan[1m]")return"Architect Mode"' in js
        and 'value:"opusplan[1m]"' in js
    )


def _native_1m_support(js: str) -> bool:
    # 2.1.242+ ships the [1m] opusplan gate natively, e.g.
    # if((o==="opusplan"||o==="opusplan[1m]")&&t==="plan"&&!r){...}
    return bool(
        re.search(
            r'\(\s*[$\w]+\s*===\s*"opusplan"\s*\|\|\s*[$\w]+\s*===\s*"opusplan\[1m\]"\s*\)'
            r'\s*&&\s*[$\w]+\s*===\s*"plan"',
            js,
        )
    )


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _already_patched(js):
        return PatchOutcome(js=js, status="skipped")
    # 2.1.242+ ships the [1m] gate natively and reshaped the selector UI, so
    # when the gate is already present the selector-shape pieces are optional;
    # first-time patching still requires every anchor.
    gate_present = _mode_switch_has_1m(js) or _native_1m_support(js)
    notes = []
    try:
        if gate_present:
            new_js = js
        else:
            new_js = _patch_mode_switch(js)
        new_js = _patch_alias_list(new_js)
        for fn, label in (
            (_patch_description, "description"),
            (_patch_label, "label"),
            (_patch_selector_options, "selector options"),
            (_patch_always_show, "always show"),
        ):
            try:
                new_js = fn(new_js)
            except ValueError:
                if not gate_present:
                    raise
                notes.append(f"skipped native-era {label}")
    except ValueError as exc:
        return PatchOutcome(js=js, status="missed", notes=(f"missing {exc}",))
    if new_js == js:
        return PatchOutcome(js=js, status="skipped", notes=tuple(notes))
    return PatchOutcome(js=new_js, status="applied", notes=tuple(notes))


def _apply_modules(modules, ctx: PatchContext):
    """Cross-module application for split bundles (Claude Code >= 2.1.242).

    The mode switch, alias list, and selector pieces moved into separate
    modules, and 2.1.242+ ships the [1m] gate natively, so each piece is
    applied wherever it anchors; a natively-present gate satisfies the mode
    switch piece. Selector-shape pieces that no longer anchor anywhere are
    acceptable only when the runtime gate is native.
    """
    from . import ModuleSetOutcome

    if any(_already_patched(js) for js in modules.values()):
        return ModuleSetOutcome(js_by_path={}, status="skipped")

    working = dict(modules)
    changed = {}
    notes = []
    applied_any = False

    def apply_piece(fn, label, required=True):
        nonlocal applied_any
        for path in list(working):
            try:
                working[path] = fn(working[path])
            except ValueError:
                continue
            changed[path] = working[path]
            applied_any = True
            return True
        if required:
            notes.append(f"missing {label}")
        return False

    native = any(
        _mode_switch_has_1m(js) or _native_1m_support(js)
        for js in working.values()
    )
    if not native:
        if not apply_piece(_patch_mode_switch, "mode switch"):
            return ModuleSetOutcome(js_by_path={}, status="missed", notes=tuple(notes))

    apply_piece(_patch_alias_list, "alias list", required=False)
    apply_piece(_patch_description, "description", required=False)
    apply_piece(_patch_label, "label", required=False)
    apply_piece(_patch_selector_options, "selector options", required=False)
    apply_piece(_patch_always_show, "always show", required=False)

    if not applied_any:
        # Native gate and no piece anchors anymore: nothing left to do.
        if native:
            return ModuleSetOutcome(js_by_path={}, status="skipped", notes=tuple(notes))
        return ModuleSetOutcome(js_by_path={}, status="missed", notes=tuple(notes))
    return ModuleSetOutcome(js_by_path=changed, status="applied", notes=tuple(notes))


PATCH = Patch(
    id="opusplan1m",
    name="Architect Mode",
    group="ui",
    versions_supported=">=2.1.0,<3",
    # 2.1.196-2.1.226 were never proven for this patch; 2.1.227+ is covered
    # after the selector-wrapper argument fix.
    versions_tested=(">=2.1.0,<=2.1.195", ">=2.1.227,<=2.1.247"),
    apply=_apply,
    apply_modules=_apply_modules,
    description=(
        "Add an Architect Mode model alias that uses a planner model in plan mode and a worker model otherwise. "
        "This alias can use normal setup auth; it does not start the setup-local OAuth architect proxy."
    ),
)
