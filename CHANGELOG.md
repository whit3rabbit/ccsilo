# Changelog

All notable changes to this project will be documented in this file.

## [0.13.0] - 2026-08-31

Claude Code 2.1.248 through 2.1.252 tracking plus two darwin build fixes. Split-bundle variants could not be built at all, and repacked Mach-O binaries were killed at exec when patched modules grew the bundle section past a page.

### Added
- Added Claude Code prompt catalogs for 2.1.248, 2.1.250, 2.1.251, and 2.1.252.
- Added Claude Code patch compatibility reports for 2.1.248 through 2.1.252. Docker linux/amd64 smoke passed; 30/30 patches ok per version.

### Changed
- Variant builds on split bundles (Claude Code 2.1.242+) now always run the extract/patch/repack workflow. Both darwin fast paths only patch the entry module, which no longer holds the anchors. The unpacked Node runtime cannot resolve `/$bunfs/root/*` imports either. `bundle_is_split` routes around both.
- Widened shared and patch-specific tested ranges to 2.1.252 after Docker runtime smoke. The registry sentinel moved to 2.1.253.

### Fixed
- Fixed `hide-startup-clawd` for Claude Code 2.1.248+. Upstream hoisted the glyph tables above the render functions, so the lookback found no function. The first clawd-referencing function after the tables is now targeted; the OAuth page handler is untouched.
- Fixed `mcp-batch-size` for Claude Code 2.1.248+. The env read moved to a typed env object with a nullish coalescing default (`a.MCP_SERVER_CONNECTION_BATCH_SIZE??3`). The local default is rewritten there; the remote batch default is left alone.
- Fixed `opusplan1m` for Claude Code 2.1.251+. Upstream replaced the plan-mode gate with an alias-to-tier mapping that already handles `opusplan[1m]`. It is now recognized as native support.
- Fixed repacked Mach-O binaries being SIGKILLed at exec on arm64. Patched modules could grow the `__BUN` section past a page: `__LINKEDIT`'s fileoff moved but its vmaddr did not, leaving overlapping vm ranges that re-signing cannot repair. The vmaddr now slides by the same page delta.

## [0.12.0] - 2026-08-27

Claude Code 2.1.242 split its bundle: the ~28MB monolithic `cli` entry became a ~20KB entry plus ~1400 JS modules and 166 whole-file text modules. Everything that assumed "the entry file contains the prompts and patch anchors" broke at once; this release moves ccsilo to bundle-wide extraction and patching.

### Added
- Added Claude Code prompt catalogs for 2.1.242, 2.1.243, 2.1.245, 2.1.246, and 2.1.247.
- Added Claude Code patch compatibility reports for 2.1.242 through 2.1.247 (Docker linux/amd64 smoke passed, 30/30 patches ok per version).
- Added module-set patch application (`apply_patches_to_modules`, `Patch.apply_modules` cross-module hooks, `Patch.module_scope`) so curated tweaks apply wherever their anchors live in split bundles. Dashboard tweak builds, variant builds, patch reports, and runtime smoke all patch across every loader-js module; entry-scoped positional patches (such as `filter-scroll-escape-sequences`) still target only the entry module.

### Changed
- Prompt extraction now scans all loader-js modules for string literals, ingests loader-13 whole-file text modules as prompts (their content was previously embedded as literals in the monolithic entry), and runs catalog recovery against the combined source corpus.
- `themes` now applies when its three anchors (name map, picker options, resolver switch) live in three different modules; a resolver case-injection fallback covers variable-return switch shapes the legacy matcher rejects.
- `opusplan1m` treats 2.1.242+ as native: upstream ships the `[1m]` opusplan gate itself, so the patch layers the alias list and treats reshaped selector UI pieces as optional when the gate is already present.
- Widened shared and patch-specific tested ranges to 2.1.247 after Docker runtime smoke, with the registry sentinel moved to 2.1.248.
- Patch compatibility reports deduplicate per-module preflight warnings and classify notes-less anchor misses as `missed` instead of `no-op`.

