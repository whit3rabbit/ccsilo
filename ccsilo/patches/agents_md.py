"""Support AGENTS.md and other CLAUDE.md alternative filenames."""

import json
import re
from typing import Optional

from . import Patch, PatchContext, PatchOutcome


DEFAULT_ALT_NAMES = [
    "AGENTS.md",
    "GEMINI.md",
    "CRUSH.md",
    "QWEN.md",
    "IFLOW.md",
    "WARP.md",
    "copilot-instructions.md",
]


def _alt_names(ctx: PatchContext):
    settings = (ctx.config or {}).get("settings") or {}
    return settings.get("claudeMdAltNames") or (ctx.config or {}).get("claude_md_alt_names") or DEFAULT_ALT_NAMES


def _apply_async(js: str, alt_names) -> str:
    pattern = re.compile(
        r'(async function ([$\w]+)\(([$\w]+),([$\w]+),([$\w]+))\)\{try\{let ([$\w]+)=await ([$\w]+)\(\)\.readFile\(\3,\{encoding:"utf-8"\}\);'
        r'return ([$\w]+)\(\6,\3,\4,\5\)\}catch\(([$\w]+)\)\{return ([$\w]+)\(\9,\3\),\{info:null,includePaths:\[\]\}\}\}',
        re.DOTALL,
    )
    match = pattern.search(js)
    if not match:
        raise ValueError("async reader")
    func_sig, func_name, path_param, type_param, third_param = match.group(1), match.group(2), match.group(3), match.group(4), match.group(5)
    read_var, fs_getter, processor_func = match.group(6), match.group(7), match.group(8)
    catch_var, error_handler = match.group(9), match.group(10)
    alt_json = json.dumps(alt_names, separators=(",", ":"))
    replacement = (
        f"{func_sig},didReroute){{try{{let {read_var}=await {fs_getter}().readFile({path_param},{{encoding:\"utf-8\"}});"
        f"return {processor_func}({read_var},{path_param},{type_param},{third_param})}}catch({catch_var}){{{error_handler}({catch_var},{path_param});"
        f"if(!didReroute&&({path_param}.endsWith(\"/CLAUDE.md\")||{path_param}.endsWith(\"\\\\CLAUDE.md\"))){{"
        f"for(let alt of {alt_json}){{let altPath={path_param}.slice(0,-9)+alt;"
        f"try{{let r=await {func_name}(altPath,{type_param},{third_param},true);if(r.info)return r}}catch{{}}}}}}"
        f"return{{info:null,includePaths:[]}}}}}}"
    )
    return js[:match.start()] + replacement + js[match.end():]


def _apply_sync(js: str, alt_names) -> str:
    pattern = re.compile(r"(function ([$\w]+)\(([$\w]+),([^)]+?))\)(?:.|\n){0,500}Skipping non-text file in @include")
    match = pattern.search(js)
    if not match:
        raise ValueError("sync reader")
    up_to_params, function_name, first_param, rest_params = match.group(1), match.group(2), match.group(3), match.group(4)
    func_start = match.start()
    fs_match = re.search(r"([$\w]+(?:\(\))?)\.(?:readFileSync|existsSync|statSync)", match.group(0))
    if not fs_match:
        caller = js[max(0, func_start - 5000):func_start]
        fs_match = re.search(r"([$\w]+(?:\(\))?)\.(?:readFileSync|existsSync|statSync)", caller)
    if not fs_match:
        raise ValueError("fs expression")
    fs_expr = fs_match.group(1)
    alt_json = json.dumps(alt_names, separators=(",", ":"))
    sig_index = func_start + len(up_to_params)
    new_js = js[:sig_index] + ",didReroute" + js[sig_index:]
    func_body = new_js[func_start:]
    old_early = re.search(r"\.isFile\(\)\)return null", func_body)
    new_early = re.search(r'==="EISDIR"\)return null', func_body)
    early = old_early or new_early
    if not early:
        raise ValueError("early return")
    fallback = (
        f"if(!didReroute&&({first_param}.endsWith(\"/CLAUDE.md\")||{first_param}.endsWith(\"\\\\CLAUDE.md\"))){{"
        f"for(let alt of {alt_json}){{let altPath={first_param}.slice(0,-9)+alt;"
        f"if({fs_expr}.existsSync(altPath)&&{fs_expr}.statSync(altPath).isFile())return {function_name}(altPath,{rest_params},true);}}}}"
    )
    replacement = f'==="EISDIR"){{{fallback}return null;}}' if new_early else f'.isFile()){{{fallback}return null;}}'
    start = func_start + early.start()
    return new_js[:start] + replacement + new_js[start + len(early.group(0)):]


