"""Correct statusline update throttling/pacing."""

import re

from . import Patch, PatchContext, PatchOutcome


def _misc(ctx: PatchContext, key: str, default):
    settings = ((ctx.config or {}).get("settings") or {}).get("misc") or {}
    snake = {
        "statuslineThrottleMs": "statusline_throttle_ms",
        "statuslineUseFixedInterval": "statusline_use_fixed_interval",
    }.get(key, key)
    return settings.get(key) if settings.get(key) is not None else (ctx.config or {}).get(snake, default)


# 2.1.233+ class-based controller: the render debounce is a bare var pair
# (X=300 trailing debounce, Y=1000 scheduling pad) followed by a latch-reset
# helper. Only the 300 constant is render pacing; the 1000 pad stays put.
_CLASS_CONTROLLER = re.compile(
    r"var ([$\w]+)=300,(?=[$\w]+=1000;function [$\w]+\([$\w]+,[$\w]+,[$\w]+,[$\w]+\)"
    r"\{if\(![$\w]+\.current\)return;[$\w]+\.current=!1,[$\w]+\([$\w]+,[$\w]+\(\)\)\})"
)

_FIXED_INTERVAL_NOTE = (
    "fixed-interval pacing is superseded by the native statusLine.refreshInterval "
    "setting on 2.1.233+; applied throttle-ms only"
)


def _apply_controller_constant(js: str, ctx: PatchContext) -> PatchOutcome:
    matches = list(_CLASS_CONTROLLER.finditer(js))
    if len(matches) > 1:
        return PatchOutcome(
            js=js,
            status="missed",
            notes=(f"ambiguous statusline controller anchor: {len(matches)} candidates",),
        )
    if not matches:
        return PatchOutcome(js=js, status="missed")
    interval_ms = int(_misc(ctx, "statuslineThrottleMs", 300))
    use_fixed_interval = bool(_misc(ctx, "statuslineUseFixedInterval", False))
    notes = (_FIXED_INTERVAL_NOTE,) if use_fixed_interval else ()
    if interval_ms == 300:
        return PatchOutcome(js=js, status="skipped", notes=notes)
    match = matches[0]
    replacement = f"var {match.group(1)}={interval_ms},"
    new_js = js[:match.start()] + replacement + js[match.end():]
    return PatchOutcome(js=new_js, status="applied", notes=notes)


def _apply(js: str, ctx: PatchContext) -> PatchOutcome:
    pattern = re.compile(
        r'(,([$\w]+)=([$\w]+(?:\.default)?)\.useCallback.{0,1000}statusLineText.{0,200}?),'
        r'([$\w]+)=([$\w.]+\(\(\)=>(\2\(([$\w]+)\)),300\)|[$\w]+\(\2,300\)|'
        r'[$\w]+\(\(\)=>\{\2\(\)\},300\)|'
        r'.{0,100}\{[$\w]+\.current=void 0,\2\(\)\},300\)\},\[\2\]\)|'
        r'[$\w]+\.useCallback\(\(\)=>\{if\([$\w]+\.current!==void 0\)'
        r'clearTimeout\([$\w]+\.current\);[$\w]+\.current=setTimeout\(\([$\w]+,[$\w]+\)=>'
        r'\{[$\w]+\.current=void 0,[$\w]+\(\)\},300,[$\w]+,\2\)\},\[\2\]\))',
        re.DOTALL,
    )
    match = pattern.search(js)
    if not match:
        return _apply_controller_constant(js, ctx)

    first_part = match.group(1)
    update_fn = match.group(2)
    react_var = match.group(3)
    callback_var = match.group(4)
    call = match.group(6) or f"{update_fn}()"
    argument = match.group(7)
    interval_ms = int(_misc(ctx, "statuslineThrottleMs", 300))
    use_fixed_interval = bool(_misc(ctx, "statuslineUseFixedInterval", False))

    dependencies = f"{update_fn}, {argument}" if argument else update_fn
    if use_fixed_interval:
        if argument:
            replacement = (
                f"{first_part},argRef={react_var}.useRef({argument})"
                f",unused1={react_var}.useEffect(()=>{{argRef.current={argument};}},[{argument}])"
                f",unused2={react_var}.useEffect(()=>{{const id=setInterval(()=>{update_fn}(argRef.current),{interval_ms});"
                f"return()=>clearInterval(id);}},[{update_fn}]),{callback_var}={react_var}.useCallback(()=>{{}},[])"
            )
        else:
            replacement = (
                f"{first_part},unused1={react_var}.useEffect(()=>{{const id=setInterval(()=>{call},{interval_ms});"
                f"return()=>clearInterval(id);}},[{update_fn}]),{callback_var}={react_var}.useCallback(()=>{{}},[])"
            )
    else:
        replacement = (
            f"{first_part},lastCall={react_var}.useRef(0),{callback_var}={react_var}.useCallback(()=>{{"
            f"let now=Date.now();if(now-lastCall.current>={interval_ms}){{lastCall.current=now;{call};}}"
            f"}},[{dependencies}])"
        )
    new_js = js[:match.start()] + replacement + js[match.end():]
    return PatchOutcome(js=new_js, status="applied")


PATCH = Patch(
    id="statusline-update-throttle",
    name="Statusline update throttling correction",
    group="ui",
    # Two shapes: <=2.1.232 React-hook debounce (useCallback + 300ms helper),
    # and >=2.1.233 class-based controller where only the debounce constant
    # var pair is rewritten.
    versions_supported=">=2.0.0,<3",
    versions_tested=(">=2.0.20,<2.1", ">=2.1.0,<=2.1.232", ">=2.1.233,<=2.1.259"),
    apply=_apply,
    description=(
        "Throttle statusline update pacing via statuslineThrottleMs (default 300ms). "
        "On 2.1.233+ rewrites the class-controller debounce constant; fixed-interval "
        "mode there is superseded by the native statusLine.refreshInterval setting."
    ),
)
