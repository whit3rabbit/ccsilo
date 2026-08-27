"""Filter terminal escape sequences that trigger unwanted scrolling."""

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


_MARKER = "SCROLLING FIX PATCH START"

_FILTER_CODE = """// SCROLLING FIX PATCH START
const _origStdoutWrite=process.stdout.write;
process.stdout.write=function(chunk,encoding,cb){
if(typeof chunk!=='string'){
return _origStdoutWrite.call(process.stdout,chunk,encoding,cb);
}
const filtered=chunk
.replace(/\\x1b\\[\\d*S/g,'')
.replace(/\\x1b\\[\\d*T/g,'')
.replace(/\\x1b\\[\\d*;?\\d*r/g,'');
return _origStdoutWrite.call(process.stdout,filtered,encoding,cb);
};
// SCROLLING FIX PATCH END
"""


def _insertion_index(js: str) -> int:
    bun_cjs = js.find("@bun-cjs")
    if bun_cjs != -1:
        line_end = js.find("\n", bun_cjs)
        function_start = js.find("(function", line_end if line_end != -1 else bun_cjs)
        open_brace = js.find("{", function_start)
        if function_start != -1 and open_brace != -1 and open_brace - function_start < 256:
            return open_brace + 1

    lines = js.splitlines(keepends=True)
    index = 0
    for line in lines:
        stripped = line.strip()
        if line.startswith("#!"):
            index += len(line)
            continue
        if line.startswith("//") and ("Version" in line or "(c)" in line):
            index += len(line)
            continue
        if stripped == "" and index < 5:
            index += len(line)
            continue
        break
    return index


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _MARKER in js:
        return PatchOutcome(js=js, status="skipped")
    index = _insertion_index(js)
    new_js = js[:index] + _FILTER_CODE + js[index:]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="filter-scroll-escape-sequences",
    name="Filter scroll escape sequences",
    group="system",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    description="Filter stdout escape sequences that set/reset scroll regions or scroll terminal content.",
    module_scope="entry",
)
