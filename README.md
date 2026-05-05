# Bun Standalone Claude Code Binary Toolkit

> [!IMPORTANT]
> This project is not affiliated with Anthropic or Claude Code. It is intended for research and educational work on Claude Code packaged binaries.

`cc-extractor` is a standalone Python tool for creating isolated Claude Code setups, downloading Claude Code artifacts, and inspecting, extracting, patching, or repacking Bun standalone bundles inside Claude Code binaries. The interactive TUI is the main workflow for setup management and guided binary builds. The CLI remains available for scripting and lower-level binary work.

## Features

- Interactive TUI with first-run setup, setup management, dashboard builds, and patch profile management.
- Create isolated Claude Code setups with provider presets, credentials, model overrides, MCP choices, wrappers, and curated tweaks.
- Download Claude Code native binary artifacts or the Anthropic NPM tarball.
- Inspect Bun bundle metadata without extracting files.
- Extract or unpack module contents and `.bundle_manifest.json`.
- Replace same-size modules or resize the entry JS module.
- Repack ELF, Mach-O, and PE Bun payloads.
- Apply theme and prompt overlays directly to bundled `cli.js`.
- Manage patch profiles for reusable build configurations.
- Prompt extraction with tree-sitter-based tooling.

Based in part on work by https://github.com/vicnaum/bun-demincer. Theme and prompt anchor logic is attributed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Install

For local development from a clone:

```bash
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e '.[dev]'
```

For a normal user install from GitHub, use `pipx` to keep the CLI isolated from
your system Python:

```bash
pipx install git+https://github.com/whit3rabbit/cc-extract.git
cc-extractor --help
```

If `cc-extractor` is not found after install, run `pipx ensurepath` and restart
your shell.

To run once from GitHub without installing a persistent command:

```bash
pipx run --spec git+https://github.com/whit3rabbit/cc-extract.git cc-extractor --help
```

`uv` is optional. If you already use it, the equivalent one-shot command is:

```bash
uv tool run --from git+https://github.com/whit3rabbit/cc-extract.git cc-extractor --help
```

## TUI Quick Start

From a development checkout, open the TUI with:

```bash
.venv/bin/python -m cc_extractor
```

After a `pipx` install, use the console command instead:

```bash
cc-extractor
```

Running with no arguments in a TTY opens the TUI. If no setups exist, it starts the first-run setup wizard. If setups already exist, it opens `Manage Setup`.

The first-run setup wizard is the fastest path to a usable isolated Claude Code command:

1. Choose a provider preset.
2. Choose a setup name. This becomes the wrapper command name.
3. Choose the Claude Code native binary version, usually `latest`.
4. Configure credentials. Use an environment variable, or turn on setup-local secret storage and type an API key.
5. Pick optional MCP servers. Provider-owned MCP servers are enabled automatically.
6. Set model aliases if the provider requires them. Some providers can refresh a model list from the endpoint.
7. Choose recommended tweaks, review the setup, then press `y` to create it.

The setup build downloads the selected native Claude Code binary if it is not already cached, applies selected provider/tweak changes, writes a wrapper command, writes setup config, and then runs a health check.

Created setups live under the workspace:

```text
.cc-extractor/
  variants/<setup-id>/variant.json
  variants/<setup-id>/native/
  variants/<setup-id>/config/
  bin/<setup-id>
```

The default workspace is `.cc-extractor/` in the current working directory. Set `CC_EXTRACTOR_WORKSPACE=/path/to/workspace` to use a different workspace.

## Downloads And Cache

Setup creation and dashboard builds use centralized downloads. The TUI loads the local download index first, then refreshes the live Claude Code version index once at startup. If no live index is available yet, the packaged seed index is used until refresh succeeds.

Native downloads are stored by version, platform, and checksum:

```text
.cc-extractor/downloads/native/<version>/<platform>/<sha256>/claude
```

Downloads are checksum-verified before they are stored. Existing cached binaries are reused when the checksum still matches. On non-Windows systems, stored native binaries are marked executable.

NPM tarballs are separate from native binaries and require `npm`:

```text
.cc-extractor/downloads/npm/<version>/<sha256>/<tarball>.tgz
```

The CLI uses the same cache when `--outdir` is omitted:

