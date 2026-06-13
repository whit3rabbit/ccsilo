`ccsilo` is a Python toolkit for isolated Claude Code silos with provider-specific patching, binary inspection, extraction, repacking, and setup management.

Use this repository for research and controlled local patching only. Do not add behavior that silently mutates user-global Claude Code state unless that workflow explicitly owns the config write.

## Current Product Surface

1. Binary tooling: download, inspect, extract/unpack, replace entry JS, apply binary-level theme and prompt patches, and repack.
2. Setup management: create isolated provider variants with model overrides, credentials, wrappers, optional MCP servers, ccrouter support, model proxy support, and curated tweaks.
3. TUI workflow: manage setups, build patched binaries from curated tweaks, inspect/download artifacts, extract bundles, and apply workspace patch packages.
4. Release tracking: extract prompt catalogs and generate Docker-backed patch compatibility reports.

## Versioned Compatibility Notes

### OpenCode Go / Zen

OpenCode Go and OpenCode Zen should use the managed local `openai` model
proxy by default. Claude Code speaks Anthropic Messages, while OpenCode's
DeepSeek and related model routes are OpenAI-compatible chat completions
underneath. Do not solve OpenCode breakage by sending Claude Code directly to
OpenCode's `/v1/messages` bridge or by adding `opencode-go/` or `opencode/`
prefixes to backend API model ids.

OpenCode backend model ids in provider JSON are raw OpenCode API ids such as
`deepseek-v4-pro`, `deepseek-v4-flash`, `big-pickle`, and
`deepseek-v4-flash-free`. The local proxy advertises Claude Code-facing
gateway ids as `anthropic/<provider-key>/<provider-model>` and decodes them
before forwarding. The wrapper passes `OPENCODE_API_KEY` only to the proxy
process, the proxy forwards it upstream as bearer auth, and the wrapper unsets
Claude-facing API key env vars before launching Claude Code.

The local proxy implementation is `ccsilo/model_proxy.py`; provider-specific
model discovery and gateway-id helpers live under `ccsilo/providers/proxy/`.
Variant wrappers start the proxy before launching Claude Code, point
`ANTHROPIC_BASE_URL` at `http://127.0.0.1:<port>/<nonce>`, and stop the proxy
with the wrapper's exit trap. The proxy is stdlib-only, loopback-only,
nonce-gated, size/timeout bounded, and scoped to the wrapper lifetime.

Proxy compatibility is deliberately narrow. `mode=architect` supports Claude
OAuth planner routing plus a backend provider for non-Claude worker models.
`mode=openai` supports backend-only Anthropic Messages to OpenAI-compatible
chat-completions conversion, including `/v1/models`, `/v1/models/<id>`,
non-streaming responses, SSE streaming responses, tool definitions/tool calls,
basic thinking/reasoning content, and cache-token usage mapping. It is not a
general-purpose OpenAI gateway and should not grow dependencies or provider SDKs
without explicit approval.

Keep `opencode-gateway-discovery` as built-in provider compatibility. It must
expose raw OpenCode and local proxy model-list entries without prefixing them,
and OpenCode variants should not select `opusplan1m` by default because
OpenCode does not advertise `[1m]` suffixed model ids.

### 0.4.8

Claude Code 2.1.154 / Opus 4.8 can emit mid-conversation system messages as
`messages[].role = "system"` when the Anthropic API supports that feature.
Anthropic documents this as a Claude API feature, but third-party
Anthropic-compatible gateways can lag that surface.

Z.ai is configured through an Anthropic Messages endpoint
(`https://api.z.ai/api/anthropic`) and worked for normal Claude Code prompts
after `mid-conversation-system-422-fallback` was added. The observed breakage
was not a prompt overlay issue: Z.ai rejected `role: "system"` inside
`messages[]` with HTTP 422 and a literal-role validation error, while Claude
Code's bundled fallback recognized only narrower 400-class rejections.

Treat this class of patch as built-in provider compatibility, not as an
optional visual or prompt tweak. Keep it hidden from Dashboard, keep the
predicate narrow to explicit `role/system/user/assistant` 422 validation
failures, and prefer enabling it automatically for affected third-party
Anthropic-compatible providers over asking users to select it manually. Do not
solve this by changing provider prompt overlays or disabling all experimental
betas unless a concrete version proves that is necessary.

