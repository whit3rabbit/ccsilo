import pytest

from ccsilo.variant_tweaks import (
    BOOLEAN_ENV_TWEAKS,
    CURATED_TWEAK_IDS,
    DASHBOARD_TWEAK_IDS,
    DEFAULT_TWEAK_IDS,
    GATEWAY_MODEL_DISCOVERY_ENV,
    GATEWAY_MODEL_DISCOVERY_TWEAK_ID,
    RTK_SHELL_PREFIX_TEXT,
    SETUP_CONFIG_TWEAK_IDS,
    TweakPatchError,
    apply_variant_tweaks,
    available_tweaks,
    compose_prompt_overlays,
    default_tweak_ids_for_provider,
    env_for_tweaks,
)


THEMES = [
    {"id": "dark", "name": "Dark mode", "colors": {"bashBorder": "#fff"}},
    {"id": "provider", "name": "Provider", "colors": {"bashBorder": "#daa"}},
]


def theme_fixture():
    return "\n".join(
        [
            'function getNames(){return{"dark":"Dark mode","light":"Light mode"}}',
            'const themeOptions=[{label:"Dark mode",value:"dark"},{label:"Light mode",value:"light"}];',
            'function pickTheme(A){switch(A){case"light":return LX9;case"dark":return CX9;default:return CX9}}',
        ]
    )


def test_apply_variant_tweaks_applies_theme_prompt_and_indicator():
    js = "\n".join(
        [
            theme_fixture(),
            'let WEBFETCH=`Fetches URLs.\\n- For GitHub URLs, prefer using the gh CLI via Bash instead (e.g., gh pr view, gh issue view, gh api).`;',
            'const version=`${pkg.VERSION} (Claude Code)`;',
        ]
    )

    result = apply_variant_tweaks(
        js,
        tweak_ids=["themes", "prompt-overlays", "patches-applied-indication"],
        config={"settings": {"themes": THEMES}},
        overlays={"webfetch": "Use provider docs."},
        provider_label="Provider",
    )

    assert result.applied == ["themes", "prompt-overlays", "patches-applied-indication"]
    assert 'case"provider":return{"bashBorder":"#daa"}' in result.js
    assert "Use provider docs." in result.js
    assert "(Claude Code, Provider variant)" in result.js