```bash
cc-extractor download                 # interactive version picker
cc-extractor download --latest        # latest native binary
cc-extractor download 2.1.123         # pinned native binary
cc-extractor download --npm 2.1.123   # pinned NPM tarball
```

Use `--outdir` only when you intentionally want the legacy output layout outside the workspace:

```bash
cc-extractor download 2.1.123 --outdir ./downloads
```

That writes `./downloads/<version>/claude` instead of the centralized workspace cache.

## TUI Reference

Navigate with arrow keys, `Tab` or `Right` to move tabs, `Left` to move back through tabs, `Enter` to activate, `Space` to toggle, and `Esc` or `Backspace` to go back.

**Tabs:**

| Tab | Description |
|-----|-------------|
| Manage Setup | Create setups, run wrapper commands, health-check, upgrade, edit models, edit tweaks, delete, search, filter, and sort. |
| Dashboard | 4-step wizard: pick source, select curated tweaks, load or save profiles, review and build. |
| Inspect | View Bun bundle metadata for a selected native download and delete cached native artifacts. |
| Extract | Extract or unpack a selected native download to disk. |
| Patch | Apply workspace patch packages to a source binary. |

**Setup keys:**

| Key | Action |
|-----|--------|
| `n` | Create a new setup |
| `x` | Run selected setup after leaving the TUI |
| `u` | Upgrade selected setup |
| `h` | Health-check selected setup |
| `m` | Edit model aliases |
| `t` | Edit tweaks for selected setup |
| `d` | Delete selected setup |
| `/` | Search setups |
| `p` | Cycle provider filter |
| `s` | Cycle setup sort |
| `c` | Copy setup command path |
| `g` | Copy setup config path |
| `l` | Open last action logs |
| `?` | Open help |
| `q` | Quit |

Deleting a setup removes its setup directory and wrapper command. Shared downloads and caches are not removed.

**Themes:** hacker-bbs (default), unicorn, dark, light, high-contrast.

## Command Reference

The installed command is `cc-extractor`. From a development checkout, the canonical equivalent is `.venv/bin/python -m cc_extractor`.

### Setup CLI

Setups are isolated, patched Claude Code installations addressed by name or id. Each setup pins a provider, optional model overrides, MCP selections, credentials, and a set of tweaks.

```bash
cc-extractor variant providers                                      # list provider presets
cc-extractor variant mcp                                            # list provider and optional MCP servers
cc-extractor variant mcp --provider kimi                            # list MCP catalog for one provider
cc-extractor variant create --name my-cc --provider kimi            # create a setup
cc-extractor variant create --name my-cc --provider kimi --credential-env KIMI_API_KEY
cc-extractor variant create --name local --provider lmstudio --api-key token --store-secret
cc-extractor variant list                                           # list all setups
cc-extractor variant show my-cc --json                              # show setup metadata
cc-extractor variant apply my-cc                                    # rebuild from saved settings
cc-extractor variant update my-cc                                   # update to latest version
cc-extractor variant update --all                                   # update all setups
cc-extractor variant doctor my-cc                                   # health check
cc-extractor variant doctor --all                                   # check all setups
cc-extractor variant run my-cc -- [args...]                         # run setup wrapper
cc-extractor variant remove my-cc --yes                             # remove setup, keep shared downloads
```

**Create options:**

| Flag | Description |
|------|-------------|
| `--name` | Setup name, also used as wrapper command. |
| `--provider` | Provider preset key (required). |
| `--claude-version` | Target version, `latest`, or `stable`. |
| `--patch-profile` | Apply a saved patch profile. |
| `--tweak` | Curated tweak id (repeatable). |
| `--mcp` | Optional MCP server id (repeatable). |
| `--credential-env` | Environment variable for provider credentials. |
| `--api-key` | API key stored locally (requires `--store-secret`). |
| `--extra-env` | Additional `KEY=VALUE` env entries (repeatable). |
| `--force` | Overwrite an existing setup. |
| Model overrides | `--opus`, `--sonnet`, `--haiku`, `--default`, `--small-fast`, `--subagent`. |

### Inspect

```bash
cc-extractor inspect /path/to/claude
cc-extractor inspect /path/to/claude --json
```

### Extract / Unpack

