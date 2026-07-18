"""MCP startup optimization patches."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


def _setting(ctx: PatchContext, name: str, default):
    settings = ((ctx.config or {}).get("settings") or {}).get("misc") or {}
    snake = {
        "mcpServerBatchSize": "mcp_batch_size",
    }.get(name, name)
    return settings.get(name) or (ctx.config or {}).get(snake) or default


def _non_blocking(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(r"![$\w]+\(process\.env\.MCP_CONNECTION_NONBLOCKING\)", js)
    if not match:
        return PatchOutcome(js=js, status="skipped", notes=("MCP non-blocking is already default in this Claude Code version.",))
    new_js = js[:match.start()] + "false" + js[match.end():]
    return PatchOutcome(js=new_js, status="applied")


def _batch_size(js: str, ctx: PatchContext) -> PatchOutcome:
    match = re.search(r'MCP_SERVER_CONNECTION_BATCH_SIZE\|\|"",10\)\|\|(\d+)', js)
    batch_size = str(int(_setting(ctx, "mcpServerBatchSize", 10)))
    if match:
        new_js = js[:match.start(1)] + batch_size + js[match.end(1):]
        return PatchOutcome(js=new_js, status="applied")
    # 2.1.211+ routes the batch-size env value through a minified int helper
    # (e.g. `zl(process.env.MCP_SERVER_CONNECTION_BATCH_SIZE)`) instead of the
    # older inline `parseInt(...||"",10)`. Tolerate both radix forms and replace
    # the default after the `return <var>>0?<var>:` ternary.
    match = re.search(
        r'process\.env\.MCP_SERVER_CONNECTION_BATCH_SIZE(?:\|\|"",10)?\)\s*;\s*return\s+([$\w]+)>0\?\1:(\d+)',
        js,
    )
    if not match:
        return PatchOutcome(js=js, status="missed")
    new_js = js[:match.start(2)] + batch_size + js[match.end(2):]
    return PatchOutcome(js=new_js, status="applied")


MCP_NON_BLOCKING_PATCH = Patch(
    id="mcp-non-blocking",
    name="MCP non-blocking",
    group="tools",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_non_blocking,
    description="Avoid blocking Claude Code startup while MCP servers connect.",
)

MCP_BATCH_SIZE_PATCH = Patch(
    id="mcp-batch-size",
    name="MCP batch size",
    group="tools",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_batch_size,
    description="Raise the default MCP server startup batch size. Defaults to 10 unless configured.",
)