def test_curated_tweak_ports_patch_fixture_patterns():
    js = "\n".join(
        [
            'function menu({visibleOptionCount:A=5}){return A}',
            'function models(){let L=[]; L.push({value:M,label:N,description:"Custom model"});return L}',
            ',R.createElement(B,{isBeforeFirstMessage:!1}),',
            'function banner(){if(x)return"Apple_Terminal";return"Welcome to Claude Code"}',
            'function inner(){return"\\u259B\\u2588\\u2588\\u2588\\u259C"}function wrapper(){return R.createElement(inner,{})}',
            'if(v&&P)p("tengu_external_editor_hint_shown",{})',
            'function fmt({content:C,startLine:S}){if(!C)return"";let L=C.split(/\\r?\\n/);return L.map(x=>x).join("\\n")}function next(){}',
            'function QK3(){if(dq()!=="firstParty")return!1;let H=I_();if(H.unpinOpus47LaunchEffort)return!1;if((H.opus47LaunchSeenCount??0)>=gK3)return!1;return!0}',
            "Claude Code has switched from npm to native installer. Run `claude install` or see https://docs.anthropic.com/en/docs/claude-code/getting-started for more options.",
            (
                'function VV8(){let H=hV8.c(5),_;if(H[0]===Symbol.for("react.memo_cache_sentinel"))'
                '_=["DISABLE_PROMPT_CACHING","DISABLE_PROMPT_CACHING_HAIKU","DISABLE_PROMPT_CACHING_OPUS","DISABLE_PROMPT_CACHING_SONNET"],H[0]=_;'
                'else _=H[0];let q;if(H[1]===Symbol.for("react.memo_cache_sentinel"))q=_.filter($43),H[1]=q;else q=H[1];'
                'let K=q;if(K.length===0)return null;let O;if(H[2]===Symbol.for("react.memo_cache_sentinel"))'
                'O=X8.createElement(v,{color:"error"},"\\u25CF "),H[2]=O;else O=H[2];let T;'
                'if(H[3]===Symbol.for("react.memo_cache_sentinel"))T=X8.createElement(v,{color:"error"},"Prompt caching disabled via ",K.join(", "),". This will impact latency and token costs."),H[3]=T;'
                'else T=H[3];let A;if(H[4]===Symbol.for("react.memo_cache_sentinel"))'
                'A=X8.createElement(B,{flexDirection:"row"},O,X8.createElement(B,{flexDirection:"column"},T,X8.createElement(v,{dimColor:!0},"We highly recommend disabling"," ",K.length===1?"this environment variable":"these environment variables"))),H[4]=A;'
                'else A=H[4];return A}'
            ),
            'R.createElement(X,{a:1}),showAllInTranscript:A,agentDefinitions:B,onOpenRateLimitOptions:C,other:true',
            'case"thinking":{if(!D&&!H)return null;let T=D&&H;isTranscriptMode:D,verbose:H,hideInTranscript:T}',
            'createElement(T,{color:V.bgColor},"\\u2500".repeat(W));borderColor:Y(),borderStyle:"round",borderLeft:!1,borderRight:!1,borderBottom:!0,width:"100%",borderText:Z();',
            '#!/usr/bin/env node\n// Version 2.1.123\nconsole.log("ready");',
            'async function readClaude(A,q,K){try{let z=await fs().readFile(A,{encoding:"utf-8"});return processClaude(z,A,q,K)}catch(_){return handleReadError(_,A),{info:null,includePaths:[]}}}',
            'function enabled(){return gate("tengu_session_memory",!1)}if(gate("tengu_coral_fern",!1)){searchPastSessions()}let per=2000,total=12000;return `# Session Title`const opts={minimumMessageTokensToInit:1e4,minimumTokensBetweenUpdate:5000,toolCallsBetweenUpdates:3};',
            'if(currentModel()==="opusplan"&&mode==="plan"&&!overLimit)return opusModel();let aliases=["sonnet","opus","haiku","sonnet[1m]","opusplan"];function desc(A){if(A==="opusplan")return"Opus 4.6 in plan mode, else Sonnet 4.6";return""}function label(A){if(A==="opusplan")return"Opus Plan";return""}function options(K,A){if(K==="opusplan")return [...A,opusPlanOption()];if(K===null||A.some((Z)=>Z.value===K))return A;}',
            'async function connect(){if(!envFlag(process.env.MCP_CONNECTION_NONBLOCKING))return await waitForServers()}',
            'let batch=parseInt(process.env.MCP_SERVER_CONNECTION_BATCH_SIZE||"",10)||3;return batch',
            'let overrideMessage:true,count=format(inputTokens+outputTokens),view={key:"tokens"},count," tokens";',
            ',O=Pc.useCallback(async()=>{let D=await run();w((j)=>({...j,statusLineText:D}))},[w]),X=Gr(()=>O(A),300);',
            'function plan(){return R.createElement(Box,{title:"Ready to code?",onChange:onPick,onCancel:onCancel})}',
            ',model:z.enum(MODELS).optional();let ok=K&&typeof K==="string"&&MODELS.includes(K)',
        ]
    )

    result = apply_variant_tweaks(
        js,
        tweak_ids=[
            "show-more-items-in-select-menus",
            "model-customizations",
            "hide-startup-banner",
            "hide-startup-clawd",
            "hide-ctrl-g-to-edit",
            "suppress-line-numbers",
            "suppress-model-launch-notice",
            "suppress-native-installer-warning",
            "suppress-prompt-caching-warning",
            "suppress-rate-limit-options",
            "thinking-visibility",
            "input-box-border",
            "filter-scroll-escape-sequences",
            "agents-md",
            "session-memory",
            "opusplan1m",
            "mcp-non-blocking",
            "mcp-batch-size",
            "token-count-rounding",
            "statusline-update-throttle",
            "auto-accept-plan-mode",
            "allow-custom-agent-models",
        ],
    )

    assert "visibleOptionCount:A=25" in result.js
    assert "claude-sonnet-4-6" in result.js
    assert "isBeforeFirstMessage" not in result.js
    assert "return null;" in result.js
    assert 'if(false)p("tengu_external_editor_hint_shown"' in result.js
    assert "return C}function next" in result.js
    assert "ccsilo:suppress-model-launch-notice" in result.js
    assert "Claude Code has switched from npm to native installer" not in result.js
    assert "ccsilo:suppress-prompt-caching-warning" in result.js
    assert "Prompt caching disabled via" not in result.js
    assert "onOpenRateLimitOptions:()=>{}" in result.js
    assert "isTranscriptMode:true," in result.js
    assert "borderStyle:undefined" in result.js
    assert "SCROLLING FIX PATCH START" in result.js
    assert "didReroute" in result.js
    assert "AGENTS.md" in result.js
    assert 'function enabled(){return true;return gate("tengu_session_memory",!1)}' in result.js
    assert 'currentModel()==="opusplan[1m]"' in result.js
    assert "if(false)" in result.js
    assert 'MCP_SERVER_CONNECTION_BATCH_SIZE||"",10)||10' in result.js
    assert "Math.round((inputTokens+outputTokens)/1000)*1000" in result.js
    assert "lastCall=Pc.useRef(0)" in result.js
    assert 'onPick("yes-accept-edits");return null;return R.createElement' in result.js
    assert ",model:z.string().optional()" in result.js
    assert 'let ok=K&&typeof K==="string"' in result.js


