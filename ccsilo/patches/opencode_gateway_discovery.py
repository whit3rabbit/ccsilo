"""Expose OpenCode gateway models in Claude Code's model picker."""

import re

from . import Patch, PatchContext, PatchOutcome


PATCHED_MARKER = "ccsiloOpenCodeGatewayModels"


def _already_patched(js: str) -> bool:
    return PATCHED_MARKER in js


def _find_base_url_var(js: str, filter_start: int) -> str:
    chunk = js[max(0, filter_start - 3000):filter_start]
    last = None
    # 2.1.212+ accesses env vars through a minified namespace (e.g.
    # `Z.ANTHROPIC_BASE_URL`) instead of `process.env.ANTHROPIC_BASE_URL`.
    for match in re.finditer(
        r"let\s+([$\w]+)\s*=\s*(?:process\.env|[$\w]+)\.ANTHROPIC_BASE_URL\s*;",
        chunk,
    ):
        last = match
    return last.group(1) if last else ""


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _already_patched(js):
        return PatchOutcome(js=js, status="skipped")
    if "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY" not in js:
        return PatchOutcome(js=js, status="skipped", notes=("gateway discovery unavailable",))

    pattern = re.compile(
        r"let\s+([$\w]+)\s*=\s*([$\w]+)\.data\.data\.filter"
        r"\(\s*\(?\s*([$\w]+)\s*\)?\s*=>\s*/\^\(claude\|anthropic\)/i\.test\(\3\.id\)\s*\)\s*;"
    )
    match = pattern.search(js)
    if not match:
        return PatchOutcome(js=js, status="missed", notes=("missing gateway discovery model filter",))

    model_var, parsed_var, item_var = match.group(1), match.group(2), match.group(3)
    base_var = _find_base_url_var(js, match.start())
    if not base_var:
        return PatchOutcome(js=js, status="missed", notes=("missing gateway discovery base URL",))

    replacement = (
        f"let {model_var}=(({PATCHED_MARKER})=>{{"
        f'let ccsiloOpenCodeBase={PATCHED_MARKER}.replace(/\\/+$/,""),'
        'ccsiloOpenCodeGateway=ccsiloOpenCodeBase==="https://opencode.ai/zen/go/v1"'
        '||ccsiloOpenCodeBase==="https://opencode.ai/zen/v1",'
        'ccsiloLocalModelProxy=/^http:\\/\\/(127\\.0\\.0\\.1|localhost):\\d+\\/[^/]+$/.test(ccsiloOpenCodeBase);'
        f"return ccsiloOpenCodeGateway||ccsiloLocalModelProxy?{parsed_var}.data.data.map(({item_var})=>"
        f'({{...{item_var},id:{item_var}.id,'
        f"display_name:{item_var}.display_name||{item_var}.id}})):"
        f"{parsed_var}.data.data.filter(({item_var})=>/^(claude|anthropic)/i.test({item_var}.id));"
        f"}})({base_var});"
    )
    return PatchOutcome(js=js[:match.start()] + replacement + js[match.end():], status="applied")


PATCH = Patch(
    id="opencode-gateway-discovery",
    name="OpenCode gateway discovery",
    group="ui",
    versions_supported=">=2.1.0,<3",
    versions_tested=(">=2.1.0,<=2.1.215",),
    apply=_apply,
    description="Expose raw OpenCode Go, Zen, and ccsilo local proxy /v1/models entries in Claude Code gateway model discovery.",
)
