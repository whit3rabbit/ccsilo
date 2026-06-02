"""Surface Anthropic-compatible SSE error events promptly."""

import re

from . import Patch, PatchContext, PatchOutcome
from ._pinned_default import DEFAULT_VERSION_RANGES


_MARKER = "ccsilo:anthropic-sse-error-surfacing"
_DECODER_RE = re.compile(
    r'if\(([$\w]+)==="event"\)this\.event=([$\w]+);'
    r'else if\(\1==="data"\)this\.data\.push\(\2\);'
    r'return null\}\}'
)
_ERROR_BRANCH_RE = re.compile(
    r'if\(([$\w]+)\.event==="error"\)\{'
    r'let ([$\w]+)=([$\w]+)\(\1\.data\)\?\?\1\.data,'
    r'([$\w]+)=\2\?\.error\?\.type;'
    r'throw new ([$\w]+)\(void 0,\2,void 0,([$\w]+)\.headers,\4\)'
    r'\}'
)
_RETRY_PREDICATE_RE = re.compile(
    r'function ([$\w]+)\(([$\w]+)\)\{'
    r'if\(([$\w]+)\(\2\)\)return!1;'
    r'if\(([$\w]+)\(\)&&([$\w]+)\(\2\)\)return!0;'
)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    if _MARKER in js:
        return PatchOutcome(js=js, status="skipped")

    original_js = js
    try:
        js = _patch_decoder(js)
        js = _patch_error_branch(js)
        js = _patch_retry_predicate(js)
    except ValueError as exc:
        return PatchOutcome(js=original_js, status="missed", notes=(f"missing {exc}",))
    return PatchOutcome(js=js, status="applied")


def _patch_decoder(js: str) -> str:
    match = _DECODER_RE.search(js)
    if not match:
        raise ValueError("SSE decoder data branch")
    field_var, value_var = match.group(1), match.group(2)
    replacement = (
        f'if({field_var}==="event")this.event={value_var};'
        f'else if({field_var}==="data"){{'
        f'this.data.push({value_var});'
        'if(this.event==="error"){'
        'let ccsiloData=this.data.join("\\n"),ccsiloPayload;'
        'try{ccsiloPayload=JSON.parse(ccsiloData)}catch{}'
        'if(ccsiloPayload?.type==="error"&&ccsiloPayload?.error){'
        'let ccsiloEvent={event:this.event,data:ccsiloData,raw:this.chunks};'
        'return this.event=null,this.data=[],this.chunks=[],ccsiloEvent'
        '}'
        '}'
        '}'
        f'return null/*{_MARKER}*/}}}}'
    )
    return js[:match.start()] + replacement + js[match.end():]


def _patch_error_branch(js: str) -> str:
    match = _ERROR_BRANCH_RE.search(js)
    if not match:
        raise ValueError("SSE error branch")
    event_var, payload_var, parse_func, type_var, error_class, response_var = match.groups()
    replacement = (
        f'if({event_var}.event==="error"){{'
        f'let {payload_var}={parse_func}({event_var}.data)??{event_var}.data,'
        f'{type_var}={payload_var}?.error?.type,'
        f'ccsiloStatus={type_var}==="rate_limit_error"?429:'
        f'{type_var}==="authentication_error"?401:'
        f'{type_var}==="permission_error"||{type_var}==="billing_error"?403:'
        f'{type_var}==="not_found_error"?404:'
        f'{type_var}==="request_too_large"?413:'
        f'{type_var}==="overloaded_error"?529:'
        f'{type_var}==="api_error"?500:'
        f'{type_var}==="invalid_request_error"?400:void 0,'
        f'ccsiloHeaders=typeof Headers<"u"?new Headers({response_var}.headers):{response_var}.headers;'
        'try{ccsiloHeaders?.set?.("x-should-retry","false")}catch{}'
        f'let ccsiloError=new {error_class}(ccsiloStatus,{payload_var},void 0,ccsiloHeaders,{type_var});'
        'ccsiloError.ccsiloNonRetryable=!0;'
        'throw ccsiloError'
        '}'
    )
    return js[:match.start()] + replacement + js[match.end():]


def _patch_retry_predicate(js: str) -> str:
    match = _RETRY_PREDICATE_RE.search(js)
    if not match:
        raise ValueError("API retry predicate")
    function_name, error_var, first_predicate, watchdog_enabled, watchdog_predicate = match.groups()
    replacement = (
        f'function {function_name}({error_var}){{'
        f'if({first_predicate}({error_var}))return!1;'
        f'let ccsiloShouldRetry={error_var}.headers?.get?.("x-should-retry"),'
        f'ccsiloErrorCode=String({error_var}.error?.error?.code??'
        f'{error_var}.error?.code??{error_var}.error?.base_resp?.status_code??""),'
        f'ccsiloQuotaExhausted=({error_var}.type==="rate_limit_error"||{error_var}.status===429)&&'
        '(["1112","1113","1121","1304","1308","1309","1310","1311","1313","1008","2056"].includes(ccsiloErrorCode)||'
        f'/limit exhausted|usage limit|insufficient balance|balance exhausted|in arrears|account .*locked|package has expired|daily call limit|subscription plan|fair use/i.test({error_var}.message??""));'
        'if(ccsiloShouldRetry==="false"||ccsiloQuotaExhausted)return!1;'
        f'if({error_var}?.ccsiloNonRetryable===!0)return!1;'
        f'if({watchdog_enabled}()&&{watchdog_predicate}({error_var}))return!0;'
    )
    return js[:match.start()] + replacement + js[match.end():]


PATCH = Patch(
    id="anthropic-sse-error-surfacing",
    name="Anthropic SSE error surfacing",
    group="system",
    versions_supported=">=2.0.0,<3",
    versions_tested=DEFAULT_VERSION_RANGES,
    apply=_apply,
    on_miss="skip",
    description=(
        "Surface Anthropic-compatible streaming event:error payloads promptly, "
        "including HTTP 200 streams that carry a terminal non-retryable error event."
    ),
)
