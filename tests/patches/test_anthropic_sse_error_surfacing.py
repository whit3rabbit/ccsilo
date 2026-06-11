import json
import shutil
import subprocess

import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.anthropic_sse_error_surfacing import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("anthropic-sse-error-surfacing")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "applied"
    assert "ccsilo:anthropic-sse-error-surfacing" in outcome.js
    assert 'this.event==="error"' in outcome.js
    assert 'x-should-retry","false"' in outcome.js
    assert 'headers?.get?.("x-should-retry")' in outcome.js
    assert '["1112","1113","1121","1304","1308","1309","1310","1311","1313","1008","2056"]' in outcome.js
    assert "ccsiloQuotaExhausted" in outcome.js
    assert "ccsiloNonRetryable=!0" in outcome.js
    assert "ccsiloNonRetryable===!0" in outcome.js
    assert '"rate_limit_error"?429' in outcome.js


def test_synthetic_decoder_surfaces_error_before_blank_line(cli_js_synthetic, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; skipping runtime SSE decoder check")

    js = cli_js_synthetic("anthropic-sse-error-surfacing")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    payload = {"type": "error", "error": {"type": "rate_limit_error", "message": "quota"}}
    probe = (
        outcome.js
        + "\nconst decoder = new Dd8();"
        + '\ndecoder.decode("event: error");'
        + "\nconst event = decoder.decode("
        + json.dumps("data: " + json.dumps(payload))
        + ");"
        + "\nif (!event || event.event !== 'error') process.exit(11);"
        + "\nif (event.data !== "
        + json.dumps(json.dumps(payload))
        + ") process.exit(12);"
        + "\nif (decoder.event !== null || decoder.data.length !== 0 || decoder.chunks.length !== 0) process.exit(13);"
    )
    path = tmp_path / "probe.js"
    path.write_text(probe, encoding="utf-8")

    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr or result.stdout


def test_synthetic_error_branch_throws_status_bearing_nonretry_error(cli_js_synthetic, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; skipping runtime SSE error check")

    js = cli_js_synthetic("anthropic-sse-error-surfacing")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    payload = {"type": "error", "error": {"type": "rate_limit_error", "message": "quota"}}
    probe = (
        outcome.js
        + "\n(async()=>{"
        + "\nconst response = {headers:new Headers(),nextEvent:{event:'error',data:"
        + json.dumps(json.dumps(payload))
        + "}};"
        + "\ntry{for await (const _ of stream(response,{})){};process.exit(21)}"
        + "\ncatch(error){"
        + "\nif(error.status!==429)process.exit(22);"
        + "\nif(error.type!=='rate_limit_error')process.exit(23);"
        + "\nif(error.headers.get('x-should-retry')!=='false')process.exit(24);"
        + "\nif(error.ccsiloNonRetryable!==true)process.exit(26);"
        + "\nif(shouldRetry(error)!==false)process.exit(27);"
        + "\nlet plainQuotaError = {status:429,type:'rate_limit_error',message:'Weekly/Monthly Limit Exhausted',error:{error:{code:'1310'}},headers:new Headers()};"
        + "\nif(shouldRetry(plainQuotaError)!==false)process.exit(28);"
        + "\nlet zaiBalanceError = {status:429,type:'rate_limit_error',message:'Account balance exhausted',error:{error:{code:'1113'}},headers:new Headers()};"
        + "\nif(shouldRetry(zaiBalanceError)!==false)process.exit(33);"
        + "\nlet zaiHighTrafficError = {status:429,type:'rate_limit_error',message:'high traffic',error:{error:{code:'1312'}},headers:new Headers()};"
        + "\nif(shouldRetry(zaiHighTrafficError)!==true)process.exit(34);"
        + "\nlet plainTransientError = {status:429,type:'rate_limit_error',message:'try later',error:{error:{code:'busy'}},headers:new Headers()};"
        + "\nif(shouldRetry(plainTransientError)!==true)process.exit(29);"
        + "\nlet minimaxBalanceError = {status:429,type:null,message:'insufficient balance',error:{base_resp:{status_code:1008}},headers:new Headers()};"
        + "\nif(shouldRetry(minimaxBalanceError)!==false)process.exit(30);"
        + "\nlet minimaxUsageError = {status:429,type:null,message:'usage limit exceeded',error:{base_resp:{status_code:2056}},headers:new Headers()};"
        + "\nif(shouldRetry(minimaxUsageError)!==false)process.exit(31);"
        + "\nlet minimaxRateLimitError = {status:429,type:null,message:'rate limit',error:{base_resp:{status_code:1002}},headers:new Headers()};"
        + "\nif(shouldRetry(minimaxRateLimitError)!==true)process.exit(32);"
        + "\n}"
        + "\n})().catch(()=>process.exit(25));"
    )
    path = tmp_path / "probe.js"
    path.write_text(probe, encoding="utf-8")

    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr or result.stdout


def test_synthetic_retry_method_handles_nonretryable_quota(cli_js_synthetic, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not on PATH; skipping runtime retry method check")

    old_retry = (
        "function skipFirst(H){return!1}"
        "function retryWatchdogEnabled(){return!0}"
        "function retryWatchdogError(H){return H.status===429}"
        "function shouldRetry(H){if(skipFirst(H))return!1;"
        "if(retryWatchdogEnabled()&&retryWatchdogError(H))return!0;"
        'let _=H.headers?.get("x-should-retry");if(_==="false")return!1;'
        "if(H.status===429)return!0;return!1}"
    )
    retry_method = (
        "class Client{constructor(){this._authState={tokenCache:null}}"
        "_authFlags(H){return{usedTokenCache:false,didRefreshFor401:false}}"
        "async shouldRetry(H,$){let q=this._authFlags($);"
        "if(H.status===401&&this._authState.tokenCache&&q.usedTokenCache&&!q.didRefreshFor401)"
        "return q.didRefreshFor401=!0,this._authState.tokenCache.invalidate(),!0;"
        'let K=H.headers.get("x-should-retry");if(K==="true")return!0;'
        'if(K==="false")return!1;if(H.status===408)return!0;'
        "if(H.status===409)return!0;if(H.status===429)return!0;"
        "if(H.status>=500)return!0;return!1}}"
    )
    js = cli_js_synthetic("anthropic-sse-error-surfacing").replace(old_retry, retry_method)
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    probe = (
        outcome.js
        + "\n(async()=>{"
        + "\nconst client = new Client();"
        + "\nlet quota = {status:429,type:'rate_limit_error',message:'Weekly/Monthly Limit Exhausted',error:{error:{code:'1310'}},headers:new Headers()};"
        + "\nif(await client.shouldRetry(quota,{})!==false)process.exit(41);"
        + "\nlet transient = {status:429,type:'rate_limit_error',message:'try later',error:{error:{code:'busy'}},headers:new Headers()};"
        + "\nif(await client.shouldRetry(transient,{})!==true)process.exit(42);"
        + "\nlet forcedOff = {status:500,type:'api_error',message:'down',error:{},headers:new Headers([['x-should-retry','false']])};"
        + "\nif(await client.shouldRetry(forcedOff,{})!==false)process.exit(43);"
        + "\nlet forcedOn = {status:400,type:'invalid_request_error',message:'retry',error:{},headers:new Headers([['x-should-retry','true']])};"
        + "\nif(await client.shouldRetry(forcedOn,{})!==true)process.exit(44);"
        + "\n})().catch(()=>process.exit(45));"
    )
    path = tmp_path / "probe.js"
    path.write_text(probe, encoding="utf-8")

    result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr or result.stdout


def test_idempotent(cli_js_synthetic):
    js = cli_js_synthetic("anthropic-sse-error-surfacing")
    once = PATCH.apply(js, PatchContext(claude_version=None))
    twice = PATCH.apply(once.js, PatchContext(claude_version=None))

    assert twice.status == "skipped"
    assert twice.js == once.js


def test_miss_has_detail():
    outcome = PATCH.apply("function unrelated(){return null}", PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert outcome.notes == ("missing SSE decoder data branch",)


def test_second_anchor_miss_returns_original_js(cli_js_synthetic):
    js = cli_js_synthetic("anthropic-sse-error-surfacing").replace('if($.event==="error")', 'if($.event==="oops")')
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert outcome.js == js
    assert outcome.notes == ("missing SSE error branch",)


def test_retry_predicate_miss_returns_original_js(cli_js_synthetic):
    js = cli_js_synthetic("anthropic-sse-error-surfacing").replace(
        "if(retryWatchdogEnabled()&&retryWatchdogError(H))return!0;",
        "if(retryWatchdogEnabled())return!0;",
    )
    outcome = PATCH.apply(js, PatchContext(claude_version=None))

    assert outcome.status == "missed"
    assert outcome.js == js
    assert outcome.notes == ("missing API retry predicate",)


def test_metadata():
    assert PATCH.id == "anthropic-sse-error-surfacing"
    assert PATCH.group == "system"


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l1(cli_js_real, version):
    outcome = PATCH.apply(cli_js_real(version), PatchContext(claude_version=version))

    if version == "2.1.159":
        assert outcome.status == "applied"
    assert outcome.status in {"applied", "missed"}
    if outcome.status == "applied":
        assert "ccsilo:anthropic-sse-error-surfacing" in outcome.js
        assert "ccsiloNonRetryable" in outcome.js
    else:
        assert outcome.notes in {
            ("missing SSE decoder data branch",),
            ("missing SSE error branch",),
            ("missing API retry predicate",),
        }


@pytest.mark.parametrize("version", resolve_tested_versions(PATCH))
def test_real_l2(cli_js_real, version, parse_js):
    js = cli_js_real(version)
    try:
        parse_js(js)
    except AssertionError:
        pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
    outcome = PATCH.apply(js, PatchContext(claude_version=version))
    if outcome.status == "applied":
        parse_js(outcome.js)