### Opus 4.8 Thinking Blocks

Claude Opus 4.8 uses adaptive thinking, not manual `budget_tokens` extended
thinking. Its default thinking display is omitted: streaming responses can open
a `thinking` block, emit only a `signature_delta`, and close the block without
any `thinking_delta` text. Treat signed empty `thinking` blocks as real
thinking blocks.

Anthropic can also return `redacted_thinking` blocks. They are opaque encrypted
thinking content and must be round-tripped unchanged when continuing Claude
tool-use conversations through an Anthropic-compatible Claude route. If
`model_proxy.py` intentionally strips thinking before sending history to a
non-Claude backend or after mixing backend and Claude planner turns, strip both
`thinking` and `redacted_thinking`; do not forward redacted Anthropic-only
blocks to unrelated backend providers.

### Anthropic-Compatible SSE Errors

Some third-party Anthropic-compatible streaming endpoints can return `HTTP 200`
with `Content-Type: text/event-stream`, then send a terminal `event: error`
payload instead of an HTTP error status. Treat this as protocol-compatible but
provider-hostile to Claude Code's retry UI when the stream is not cleanly
terminated.

The `anthropic-sse-error-surfacing` patch is built-in provider compatibility.
It detects Anthropic-style SSE error payloads
(`{"type":"error","error":{...}}`), emits them as soon as the JSON payload is
readable, maps known Anthropic error types to status-like API errors, and marks
that terminal stream error as non-retryable before Claude Code's 429 retry
watchdog runs. It also treats explicit quota-exhausted, balance-exhausted,
account-locked, plan-expired, or plan-ineligible Anthropic-compatible 429
bodies as non-retryable while leaving ordinary transient 429s retryable. Keep
it provider-generic for
Anthropic-compatible endpoints such as Z.ai and MiniMax; do not make it a
Z.ai-branded quota patch.

### Z.ai Troubleshooting

When Z.ai quota is exhausted, Claude Code can surface the failure as retrying
timeouts such as `Retrying in 1s ... API_TIMEOUT_MS=3000000ms` instead of
showing the upstream reason. The observed upstream shape was `HTTP 200` with an
SSE `event: error` payload containing `rate_limit_error` code `1310` and a
weekly/monthly limit reset timestamp. Non-streaming requests can instead return
the same Anthropic error body with an HTTP 429 status.

Z.ai's documented transient 429s include high concurrency, high request
frequency, rate limit, and high traffic. Keep those retryable. Treat account
balance exhaustion, account lock/anomaly, daily call limits, package expiry,
weekly/monthly exhaustion, plan ineligibility, and Fair Use restrictions as
non-retryable in Claude Code's retry predicate.

MiniMax documents `base_resp.status_code` values on Anthropic-compatible
responses. Preserve retries for `1002` rate limit, but do not spin on account
state or quota-like failures such as `1008` insufficient balance and `2056`
usage limit exceeded.

Use `/v1/messages` for request-path diagnostics; `max_tokens: 1` may consume a
tiny amount if quota is available:

```bash
curl -sS -D - \
  -H "x-api-key: $Z_AI_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  https://api.z.ai/api/anthropic/v1/messages \
  --data '{"model":"glm-5-turbo","max_tokens":1,"stream":true,"messages":[{"role":"user","content":"hi"}]}'
```

`/v1/models` only proves auth and model discovery; it does not prove request
quota is available.

Do not route Z.ai through `model_proxy.py` by default to fix timeout-looking
quota failures. The current proxy is not a generic Anthropic-compatible gateway
normalizer: `openai` mode is for OpenAI chat-completions conversion, and
`architect` mode requires a Claude planner route and does not currently
normalize Anthropic SSE error events. If a future Claude Code change requires
proxying Z.ai, implement a narrow Z.ai-specific normalization path with tests
before changing provider defaults.

## Commands

Use `.venv/bin/python` from the repository root.