### Fixed
- Fixed `suppress-rate-limit-options` for Claude Code 2.1.242+. The callback moved into a props-object pass-through and a compact message-item JSX call; both shapes are accepted.
- Fixed `session-memory` for Claude Code 2.1.242+. The memory-enable module lost the cowork guidelines marker, so the file-memory detector rejected it and the obsolete-gate skip never fired. Either memory marker plus the missing experiment gate now identifies the rewrite.

## [0.11.7] - 2026-08-23

### Added
- Added Claude Code prompt catalogs for 2.1.234 through 2.1.241.
- Added Claude Code patch compatibility reports for 2.1.234 through 2.1.241 (Docker smoke passed, 30/30 patches ok).

### Changed
- Updated MiniMax China defaults from `MiniMax-M2.7` to `MiniMax-M3` across all tiers; the China Anthropic-compatible endpoint now serves MiniMax-M3.
- Updated Alibaba Coding Plan defaults to `qwen3.7-plus` across all tiers, matching Alibaba's official Claude Code coding-plan guidance.
- Updated NanoGPT defaults from `moonshotai/kimi-k2.5` to `moonshotai/kimi-k3`.
- Corrected the Kimi Code provider description: `kimi-for-coding` now routes to Kimi K2.7 Code, not K2.5.
- Widened the shared tested version range and the `opencode-gateway-discovery` range to 2.1.241, with the registry sentinel moved to 2.1.242.
- Widened the `opusplan1m` tested range to cover 2.1.227-2.1.241.

### Fixed
- Fixed `hide-startup-clawd` for Claude Code 2.1.236+. Upstream redrew the head-row art from the `▛███▜` close to a `▛█` arm suffix, so the anchor missed. Both drawings are now accepted.
- Fixed `suppress-rate-limit-options` for Claude Code 2.1.235+. Upstream dropped `agentDefinitions` from the messages-list props, a third shape after the 2.1.232 reorder. All three prop orders are now accepted.
- Fixed MiniMax Anthropic passthrough in the local model proxy for cased model ids. `_is_anthropic_passthrough_backend_model` matched only lowercase `minimax-` prefixes, so registry ids like `MiniMax-M3` silently skipped passthrough and went through OpenAI chat-completions conversion instead.

## [0.11.6] - 2026-08-15

### Added
- Added Claude Code prompt catalogs for 2.1.232 and 2.1.233.
- Added Claude Code patch compatibility reports for 2.1.232 and 2.1.233 (Docker smoke passed, 30/30 patches ok), and regenerated 2.1.226 through 2.1.231.

### Changed
- Changed the Z.ai default Opus/Sonnet model to `glm-5.3[1m]`. Haiku stays `glm-4.5-air`.
- Widened the shared tested version range and the `opencode-gateway-discovery` range to 2.1.233, with the registry sentinel moved to 2.1.234.
- Widened the `opusplan1m` tested range to cover 2.1.227-2.1.233.
- Narrowed `statusline-update-throttle` to `versions_supported <=2.1.232` and widened its tested range to 2.1.232. Claude Code 2.1.233 replaced the React-hook statusline debounce with a class-based controller, so the patch now reports unsupported there instead of silently missing.

### Fixed
- Fixed `suppress-rate-limit-options` for Claude Code 2.1.232+. Upstream reordered the messages-list props from `showAllInTranscript,agentDefinitions` to `agentDefinitions,streamingToolUses,showAllInTranscript`, so the anchor missed. Both orders are now accepted.
- Corrected `docs/RELEASE.md`: pushing a tag does not publish; the release workflow triggers only on `release: published` and `workflow_dispatch`.

## [0.11.5] - 2026-08-13

### Added
- Added Claude Code prompt catalogs for 2.1.227, 2.1.228, 2.1.229, and 2.1.231.
- Added Claude Code patch compatibility reports for 2.1.227, 2.1.228, 2.1.229, and 2.1.231 (Docker smoke passed, 30/30 patches ok), and regenerated 2.1.226.

### Changed
- Widened the shared tested version range and the `opencode-gateway-discovery` range to 2.1.231, with the registry sentinel moved to 2.1.232.
- Widened the `opusplan1m` tested range to cover 2.1.227-2.1.231.