```bash
cc-extractor extract /path/to/claude ./extracted_files
cc-extractor unpack /path/to/claude --out ./extracted_files
cc-extractor extract /path/to/claude ./extracted_files --include-sourcemaps
```

Extraction writes module files plus `.bundle_manifest.json`. The manifest records platform, module struct size, entry point, byte count, section metadata, and per-module offsets needed by repack.

### Replace Entry JS

```bash
cc-extractor replace-entry /path/to/claude ./entry.js --out ./claude-patched
```

Resizes only the Bun entry module and repacks the binary through `binary_patcher.repack_binary`.

### Apply Binary Theme And Prompt Patches

```bash
cc-extractor apply-binary /path/to/claude --config ./config.json
cc-extractor apply-binary /path/to/claude --config ./config.json --overlays ./overlays.json
```

`config.json` may provide themes as either `{"themes": [...]}` or `{"settings": {"themes": [...]}}`. Prompt overlay misses are reported in the structured JSON result and are not fatal. Theme anchor misses return `anchor-not-found`. On Mach-O binaries, patches that would grow the bundled entry JS are skipped without writing and return `ok: true` with `skipped_reason: "macho-grow-not-supported"`.

### Patch Manifests

```bash
cc-extractor patch init ./my_patch
cc-extractor patch apply ./my_patch ./extracted_files
cc-extractor patch apply ./my_patch ./extracted_files --check
cc-extractor patch apply ./my_patch ./extracted_files --binary /path/to/claude --source-version 1.2.3
```

Creates or applies text patch manifests against extracted bundle files. `--check` validates without writing. `--binary` and `--source-version` override source metadata for cross-version patches.

**CC Router provider:**

The `ccrouter` provider points an isolated Claude Code setup at a local
Claude Code Router service. Install CCR, configure it, and start the service
before running the cc-extractor wrapper:

```bash
npm install -g @musistudio/claude-code-router
# edit ~/.claude-code-router/config.json
ccr start
cc-extractor variant create --name ccrouter --provider ccrouter
```

