# ccsilo

[![CI](https://github.com/whit3rabbit/ccsilo/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/whit3rabbit/ccsilo/actions/workflows/ci.yml)
[![Release](https://github.com/whit3rabbit/ccsilo/actions/workflows/release.yml/badge.svg)](https://github.com/whit3rabbit/ccsilo/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/ccsilo.svg)](https://pypi.org/project/ccsilo/)
[![GitHub Release](https://img.shields.io/github/v/release/whit3rabbit/ccsilo?label=github%20release)](https://github.com/whit3rabbit/ccsilo/releases/latest)
[![Python](https://img.shields.io/pypi/pyversions/ccsilo.svg)](https://pypi.org/project/ccsilo/)
[![License](https://img.shields.io/pypi/l/ccsilo.svg)](https://github.com/whit3rabbit/ccsilo/blob/main/LICENSE)

> [!IMPORTANT]
> This project is not affiliated with Anthropic or Claude Code. It is for research and controlled local patching of Claude Code packaged binaries. Do not use it to silently mutate a global Claude Code install.

`ccsilo` creates isolated Claude Code silos with provider-specific patching. Think ccmirror/tweakcc-style workflows first: it creates isolated commands, routes them through provider presets, applies curated UI/system/prompt tweaks, manages local setup config, and can build patched binaries from selected tweaks.

The extractor/repacker is still here, but it is the advanced layer. Most users should use the TUI to create a setup, then run the generated wrapper command.

Based in part on work by https://github.com/vicnaum/bun-demincer. Theme and prompt anchor logic is attributed in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).

## Quick Start

Install with `pipx`, then open the TUI:

```bash
pipx install ccsilo
ccsilo
```

If `ccsilo` is not found after a pipx install:

```bash
pipx ensurepath
```

Then restart your shell.

The TUI is the easiest path for most users. Running `ccsilo` with no arguments in a TTY opens it. If no setups exist, it starts the first-run setup wizard. If setups already exist, it opens `Manage Setup`.

In the first-run wizard:

1. Choose a provider preset, for example `mirror`, `kimi`, `openrouter`, `ccrouter`, or `lmstudio`.
2. Choose a setup name. This becomes the local wrapper command name.
3. Choose a Claude Code native binary version, usually `latest`.
4. Configure credentials. Use an environment variable, or store an API key in the setup-local `secrets.env`.
5. Pick optional MCP servers. Provider-owned MCP servers are enabled automatically.
6. Set model aliases if the provider needs them.
7. Choose recommended tweaks, review, then create the setup.
8. Run it from `Manage Setup`, from the installed provider command, from the workspace wrapper, or with `ccsilo variant run <setup-id> -- ...`.

If you just want the latest version from a shell, use a provider shortcut. Pick one:

```bash
# Clean isolated first-party Claude Code setup, no alternate provider.
ccsilo --provider mirror install --yes
mirror --version

# Kimi Code, reads credentials from KIMI_API_KEY.
ccsilo --provider kimi install --credential-env KIMI_API_KEY --yes
kimi --version

# OpenRouter, reads credentials from OPENROUTER_API_KEY.
ccsilo --provider openrouter install --credential-env OPENROUTER_API_KEY --yes
openrouter --version

# Local LM Studio endpoint, stores this setup under the lmstudio command.
ccsilo --provider lmstudio install --credential-env LM_API_TOKEN --yes
lmstudio --version
```

Provider shortcuts default to the latest Claude Code native binary. Add `--claude-version <version>` only when you need a pinned version.

Install with `pip` inside a virtual environment if you do not use `pipx`:

```bash
python -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install ccsilo
.venv/bin/ccsilo
```

To run once from GitHub without keeping an installed command:

```bash
pipx run --spec git+https://github.com/whit3rabbit/ccsilo.git ccsilo
```

If you already use `uv`, the equivalent one-shot command is:

```bash
uv tool run --from git+https://github.com/whit3rabbit/ccsilo.git ccsilo
```

From a developer checkout:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m ccsilo
```

Inspect the resolved command and workspace paths:

```bash
ccsilo paths
```

## Where Files Go

By default, installed usage stores managed setups in the platform user data directory:

| Platform | Default workspace |
|----------|-------------------|
| macOS | `~/Library/Application Support/ccsilo` |
| Linux | `$XDG_DATA_HOME/ccsilo` |
| Linux, when `XDG_DATA_HOME` is unset | `~/.local/share/ccsilo` |
| Windows | `%APPDATA%\ccsilo` |

Equivalent Linux shell expansion:

```bash
${XDG_DATA_HOME:-~/.local/share}/ccsilo  # ~/.local/share if XDG_DATA_HOME is unset
```

Set `CCSILO_WORKSPACE=/path/to/workspace` to use a project-local or disposable workspace. For repository development, this keeps the old local layout:

```bash
CCSILO_WORKSPACE="$PWD/.ccsilo" .venv/bin/python -m ccsilo
```

The workspace contains:

```text
<workspace>/
  variants/<setup-id>/variant.json
  variants/<setup-id>/native/
  variants/<setup-id>/unpacked/          # Node fallback runtime only
  variants/<setup-id>/config/
  variants/<setup-id>/tweakcc/config.json
  variants/<setup-id>/tmp/
  variants/<setup-id>/secrets.env        # stored credentials only
  downloads/native/
  downloads/npm/
  extractions/native/
  patches/packages/
  patches/profiles/
  patches/tweak-profiles/
  patched/native/
  tmp/
  bin/<setup-id>
```

Important paths:

| Path | Purpose |
|------|---------|
| `<workspace>/bin/<setup-id>` | Wrapper command for the finished setup. |
| `<workspace>/variants/<setup-id>/variant.json` | Setup manifest: provider, source version, selected tweaks, model overrides, MCP choices, and wrapper paths. |
| `<workspace>/variants/<setup-id>/native/` | Setup-local native binary output. |
| `<workspace>/variants/<setup-id>/unpacked/` | Setup-local unpacked Node runtime files, only used for setups that need the Node fallback runtime. |
| `<workspace>/variants/<setup-id>/config/` | Isolated Claude Code config for the setup. |
| `<workspace>/variants/<setup-id>/tweakcc/config.json` | Setup-local tweakcc config pointing at the setup binary. |
| `<workspace>/variants/<setup-id>/tmp/` | Setup-local temporary files and logs. |
| `<workspace>/variants/<setup-id>/secrets.env` | Optional setup-local credential file, only written when you choose stored credentials. |
| `<workspace>/downloads/native/` | Checksum-verified downloaded or imported native Claude Code binaries. |
| `<workspace>/downloads/npm/` | Cached NPM package downloads. |
| `<workspace>/extractions/native/` | Central extracted native bundles and extraction metadata. |
| `<workspace>/patches/packages/` | Workspace patch package manifests and operations. |
| `<workspace>/patches/profiles/` | Saved patch-package profile selections. |
| `<workspace>/patches/tweak-profiles/` | Saved Dashboard tweak selections. |
| `<workspace>/patched/native/` | Dashboard-built patched native binaries. |
| `<workspace>/tmp/` | Shared workspace temporary files. |

Deleting a setup removes its setup directory and wrapper command. Shared downloads and caches are not removed.

## Running A Finished Setup

From the TUI, select a setup in `Manage Setup`, then choose `Run Claude`.

From a shell, run the generated wrapper:

```bash
ccsilo variant run my-setup -- --version
ccsilo variant run my-setup -- --print "hello"
```

Or run the workspace wrapper directly:

```bash
"$(ccsilo paths --json | python -c 'import json,sys; print(json.load(sys.stdin)["workspace"])')/bin/my-setup" --version
```

### Adding MCP Servers To A Setup

Run `mcp add` through the setup command you want to modify, not through the global `claude` command. The wrapper sets `CLAUDE_CONFIG_DIR`, so Claude Code writes MCP config under `<workspace>/variants/<setup-id>/config/` instead of your normal Claude Code config.

```bash
# Installed provider/setup command.
zai mcp add camoufox -- npx -y camoufox-mcp-server@latest

# Or without installing the wrapper into PATH.
ccsilo variant run zai -- mcp add camoufox -- npx -y camoufox-mcp-server@latest
```

Run the command from the project where you want Claude Code's local MCP scope to apply. For built-in optional MCP choices, list the catalog with `ccsilo variant mcp` and pass `--mcp <id>` when creating a setup.

To install a stable command into a home PATH directory:

```bash
ccsilo variant install my-setup
ccsilo variant install my-setup --alias claude-kimi
ccsilo variant install my-setup --bin-dir ~/.local/bin --yes
```

`variant install` creates a managed symlink to the setup wrapper. It refuses to overwrite non-symlinks or symlinks owned by something else.

Provider shortcuts can create or update the default setup for a provider and install the command in one step. By default, the installed command is the provider key, for example `kimi`, `zai`, or `ccrouter`.

```bash
ccsilo --provider kimi install --credential-env KIMI_API_KEY
ccsilo --provider zai install --credential-env Z_AI_API_KEY
ccsilo install --provider openrouter --credential-env OPENROUTER_API_KEY --alias claude-openrouter
ccsilo --provider kimi update
ccsilo --provider kimi uninstall --yes
```

## How To Uninstall

Remove one provider setup:

```bash
ccsilo --provider kimi uninstall --yes
```

This removes only that provider setup and its wrapper command. Shared downloads, patch outputs, and other setups remain in the active workspace.

Remove managed symlinks and the current workspace:

```bash
ccsilo paths
ccsilo uninstall --yes
```

`ccsilo uninstall --yes` removes the workspace shown by `ccsilo paths`: `CCSILO_WORKSPACE` when set, otherwise the platform user data directory listed above. It also removes managed symlinks created by `ccsilo variant install` or provider installs. It does not uninstall the `ccsilo` Python package.

Remove the `ccsilo` command installed by pipx:

```bash
pipx uninstall ccsilo
```

`pipx uninstall ccsilo` removes the installed command and pipx environment. It does not remove the ccsilo workspace; run `ccsilo uninstall --yes` first if you want managed setups, downloads, cached artifacts, and setup-local secrets removed too.

## Troubleshooting PATH

Use `ccsilo paths` to see the active workspace and whether `ccsilo` is on PATH.

If `ccsilo` itself is missing after pipx install, run `pipx ensurepath` and restart your shell.

If a setup command such as `kimi` is missing, rerun the provider install with `--yes` to create `~/.local/bin`, or pass an explicit bin directory:

```bash
ccsilo --provider kimi install --credential-env KIMI_API_KEY --yes
ccsilo --provider kimi install --credential-env KIMI_API_KEY --bin-dir ~/.local/bin --yes
```

## TUI Guide

Navigate with arrow keys, `Tab` or `Right` to move tabs, `Left` to move back through tabs, `Enter` to activate, `Space` to toggle, and `Esc` or `Backspace` to go back.

| Tab | What it is for |
|-----|----------------|
| Manage Setup | Create, run, health-check, upgrade, edit models, edit tweaks, delete, search, filter, and sort setups. |
| Dashboard | Build a patched native binary from a selected source and curated tweak set. |
| Inspect | View Bun bundle metadata for a selected native download and delete cached native artifacts. |
| Extract | Extract or unpack a selected native download to disk. |
| Patch | Apply workspace patch packages to a source binary. |

Common setup keys:

| Key | Action |
|-----|--------|
| `n` | Create a new setup |
| `x` | Run selected setup after leaving the TUI |
| `u` | Upgrade selected setup |
| `h` | Health-check selected setup |
| `m` | Edit model aliases |
| `t` | Edit tweaks |
| `d` | Delete selected setup |
| `/` | Search setups |
| `p` | Cycle provider filter |
| `s` | Cycle setup sort |
| `c` | Copy setup command path |
| `g` | Copy setup config path |
| `l` | Open last action logs |
| `?` | Open help |
| `q` | Quit |

Themes for the TUI itself are `hacker-bbs` (default), `unicorn`, `dark`, `light`, and `high-contrast`.

## Providers

Provider presets configure endpoint environment variables, credentials, optional prompt overlays, theme labels, MCP config, and model defaults. `mirror` is the clean isolated Claude Code setup with no alternate provider.

| Key | Display name | Auth | Credential env | Best use |
|-----|--------------|------|----------------|----------|
| `mirror` | Mirror Claude Code | none | not required | Isolated first-party Claude Code config with clean defaults. |
| `ccrouter` | CC Router | auth token | `CCROUTER_AUTH_TOKEN` | Local Claude Code Router service at `127.0.0.1:3456`. |
| `ccr-oauth` | CCR OAuth Proxy | auth token | `CCROUTER_AUTH_TOKEN` | Managed CCR plus Architect Mode, keeping `claude-*` calls on Claude Code OAuth/session auth. |
| `kimi` | Kimi Code | API key | `KIMI_API_KEY` | Kimi coding models through Kimi Code. |
| `minimax` | MiniMax Cloud | API key | `MINIMAX_API_KEY` | MiniMax cloud endpoint. |
| `minimax-cn` | MiniMax China | API key | `MINIMAX_CN_API_KEY` | MiniMax China Anthropic-compatible endpoint. |
| `zai` | Zai Cloud | API key | `Z_AI_API_KEY` | GLM models through Z.ai Coding Plan. |
| `deepseek` | DeepSeek | API key | `DEEPSEEK_API_KEY` | DeepSeek Anthropic API. |
| `alibaba` | Alibaba Cloud | API key | `ALIBABA_CLOUD_API_KEY` | DashScope Anthropic-compatible API. |
| `poe` | Poe | auth token | `POE_API_KEY` | Claude through Poe Anthropic-compatible API. |
| `openrouter` | OpenRouter | auth token | `OPENROUTER_API_KEY` | OpenRouter gateway. |
| `vercel` | Vercel AI Gateway | auth token | `VERCEL_AI_GATEWAY_KEY` | Vercel AI Gateway. |
| `ollama` | Ollama | auth token | `OLLAMA_API_KEY` | Local or cloud models through Ollama. |
| `nanogpt` | NanoGPT | auth token | `NANOGPT_API_KEY` | NanoGPT model gateway. |
| `9router` | 9Router | API key | `NINEROUTER_API_KEY` | Local 9Router fallback and format translation. |
| `cerebras` | Cerebras (via CCRouter) | auth token | `CEREBRAS_API_KEY` | Cerebras through local Claude Code Router. |
| `anthropic` | Anthropic Console | API key | `ANTHROPIC_API_KEY` | First-party Anthropic Console API key. |
| `gatewayz` | GatewayZ | auth token | `GATEWAYZ_API_KEY` | GatewayZ AI Gateway. |
| `custom` | Custom | API key | `ANTHROPIC_API_KEY` | Bring your own Anthropic-compatible endpoint. |
| `lmstudio` | LM Studio | auth token | `LM_API_TOKEN` | Local OpenAI-compatible models through LM Studio. |
| `omlx` | oMLX | auth token | `OMLX_API_KEY` | Local MLX-powered models through oMLX. |
| `local-custom` | Custom Local Endpoint | auth token | `LOCAL_LLM_API_KEY` | Custom local Anthropic or OpenAI-compatible endpoint. |

List provider details from the CLI:

```bash
ccsilo variant providers
ccsilo variant providers --json
ccsilo variant mcp
ccsilo variant mcp --provider kimi
```

### CC Router

The `ccrouter` provider can manage Claude Code Router inside the setup workspace. By default, ccsilo installs CCR locally under the setup, copies `~/.claude-code-router/config.json` into the setup when it exists, assigns an isolated local port, and runs CCR with `HOME` pointed at the setup-local home.

```bash
ccsilo variant create --name ccrouter --provider ccrouter
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-config empty
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-package @musistudio/claude-code-router@2.0.0
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-port 4567
ccsilo variant create --name ccrouter --provider ccrouter --no-ccrouter-autostart
```

Managed CCR config lives at:

```text
.ccsilo/variants/<setup-id>/ccr-home/.claude-code-router/config.json
```

Use `--ccrouter-mode external` when you want to install, configure, and start CCR yourself:

```bash
npm install -g @musistudio/claude-code-router
ccr start
ccsilo variant create --name ccrouter --provider ccrouter --ccrouter-mode external
```

For managed setups, edit the setup-local CCR config instead of the global CCR config. The wrapper starts the local `ccr` service when needed and runs the patched Claude binary directly. It does not call `ccr code`. See [docs/CCR.md](docs/CCR.md) for the longer flow.

`ccr-oauth` plus the Architect Mode tweak can use a planner model in plan mode and worker models otherwise:

```bash
ccsilo variant create \
  --name architect \
  --provider ccr-oauth \
  --model-proxy architect \
  --tweak opusplan1m
```

This requires a Claude Code account and login. `claude-*` planner requests use the normal Claude Code OAuth/session path, while non-Claude worker aliases are forwarded to the configured provider backend.

## Supported Sources And Binaries

The wrapper command is the recommended runtime. Direct binary paths are managed implementation details unless you are doing advanced extraction or patch development.

| Source or binary | Supported container | Main workflow | Notes |
|------------------|---------------------|---------------|-------|
| Downloaded native Claude Code binary | macOS Mach-O, Linux ELF, Windows PE | TUI setup creation, Dashboard builds, CLI `download` | Cached under `<workspace>/downloads/native/<version>/<platform>/<sha256>/`. |
| Imported local native binary | Mach-O, ELF, or PE matching `--source-platform` | CLI-only `variant create/update --source-binary` | Requires a concrete semver in `--claude-version`. The original file is copied into the managed cache. |
| NPM tarball | Anthropic NPM package tarball | CLI `download --npm` | Separate cache, mainly useful for advanced inspection/source comparison. Requires `npm`. |
| Extracted bundle directory | `.bundle_manifest.json` plus extracted modules | `extract`, `unpack`, `pack`, legacy patch manifests | Advanced workflow for bundle research and controlled patch packages. |
| Dashboard patched binary | Same native platform as selected source | Dashboard tab | Written under `<workspace>/patched/native/`; a setup wrapper is still the normal thing to run. |

Normal setup creation and Dashboard builds use centralized downloads. The TUI loads the local download index first, then refreshes the live Claude Code version index once at startup. If no live index is available, the packaged seed index is used until refresh succeeds.

Native downloads are checksum-verified before storage. On non-Windows systems, stored native binaries and wrappers are marked executable.

## Tweaks

Setup tweaks can change the native binary, the unpacked Node fallback, prompt overlays, wrapper environment, or setup launch arguments. Dashboard tweaks are for standalone patched binary builds. Env tweaks only affect wrapper environment.

Badges:

| Badge | Meaning |
|-------|---------|
| Setup default | Enabled by default in new setups when applicable. |
| Setup | Available in setup tweak selection. |
| Dashboard | Available in Dashboard binary builds. |
| Env | Wrapper environment tweak, not a regex patch. |

<details>
<summary>Full tweak reference</summary>

| ID | Name | Group | Availability | Description |
|----|------|-------|--------------|-------------|
| `themes` | Custom themes | ui | Setup default, Setup | Inject custom theme entries into Claude Code's theme registry. |
| `prompt-overlays` | Prompt overlays | prompts | Setup default, Setup | Inject provider-specific overlay text after known prompt anchors. |
| `show-more-items-in-select-menus` | Show more items in select menus | ui | Setup, Dashboard | Increase visible options to show more items on screen. |
| `model-customizations` | Custom Claude models in picker | ui | Setup, Dashboard | Add extended Claude model entries to the model picker. |
| `hide-startup-banner` | Hide startup banner | ui | Setup default, Setup, Dashboard | Hide the welcome banner shown before the first message. |
| `hide-startup-clawd` | Hide ASCII startup banner | ui | Setup default, Setup, Dashboard | Hide the ASCII startup mascot. |
| `hide-ctrl-g-to-edit` | Hide Ctrl+G edit hint | ui | Setup, Dashboard | Hide the input footer edit hint. |
| `suppress-line-numbers` | Suppress line numbers in file reads | ui | Setup, Dashboard | Strip per-line line-number prefixes from file-read output. |
| `suppress-model-launch-notice` | Suppress model launch notice | ui | Setup default, Setup, Dashboard | Hide startup notices announcing newly available Claude models. |
| `suppress-native-installer-warning` | Suppress native installer warning | ui | Setup default, Setup, Dashboard | Remove the warning that prompts NPM users to install the native binary. |
| `suppress-prompt-caching-warning` | Suppress prompt caching warning | ui | Setup default, Setup, Dashboard | Hide the warning shown when prompt caching is disabled by env vars. |
| `suppress-rate-limit-options` | Suppress rate limit options | ui | Setup, Dashboard | Disable the injected `/rate-limit-options` opener when rate limits are reached. |
| `thinking-visibility` | Thinking block visibility | thinking | Setup, Dashboard | Show model thinking blocks without the transcript-mode visibility toggle. |
| `input-box-border` | Input box border | ui | Setup, Dashboard | Remove the rounded border around the main prompt input box. |
| `filter-scroll-escape-sequences` | Filter scroll escape sequences | system | Setup, Dashboard | Filter stdout escape sequences that set or reset scroll regions. |
| `agents-md` | AGENTS.md support | system | Setup, Dashboard | Read `AGENTS.md` and configured alternative instruction filenames when `CLAUDE.md` is absent. |
| `session-memory` | Session memory | prompts | Setup, Dashboard | Enable session memory extraction and past-session search with env-configurable thresholds. |
| `remember-skill` | Remember skill | prompts | Setup | Register the built-in `/remember` skill for older Claude Code versions that do not bundle it. |
| `opusplan1m` | Architect Mode | ui | Setup, Dashboard | Add an Architect Mode alias that uses a planner model in plan mode and a worker model otherwise. |
| `mcp-non-blocking` | MCP non-blocking | tools | Setup default, Setup, Dashboard | Avoid blocking Claude Code startup while MCP servers connect. |
| `mcp-batch-size` | MCP batch size | tools | Setup default, Setup, Dashboard | Raise MCP server startup batch size. Defaults to 10 unless configured. |
| `rtk-shell-prefix` | RTK shell prefix | prompts | Setup default, Setup | Add prompt guidance to prefix shell commands with `rtk` when available. |
| `dangerously-skip-permissions` | Dangerously skip permissions | tools | Setup default, Setup | Launch the wrapper with `--dangerously-skip-permissions`. Use only when you understand the risk. |
| `token-count-rounding` | Token count rounding | ui | Setup, Dashboard | Round displayed token counts to the configured base. Defaults to 1000. |
| `statusline-update-throttle` | Statusline update throttling correction | ui | Setup, Dashboard | Replace flawed statusline debounce behavior with throttle pacing. Defaults to 300ms. |
| `auto-accept-plan-mode` | Auto-accept plan mode | ui | Setup, Dashboard | Auto-accept the "Ready to code?" plan-mode prompt. |
| `allow-custom-agent-models` | Allow custom agent models | ui | Setup, Dashboard | Relax subagent model validation so arbitrary string values are accepted. |
| `patches-applied-indication` | Patches-applied indication | ui | Setup, Dashboard | Append the provider label after `(Claude Code)` in the version banner. |
| `context-limit` | Context limit | env | Setup, Env | Set `CLAUDE_CODE_CONTEXT_LIMIT` in the wrapper. |
| `file-read-limit` | File read limit | env | Setup, Env | Set `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS` in the wrapper. |
| `subagent-model` | Subagent model | env | Setup, Env | Set `CLAUDE_CODE_SUBAGENT_MODEL` in the wrapper. |
| `disable-telemetry` | Disable telemetry | env | Setup, Env | Opt out of Statsig telemetry. |
| `disable-error-reporting` | Disable error reporting | env | Setup, Env | Disable Sentry error reporting. |
| `disable-feedback-command` | Disable feedback command | env | Setup, Env | Hide the feedback command. |
| `disable-feedback-survey` | Disable feedback survey | env | Setup, Env | Disable session quality surveys. |
| `disable-prompt-caching` | Disable prompt caching | env | Setup, Env | Disable prompt caching for all models. |
| `disable-auto-compact` | Disable auto compact | env | Setup, Env | Disable automatic compaction while leaving manual compact available. |
| `disable-all-compact` | Disable all compact | env | Setup, Env | Disable automatic and manual compaction. |
| `disable-growthbook` | Disable GrowthBook | env | Setup, Env | Disable GrowthBook feature flag fetching. |
| `disable-nonessential-traffic` | Disable nonessential traffic | env | Setup, Env | Disable updater, feedback, error reporting, and telemetry traffic. |
| `skip-prompt-history` | Skip prompt history | env | Setup, Env | Skip writing prompt history and session transcripts. |
| `disable-auto-memory` | Disable auto memory | env | Setup, Env | Disable Claude Code auto memory. |
| `disable-cron` | Disable scheduled tasks | env | Setup, Env | Disable scheduled tasks and cron tools. |
| `subprocess-env-scrub` | Scrub subprocess env | env | Setup, Env | Strip provider credentials from subprocess environments. |
| `mcp-allowlist-env` | MCP allowlist env | env | Setup, Env | Start stdio MCP servers with a safe baseline environment plus configured env. |
| `disable-experimental-betas` | Disable experimental betas | env | Setup, Env | Strip Anthropic beta headers and beta tool-schema fields from API requests. |

</details>

For non-`mirror` providers, new setups also select these env-backed defaults: `disable-telemetry`, `disable-error-reporting`, `disable-feedback-command`, `disable-feedback-survey`, and `disable-prompt-caching`.

## Setup CLI

The installed command is `ccsilo`. From a checkout, the canonical equivalent is `.venv/bin/python -m ccsilo`.

```bash
ccsilo variant providers
ccsilo variant mcp
ccsilo variant create --name my-cc --provider kimi
ccsilo variant create --name my-cc --provider kimi --credential-env KIMI_API_KEY
ccsilo variant create --name local --provider lmstudio --api-key token --store-secret
ccsilo variant create --name offline --provider mirror --claude-version 2.1.123 --source-binary /path/to/claude
ccsilo variant list
ccsilo variant show my-cc --json
ccsilo variant apply my-cc
ccsilo variant update my-cc
ccsilo variant update offline --claude-version 2.1.124 --source-binary /path/to/claude
ccsilo variant update --all
ccsilo variant doctor my-cc
ccsilo variant doctor --all
ccsilo variant run my-cc -- [args...]
ccsilo variant install my-cc
ccsilo variant remove my-cc --yes
ccsilo --provider kimi install
ccsilo --provider zai install --credential-env Z_AI_API_KEY
ccsilo --provider kimi update
ccsilo --provider kimi uninstall --yes
```

Create options:

| Flag | Description |
|------|-------------|
| `--name` | Setup name, also used as wrapper command. |
| `--provider` | Provider preset key. |
| `--claude-version` | Target version, `latest`, or `stable`. |
| `--source-binary` | Advanced: import a local Claude Code native binary instead of downloading. Requires concrete `--claude-version`. |
| `--source-platform` | Advanced: platform key for `--source-binary`. Defaults to the current host platform. |
| `--patch-profile` | Apply a saved patch profile. |
| `--tweak` | Curated tweak id, repeatable. |
| `--mcp` | Optional MCP server id, repeatable. |
| `--base-url` | Override the provider endpoint URL. |
| `--credential-env` | Environment variable for provider credentials. |
| `--api-key` | API key stored locally, requires `--store-secret`. |
| `--store-secret` | Store `--api-key` in setup-local `secrets.env`. |
| `--bin-dir` | Wrapper output directory. |
| `--install` | Install the setup command into a home PATH directory during creation. |
| `--extra-env` | Additional `KEY=VALUE` env entries, repeatable. |
| `--force` | Overwrite an existing setup. |
| Model overrides | `--opus`, `--sonnet`, `--haiku`, `--default`, `--small-fast`, `--subagent`. |

`--source-binary` is intentionally CLI-only. It is not shown in the TUI first-run wizard because it is an escape hatch for controlled local builds, not the normal setup path.

Rules for local source binaries:

- `--claude-version` must be a concrete semver such as `2.1.123`. `latest` and `stable` are rejected.
- `--source-platform` may be omitted. When omitted, ccsilo uses the current host platform key.
- The binary must parse as a Bun standalone binary. Mach-O requires a `darwin-*` platform, ELF requires `linux-*`, and PE requires `win32-*`.
- Rebuilds use the imported managed copy, not the original path.
- If the managed copy is missing or its hash changes, re-import it with `variant update <name> --claude-version <version> --source-binary <path>`.
- `variant update --all --source-binary ...` is rejected. Local binary replacement is only allowed for one setup at a time.

## Downloads And Cache

```bash
ccsilo download
ccsilo download --latest
ccsilo download 2.1.123
ccsilo download --npm 2.1.123
```

When `--outdir` is omitted, downloads go into the centralized workspace cache. Use `--outdir` only when you intentionally want the legacy output layout outside the workspace:

```bash
ccsilo download 2.1.123 --outdir ./downloads
```

Native cache layout:

```text
<workspace>/downloads/native/<version>/<platform>/<sha256>/claude
```

NPM tarball cache layout:

```text
<workspace>/downloads/npm/<version>/<sha256>/<tarball>.tgz
```

## Advanced Binary And Patch Commands

These commands are for research, fixture work, patch development, and controlled binary workflows. They are not the normal way to run a finished setup.

### Inspect

```bash
ccsilo inspect /path/to/claude
ccsilo inspect /path/to/claude --json
```

### Extract And Unpack

```bash
ccsilo extract /path/to/claude ./extracted_files
ccsilo extract /path/to/claude ./extracted_files --include-sourcemaps
ccsilo unpack /path/to/claude --out ./extracted_files
```

Extraction writes module files plus `.bundle_manifest.json`. The manifest records platform, module struct size, entry point, byte count, section metadata, and per-module offsets needed by repack.

### Replace Entry JS

```bash
ccsilo replace-entry /path/to/claude ./entry.js --out ./claude-patched
```

This resizes only the Bun entry module and repacks the binary through `binary_patcher.repack_binary`.

### Apply Binary Theme And Prompt Patches

```bash
ccsilo apply-binary /path/to/claude --config ./config.json
ccsilo apply-binary /path/to/claude --config ./config.json --overlays ./overlays.json
```

`config.json` may provide themes as either `{"themes": [...]}` or `{"settings": {"themes": [...]}}`. Prompt overlay misses are reported in the structured JSON result and are not fatal. Theme anchor misses return `anchor-not-found`.

On Mach-O binaries, patches that would grow the bundled entry JS may use the unpacked Node runtime fallback in setup workflows. Low-level `apply-binary` reports unsupported growth instead of silently rewriting a risky binary.

### Patch Manifests

```bash
ccsilo patch init ./my_patch
ccsilo patch apply ./my_patch ./extracted_files
ccsilo patch apply ./my_patch ./extracted_files --check
ccsilo patch apply ./my_patch ./extracted_files --binary /path/to/claude --source-version 1.2.3
```

Creates or applies text patch manifests against extracted bundle files. `--check` validates without writing. `--binary` and `--source-version` override source metadata for cross-version patches.

### Pack

```bash
ccsilo pack ./modified_files /path/to/original_claude ./new_claude
```

Rebuilds raw Bun bytes from `.bundle_manifest.json`, parses the base binary, and delegates container rewriting to `binary_patcher.repack_binary`.

## Python API

```python
from ccsilo import (
    apply_patches,
    download_binary,
    download_npm,
    extract_all,
    pack_bundle,
    parse_bun_binary,
    replace_entry_js,
    replace_module,
)
```

The core model is `BunBinaryInfo` and `BunModule` from `ccsilo.bun_extract.types`.

## Development

Install from a clone:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e '.[dev]'
```

Run checks:

```bash
.venv/bin/python -m pytest -q
ruff check ccsilo tests tools
```

Build and publish release artifacts with the checklist in [docs/RELEASE.md](docs/RELEASE.md).

The default test suite does not download real Claude Code binaries. Run gated integration tests explicitly when you need live binary coverage:

```bash
CCSILO_RUN_REAL_BINARY_TEST=1 .venv/bin/python -m pytest -q tests/test_integration_real_binary.py
CCSILO_RUN_REAL_BINARY_TEST=1 CCSILO_REAL_BINARY_VERSION=2.1.119 .venv/bin/python -m pytest -q tests/test_integration_real_binary.py
```

Docker runtime smoke is preferred for release-prep patch proof:

```bash
tools/run_patch_smoke_docker.sh --all --max-versions 10 --run-smoke --smoke-timeout 60
```

### Prompt Catalogs

Prompt catalogs live under `prompts/<version>.json`.

```bash
.venv/bin/python tools/extract_prompt_versions.py --since-existing-latest
.venv/bin/python tools/extract_prompt_versions.py --missing
.venv/bin/python tools/extract_prompt_versions.py --missing --max-versions 5
.venv/bin/python tools/extract_prompt_versions.py --versions 2.1.130 2.1.129 --force-prompts
```

The extractor downloads each native binary, extracts the bundled entry JS, extracts prompt strings, validates the prompt JSON schema, and writes `prompts/<version>.json`. New versions inherit prompt metadata from the nearest older local prompt catalog when same-version metadata is unavailable.

### Architecture

```text
ccsilo/
  __main__.py                  CLI entry point, variant dispatcher, and TUI launch
  cli/                         argparse tree, command handlers, JSON payload helpers
  tui/                         setup manager, dashboard, rendering, state, navigation, keys
  workspace/                   workspace paths, artifacts, patch profiles, settings
  variants/                    setup lifecycle, builder, tweaks, wrapper, installs
  providers/                   provider registry, env builder, MCP config, model discovery
  patches/                     curated tweak registry and regex patch modules
  bun_extract/                 Bun standalone parser, extract, same-size replacement
  binary_patcher/              native patching, entry replacement, repack, codesign, fallback
  patch_workflow.py            dashboard and workspace patch package workflows
  patcher.py                   legacy extracted-text patch manifests
  downloader.py                native and NPM download helpers
```

```text
tools/
  prompt_extractor.py           Tree-sitter prompt extractor
  extract_prompt_versions.py    Batch prompt extraction and validation
  check_patch_releases.py       Patch compatibility report generator
  run_patch_smoke_docker.sh     Docker runtime smoke helper
```