### Fixed
- Fixed `agents-md` for Claude Code 2.1.227+. Upstream gave the CLAUDE.md reader a fourth `{backend,key}` storage parameter and split the read into a backend switch and a filesystem branch, so every existing matcher missed. A new reader variant handles that shape.
- Fixed `mid-conversation-system-422-fallback` for Claude Code 2.1.228+. Upstream split the predicate into a message-only matcher plus a wrapper owning the `instanceof` and status gate. The 422 relaxation now anchors on the wrapper, keyed to `mid_conv_system` so the identically shaped `cache_control` and `thinking_signature` siblings are left untouched.
- Fixed `opusplan1m` for Claude Code 2.1.227+. Upstream added a second argument to the model-selector option-list wrapper, so the selector-option and always-show anchors missed. Trailing arguments are now tolerated and replayed.
- Fixed the `agents-md` fallback never firing on Claude Code 2.1.196-2.1.226. The reroute was wired only into the "content is null" branch, but the upstream read helper stats the path first, so a missing CLAUDE.md rejects with `ENOENT` and lands in the catch branch. The patch applied cleanly and silently never fell back to AGENTS.md. Every reader variant now reroutes from both branches through one shared helper, which also removes a hardcoded loop variable that could shadow a minified parameter.

## [0.11.4] - 2026-08-08

### Added
- Added Claude Code prompt catalogs for 2.1.223, 2.1.224, 2.1.225, and 2.1.226, and backfilled the missing 2.1.176 catalog.
- Added Claude Code patch compatibility reports for 2.1.223, 2.1.224, 2.1.225, and 2.1.226 (Docker smoke passed, 30/30 patches ok).

### Changed
- Widened the shared tested version range and the `opencode-gateway-discovery` range to 2.1.226, with the registry sentinel moved to 2.1.227.
- Regenerated the 2.1.222 patch compatibility report against the widened ranges (untested 28 -> 8).

### Fixed
- Fixed `opencode-gateway-discovery` for Claude Code 2.1.223+. Upstream dropped the leading `^` from the gateway model filter (`/^(claude|anthropic)/i` -> `/(claude|anthropic)/i`), so the anchor missed and aborted smoke at the patch stage. The anchor now accepts both shapes and reuses the matched regex literal in the non-gateway fallback branch.
- Fixed `allow-custom-agent-models` for Claude Code 2.1.224+. Upstream moved the Task tool schema to zod-mini helper calls, emitting `z.enum([...])` as a bare `Nr(["sonnet","opus","haiku","fable"])` and `z.string()` as `N()`, so all three existing matchers missed. A new branch recovers the string helper from a sibling field in the same schema literal instead of guessing the minified name.

## [0.11.3] - 2026-08-04

### Added
- Added Claude Code prompt catalogs for 2.1.219, 2.1.220, and 2.1.221.
- Added Claude Code patch compatibility reports for 2.1.219, 2.1.220, and 2.1.221 (Docker smoke passed, 30/30 patches ok).

## [0.11.2] - 2026-07-22

### Added
- Added Claude Code prompt catalogs for 2.1.217 and 2.1.218.
- Added Claude Code patch compatibility reports for 2.1.217 and 2.1.218 (Docker smoke passed, 30/30 patches ok).

### Changed
- Widened `session-memory` `versions_tested` to cover the new file-memory era (`>=2.1.216,<=2.1.218`), proven by Docker runtime smoke.

### Fixed
- Fixed `session-memory` for Claude Code 2.1.217+. Upstream reintroduced `tengu_session_memory_*` telemetry event names (rated, deleted, viewer_opened, ...). The new-file-memory-system detector keyed on a bare `tengu_session_memory` substring, so the telemetry names made it return False, the obsolete-gate skip path stopped firing, and the past-sessions/token-limit/threshold sub-patches hard-failed (`status=missed`, smoke error at the patch stage). The detector now matches the `("tengu_session_memory",!1)` gate-call form, which telemetry names never carry.

## [0.11.1] - 2026-07-20

### Added
- Added Claude Code prompt catalog and patch compatibility report for 2.1.216 (Docker smoke passed, 30/30 patches ok).