def test_missing_curated_anchor_is_failure():
    with pytest.raises(TweakPatchError, match="failed to find anchor"):
        apply_variant_tweaks("no useful anchors", tweak_ids=["hide-ctrl-g-to-edit"])


def test_env_backed_tweaks_emit_env_without_patching_js():
    env = env_for_tweaks(
        ["context-limit", "file-read-limit", "subagent-model"],
        {
            "context_limit": "1000000",
            "file_read_limit": "90000",
            "subagent_model": "model-x",
        },
    )

    assert env["CLAUDE_CODE_CONTEXT_LIMIT"] == "1000000"
    assert env["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"] == "90000"
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "model-x"


def test_default_tweaks_include_mcp_startup_and_rtk_instruction():
    assert DEFAULT_TWEAK_IDS == [
        "themes",
        "prompt-overlays",
        "hide-startup-banner",
        "hide-startup-clawd",
        "suppress-native-installer-warning",
        "suppress-prompt-caching-warning",
        "suppress-model-launch-notice",
        "mcp-non-blocking",
        "mcp-batch-size",
        "rtk-shell-prefix",
        "dangerously-skip-permissions",
    ]


def test_yet_another_statusline_is_optional_setup_config_tweak():
    tweak_id = "yet-another-statusline"

    assert tweak_id in CURATED_TWEAK_IDS
    assert tweak_id in SETUP_CONFIG_TWEAK_IDS
    assert tweak_id not in DEFAULT_TWEAK_IDS
    assert tweak_id not in DASHBOARD_TWEAK_IDS

    meta = {item["id"]: item for item in available_tweaks()}[tweak_id]
    assert meta["envBacked"] is False
    assert meta["promptOnly"] is False
    assert meta["setupOnly"] is True
    assert meta["setupConfig"] is True


