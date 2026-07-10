import pytest

from ccsilo.patches import PatchContext
from ccsilo.patches.auto_accept_plan_mode import PATCH
from tests.patches.conftest import resolve_tested_versions


def test_synthetic_applies(cli_js_synthetic):
    js = cli_js_synthetic("auto-accept-plan-mode")
    outcome = PATCH.apply(js, PatchContext(claude_version=None))
    assert outcome.status == "applied"
    assert 'onPick("yes-accept-edits");return null;return R.createElement' in outcome.js


def test_react_compiler_output_applies():
    js = (
        'function plan(){let card;if(x)card=create({title:"Ready to code?"});'
        'let B$;if($[88]!==H$)B$=(tH)=>void H$(tH),$[88]=H$,$[89]=B$;'
        'else B$=$[89];let d$;d$=create(U8,{options:F,onChange:B$,onCancel:D$});'
        'return d$}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.142"))
    assert outcome.status == "applied"
    assert 'else B$=$[89];B$("yes-accept-edits");return null;let d$;' in outcome.js


def test_react_compiler_underscore_cache_output_applies():
    js = (
        'function plan(){let card;if(x)card=create({title:"Ready to code?"});'
        'let p_;if(_[88]!==H_)p_=(tH)=>void H_(tH),_[88]=H_,_[89]=p_;'
        'else p_=_[89];let d_;d_=create(U8,{options:F,onChange:p_,onCancel:D_,onImagePaste:I});'
        'return d_}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.143"))
    assert outcome.status == "applied"
    assert 'else p_=_[89];p_("yes-accept-edits");return null;let d_;' in outcome.js


def test_inline_void_handler_applies():
    # 2.1.206+ shape: a review branch exposes a bare `onChange:<ident>` first,
    # then the proceed branch inlines `onChange:(v)=>void <handler>(v)`, and the
    # memoized component ends in a single terminal `return <ident>}`.
    js = (
        'function plan(){let card;if(x)card=create({title:"Ready to code?"});'
        'let rev;rev=tjp==="review"?create(U8,{options:C,onChange:HFo,onCancel:D$}):'
        'create(U8,{options:F,onChange:(eQR)=>void DMt(eQR),onCancel:D$,onImagePaste:I});'
        'let box;box=create(A,{children:[rev]});return box}'
    )
    outcome = PATCH.apply(js, PatchContext(claude_version="2.1.206"))
    assert outcome.status == "applied"
    # Must call the underlying proceed handler (DMt), not the review handler HFo.
    assert 'DMt("yes-accept-edits");return null;return box}' in outcome.js
    assert 'HFo("yes-accept-edits")' not in outcome.js
    # Idempotent.
    again = PATCH.apply(outcome.js, PatchContext(claude_version="2.1.206"))
    assert again.status == "skipped"


def test_metadata():
    assert PATCH.id == "auto-accept-plan-mode"
    assert PATCH.group == "ui"
    assert PATCH.versions_tested  # non-empty


@pytest.fixture
def real_js_versions():
    return resolve_tested_versions(PATCH)


def test_real_l1_anchor_matches(cli_js_real, real_js_versions):
    if not real_js_versions:
        pytest.skip("no resolved versions")
    for version in real_js_versions:
        js = cli_js_real(version)
        outcome = PATCH.apply(js, PatchContext(claude_version=version))
        assert outcome.status == "applied", (
            f"auto-accept-plan-mode did not apply against {version}"
        )


def test_real_l2_patched_js_parses(cli_js_real, real_js_versions, parse_js):
    if not real_js_versions:
        pytest.skip("no resolved versions")
    for version in real_js_versions:
        js = cli_js_real(version)
        # Skip L2 test if the original JS doesn't parse (extraction issue, not patch issue)
        try:
            parse_js(js)
        except AssertionError:
            pytest.skip(f"original extracted JS for {version} does not parse; skipping L2 test")
        outcome = PATCH.apply(js, PatchContext(claude_version=version))
        parse_js(outcome.js)