### Fixed
- AnyLLM local proxy: skip the credential-env require guard when a local proxy is configured. The proxy generates its own inbound key (`localProxy.key`) and exports the auth token itself, so `: ${ANYLLM_PROXY_KEY:?...}` wrongly blocked wrapper startup.
- AnyLLM local proxy: make the listen port overridable at launch via `ANYLLM_PROXY_PORT` (or `LISTEN_PORT`), defaulting to the manifest port. Export `LISTEN_PORT` so `anyllm-proxy` binds to the port the wrapper probes and points `ANTHROPIC_BASE_URL` at. Host stays loopback-only.

## [0.11.0] - 2026-07-19

### Added
- AnyLLM proxy provider (`anyllm`): a local `anyllm-proxy` gateway that bridges Claude Code to any OpenAI-compatible backend, local LLM, or provider, with runtime gateway model discovery.
- Full managed AnyLLM integration in the setup TUI (parallel to CCR): AnyLLM status, Start, Stop, Restart, Open AnyLLM UI, and Copy admin token. Because `anyllm-proxy` is foreground-only with no daemon/pid/CLI, ccsilo supervises the process itself (detached launch, own pid file, `/health` detection, reuse of an already-running proxy). The admin web UI token is read from `~/.anyllm/.admin_token` (honors `ADMIN_TOKEN`/`ANYLLM_HOME`/`ADMIN_TOKEN_PATH`) and surfaced in the Open UI / Copy token actions.
- `anyllm-running` and `anyllm-admin-token` doctor checks (informational; the proxy is on-demand and the token is created on first run).

### Changed
- Pinned `anyllm-proxy` to 0.16.0 and use the hyphenated installed binary name `anyllm-proxy` (the crate stays `anyllm_proxy`; Homebrew/deb/release archives ship the hyphenated executable since 0.12.0).
- AnyLLM provider env now matches ccrouter for the common Claude Code toggles (`DISABLE_TELEMETRY`, `DISABLE_COST_WARNINGS`) alongside its longer `API_TIMEOUT_MS`.

## [0.10.3] - 2026-07-19

### Added
- Added Claude Code patch compatibility reports for 2.1.214 and 2.1.215 (Docker smoke passed, 30/30 patches ok).

### Changed
- Widened the shared tested version range to include 2.1.214 and 2.1.215, with the registry sentinel moved to 2.1.216.

## [0.10.2] - 2026-07-17

### Added
- Added Claude Code prompt catalogs for 2.1.211, 2.1.212, and 2.1.213.
- Added Claude Code patch compatibility reports for 2.1.211, 2.1.212, and 2.1.213 (Docker smoke passed, 30/30 patches ok).

### Changed
- Widened the shared tested version range to include 2.1.211 through 2.1.213, with the registry sentinel moved to 2.1.214.

### Fixed
- Fixed `mcp-batch-size` for Claude Code 2.1.211+. Upstream routes the batch-size env value through a minified int helper (e.g. `zl(process.env.MCP_SERVER_CONNECTION_BATCH_SIZE)`) instead of inline `parseInt(...||"",10)`, so the anchor missed; `mcp-batch-size` defaults to fatal-on-miss and aborted smoke at the patch stage. The regex now matches both the inline radix and the helper-call shapes.
- Fixed `opencode-gateway-discovery` for Claude Code 2.1.212+. Upstream reads env vars through a minified namespace (e.g. `Z.ANTHROPIC_BASE_URL`) instead of `process.env.`, so the base-URL lookback missed. The lookback now tolerates either accessor.
- Fixed `mid-conversation-system-422-fallback` for Claude Code 2.1.212+. Upstream moved the anthropic-beta header probe into a minified helper call (e.g. `BQn(t,e3)`) instead of the inline `t.includes(X.header)&&t.includes("anthropic-beta")`, so the predicate anchor missed. The clause now matches either the inline probe or a bare helper call.

## [0.10.1] - 2026-07-14

### Added
- Added Claude Code prompt catalogs for 2.1.209 and 2.1.210.
- Added Claude Code patch compatibility reports for 2.1.209 and 2.1.210 (Docker smoke passed, 30/30 patches ok).

### Changed
- Widened the shared tested version range to include 2.1.208 through 2.1.210, with the registry sentinel moved to 2.1.211.

### Fixed
- Synchronized `ccsilo/_version.py` with `pyproject.toml`. The 0.10.0 bump had left `__version__` at 0.9.2, failing `test_runtime_version_matches_pyproject`.

## [0.10.0] - 2026-07-13