def _apply_async_qn(js: str, alt_names) -> str:
    """Match async readers using qN (2.1.196+), which use a helper for stat+read.

    Pattern: async function NAME(A,B,C){try{let X=Y(),Z=await qN(X,A,...);if(Z===null)return...;return PROC(Z,A,B,C)}catch(E){return HANDLER(E,A),{info:null,includePaths:[]}}}
    """
    pattern = re.compile(
        r'(async function ([$\w]+)\(([$\w]+),([$\w]+),([$\w]+))\)\{try\{'
        r'let ([$\w]+)=([$\w]+)\(\),'
        r'([$\w]+)=await qN\(\6,\3,'
        r'[^;]+;if\(\8===null\)return[^;]+;'
        r'return ([$\w]+)\(\8,\3,\4,\5\)\}'
        r'catch\(([$\w]+)\)\{return ([$\w]+)\(\10,\3\),\{info:null,includePaths:\[\]\}\}',
        re.DOTALL,
    )
    match = pattern.search(js)
    if not match:
        raise ValueError("async reader (qN)")
    func_sig, func_name = match.group(1), match.group(2)
    path_param, type_param, third_param = match.group(3), match.group(4), match.group(5)
    getter_var, getter_func = match.group(6), match.group(7)
    content_var, processor_func = match.group(8), match.group(9)
    catch_var, error_handler = match.group(10), match.group(11)
    alt_json = json.dumps(alt_names, separators=(",", ":"))
    replacement = (
        f"{func_sig},didReroute){{try{{let {getter_var}={getter_func}(),"
        f"{content_var}=await qN({getter_var},{path_param},Gao);"
        f"if({content_var}===null){{"
        f"if(!didReroute&&({path_param}.endsWith(\"/CLAUDE.md\")||{path_param}.endsWith(\"\\\\CLAUDE.md\"))){{"
        f"for(let alt of {alt_json}){{let altPath={path_param}.slice(0,-9)+alt;"
        f"try{{let r=await {func_name}(altPath,{type_param},{third_param},true);if(r.info)return r}}catch{{}}}}}}"
        f"return C(`[CLAUDE.md] skipping ${{{path_param}}}: not a regular file or exceeds ${{Gao}} byte limit`),{{info:null,includePaths:[]}}}}"
        f"return {processor_func}({content_var},{path_param},{type_param},{third_param})"
        f"}}catch({catch_var}){{{error_handler}({catch_var},{path_param});"
        f"return{{info:null,includePaths:[]}}}}"
    )
    return js[:match.start()] + replacement + js[match.end():]


def _apply_async_wn(js: str, alt_names) -> str:
    """Match async readers using a file-reading helper (2.1.197+).

    The helper name (WN, F1, VP, etc.) is platform-specific due to
    per-build minification, so we match any word before (r,e,.
    (zt() is always the filesystem getter, and the 3-param signature
    with try/catch and {info:null,includePaths:[]} is the invariant.)

    Pattern: async function NAME(A,B,C){try{let X=Y(),Z=await *HELPER*(X,A,L);if(Z===null)return...,{info:null,includePaths:[]};return PROC(Z,A,B,C)}catch(E){return HANDLER(E,A),{info:null,includePaths:[]}}}
    """
    pattern = re.compile(
        r'(async function ([$\w]+)\(([$\w]+),([$\w]+),([$\w]+))\)\{try\{'
        r'let ([$\w]+)=([$\w]+)\(\),'                                 # X=Y()
        r'([$\w]+)=await ([$\w]+)\(\6,\3,([$\w]+)\);if\(\8===null\)'  # Z=await *HELPER*(X,A,L)
        r'return[^;]+;'                                                # ...return
        r'return ([$\w]+)\(\8,\3,\4,\5\)\}'                            # PROC(Z,A,B,C)
        r'catch\(([$\w]+)\)\{return ([$\w]+)\(\12,\3\),\{info:null,includePaths:\[\]\}\}\}',  # HANDLER
        re.DOTALL,
    )
    match = pattern.search(js)
    if not match:
        raise ValueError("async reader (WN)")
    func_sig, func_name = match.group(1), match.group(2)
    path_param, type_param, third_param = match.group(3), match.group(4), match.group(5)
    getter_var, getter_func = match.group(6), match.group(7)
    content_var, helper_func, limit_var = match.group(8), match.group(9), match.group(10)
    processor_func = match.group(11)
    catch_var, error_handler = match.group(12), match.group(13)
    alt_json = json.dumps(alt_names, separators=(",", ":"))
    replacement = (
        f"{func_sig},didReroute){{try{{let {getter_var}={getter_func}(),"
        f"{content_var}=await {helper_func}({getter_var},{path_param},{limit_var});"
        f"if({content_var}===null){{"
        f"if(!didReroute&&({path_param}.endsWith(\"/CLAUDE.md\")||{path_param}.endsWith(\"\\\\CLAUDE.md\"))){{"
        f"for(let alt of {alt_json}){{let altPath={path_param}.slice(0,-9)+alt;"
        f"try{{let r=await {func_name}(altPath,{type_param},{third_param},true);if(r.info)return r}}catch{{}}}}}}"
        f"return C(`[CLAUDE.md] skipping ${{{path_param}}}: not a regular file or exceeds ${{{limit_var}}} byte limit`),{{info:null,includePaths:[]}}}}"
        f"return {processor_func}({content_var},{path_param},{type_param},{third_param})"
        f"}}catch({catch_var}){{{error_handler}({catch_var},{path_param});"
        f"return{{info:null,includePaths:[]}}}}}}"
    )
    return js[:match.start()] + replacement + js[match.end():]