If CCR config sets `APIKEY`, expose the same value as `CCROUTER_AUTH_TOKEN`
when creating or running the setup. Custom CCR ports require overriding
`ANTHROPIC_BASE_URL` with `--extra-env ANTHROPIC_BASE_URL=http://127.0.0.1:<port>`.
cc-extractor does not start `ccr`, call `ccr code`, or write CCR's global
config. See the [CCR README](https://github.com/musistudio/claude-code-router),
[basic config docs](https://musistudio.github.io/claude-code-router/docs/cli/config/basic/),
and CCR's `ccr activate`/`ccr env` behavior for the upstream environment model.

### Pack

```bash
cc-extractor pack ./modified_files /path/to/original_claude ./new_claude
```

Rebuilds raw Bun bytes from `.bundle_manifest.json`, parses the base binary, and delegates container rewriting to `binary_patcher.repack_binary`.

### Updating Prompt Catalogs

Prompt catalogs live under `prompts/<version>.json`.

Update prompt catalogs for released versions newer than the newest local catalog:

```bash
.venv/bin/python tools/extract_prompt_versions.py --since-existing-latest
```

Fill missing prompt catalogs without touching already-valid files:

```bash
.venv/bin/python tools/extract_prompt_versions.py --missing
```

Process only the newest five missing versions:

```bash
.venv/bin/python tools/extract_prompt_versions.py --missing --max-versions 5
```

Regenerate explicit versions intentionally:

```bash
.venv/bin/python tools/extract_prompt_versions.py \
  --versions 2.1.130 2.1.129 \
  --force-prompts
```

The extractor downloads each native binary, extracts the bundled entry JS, extracts prompt strings, validates the prompt JSON schema, and writes `prompts/<version>.json`.

New versions inherit prompt metadata from the nearest older local prompt catalog when same-version metadata is unavailable. Review unnamed prompts before release, or use `--fail-on-unnamed` to make unnamed entries fail the run.

## Python API

```python
from cc_extractor import (
    download_binary,
    download_npm,
    extract_all,
    pack_bundle,
    apply_patches,
    parse_bun_binary,
    replace_entry_js,
    replace_module,
)
```

The core model is `BunBinaryInfo` and `BunModule` from `cc_extractor.bun_extract.types`.

## Architecture

```text
cc_extractor/
  __init__.py                   Public API with lazy imports
  __main__.py                   CLI entry point and variant dispatcher
  _utils.py                     Cross-module stdlib helpers
  cli/
    parsers.py                  Argparse parser tree
    handlers.py                 Per-subcommand handlers
    payloads.py                 JSON payload helpers
  tui/
    __init__.py                 TUI action layer and main loop
    state.py                    TuiState dataclass and refresh
    themes.py                   Theme definitions
    options.py                  Menu option builders
    rendering.py                Frame rendering
    dashboard.py                Dashboard state management
    variant_actions.py          Variant wizard actions
    keys.py                     Key binding dispatch
    nav.py                      Navigation handlers
    _const.py                   Constants and data classes
    _runtime.py                 ratatui app setup
  workspace/
    __init__.py                 Re-exports
    paths.py                    Workspace path helpers
    models.py                   NativeArtifact, PatchPackage, PatchProfile
    artifacts.py                Artifact scanning
    patches.py                  Patch package helpers
    settings.py                 TUI settings persistence
  variants/
    __init__.py                 Variant lifecycle actions
    model.py                    Variant data model
    builder.py                  Variant builder
    tweaks.py                   Curated tweak definitions
    wrapper.py                  Wrapper script generation
  providers/
    __init__.py                 Provider registry facade
    loader.py                   Provider lookup, env building, theme/prompt helpers
    schema.py                   Provider JSON schema validation/deserialization
    config.py                   Claude settings and MCP server config merges
    mcp_catalog.py              Built-in optional MCP catalog
    model_discovery.py          Provider model discovery helpers
    registry/*.json             Provider templates
  bun_extract/
    constants.py                Shared constants and magic values
    types.py                    BunBinaryInfo, BunModule, exceptions
    parser.py                   Mach-O, ELF, and PE Bun parser
    macho.py                    Read-only Mach-O section scan
    elf.py                      ELF detection and data-start logic
    pe.py                       PE .bun section scan
    extract.py                  Module writer and manifest generation
    replace.py                  Same-size module replacement
  binary_patcher/
    replace_entry.py            Resize-capable entry JS replacement
    repack.py                   Platform repack dispatcher
    elf_resize.py               ELF header, section, and PT_LOAD resize
    macho_resize.py             Mach-O section resize and signature stripping
    pe_resize.py                PE .bun section resize with last-section guard
    theme.py                    Theme anchor patching
    prompts.py                  Prompt overlay patching
    index.py                    Structured apply_patches orchestrator
    codesign.py                 Soft macOS ad-hoc signing helper
    js_patch.py                 Patch extracted entry JS
    unpack_and_patch.py         Extract, patch, package, and npm install fallback
  patcher.py                    Legacy extracted-text patch manifests
  patch_workflow.py             High-level patch, repack, and metadata workflow
  downloader.py                 GCS and NPM download helpers
  download_index.py             Cached live/seed download version index
  download_picker.py            Interactive version picker
  extractor.py                  Compatibility wrapper over bun_extract
  bundler.py                    Compatibility wrapper over binary_patcher
  variant_tweaks.py             Backwards-compat shim
```

```text
tools/
  prompt_extractor.py           Tree-sitter prompt extractor
  extract_prompt_versions.py    Batch prompt extraction and validation
  check_patch_releases.py       Patch compatibility report generator
  run_patch_smoke_docker.sh     Docker runtime smoke helper
```

## Development

```bash
.venv/bin/python -m pytest -q
ruff check cc_extractor tests tools
```

The default test suite does not download real Claude Code binaries. Run the gated integration test explicitly when you need live binary coverage:

```bash
CC_EXTRACTOR_RUN_REAL_BINARY_TEST=1 .venv/bin/python -m pytest -q tests/test_integration_real_binary.py
CC_EXTRACTOR_RUN_REAL_BINARY_TEST=1 CC_EXTRACTOR_REAL_BINARY_VERSION=2.1.119 .venv/bin/python -m pytest -q tests/test_integration_real_binary.py
```

The integration test downloads the host-platform Claude Code binary, patches a temporary copy with a tiny theme config, executes `claude --version`, verifies patched JS markers, and extracts the patched bundle. It is intentionally gated because the download is large and depends on network access.
