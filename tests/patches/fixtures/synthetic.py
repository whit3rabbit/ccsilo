"""Hand-crafted JS snippets per patch.

Each snippet is the smallest possible chunk that exercises the patch's
anchor regex. They are NOT minified Claude Code; they exist for fast
iteration during a port and for catching obvious anchor breakages
without downloading a real binary."""

SYNTHETIC = {
    "hide-startup-banner": (
        ',R.createElement(B,{isBeforeFirstMessage:!1}),'
        'function banner(){if(x)return"Apple_Terminal";return"Welcome to Claude Code"}'
    ),
    "hide-startup-clawd": (
        'function inner(){return"\\u259B\\u2588\\u2588\\u2588\\u259C"}'
        'function wrapper(){return R.createElement(inner,{})}'
    ),
    "hide-ctrl-g-to-edit": 'if(v&&P)p("tengu_external_editor_hint_shown",{})',
    "show-more-items-in-select-menus": 'function menu({visibleOptionCount:A=5}){return A}',
    "model-customizations": (
        'function models(){let L=[]; '
        'L.push({value:M,label:N,description:"Custom model"});return L}'
    ),
    "opencode-gateway-discovery": (
        'async function discover(){if(!process.env.CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY)return;'
        'let H=process.env.ANTHROPIC_BASE_URL;if(!H)return;'
        'let z={data:{data:[{id:"deepseek-v4-pro"}]}};'
        'let Y=z.data.data.filter((j)=>/^(claude|anthropic)/i.test(j.id));'
        'if(Y.length===0)return}'
    ),
    "suppress-line-numbers": (
        'function fmt({content:C,startLine:S}){if(!C)return"";'
        'let L=C.split(/\\r?\\n/);return L.map(x=>x).join("\\n")}function next(){}'
    ),
    "suppress-model-launch-notice": (
        'function QK3(){if(dq()!=="firstParty")return!1;let H=I_();'
        'if(H.unpinOpus47LaunchEffort)return!1;'
        'if((H.opus47LaunchSeenCount??0)>=gK3)return!1;return!0}'
    ),
    "suppress-model-launch-notice-v2": (
        'function Xe8(){if(Zq()!=="firstParty")return!1;'
        'if((I_().opus48LaunchSeenCount??0)>=k9O)return!1;return!0}'
    ),
    "suppress-native-installer-warning": (
        "Claude Code has switched from npm to native installer. Run `claude install` "
        "or see https://docs.anthropic.com/en/docs/claude-code/getting-started "
        "for more options."
    ),
    "suppress-native-installer-warning-v2": (
        'jN3={id:"npm-deprecation",tier:"warning",type:"warning",'
        'isActive:(H)=>H.npmInstallDeprecated,render:()=>kK.createElement(uS,'
        '{status:"warning"},"Installed via npm (deprecated)",'
        'kK.createElement(N,{dimColor:!0}," ","\\xB7 run claude install to switch '
        'to the native version"))}'
    ),
    "suppress-prompt-caching-warning": (
        'function VV8(){let H=hV8.c(5),_;'
        'if(H[0]===Symbol.for("react.memo_cache_sentinel"))'
        '_=["DISABLE_PROMPT_CACHING","DISABLE_PROMPT_CACHING_HAIKU",'
        '"DISABLE_PROMPT_CACHING_OPUS","DISABLE_PROMPT_CACHING_SONNET"],H[0]=_;'
        'else _=H[0];let q;if(H[1]===Symbol.for("react.memo_cache_sentinel"))'
        'q=_.filter($43),H[1]=q;else q=H[1];let K=q;if(K.length===0)return null;'
        'let O;if(H[2]===Symbol.for("react.memo_cache_sentinel"))'
        'O=X8.createElement(v,{color:"error"},"\\u25CF "),H[2]=O;else O=H[2];'
        'let T;if(H[3]===Symbol.for("react.memo_cache_sentinel"))'
        'T=X8.createElement(v,{color:"error"},"Prompt caching disabled via ",K.join(", "),'
        '". This will impact latency and token costs."),H[3]=T;else T=H[3];'
        'let A;if(H[4]===Symbol.for("react.memo_cache_sentinel"))'
        'A=X8.createElement(B,{flexDirection:"row"},O,X8.createElement(B,{flexDirection:"column"},'
        'T,X8.createElement(v,{dimColor:!0},"We highly recommend disabling"," ",'
        'K.length===1?"this environment variable":"these environment variables"))),H[4]=A;'
        'else A=H[4];return A}'
    ),
    "mid-conversation-system-422-fallback": (
        'class rq extends Error{}let Yy={header:"mid-conversation-system-2026-04-07"};'
        'function pP8(H){if(!Yy)return!1;if(!(H instanceof rq)||H.status!==400)return!1;'
        'let _=H.message;if(_.includes(Yy.header)&&_.includes("anthropic-beta"))return!0;'
        'if(_.includes("Unexpected role")&&_.includes("input message role"))return!0;'
        'return _.includes("not supported")&&/role .{0,2}system/i.test(_)}'
    ),
    "anthropic-sse-error-surfacing": (
        'function s0_(H){try{return JSON.parse(H)}catch(_){return}}'
        'class mq extends Error{constructor(H,_,q,K,O){super(JSON.stringify(_));'
        'this.status=H;this.error=_;this.headers=K;this.type=O}}'
        'function iQK(H,_){let q=H.indexOf(_);if(q!==-1)return[H.substring(0,q),_,H.substring(q+_.length)];'
        'return[H,"",""]}'
        'class Dd8{constructor(){this.event=null,this.data=[],this.chunks=[]}'
        'decode(H){if(H.endsWith("\\r"))H=H.substring(0,H.length-1);'
        'if(!H){if(!this.event&&!this.data.length)return null;let O={event:this.event,data:this.data.join("\\n"),raw:this.chunks};'
        'return this.event=null,this.data=[],this.chunks=[],O}'
        'if(this.chunks.push(H),H.startsWith(":"))return null;let[_,q,K]=iQK(H,":");'
        'if(K.startsWith(" "))K=K.substring(1);'
        'if(_==="event")this.event=K;else if(_==="data")this.data.push(K);return null}}'
        'async function*lQK(H,_){yield H.nextEvent}'
        'async function*stream(H,_){for await(let $ of lQK(H,_)){'
        'if($.event==="completion")try{yield JSON.parse($.data)}catch(z){throw z}'
        'if($.event==="message_start"||$.event==="message_delta"||$.event==="message_stop"||'
        '$.event==="content_block_start"||$.event==="content_block_delta"||$.event==="content_block_stop")'
        'try{yield JSON.parse($.data)}catch(z){throw z}'
        'if($.event==="ping")continue;'
        'if($.event==="error"){let z=s0_($.data)??$.data,Y=z?.error?.type;'
        'throw new mq(void 0,z,void 0,H.headers,Y)}}}'
        'function skipFirst(H){return!1}'
        'function retryWatchdogEnabled(){return!0}'
        'function retryWatchdogError(H){return H.status===429}'
        'function shouldRetry(H){if(skipFirst(H))return!1;'
        'if(retryWatchdogEnabled()&&retryWatchdogError(H))return!0;'
        'let _=H.headers?.get("x-should-retry");if(_==="false")return!1;'
        'if(H.status===429)return!0;return!1}'
    ),
    "suppress-rate-limit-options": (
        'R.createElement(X,{a:1}),showAllInTranscript:A,'
        'agentDefinitions:B,onOpenRateLimitOptions:C,other:true'
    ),
    "thinking-visibility": (
        'case"thinking":{if(!D&&!H)return null;'
        'let T=D&&H;isTranscriptMode:D,verbose:H,hideInTranscript:T}'
    ),
    "input-box-border": (
        'createElement(T,{color:V.bgColor},"\\u2500".repeat(W));'
        'borderColor:Y(),borderStyle:"round",borderLeft:!1,borderRight:!1,'
        'borderBottom:!0,width:"100%",borderText:Z();'
        'borderStyle:"round",borderLeft:!1,borderRight:!1,borderBottom:!0,'
        'width:"100%"},x,"Save and close editor"'
    ),
    "filter-scroll-escape-sequences": (
        '#!/usr/bin/env node\n'
        '// Version 2.1.123\n'
        'console.log("ready");'
    ),
    "mcp-non-blocking": (
        'async function connect(){if(!envFlag(process.env.MCP_CONNECTION_NONBLOCKING))'
        'return await waitForServers()}'
    ),
    "mcp-batch-size": (
        'let batch=parseInt(process.env.MCP_SERVER_CONNECTION_BATCH_SIZE||"",10)||3;'
        'return batch'
    ),
    "token-count-rounding": (
        'let overrideMessage:true,count=format(inputTokens+outputTokens),'
        'view={key:"tokens"},count," tokens";'
    ),
    "statusline-update-throttle": (
        ',O=Pc.useCallback(async()=>{let D=await run();'
        'w((j)=>({...j,statusLineText:D}))},[w]),X=Gr(()=>O(A),300);'
    ),
    "statusline-update-throttle-v2": (
        ',I=xj.useCallback(async()=>{let D=await run();'
        '$(($H)=>{if($H.statusLineText===D)return $H;return{...$H,statusLineText:D}})}},[H,$]),'
        'u=Dr_(()=>{I()},300);'
    ),
    "session-memory": (
        'function enabled(){return gate("tengu_session_memory",!1)}'
        'if(gate("tengu_coral_fern",!1)){searchPastSessions()}'
        'let per=2000,total=12000;return `# Session Title`'
        'const opts={minimumMessageTokensToInit:1e4,'
        'minimumTokensBetweenUpdate:5000,toolCallsBetweenUpdates:3};'
    ),
    "remember-skill": (
        '{register({name:"claude-in-chrome",description:"Chrome"})}'
        'function loadSessionMemory(A){return []}function addCommands(){return},'
        'skillPrompt=`# Remember Skill\\nUse memories`;'
    ),
    "agents-md": (
        'async function readClaude(A,q,K){try{let z=await fs().readFile(A,{encoding:"utf-8"});'
        'return processClaude(z,A,q,K)}catch(_){return handleReadError(_,A),'
        '{info:null,includePaths:[]}}}'
    ),
    "opusplan1m": (
        'if(currentModel()==="opusplan"&&mode==="plan"&&!overLimit)return opusModel();'
        'let aliases=["sonnet","opus","haiku","sonnet[1m]","opusplan"];'
        'function desc(A){if(A==="opusplan")return"Opus 4.6 in plan mode, else Sonnet 4.6";return""}'
        'function label(A){if(A==="opusplan")return"Opus Plan";return""}'
        'function options(K,A){if(K==="opusplan")return [...A,opusPlanOption()];'
        'if(K===null||A.some((Z)=>Z.value===K))return A;}'
    ),
    "auto-accept-plan-mode": (
        'function plan(){return R.createElement(Box,'
        '{title:"Ready to code?",onChange:onPick,onCancel:onCancel})}'
    ),
    "allow-custom-agent-models": (
        ',model:z.enum(MODELS).optional();'
        'let ok=K&&typeof K==="string"&&MODELS.includes(K)'
    ),
    "patches-applied-indication": 'const version=`${pkg.VERSION} (Claude Code)`;',
    "themes": "\n".join([
        'function getNames(){return{"dark":"Dark mode","light":"Light mode"}}',
        'const themeOptions=[{label:"Dark mode",value:"dark"},'
        '{label:"Light mode",value:"light"}];',
        'function pickTheme(A){switch(A){case"light":return LX9;'
        'case"dark":return CX9;default:return CX9}}',
    ]),
    "prompt-overlays": (
        'let WEBFETCH=`Fetches URLs.\\n'
        '- For GitHub URLs, prefer using the gh CLI via Bash instead '
        '(e.g., gh pr view, gh issue view, gh api).`;'
    ),
}
