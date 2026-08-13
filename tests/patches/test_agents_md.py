import shutil
import subprocess

import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.agents_md import PATCH
from tests.patches.conftest import resolve_tested_versions

# Stubs mimicking the upstream read helpers: `eX`/`qN` stat the path first, so
# a missing CLAUDE.md rejects with ENOENT rather than resolving to null. Only
# AGENTS.md exists on this fake disk.
_RUNTIME_STUBS = """
const LIM=1e6, Gao=1e6;
function getFs(){return {}} function zt(){return {}}
function C(){} function log(){} function handleReadError(){}
function processClaude(z,A,q,K){return {info:{path:A,content:z},includePaths:[]}}
async function readLimited(fs,path,limit,cb){
  if(path.endsWith("AGENTS.md")) return "agents-content";
  const e=new Error("ENOENT"); e.code="ENOENT"; throw e;
}
async function qN(fs,path,limit){ return readLimited(fs,path,limit); }
async function probeBackend(){return {kind:"absent"}}
let warned=false; function tel(){}
"""

# The third parameter is deliberately named `r` in every shape: it collides
# with a naively hardcoded loop result variable and would throw a TDZ
# ReferenceError.
_QN_SHAPE = (
    'async function readClaude(A,q,r){try{let X=zt(),z=await qN(X,A,Gao);'
    'if(z===null)return C(),{info:null,includePaths:[]};'
    'return processClaude(z,A,q,r)}catch(_){return handleReadError(_,A),{info:null,includePaths:[]}}}'
)
_WN_SHAPE = (
    'async function readClaude(A,q,r){try{let X=zt(),z=await readLimited(X,A,LIM);'
    'if(z===null)return C(),{info:null,includePaths:[]};'
    'return processClaude(z,A,q,r)}catch(_){return handleReadError(_,A),{info:null,includePaths:[]}}}'
)
_DIR_SHAPE = (
    'async function readClaude(A,q,r){try{let X=getFs(),D=!1,z=await readLimited(X,A,LIM,(s)=>{D=s.isDirectory()});'
    'if(z===null){log();return{info:null,includePaths:[]}}return processClaude(z,A,q,r)}'
    'catch(_){return handleReadError(_,A),{info:null,includePaths:[]}}}'
)
_BACKEND_SHAPE = (
    'async function readClaude(A,q,r,S){try{let z,D=!1;'
    'if(S){let p=await probeBackend(S);switch(p.kind){'
    'case"absent":return{info:null,includePaths:[]};'
    'case"error":return handleReadError(p.code,A),{info:null,includePaths:[]};'
    'case"skipped":D=p.isDirectory,z=null;break;case"content":z=p.content;break}}'
    'else{let f=getFs();z=await readLimited(f,A,LIM,(s)=>{D=s.isDirectory()})}'
    'if(z===null){if(log(`x ${A}`),!warned&&!D)warned=!0,tel("a","b");return{info:null,includePaths:[]}}'
    'return processClaude(z,A,q,r)}catch(_){return handleReadError(_,A),{info:null,includePaths:[]}}}'
)


@pytest.mark.parametrize(
    "label,shape,argc",
    [
        ("qn", _QN_SHAPE, 4),
        ("wn", _WN_SHAPE, 4),
        ("dir", _DIR_SHAPE, 4),
        ("backend", _BACKEND_SHAPE, 5),
    ],
)
def test_missing_claude_md_reroutes_at_runtime(label, shape, argc, tmp_path):
    # A missing CLAUDE.md surfaces as a rejected read, not a null result, so
    # every reader shape must reroute from its catch branch too. Wiring the
    # reroute only into the null branch made this patch a silent no-op.
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; skipping runtime reroute check")

    outcome = PATCH.apply(shape, PatchContext(claude_version=None))
    assert outcome.status == "applied"

    args = '"/p/CLAUDE.md","Project","/p/CLAUDE.md"' + (",void 0" if argc == 5 else "")
    program = (
        _RUNTIME_STUBS
        + outcome.js
        + f"\nreadClaude({args}).then((x)=>{{"
        + "if(!x.info||x.info.path!=='/p/AGENTS.md')process.exit(17);"
        + "}).catch(()=>process.exit(18));"
    )
    path = tmp_path / f"reroute_{label}.js"
    path.write_text(program, encoding="utf-8")

    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr or result.stdout


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("agents-md")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "didReroute" in outcome.js
    assert "AGENTS.md" in outcome.js
    assert "GEMINI.md" in outcome.js
    assert "await readClaude(altPath,q,K,true)" in outcome.js


def test_synthetic_applies_custom_alt_names(cli_js_synthetic):
    js = cli_js_synthetic("agents-md")
    outcome = PATCH.apply(
        js,
        PatchContext(claude_version=None, config={"claude_md_alt_names": ["TEAM.md"]}),
    )
    assert outcome.status == "applied"
    assert '["TEAM.md"]' in outcome.js
    assert "AGENTS.md" not in outcome.js


def test_synthetic_backend_applies(cli_js_synthetic):
    js = cli_js_synthetic("agents-md-backend")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert "didReroute" in outcome.js
    assert "AGENTS.md" in outcome.js
    # The reroute reads alternative files from the filesystem, never through
    # the caller's opaque storage backend key.
    assert "await readClaude(altPath,q,altPath,void 0,!0)" in outcome.js
    # All three "no CLAUDE.md here" exits reroute: backend absent, null
    # content, and the catch branch a missing file actually lands in.
    assert outcome.js.count("await altLookup()??{info:null,includePaths:[]}") == 3
    assert 'case"absent":return await altLookup()' in outcome.js


def test_synthetic_backend_parses(cli_js_synthetic, parse_js):
    js = cli_js_synthetic("agents-md-backend")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    parse_js(outcome.js)


def test_metadata():
    assert PATCH.id == "agents-md"
    assert PATCH.group == "system"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))
    assert outcome.status == "applied"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    parse_js(outcome.js)