def _apply_async_dir(js: str, alt_names) -> str:
    """Match async readers with a directory-detection callback (2.1.208+).

    The reader gained a local `dir` flag set from an isDirectory() callback
    passed to the read helper, and the null branch became a logging block
    instead of a bare return:

    async function NAME(A,B,C){try{let X=Y(),D=!1,Z=await HELPER(X,A,L,(s)=>{D=s.isDirectory()});
    if(Z===null){<log-skip>return{info:null,includePaths:[]}}return PROC(Z,A,B,C)}
    catch(E){return HANDLER(E,A),{info:null,includePaths:[]}}}
    """
    pattern = re.compile(
        r'(async function ([$\w]+)\(([$\w]+),([$\w]+),([$\w]+))\)\{try\{'
        r'(let [$\w]+=[$\w]+\(\),[$\w]+=!1,([$\w]+)=await [$\w]+\([^;]*?\);)'  # decl + content_var
        r'if\(\7===null\)\{'
        r'((?:.|\n)*?return\{info:null,includePaths:\[\]\})\}'                # null-branch tail
        r'(return ([$\w]+)\(\7,\3,\4,\5\)\}catch\(([$\w]+)\)\{'               # verbatim tail + catch var
        r'return [$\w]+\(\11,\3\),\{info:null,includePaths:\[\]\}\}\})',
        re.DOTALL,
    )
    match = pattern.search(js)
    if not match:
        raise ValueError("async reader (dir)")
    func_sig, func_name = match.group(1), match.group(2)
    path_param, type_param, third_param = match.group(3), match.group(4), match.group(5)
    decl, content_var, null_tail, tail = match.group(6), match.group(7), match.group(8), match.group(9)
    alt_json = json.dumps(alt_names, separators=(",", ":"))
    # third_param can be minified to `r`, which would collide with a hardcoded
    # `let r=await ...` loop result and throw a TDZ ReferenceError. Pick a
    # result var name that is not any of the reader's params.
    params = {path_param, type_param, third_param}
    res_var = next(name for name in ("altRes", "altR", "_altR", "__altR") if name not in params)
    replacement = (
        f"{func_sig},didReroute){{try{{{decl}"
        f"if({content_var}===null){{"
        f"if(!didReroute&&({path_param}.endsWith(\"/CLAUDE.md\")||{path_param}.endsWith(\"\\\\CLAUDE.md\"))){{"
        f"for(let alt of {alt_json}){{let altPath={path_param}.slice(0,-9)+alt;"
        f"try{{let {res_var}=await {func_name}(altPath,{type_param},{third_param},true);if({res_var}.info)return {res_var}}}catch{{}}}}}}"
        f"{null_tail}}}"
        f"{tail}"
    )
    return js[:match.start()] + replacement + js[match.end():]


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    alt_names = _alt_names(ctx)
    last_error: Optional[str] = None
    for apply_fn in (_apply_async_dir, _apply_async_wn, _apply_async_qn, _apply_async, _apply_sync):
        try:
            return PatchOutcome(js=apply_fn(js, alt_names), status="applied")
        except ValueError as exc:
            last_error = str(exc)
            continue
    return PatchOutcome(js=js, status="missed", notes=(f"missing {last_error}",))


PATCH = Patch(
    id="agents-md",
    name="AGENTS.md support",
    group="system",
    versions_supported=">=2.1.0,<3",
    versions_tested=(">=2.1.0,<2.2",),
    apply=_apply,
    description="Read AGENTS.md and other configured alternative instruction filenames when CLAUDE.md is absent.",
)