```bash
# Install for development
.venv/bin/python -m pip install -e '.[dev]'

# Open the TUI
.venv/bin/python -m ccsilo

# Binary / bundle commands
.venv/bin/python -m ccsilo download [version]
.venv/bin/python -m ccsilo download --latest
.venv/bin/python -m ccsilo download --npm [version]
.venv/bin/python -m ccsilo inspect <binary> --json
.venv/bin/python -m ccsilo extract <binary> [outdir] [--source-version <version>] [--include-sourcemaps]
.venv/bin/python -m ccsilo unpack <binary> --out <dir>
.venv/bin/python -m ccsilo replace-entry <binary> <entry-js> --out <binary>
.venv/bin/python -m ccsilo apply-binary <binary> --config <config.json> [--overlays <overlays.json>]
.venv/bin/python -m ccsilo pack <dir> <base-binary> <out-binary>

# Legacy extracted-bundle patch manifests
.venv/bin/python -m ccsilo patch init <patch-dir>
.venv/bin/python -m ccsilo patch apply <patch-dir> <extract-dir> [--check] [--binary <binary>] [--source-version <version>]

# Provider shortcut commands
.venv/bin/python -m ccsilo --provider <key>
.venv/bin/python -m ccsilo --provider <key> install [--credential-env <ENV_NAME>] [--api-key <key> --store-secret] [--json]
.venv/bin/python -m ccsilo --provider <key> update [--claude-version <v>] [--json]
.venv/bin/python -m ccsilo --provider <key> uninstall --yes [--json]
.venv/bin/python -m ccsilo paths [--json]
.venv/bin/python -m ccsilo uninstall --yes [--json]

# Setup / variant commands
.venv/bin/python -m ccsilo variant providers [--json | --ascii-art | --quote-blocks]
.venv/bin/python -m ccsilo variant mcp [--provider <key>] [--json]
.venv/bin/python -m ccsilo variant create --name <name> --provider <key> [--claude-version <v>] [--patch-profile <id>] [--tweak <id> ...]
.venv/bin/python -m ccsilo variant create --name <name> --provider <key> --credential-env <ENV_NAME>
.venv/bin/python -m ccsilo variant create --name <name> --provider <key> --api-key <key> --store-secret
.venv/bin/python -m ccsilo variant install <name-or-id> [--alias <cmd>] [--json]
.venv/bin/python -m ccsilo variant list [--json]
.venv/bin/python -m ccsilo variant show <name-or-id> [--json]
.venv/bin/python -m ccsilo variant apply <name-or-id> [--json]
.venv/bin/python -m ccsilo variant update [<name-or-id> | --all] [--claude-version <v>] [--json]
.venv/bin/python -m ccsilo variant doctor [<name-or-id> | --all] [--json]
.venv/bin/python -m ccsilo variant remove <name-or-id> [--yes]
.venv/bin/python -m ccsilo variant run <name-or-id> -- [args...]

# Test / lint
.venv/bin/python -m pytest -q
ruff check ccsilo tests tools
ruff check --fix ccsilo tests tools
```

Do not document `python main.py ...` as canonical unless `main.py` is restored. Treat `ccsilo/cli/parsers.py` and `ccsilo/__main__.py` as the command source of truth.

## Prompt Catalogs And Patch Reports

Prompt catalogs live in `prompts/<version>.json`. Patch compatibility reports live in `reports/patch-compat/<version>.json`, with the latest run index in `reports/patch-compat/index.json`.

Preferred commands:

```bash
# Prompt catalogs
.venv/bin/python tools/extract_prompt_versions.py --since-existing-latest
.venv/bin/python tools/extract_prompt_versions.py --missing
.venv/bin/python tools/extract_prompt_versions.py --versions <v1> <v2> --force-prompts

# Patch reports
.venv/bin/python tools/check_patch_releases.py --since-existing-latest
.venv/bin/python tools/check_patch_releases.py --latest
.venv/bin/python tools/check_patch_releases.py --versions <v1> <v2> [--run-smoke]

# Reproducible Linux runtime smoke
tools/run_patch_smoke_docker.sh --since-existing-latest --run-smoke --smoke-timeout 60
tools/run_patch_smoke_docker.sh --all --max-versions 10 --run-smoke --smoke-timeout 60
```

