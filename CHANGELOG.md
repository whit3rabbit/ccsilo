# Changelog

All notable changes to this project will be documented in this file.

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