### Fixed
- Pinned managed ccrouter to `@musistudio/claude-code-router@1.0.73` instead of `@latest`. claude-code-router 3.x (published 2026-07) is a rewrite that tracks the running service in `service.json` rather than a `.claude-code-router.pid` file, picks its own gateway port and ignores `config.json` `PORT`, and stores config in sqlite. The managed integration's pid-file detection, PORT-in-config, and `ANTHROPIC_BASE_URL` wiring only work with the 1.x-2.x model, so `@latest` resolving to 3.x made new ccrouter variants fail to autostart (`CCR service is not running`, exit 127).

### Added
- Added a `ccrouter-version` doctor check that fails when an installed ccr major is `>= 3`, pointing users at the pinned package.

## [0.9.2] - 2026-07-13

### Added
- Added Claude Code prompt catalog for 2.1.208.
- Added Claude Code patch compatibility report for 2.1.208 (Docker smoke passed, 30/30 patches ok).

### Fixed
- Fixed `agents-md` for Claude Code 2.1.208. Upstream rewrote the CLAUDE.md reader: it added a `dir` flag set from an `isDirectory()` callback passed to the read helper, and turned the `null` branch into a logging block instead of a bare return, so all four existing matchers missed and the patch (and full-set boot smoke) failed. Added an `_apply_async_dir` matcher for the new shape. Its fallback result variable is now chosen to avoid the reader's parameters, since 2.1.208 minifies the third parameter to `r`, which would collide with the hardcoded loop variable and throw a TDZ `ReferenceError` (silently swallowed by the surrounding try/catch, leaving the reroute dead).

## [0.9.1] - 2026-07-11

### Added
- Added Claude Code prompt catalog for 2.1.207.
- Added Claude Code patch compatibility report for 2.1.207 (Docker smoke passed, 30/30 patches ok).

### Changed
- Bumped shared tested version range to include 2.1.207.

### Fixed
- Fixed `mid-conversation-system-422-fallback` for Claude Code 2.1.207. Upstream inserted a new `cache_control` clause between the "input message role" check and the final "not supported" return in the 400-class fallback predicate, so the anchor missed and the patch stopped applying (applied cleanly through 2.1.206). Widened the anchor to tolerate any brace-free `if(...)return!0;` clauses before the final return; older versions still match via zero-or-more.

## [0.9.0] - 2026-07-10

### Added
- Added Claude Code prompt catalogs for 2.1.203, 2.1.204, 2.1.205, and 2.1.206.
- Added Claude Code patch compatibility reports for 2.1.204, 2.1.205, and 2.1.206 (Docker smoke passed, 30/30 patches ok).

### Changed
- Bumped shared tested version range to include 2.1.206.

### Fixed
- Fixed `auto-accept-plan-mode` for Claude Code 2.1.206. React-compiler memoization inlined the proceed handler as `onChange:(v)=>void <fn>(v)` and added a review branch whose bare `onChange:<ident>` was matched first, while the pre-title `return` used for injection was gone. Added an inline path that extracts the underlying handler and short-circuits the component's terminal `return`, keeping the legacy path unchanged for <=2.1.205.

## [0.8.3] - 2026-07-07

### Added
- Added Claude Code patch compatibility reports for 2.1.202 and 2.1.203 (Docker smoke passed, 30/30 patches ok).

### Changed
- Bumped shared tested version range to include 2.1.203.

### Fixed
- Fixed `thinking-visibility` for Claude Code 2.1.203, whose minifier changed the thinking-render gate from `if(C)return null;` to `if(C){return null}`. The hard-coded `return null;` anchor caused a runaway regex match that spliced `isTranscriptMode:true,` into an unrelated function's parameter list, failing boot smoke with a `SyntaxError`.

## [0.8.2] - 2026-07-04

### Added
- Added Claude Code patch compatibility reports for 2.1.199, 2.1.200, and 2.1.201 (Docker smoke passed, 30/30 patches ok).

### Changed
- Bumped shared tested version range to include 2.1.201.

## [0.8.1] - 2026-07-02

### Added
- Added prompt catalog and patch compatibility report for Claude Code 2.1.198.