Rules:

* Prefer `--since-existing-latest` after upstream releases and `--missing` for gap filling.
* Validate generated prompt files before writing. Treat review-only prompt metadata candidates as release blockers unless explicitly resolved. Use `tools/suggest_prompt_metadata.py --update-target --fail-on-review-needed` for release-prep runs; leave `no_candidate` extras unnamed unless a verified catalog match exists.
* Commit prompt JSON updates separately from unrelated patch, TUI, or feature changes.
* Use Docker smoke for committed patch reports. It defaults to `DOCKER_PLATFORM=linux/amd64` and writes reports to `reports/patch-compat`.
* `tools/check_patch_releases.py --latest` rewrites `reports/patch-compat/index.json` with only the versions processed in that run. If the index should keep multiple latest reports, run those versions together with `--versions <latest> <previous> --run-smoke`.
* If `tools/run_patch_smoke_docker.sh` stalls while loading Docker base-image metadata and `ccsilo-patch-smoke:local` already exists, you can run the local image directly for verification:
  `docker run --rm --platform linux/amd64 --user "$(id -u):$(id -g)" -e CCSILO_WORKSPACE=/work/.ccsilo/docker-linux -e HOME=/tmp/ccsilo-home -v "$PWD:/work" ccsilo-patch-smoke:local --versions <v1> <v2> --run-smoke --smoke-timeout 60`.
* Do not commit `.ccsilo/`.
* Runtime smoke must prove Claude Code booted. `<binary> --version` must contain the expected Claude Code version, not only a Bun runtime version.
* If the unpatched baseline repack does not boot, fix extract/repack infrastructure before blaming a patch.
* Passing smoke reports are proof for that report artifact only. Do not widen `versions_tested` until tests or targeted real-version reports prove that concrete Claude Code version.
* When widening tested patch ranges after a real-version smoke, update both shared defaults in `ccsilo/patches/_pinned_default.py` and any patch-specific `versions_tested` ranges. Keep unsupported patches such as `remember-skill` untested on versions outside their `versions_supported`.

## CI And Release

GitHub Actions:

* `.github/workflows/ci.yml` runs on push, pull request, and manual dispatch. It installs `.[dev]`, runs `ruff check ccsilo tests tools`, runs `pytest -q`, builds a wheel, installs it in a clean venv, and smoke-checks `ccsilo --help` plus `ccsilo variant providers --json`.
* The `CI` workflow has an optional manual Docker patch smoke job controlled by `run_docker_smoke`.
* `.github/workflows/update-prompts.yml` is the daily release-tracking workflow. It updates prompt catalogs, runs Docker patch smoke for releases newer than the newest local report, validates prompt/report tooling, and commits prompt/report changes.
* `.github/workflows/release.yml` automatically builds, publishes to PyPI, and uploads built distribution assets to the GitHub Release when a Release is published. It can also be run manually via `workflow_dispatch` to publish to PyPI and create/update the GitHub Release.

Release rules:

* PyPI publishing uses Trusted Publishing. Do not store PyPI API tokens.
* TestPyPI and PyPI environments must be named `testpypi` and `pypi`; require manual approval on `pypi`.
* Dispatch `Release` with `repository=testpypi` before the first real upload for a version.
* Publish to real PyPI and GitHub Releases by publishing a release on GitHub, or by manually dispatching `Release` with `repository=pypi` from the exact `v<pyproject.toml version>` tag.
* Derive release tags from `pyproject.toml`, do not hand-type them:
  `VERSION="$(.venv/bin/python -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"; TAG="v${VERSION}"`
* Update `CHANGELOG.md` with release notes before pushing a new release.
* PyPI versions are immutable. If a real upload succeeds or partially creates a version, bump `pyproject.toml` before trying again.
* After publishing, verify `pipx install ccsilo`, `ccsilo --help`, and `ccsilo variant providers --json`.
* Keep `docs/RELEASE.md` synchronized with the workflow.

