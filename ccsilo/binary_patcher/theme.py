# Adapted from tweakcc 303b756 src/patches/themes.ts. See THIRD_PARTY_NOTICES.md.
import json
import re
from dataclasses import dataclass


class ThemeAnchorNotFound(Exception):
    def __init__(self, anchor):
        self.anchor = anchor
        super().__init__(f"theme: failed to find {anchor} anchor in cli.js")


def themes_from_config(config):
    """Return the themes list from a tweakcc-style config (or empty list)."""
    if config is None:
        return []
    if "settings" in config and isinstance(config["settings"], dict):
        return config["settings"].get("themes") or []
    return config.get("themes") or []


@dataclass
class ThemeResult:
    js: str
    replaced: int


@dataclass
class _Location:
    start: int
    end: int
    identifiers: list = None
    prefix: str = ""


def apply_theme(js, themes):
    themes = themes or []
    if not themes:
        return ThemeResult(js=js, replaced=0)

    locations = _find_theme_locations(js)
    new_js = js

    obj_prefix = locations["obj"].prefix or "return"
    obj_text = obj_prefix + _json({theme["id"]: theme["name"] for theme in themes})
    new_js = new_js[: locations["obj"].start] + obj_text + new_js[locations["obj"].end :]

    obj_arr_text = _json([{"label": theme["name"], "value": theme["id"]} for theme in themes])
    obj_delta = len(obj_text) - (locations["obj"].end - locations["obj"].start)
    obj_arr_start = locations["objArr"].start
    if locations["objArr"].start >= locations["obj"].end:
        obj_arr_start += obj_delta
    obj_arr_end = obj_arr_start + (locations["objArr"].end - locations["objArr"].start)
    new_js = new_js[:obj_arr_start] + obj_arr_text + new_js[obj_arr_end:]

    ident = (locations["switch"].identifiers or ["A"])[0]
    switch_parts = [f"switch({ident}){{"]
    for theme in themes:
        switch_parts.append(f'case"{theme["id"]}":return{_json(theme.get("colors", {}))};')
    switch_parts.append(f"default:return{_json(themes[0].get('colors', {}))};")
    switch_parts.append("}")
    switch_text = "\n".join(switch_parts)

    obj_arr_delta = len(obj_arr_text) - (locations["objArr"].end - locations["objArr"].start)
    original_switch_start = locations["switch"].start
    switch_start = original_switch_start
    if switch_start >= locations["obj"].end:
        switch_start += obj_delta
    if original_switch_start >= locations["objArr"].end:
        switch_start += obj_arr_delta
    switch_end = switch_start + (locations["switch"].end - locations["switch"].start)
    new_js = new_js[:switch_start] + switch_text + new_js[switch_end:]

    return ThemeResult(js=new_js, replaced=3)


def _find_theme_locations(js):
    switch_loc = _find_switch(js)
    if switch_loc is None:
        raise ThemeAnchorNotFound("switch")

    obj_arr_loc = _find_options_array(js)
    if obj_arr_loc is None:
        raise ThemeAnchorNotFound("objArr")

    obj_match = re.search(
        r'(?P<prefix>return|[$\w]+=)\{(?:"?(?:[$\w-]+)"?:"(?:Auto |Dark|Light|Monochrome)[^"]*",?)+\}',
        js,
    )
    if obj_match is None:
        raise ThemeAnchorNotFound("obj")

    return {
        "switch": switch_loc,
        "objArr": obj_arr_loc,
        "obj": _Location(obj_match.start(), obj_match.end(), prefix=obj_match.group("prefix")),
    }


def _find_options_array(js):
    obj_arr_match = re.search(
        r'\[(?:\.\.\.\[\],)?(?:\{"?label"?:"(?:Dark|Light|Auto|Monochrome)[^"]*","?value"?:"[^"]+"\},?)+\]',
        js,
    )
    if obj_arr_match is not None:
        return _Location(obj_arr_match.start(), obj_arr_match.end())

    label_match = re.search(
        r'(?P<auto>[$\w]+)=\{label:"Auto \(match terminal\)",value:"auto"\},'
        r'(?P<dark>[$\w]+)=\{label:"Dark mode",value:"dark"\},'
        r'(?P<light>[$\w]+)=\{label:"Light mode",value:"light"\}',
        js,
    )
    if label_match is None:
        return None

    auto = re.escape(label_match.group("auto"))
    dark = re.escape(label_match.group("dark"))
    light = re.escape(label_match.group("light"))
    final_arr_match = re.search(
        rf'\[{auto},{dark},{light},[^\]]*?\.\.\.[$\w]+\.map\([$\w]+\),\.\.\.[$\w]+\]',
        js[label_match.end() :],
    )
    if final_arr_match is None:
        return None

    start = label_match.end() + final_arr_match.start()
    return _Location(start, label_match.end() + final_arr_match.end())


