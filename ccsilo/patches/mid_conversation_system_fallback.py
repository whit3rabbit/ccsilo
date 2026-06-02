"""Fallback when gateways reject mid-conversation system messages."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


_MARKER = "ccsilo:mid-conversation-system-422-fallback"
_FALLBACK_RE = re.compile(
    r'(function\s+[$\w]+\(([$\w]+)\)\{'
    r'(?:if\(![$\w]+\)return!1;)?'
    r'if\(!\(\2 instanceof [$\w]+\)\|\|\2\.status!==400\)return!1;'
    r'let ([$\w]+)=\2\.message;'
    r'if\(\3\.includes\([$\w]+\.header\)&&\3\.includes\("anthropic-beta"\)\)return!0;'
    r'if\(\3\.includes\("Unexpected role"\)&&\3\.includes\("input message role"\)\)return!0;)'
    r'return \3\.includes\("not supported"\)&&/role \.\{0,2\}system/i\.test\(\3\)'
    r'\}'
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _MARKER in js:
        return PatchOutcome(js=js, status="skipped")

    match = _FALLBACK_RE.search(js)
    if not match:
        return PatchOutcome(
            js=js,
            status="missed",
            notes=("missing mid-conversation system fallback predicate",),
        )

    request_var = match.group(2)
    message_var = match.group(3)
    prefix = match.group(1).replace(
        f"{request_var}.status!==400",
        f"({request_var}.status!==400&&{request_var}.status!==422)",
        1,
    )
    # Anthropic documents mid-conversation system messages as
    # messages[].role="system"; Z.ai documents Claude Code through its
    # Anthropic Messages endpoint. Some gateways still reject that newer
    # surface with HTTP 422 instead of Claude Code's expected HTTP 400.
    # Sources:
    # https://platform.claude.com/docs/en/build-with-claude/mid-conversation-system-messages
    # https://docs.z.ai/devpack/tool/others
    replacement = (
        f"{prefix}"
        f"if({request_var}.status===422&&"
        f"(({message_var}.includes(\"Input should be 'user' or 'assistant'\")&&"
        f"{message_var}.includes('\"system\"'))||"
        f"({message_var}.includes(\"literal_error\")&&"
        f"{message_var}.includes(\"role\")&&"
        f"{message_var}.includes(\"system\"))))return!0;"
        f"return {message_var}.includes(\"not supported\")&&"
        f"/role .{{0,2}}system/i.test({message_var})/*{_MARKER}*/}}"
    )
    new_js = js[:match.start()] + replacement + js[match.end():]
    if new_js == js:
        return PatchOutcome(js=js, status="skipped")
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="mid-conversation-system-422-fallback",
    name="Mid-conversation system 422 fallback",
    group="system",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    on_miss="skip",
    description=(
        "Retry with Claude Code's system-reminder fallback when an Anthropic-compatible "
        "gateway rejects mid-conversation role:\"system\" messages with HTTP 422."
    ),
)