Before committing and pushing, pull/rebase against upstream and rerun relevant checks. Daily release-tracking may commit prompt catalogs or patch reports while local work is in progress.

## Architecture Map

```text
__main__.py                  -> CLI entrypoint, provider shortcuts, variant dispatcher, TUI launch
cli/parsers.py               -> argparse tree only
cli/handlers.py              -> top-level non-variant handlers
cli/payloads.py              -> JSON payload helpers and variant argument mappers

bun_extract/                 -> Bun standalone parser, extract, replacement, binary metadata
binary_patcher/              -> Native binary patching, entry replacement, platform repack, codesign, unpacked fallback
patches/                     -> Curated regex-tweak registry. See ccsilo/patches/AGENTS.md before editing patches.
patch_workflow.py            -> Native artifact workflows for patch packages and dashboard tweak builds
patcher.py                   -> Legacy extracted-text patch manifest workflow

providers/registry/<key>/provider.json -> Provider templates
providers/schema.py          -> Provider JSON schema validation/deserialization
providers/loader.py          -> Provider lookup, env building, theme/prompt overlay helpers
providers/config.py          -> Claude config merges for settings permissions and MCP servers
providers/mcp_catalog.py     -> Optional MCP catalog and plugin recommendations
providers/model_discovery.py -> OpenAI-compatible model-list fetching
providers/proxy/             -> Model proxy provider adapters for discovery, gateway ids, and provider quirks
model_proxy.py               -> Stdlib-only local proxy for Architect OAuth routing and OpenAI-compatible backend conversion

variants/                    -> Setup/variant lifecycle, build, install, ccrouter, model updates, wrapper writing
variants/model.py            -> Variant dataclasses and manifest validation authority
variants/tweaks.py           -> Curated tweak selection, env-only tweaks, prompt-only tweaks
variant_tweaks.py            -> Backwards-compatible shim over variants.tweaks

workspace/                   -> Workspace paths, models, artifact scanning, profiles, TUI settings
tui/                         -> TUI state, rendering, navigation, dashboard, setup actions, keys, themes
download_index.py            -> Cached live/seed version index
download_picker.py           -> Interactive version picker
downloader.py                -> Native and NPM download logic
extractor.py                 -> Compatibility wrapper over bun_extract
bundler.py                   -> Compatibility wrapper over binary_patcher.repack_binary
_utils.py                    -> stdlib-only helpers shared across modules
```

## Workspace Layout

Default workspace root is the platform user data directory (`~/Library/Application Support/ccsilo` on macOS, `${XDG_DATA_HOME:-~/.local/share}/ccsilo` on Linux, `%APPDATA%\ccsilo` on Windows), unless `CCSILO_WORKSPACE` is set.

```text
.ccsilo/
  downloads/native/
  downloads/npm/
  extractions/native/
  patches/packages/
  patches/profiles/
  patches/tweak-profiles/
  patched/native/
  variants/
  bin/
  tmp/
  tui-settings.json
```

Important distinctions:

* `patches/packages/` stores workspace patch package manifests and operations.
* `patches/profiles/` stores patch-package profile refs.
* `patches/tweak-profiles/` stores Dashboard curated tweak profile refs.
* `variants/<id>/variant.json` is the setup manifest.
* `variants/<id>/secrets.env` may exist only when the user explicitly uses stored credentials. Secrets files must be regular, owner-owned, non-symlink files with mode `0600`.
* `bin/` stores wrapper commands.

## Binary And Patch Invariants