def _find_switch(js):
    new_match = re.search(
        r'switch\(([$\w]+)\)\{case"(?:light|dark)":[^}]*return [$\w]+;[^}]*default:return [$\w]+\}',
        js,
    )
    if new_match is not None:
        return _Location(new_match.start(), new_match.end(), [new_match.group(1)])

    anchors = [index for index in (js.find('case"dark":return{'), js.find('case"light":return{')) if index != -1]
    if not anchors:
        return None
    anchor = min(anchors)
    before_start = max(0, anchor - 200)
    before = js[before_start:anchor]
    open_match = re.search(r"switch\(([$\w]+)\)\{\s*$", before)
    if open_match is None:
        return None

    switch_start = before_start + open_match.start()
    depth = 0
    for index in range(switch_start, min(len(js), switch_start + 50000)):
        if js[index] == "{":
            depth += 1
        elif js[index] == "}":
            depth -= 1
            if depth == 0:
                return _Location(switch_start, index + 1, [open_match.group(1)])
    return None


def _json(value):
    return json.dumps(value, separators=(",", ":"))


def _theme_switch_text(ident, themes):
    switch_parts = [f"switch({ident}){{"]
    for theme in themes:
        switch_parts.append(f'case"{theme["id"]}":return{_json(theme.get("colors", {}))};')
    switch_parts.append(f"default:return{_json(themes[0].get('colors', {}))};")
    switch_parts.append("}")
    return "\n".join(switch_parts)


def _injected_theme_cases(themes):
    return "".join(
        f'case"{theme["id"]}":return{_json(theme.get("colors", {}))};'
        for theme in themes
    )


def _find_resolver_switch(js):
    # 2.1.242+ theme resolver returns color-table variables per case:
    # switch(r){case"light":return D;case"light-ansi":return P;...default:return R}
    # Fallback for resolver shapes the legacy literal-switch matcher rejects.
    match = re.search(r'switch\(([$\w]+)\)\{(?=case"[$\w-]+":return [$\w]+;)', js)
    if match is None:
        return None
    open_brace = match.end() - 1
    depth = 0
    for index in range(open_brace, min(len(js), open_brace + 50000)):
        if js[index] == "{":
            depth += 1
        elif js[index] == "}":
            depth -= 1
            if depth == 0:
                return _Location(match.start(), index + 1, [match.group(1)])
    return None


def _obj_anchor(js):
    return re.search(
        r'(?P<prefix>return|[$\w]+=)\{(?:"?(?:[$\w-]+)"?:"(?:Auto |Dark|Light|Monochrome)[^"]*",?)+\}',
        js,
    )


def apply_theme_to_modules(modules, themes):
    """Apply theme injection when the three anchors may span several modules.

    Claude Code >= 2.1.242 splits the theme name map, picker options, and
    resolver switch into separate JS modules, so each anchor is located in
    whichever module holds it and replaced independently. All three anchors
    must be found or nothing is written; returns (changed_map, replaced).
    """
    themes = themes or []
    if not themes:
        return {}, 0

    obj_module = options_module = switch_module = None
    obj_match = options_loc = legacy_switch = resolver_switch = None
    for path, js in modules.items():
        if obj_module is None:
            match = _obj_anchor(js)
            if match is not None:
                obj_module, obj_match = path, match
        if options_module is None:
            loc = _find_options_array(js)
            if loc is not None:
                options_module, options_loc = path, loc
        if switch_module is None:
            legacy = _find_switch(js)
            if legacy is not None:
                switch_module, legacy_switch = path, legacy
                continue
            resolver = _find_resolver_switch(js)
            if resolver is not None:
                switch_module, resolver_switch = path, resolver

    missing = [
        name
        for name, found in (
            ("switch", switch_module),
            ("objArr", options_module),
            ("obj", obj_module),
        )
        if found is None
    ]
    if missing:
        raise ThemeAnchorNotFound(missing[0])

    changed = {}

    def module_text(path):
        return changed.get(path, modules[path])

    # Theme name map: `uu={auto:"Auto (match terminal)",...}` -> custom map.
    obj_text = (obj_match.group("prefix") or "return") + _json(
        {theme["id"]: theme["name"] for theme in themes}
    )
    js = module_text(obj_module)
    changed[obj_module] = js[: obj_match.start()] + obj_text + js[obj_match.end() :]

    # Picker options array.
    options_text = _json([{"label": theme["name"], "value": theme["id"]} for theme in themes])
    js = module_text(options_module)
    options_loc = _find_options_array(js)
    changed[options_module] = (
        js[: options_loc.start] + options_text + js[options_loc.end :]
    )

    # Resolver switch: replace legacy literal switches wholesale, or inject
    # custom cases ahead of the built-in ones for variable-return resolvers.
    js = module_text(switch_module)
    if legacy_switch is not None:
        legacy_switch = _find_switch(js)
        switch_text = _theme_switch_text((legacy_switch.identifiers or ["A"])[0], themes)
        changed[switch_module] = (
            js[: legacy_switch.start] + switch_text + js[legacy_switch.end :]
        )
    else:
        resolver_switch = _find_resolver_switch(js)
        injection = _injected_theme_cases(themes)
        open_brace = resolver_switch.start + js[resolver_switch.start :].find("{") + 1
        changed[switch_module] = js[:open_brace] + injection + js[open_brace:]

    return changed, 3
