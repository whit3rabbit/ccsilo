"""Register the /remember skill on versions before it was bundled.

Superseded upstream: Claude Code >=2.1.42 replaced the standalone skill with
native auto-memory (Memory tool, /memory command, automatic extraction, and
sessionMemories state by 2.1.259). No anchor to extend onto newer versions.
"""

import re

from . import Patch, PatchContext, PatchOutcome


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    registration = re.search(r'\{([$\w]+)\(\{name:"claude-in-chrome"', js)
    if not registration:
        return PatchOutcome(js=js, status="missed")
    registration_fn = registration.group(1)

    match = re.search(
        r"(function ([$\w]+)\(.{0,500}\}function [$\w]+\(\)\{)return(\}.{0,10}[, ]([$\w]+)=`# Remember Skill)",
        js,
        re.DOTALL,
    )
    if not match:
        return PatchOutcome(js=js, status="missed")
    pre, session_loader_fn, post, skill_data_var = match.group(1), match.group(2), match.group(3), match.group(4)
    insert = (
        f'{registration_fn}({{name:"remember",description:"Review session memories and update CLAUDE.local.md with learnings",'
        f'whenToUse:"When the user wants to save learnings from past sessions",userInvocable:!0,isEnabled:()=>!0,'
        f'async getPromptForCommand(A){{let content={skill_data_var};let sessionMemFiles={session_loader_fn}(null);'
        f'content+="\\n\\n## Session Memory Files to Review\\n\\n"+(sessionMemFiles.length?sessionMemFiles.join("\\n"):"None found");'
        f'if(A)content+="\\n\\n## User Arguments\\n\\n"+A;return[{{type:"text",text:content}}]}}}});'
    )
    replacement = pre + insert + "return" + post
    new_js = js[:match.start()] + replacement + js[match.end():]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="remember-skill",
    name="Remember skill",
    group="prompts",
    versions_supported=">=2.1.0,<2.1.42",
    versions_tested=(">=2.1.0,<=2.1.41",),
    apply=_apply,
    description=(
        "Register the built-in /remember skill on versions before 2.1.42. Superseded on "
        "newer versions by native auto-memory (Memory tool, /memory command, automatic "
        "extraction, sessionMemories state)."
    ),
)