* `parse_bun_binary` is the single source of truth for binary layout.
* Use `info.entry_point_id` to find the entry module. Do not assume entry names like `claude` or `cli.js`.
* Bun module bytes use `cont_off` and `cont_len`; do not invent `data_offset` or `data_size`.
* Manifest `name` is the sanitized display/extract path. Manifest `rawName` is the runtime Bun module name and may include `/$bunfs/root/`. Repacking must preserve `rawName`.
* Manifest offsets such as `nameOffset`, `contentOffset`, `bytecodeOffset`, and `execArgvOffset` are relocation inputs, not decorative metadata.
* Real ELF payloads can contain unreferenced prefix bytes before the first module name. When a base binary is available, use the base payload as the template and replace relocated ranges.
* On Mach-O, prompt overlays that grow the entry module must force the unpacked Node runtime fallback even if later shrink tweaks make the final byte length fit.
* Mach-O repacking must preserve and relocate non-signature `__LINKEDIT` data. The `__BUN` section starts with an 8-byte size header for the full inner payload.
* After Mach-O repack changes, check `otool -l <binary>` for `past end of file`, run `codesign --verify --strict --verbose=4 -- <binary>` after ad-hoc signing, and verify `--version`.
* Bun CJS entry modules must keep a valid `// @bun ... @bun-cjs` function wrapper. Inject runtime code inside the existing wrapper, immediately after the opening `{`.
* `extractor.py` and `bundler.py` are compatibility wrappers, not independent implementations.
* Keep `patcher.py` separate from `binary_patcher`; it handles legacy extracted-text patch manifests.
* `ccsilo.patches.apply_patches` applies curated regex tweaks.
* `ccsilo.binary_patcher.index.apply_patches` applies binary theme/prompt patches.
* `patch_workflow.apply_patch_packages_to_native` extracts, applies workspace patch packages, repacks, and writes patched metadata.
* `patch_workflow.apply_dashboard_tweaks_to_native` applies curated tweak IDs directly for Dashboard builds.
* Theme anchor misses are fatal structured failures. Prompt anchor misses are recorded and non-fatal.
* Text-level parse tests are not enough for entry patches that change byte length or wrapper shape. Pair anchor tests with Docker runtime smoke before using a report as release signal.
* Unpacked Node runtime entry JS must pass through `binary_patcher.bun_compat.ensure_bun_node_compat` after stripping the Bun wrapper and after later variant-only JS tweak writes. Preserve the `ccsilo:bun-node-compat` marker.
* `variant doctor` includes a `node-bun-compat` check for stale Node-runtime entries that still reference `Bun.*` without the compat marker.
* PE resize requires `.bun` to be the last raw-data section.
* On non-Windows, written binaries and wrappers should be executable.

## Providers And Variants

* Provider definitions live in `providers/registry/<provider-key>/provider.json`.
* Validate provider JSON through `providers/schema.py`; unknown schema keys are errors.
* The provider loader recursively reads JSON under `providers/registry/`. Keep each active provider manifest named `provider.json` under its provider-key directory.
* Build runtime env through `build_provider_env`; do not hand-roll provider env dictionaries.
* Provider auth modes are `apiKey`, `authToken`, and `none`.
* Provider templates may define model mappings, prompt overlays, themes, denied tools, MCP servers, setup links, TUI metadata, and model discovery.
* Providers with `tui.modelDiscovery.enabled` must export `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` unless a provider intentionally overrides it.
* Registry JSON may select model proxy mode, backend format, and auth with `modelProxy`, but provider-aware parsing and gateway-id behavior belongs under `providers/proxy/`.
* Keep `model_proxy.py` stdlib-only. Do not add LiteLLM, FastAPI, httpx, OpenAI SDK, or Pydantic dependencies to the local proxy without explicit approval.
* The local model proxy supports `architect` mode for Claude OAuth planner routing and `openai` mode for backend-only Anthropic Messages to OpenAI chat-completions conversion. Keep it loopback-only, nonce-gated, bounded, and wrapper-lifetime scoped.
* The `litellm` provider is an external gateway provider. It assumes the user runs LiteLLM separately and maps Claude Code model tiers to LiteLLM model ids. Do not embed the LiteLLM SDK in ccsilo by default.
* Variants are addressable by name or id; `variant_id_from_name` derives lower-kebab-case ids.
* `validate_variant_manifest` is the manifest authority. Do not bypass it.
* Runtime may be `native` or `node`.
* Node runtime wrappers require a Node version with explicit resource management support and allow `NODE=/path/to/node` override.
* If a Node-runtime setup fails `node-bun-compat`, run `.venv/bin/python -m ccsilo variant apply <name-or-id> --json` instead of hand-editing generated unpacked files.
* `DEFAULT_TWEAK_IDS` are selected on create. `ENV_TWEAK_IDS` affect wrapper environment rather than patching JS.
* The OAuth Architect model proxy requires the `gateway-model-discovery` env tweak. OpenAI-compatible backend proxy setups also need gateway discovery so Claude Code sees proxy-advertised model ids.
* Model proxy runtime config may include `backendProviderKey`, `backendProviderLabel`, and `backendModelsUrl`. Discovered backend models are advertised as `anthropic/<provider-key>/<provider-model>` and decoded before forwarding.
* In-place rebuild optimization applies only to supported theme/prompt/env tweak changes; otherwise rebuild from source.