def test_non_mirror_defaults_include_privacy_cache_env_toggles():
    assert default_tweak_ids_for_provider("mirror") == DEFAULT_TWEAK_IDS

    defaults = default_tweak_ids_for_provider("zai")

    assert "dangerously-skip-permissions" in defaults
    assert "disable-telemetry" in defaults
    assert "disable-error-reporting" in defaults
    assert "disable-feedback-command" in defaults
    assert "disable-feedback-survey" in defaults
    assert "disable-prompt-caching" in defaults

    ccr_oauth_defaults = default_tweak_ids_for_provider("ccr-oauth")
    assert "opusplan1m" in ccr_oauth_defaults
    assert "disable-telemetry" in ccr_oauth_defaults


def test_mcp_batch_size_setup_tweak_emits_wrapper_env():
    env = env_for_tweaks(["mcp-batch-size"])

    assert env["MCP_SERVER_CONNECTION_BATCH_SIZE"] == "10"


def test_boolean_env_tweaks_emit_documented_on_off_values():
    env = env_for_tweaks(
        [
            GATEWAY_MODEL_DISCOVERY_TWEAK_ID,
            "disable-telemetry",
            "disable-prompt-caching",
            "mcp-allowlist-env",
        ]
    )

    assert env[GATEWAY_MODEL_DISCOVERY_ENV] == "1"
    assert env["DISABLE_TELEMETRY"] == "1"
    assert env["DISABLE_PROMPT_CACHING"] == "1"
    assert env["CLAUDE_CODE_MCP_ALLOWLIST_ENV"] == "1"
    assert BOOLEAN_ENV_TWEAKS[GATEWAY_MODEL_DISCOVERY_TWEAK_ID]["env"] == GATEWAY_MODEL_DISCOVERY_ENV
    assert BOOLEAN_ENV_TWEAKS["disable-telemetry"]["env"] == "DISABLE_TELEMETRY"


def test_sync_tweak_env_removes_unselected_managed_env():
    from ccsilo.variant_tweaks import sync_tweak_env

    env = {
        "ANTHROPIC_BASE_URL": "https://example.test",
        "MCP_SERVER_CONNECTION_BATCH_SIZE": "10",
        "CLAUDE_CODE_CONTEXT_LIMIT": "1000000",
        "DISABLE_COMPACT": "1",
        "DISABLE_TELEMETRY": "1",
        GATEWAY_MODEL_DISCOVERY_ENV: "1",
    }

    synced = sync_tweak_env(env, ["themes"], {})

    assert synced == {"ANTHROPIC_BASE_URL": "https://example.test"}


def test_rtk_shell_prefix_composes_prompt_overlays():
    overlays = compose_prompt_overlays({"explore": "Use provider docs."}, ["rtk-shell-prefix"])

    assert "Use provider docs." in overlays["explore"]
    assert RTK_SHELL_PREFIX_TEXT in overlays["explore"]
    assert RTK_SHELL_PREFIX_TEXT in overlays["planEnhanced"]


def test_rtk_shell_prefix_applies_without_provider_prompt_overlays():
    js = "let EXPLORE=`Complete the user's search request efficiently and report your findings clearly.`;"
    overlays = compose_prompt_overlays({}, ["rtk-shell-prefix"])

    result = apply_variant_tweaks(js, tweak_ids=["rtk-shell-prefix"], overlays=overlays)

    assert result.applied == ["rtk-shell-prefix"]
    assert "prefix each command with \\`rtk\\`" in result.js


def test_apply_variant_tweaks_warns_on_untested_version():
    import warnings

    js = ",R.createElement(B,{isBeforeFirstMessage:!1}),"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        apply_variant_tweaks(
            js,
            tweak_ids=["hide-startup-banner"],
            claude_version="1.0.0",  # not in any tested range
            force=True,  # bypass unsupported-version error so we can observe the warning
        )
    assert any("1.0.0" in str(w.message) for w in caught)


def test_apply_variant_tweaks_anchor_miss_includes_patch_detail():
    js = 'function enabled(){return gate("tengu_session_memory",!1)}'

    with pytest.raises(TweakPatchError, match="missing past sessions gate"):
        apply_variant_tweaks(js, tweak_ids=["session-memory"])
