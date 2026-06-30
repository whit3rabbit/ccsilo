"""Disable prompt steganography in the system date string.

Since ~2.1.97, Claude Code embeds a classification signal in the "Today's
date" sentence sent inside the system context.  When ANTHROPIC_BASE_URL points
to a known proxy/reseller domain or an AI-lab keyword, the apostrophe in
"Today's" is silently replaced with one of three visually-identical Unicode
variants (U+2019, U+02BC, U+02B9).  When the system timezone is China-adjacent
the date separator is flipped from "-" to "/".

This patch replaces the stego function with a clean version that always emits
a normal apostrophe and dash separator, removing the implicit fingerprint
without affecting any other system behaviour.
"""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES

_MARKER = "ccsilo:no-prompt-steganography"

# Match the stego date-construction function across rotating minified variable
# names.  Two invariant anchors make this reliable across versions:
#
#   1. .replaceAll("-","/")  -- the date-separator flip, unique to this
#      function in the bundle.
#   2. `Today${...}s date is ${...}.`  -- the template literal.
#
# Bounded lazy wildcards accommodate rotating variable names while preventing
# runaway matching across function boundaries.
_DISTILL_FUNC_RE = re.compile(
    r"function\s+([$\w]+)\(([$\w]+)\)\{"
    r"[\s\S]{0,300}?\.replaceAll\(\"-\",\"/\"\)"
    r"[\s\S]{0,100}?`Today\$\{[$\w]+\}s date is \$\{[$\w]+\}\.`"
    r"\}"
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _MARKER in js:
        return PatchOutcome(js=js, status="skipped")

    match = _DISTILL_FUNC_RE.search(js)
    if not match:
        return PatchOutcome(
            js=js,
            status="missed",
            notes=(
                "stego date function not found; "
                "the bundle may have been restructured upstream",
            ),
        )

    func_name = match.group(1)
    param = match.group(2)

    # Build a clean function that always produces the normal date string.
    # Template literal markers: Python f-string escapes {{ → {, }} → }.
    clean_func = (
        f"function {func_name}({param})"
        f"{{return`Today's date is ${{{param}}}.`/*{_MARKER}*/}}"
    )

    new_js = js[: match.start()] + clean_func + js[match.end() :]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="no-prompt-steganography",
    name="No prompt steganography",
    group="prompts",
    versions_supported=">=2.0.20,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    on_miss="warn",
    description=(
        "Remove invisible Unicode fingerprinting from the system date prompt "
        "that silently encodes API endpoint classification."
    ),
)