## TUI Notes

* The TUI tabs are `Manage Setup`, `Dashboard`, `Inspect`, `Extract`, and `Patch`.
* Startup routes to `setup-manager` when variants exist and `first-run-setup` when none exist.
* `Manage Setup` owns setup lifecycle: create, run, upgrade, health check, delete, logs, tweak editing, and command/config copy actions.
* `Dashboard` is a guided native-binary tweak workflow: choose source, choose curated dashboard tweaks, manage tweak profiles, review, then build.
* `Patch` is for workspace patch packages under `.ccsilo/patches/packages/`.
* Keep action-layer functions that tests monkey-patch in `tui/__init__.py` and `variants/__init__.py`.
* Pure rendering, options, navigation, and state helpers belong in submodules.
* Do not enable `ratatui_py.App(clear_each_frame=True)` for steady-state TUI render loops. Use startup clear via `on_start` and keep constructor-flag tests.
* Grouped selectors must keep selectable option order and rendered row order aligned. Add regression tests when group headers or selection mapping changes.
* TUI MCP tests should use isolated `CCSILO_WORKSPACE`, named keys (`Down`, `Up`, `Tab`, `Enter`, `Space`, `Esc`, `q`), one key per send, and assertions on visible text/mode transitions.
* For provider MCP TUI checks, verify both the MCP step provider servers and the later Tweaks step MCP rows. A Z.ai first-run flow should show provider MCP servers auto-enabled before continuing to tweaks where `mcp-non-blocking` and `mcp-batch-size` are visible.

## Patch Development

Curated regex tweaks live in `ccsilo/patches/` and are registered in `ccsilo/patches/_registry.py`. Read `ccsilo/patches/AGENTS.md` before changing patch modules; it is the directory-local source of truth for patch format, regex rules, version rules, TUI visibility, and required checks.

Root-level reminders:

* Do not confuse curated regex tweaks with workspace patch packages.
* Add a patch module, synthetic fixture, real fixture test file, registry entry, and visibility update when creating a new curated tweak.
* Return only `applied`, `skipped`, or `missed` from `_apply`.
* Do not silently return `applied` when output is identical.
* Keep regex windows narrow enough to avoid unrelated minified code.
* Do not widen `versions_tested` until a concrete Claude Code version is proven.
* Expected environment-gated skips are not failures. Use `pytest -q -rs` to verify skip reasons.

Useful patch checks:

```bash
.venv/bin/python -m pytest -q tests/patches/
.venv/bin/python -m pytest -q -rs tests/patches/
.venv/bin/python -m pytest -q tests/test_variant_tweaks.py tests/test_tui.py
tools/run_patch_smoke_docker.sh --all --max-versions 10 --run-smoke --smoke-timeout 60
```

Use TUI MCP behavioral tests for workflows that cannot be validated by pure state/render tests alone: first-run setup, setup manager navigation, tweak selection/edit/apply, Dashboard source and profile flows, patch package profile selection, focus, resize, and keyboard navigation.

## Development Notes

* Python target: 3.8+.
* The TUI dependency is the holo-q `ratatui-py` shim imported as `ratatui_py`.
* Do not swap to `pyratatui` unless the TUI/test API is deliberately migrated.
* Keep `_utils.py` stdlib-only to avoid circular imports.
* Do not move `downloader.py` without updating tests that patch `ccsilo.downloader.*`.
* Do not stage or commit submodule/vendor changes unless explicitly requested.
* Do not add or upgrade dependencies without approval.
* Do not document destructive commands, global config writes, or release workflow shortcuts as safe defaults.
