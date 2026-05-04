"""Suppress per-line line number prefixes in file-read output."""

import re

from . import Patch, PatchContext, PatchOutcome


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    already = re.search(
        r"function [$\w]+\(\{content:([$\w]+),startLine:[$\w]+\}\)\{if\(!\1\)return\"\";return \1\}",
        js,
    )
    if already:
        return PatchOutcome(js=js, status="skipped")

    # First pattern: simple split and map form
    sig = re.search(
        r"\{content:([$\w]+),startLine:[$\w]+\}\)\{if\(!\1\)return\"\";"
        r"let ([$\w]+)=\1\.split\([^)]+\);",
        js,
    )
    if sig:
        replace_start = sig.end()
        end = re.search(r"\}(?=function |var |let |const |[$\w]+=[$\w]+\()", js[replace_start:])
        if end:
            new_js = js[:replace_start] + f"return {sig.group(1)}" + js[replace_start + end.start():]
            return PatchOutcome(js=new_js, status="applied")

    # Second pattern: arrow function with line number padding
    arrow = re.search(
        r"if\(([$\w]+)\.length>=\d+\)return`\$\{\1\}(?:→|\\u2192)\$\{([$\w]+)\}`;"
        r"return`\$\{\1\.padStart\(\d+,\" \"\)\}(?:→|\\u2192)\$\{\2\}`",
        js,
    )
    if arrow:
        new_js = js[:arrow.start()] + f"return {arrow.group(2)}" + js[arrow.end():]
        return PatchOutcome(js=new_js, status="applied")

    # Third pattern: newer form with yN6() helper
    newer = re.search(
        r"(\{)content:([$\w]+),startLine:([$\w]+)\}\)\{if\(!([$\w]+)\)return\"\";let ([$\w]+)=([$\w]+)\(\),",
        js,
    )
    if newer:
        # Extract the function body and replace it with simpler return
        match_end = newer.end()
        # Find the end of the function body (the closing })
        depth = 0
        pos = match_end
        while pos < len(js):
            if js[pos] == '{':
                depth += 1
            elif js[pos] == '}':
                if depth == 0:
                    break
                depth -= 1
            pos += 1
        if pos < len(js):
            # Replace with return of the content variable
            content_var = newer.group(2)
            new_js = js[:match_end] + f"return {content_var}" + js[pos:]
            return PatchOutcome(js=new_js, status="applied")

    # Fourth pattern: indexOf loop with a dedicated line formatter helper
    indexof = re.search(
        r"function ([$\w]+)\(\{content:([$\w]+),startLine:([$\w]+)\}\)\{"
        r"if\(!\2\)return\"\";let [\s\S]{0,500}?Rqq\([\s\S]{0,250}?\.join\(`\s*`\)\}",
        js,
    )
    if indexof:
        name, content_var, start_line_var = indexof.groups()
        replacement = (
            f"function {name}({{content:{content_var},startLine:{start_line_var}}})"
            f"{{if(!{content_var})return\"\";return {content_var}}}"
        )
        new_js = js[:indexof.start()] + replacement + js[indexof.end():]
        return PatchOutcome(js=new_js, status="applied")

    return PatchOutcome(js=js, status="missed", notes=("line-number formatter",))


PATCH = Patch(
    id="suppress-line-numbers",
    name="Suppress line numbers in file reads",
    group="ui",
    versions_supported=">=2.0.0,<3",
    versions_tested=(">=2.0.20,<2.1", ">=2.1.0,<=2.1.128"),
    apply=_apply,
    description="Strip per-line line-number prefixes from file-read output.",
)