### Changed
- Bumped shared tested version range to include 2.1.198.
- Widen agents-md async WN regex to handle cross-platform minification differences (linux-x64 vs darwin-arm64).
- no-prompt-steganography now gracefully returns `skipped` for >= 2.1.198 where Anthropic removed the steganography function upstream after detection.

## [0.8.0] - 2026-06-30

### Added
- Added `no-prompt-steganography` curated tweak that removes invisible Unicode fingerprinting from the system date prompt.
- Regenerated 2.1.186 patch compatibility report with the new patch passing (30/30 patches ok).

## [0.7.3] - 2026-06-27

### Added
- Added Claude Code prompt catalogs and patch compatibility reports for 2.1.190, 2.1.191, 2.1.193, and 2.1.195 (Docker smoke passed, 29/29 patches ok).
- Added a `model-proxy-import` variant doctor check that verifies the variant's Python can import `ccsilo.model_proxy` from a neutral working directory, catching moved/renamed editable installs before the proxy fails at launch.

### Changed
- Bumped shared and patch-specific `versions_tested` ranges to 2.1.195.

### Fixed
- Model proxy now swallows client disconnect errors (`BrokenPipeError`/`ConnectionResetError`) when Claude Code drops mid-response, preventing log-flooding tracebacks and a double-fault on the 502 error path.

## [0.7.2] - 2026-06-23

### Added
- Added Claude Code prompt catalogs and patch compatibility reports for 2.1.186 and 2.1.187.
- Added MCP tool timeout defaults.

### Changed
- Widened curated patch tested ranges through Claude Code 2.1.187 after Docker runtime smoke.

### Fixed
- Fixed `suppress-rate-limit-options` for Claude Code's JSX runtime render shape.

## [0.7.1] - 2026-06-21

### Added
- Added Claude Code 2.1.185 patch compatibility report with Docker runtime smoke evidence.

### Changed
- Widened curated patch tested ranges through Claude Code 2.1.185 after Docker runtime smoke.

### Fixed
- Fixed model proxy variants preserving stale Python interpreter paths across setup rebuilds.

## [0.7.0] - 2026-06-17

### Added
- Added Claude Code prompt catalogs for 2.1.179 and 2.1.181.
- Added latest Claude Code patch compatibility artifacts through 2.1.181.

### Changed
- Widened curated patch tested ranges through Claude Code 2.1.181 after Docker runtime smoke.

### Fixed
- Fixed `token-count-rounding` for Claude Code 2.1.179's arrow statusline token display.
- Bounded token-count fallback matching to avoid runaway regex scans on no-match bundles.

## [0.6.6] - 2026-06-13

### Added
- Added a `compact-window` environment tweak and `--compact-window` variant option for `CLAUDE_CODE_AUTO_COMPACT_WINDOW`.

### Changed
- Updated Z.ai defaults to GLM-5.2[1m] for Opus and Sonnet mappings.
- Updated MiniMax Cloud defaults to MiniMax-M3 and set provider compact-window defaults.

## [0.6.5] - 2026-06-13

### Added
- Improved release automation: updated `.github/workflows/release.yml` to automatically build, publish to PyPI, and upload distributions to the GitHub Release when a Release is published.

### Fixed
- Robustness improvements for variant configuration and model updates:
  - Ensured variant model updates call `_write_settings_config` to sync settings properly.
  - Preserved user-defined environment variables in variant settings.
  - Omitted `export ANTHROPIC_MODEL` in wrappers when using Architect mode (`opusplan1m` tweak) so the silo default model configuration wins.
  - Cleaned up statusline configuration dynamically when disabling the statusline tweak.

## [0.6.4] - 2026-06-08

### Added
- Improved latest version selection and created preview install UX.
- Refactored patch compatibility workflow.

## [0.6.3] - 2026-05-30

### Added
- Hardened prompt metadata review checks.
- Updated Architect Mode model picker and patch report index.

## [0.6.2] - 2026-05-20

### Added
- Support for Claude Code 2.1.172.

## [0.6.1] - 2026-05-10

### Added
- Organized provider selector by type.
- Added input border patch and startup banner anchor fixes for Claude Code 2.1.167.

## [0.6.0] - 2026-04-28

### Added
- Added tweak to hide the npm deprecation warning in newer Claude Code native binaries.
