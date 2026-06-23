"""Force-enable session memory and past-session search."""

import re

from . import Patch, PatchContext, PatchOutcome


def _is_new_file_memory_system(js: str) -> bool:
    return (
        "CLAUDE_COWORK_MEMORY_GUIDELINES" in js
        and "CLAUDE_CODE_DISABLE_AUTO_MEMORY" in js
        and "tengu_session_memory" not in js
    )


def _patch_extraction(js: str) -> str:
    match = re.search(r'function [$\w]+\(\)\{return [$\w]+\("tengu_session_memory"', js)
    if not match:
        match = re.search(
            r"function [$\w]+\(\)\{(?:if\([$\w]+\(\)\)return!1;){1,3}let [$\w]+=process\.env\.CLAUDE_CODE_DISABLE_AUTO_MEMORY;",
            js,
        )
    if not match:
        if re.search(r'function [$\w]+\(\)\{return true;return [$\w]+\("tengu_session_memory"', js):
            return js
        if re.search(
            r"function [$\w]+\(\)\{return true;(?:if\([$\w]+\(\)\)return!1;){1,3}let [$\w]+=process\.env\.CLAUDE_CODE_DISABLE_AUTO_MEMORY;",
            js,
        ):
            return js
        raise ValueError("extraction gate")
    insert_at = match.start() + match.group(0).index("{") + 1
    return js[:insert_at] + "return true;" + js[insert_at:]


def _patch_past_sessions(js: str) -> str:
    match = re.search(r'if\([$\w]+\("tengu_coral_fern",!1\)\)\{', js)
    if match:
        return js[:match.start()] + "if(true){" + js[match.end():]
    if "if(true){" in js and "tengu_coral_fern" in js:
        return js
    match = re.search(r'if\(![$\w]+\("tengu_coral_fern",!1\)\)return\s*(?:null|\[\]);', js)
    if match:
        return js[:match.start()] + js[match.end():]
    raise ValueError("past sessions gate")


def _patch_token_limits(js: str) -> str:
    match = re.search(r"(=)2000([\s\S]{0,15}?=)12000([\s\S]{0,20}# Session Title)", js)
    if not match:
        raise ValueError("token limits")
    replacement = (
        f"{match.group(1)}Number(process.env.CC_SM_PER_SECTION_TOKENS??2000)"
        f"{match.group(2)}Number(process.env.CM_SM_TOTAL_FILE_LIMIT??12000)"
        f"{match.group(3)}"
    )
    return js[:match.start()] + replacement + js[match.end():]


def _patch_update_thresholds(js: str) -> str:
    new_js = re.sub(
        r"minimumMessageTokensToInit:1e4\b",
        "minimumMessageTokensToInit:Number(process.env.CC_SM_MINIMUM_MESSAGE_TOKENS_TO_INIT??1e4)",
        js,
    )
    new_js = re.sub(
        r"minimumTokensBetweenUpdate:5000\b",
        "minimumTokensBetweenUpdate:Number(process.env.CC_SM_MINIMUM_TOKENS_BETWEEN_UPDATE??5000)",
        new_js,
    )
    new_js = re.sub(
        r"toolCallsBetweenUpdates:3\b",
        "toolCallsBetweenUpdates:Number(process.env.CC_SM_TOOL_CALLS_BETWEEN_UPDATES??3)",
        new_js,
    )
    if new_js == js:
        raise ValueError("update thresholds")
    return new_js


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    notes = []
    try:
        new_js = _patch_extraction(js)
        try:
            new_js = _patch_past_sessions(new_js)
        except ValueError as exc:
            if not _is_new_file_memory_system(new_js):
                raise
            notes.append(f"skipped obsolete {exc}")
        try:
            new_js = _patch_token_limits(new_js)
        except ValueError as exc:
            if not _is_new_file_memory_system(new_js):
                raise
            notes.append(f"skipped obsolete {exc}")
        try:
            new_js = _patch_update_thresholds(new_js)
        except ValueError as exc:
            if not _is_new_file_memory_system(new_js):
                raise
            notes.append(f"skipped obsolete {exc}")
    except ValueError as exc:
        return PatchOutcome(js=js, status="missed", notes=(f"missing {exc}",))
    if new_js == js:
        return PatchOutcome(js=js, status="skipped", notes=tuple(notes))
    return PatchOutcome(js=new_js, status="applied", notes=tuple(notes))


PATCH = Patch(
    id="session-memory",
    name="Session memory",
    group="prompts",
    versions_supported=">=2.1.0,<3",
    versions_tested=(">=2.1.0,<=2.1.187",),
    apply=_apply,
    description="Enable session memory extraction and past-session search with environment-configurable thresholds.",
)
