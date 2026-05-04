`cc-extractor` is a Python toolkit for inspecting, extracting, patching, repacking, and managing Claude Code Bun standalone binaries.

The current product surface has three major workflows:

1. Binary tooling: download, inspect, extract, unpack, replace entry JS, apply binary-level theme/prompt patches, and repack.
2. Setup management: create isolated Claude Code setups/variants with provider configuration, model overrides, credentials, wrappers, and curated tweaks.
3. TUI workflow: manage setups, build patched binaries from curated tweaks, inspect/download artifacts, extract bundles, and apply workspace patch packages.

Use this repository for research and controlled local patching only. Avoid adding behavior that silently mutates user-global Claude Code state unless the relevant workflow explicitly owns that config write.

## Commands

Use `.venv/bin/python` from the repository root.

```bash
# Install
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install -e '.[dev]'

# Open TUI
.venv/bin/python -m cc_extractor

# Binary / bundle commands
.venv/bin/python -m cc_extractor download [version]
.venv/bin/python -m cc_extractor download --latest
.venv/bin/python -m cc_extractor download --npm [version]
.venv/bin/python -m cc_extractor inspect <binary> --json
.venv/bin/python -m cc_extractor extract <binary> [outdir] [--source-version <version>] [--include-sourcemaps]
.venv/bin/python -m cc_extractor unpack <binary> --out <dir>
.venv/bin/python -m cc_extractor replace-entry <binary> <entry-js> --out <binary>
.venv/bin/python -m cc_extractor apply-binary <binary> --config <config.json> [--overlays <overlays.json>]
.venv/bin/python -m cc_extractor pack <dir> <base-binary> <out-binary>

# Legacy extracted-bundle patch manifests
.venv/bin/python -m cc_extractor patch init <patch-dir>
.venv/bin/python -m cc_extractor patch apply <patch-dir> <extract-dir> [--check] [--binary <binary>] [--source-version <version>]

# Setup / variant commands
.venv/bin/python -m cc_extractor variant providers [--json]
.venv/bin/python -m cc_extractor variant create --name <name> --provider <key> [--claude-version <v>] [--patch-profile <id>] [--tweak <id> ...]
.venv/bin/python -m cc_extractor variant create --name <name> --provider <key> --credential-env <ENV_NAME>
.venv/bin/python -m cc_extractor variant create --name <name> --provider <key> --api-key <key> --store-secret
.venv/bin/python -m cc_extractor variant list [--json]
.venv/bin/python -m cc_extractor variant show <name-or-id> [--json]
.venv/bin/python -m cc_extractor variant apply <name-or-id> [--json]
.venv/bin/python -m cc_extractor variant update [<name-or-id> | --all] [--claude-version <v>] [--json]
.venv/bin/python -m cc_extractor variant doctor [<name-or-id> | --all] [--json]
.venv/bin/python -m cc_extractor variant remove <name-or-id> [--yes]
.venv/bin/python -m cc_extractor variant run <name-or-id> -- [args...]

# Test / lint
.venv/bin/python -m pytest -q
ruff check cc_extractor/
ruff check --fix cc_extractor/
```

Do not document `python main.py ...` as canonical unless `main.py` is restored.

## Prompt Catalog Updates

Prompt catalogs live in `prompts/<version>.json`.

Preferred update commands:

```bash
# Update all released versions newer than the newest local prompt catalog
.venv/bin/python tools/extract_prompt_versions.py --since-existing-latest

# Fill gaps in prompts/ without touching already-valid files
.venv/bin/python tools/extract_prompt_versions.py --missing

# Process only the newest five missing catalogs
.venv/bin/python tools/extract_prompt_versions.py --missing --max-versions 5

# Regenerate known versions intentionally
.venv/bin/python tools/extract_prompt_versions.py --versions <v1> <v2> --force-prompts
```

Rules:

* Prefer `--since-existing-latest` after upstream releases.
* Prefer `--missing` when backfilling gaps.
* Avoid `--all --force-prompts` unless intentionally rebuilding the whole catalog.
* New prompt catalogs should use the nearest older local prompt JSON as metadata seed when same-version tweakcc metadata is unavailable.
* Validate every generated file before writing.
* Treat unnamed prompt entries as release blockers unless explicitly accepted. Use `--fail-on-unnamed` for release-prep runs.
* Commit prompt JSON updates separately from unrelated patch or TUI changes.

## Architecture

```text
__main__.py                  -> CLI entrypoint, simple dispatcher, variant dispatcher, TUI launch when attached to TTY
cli/parsers.py               -> argparse tree only
cli/handlers.py              -> top-level command handlers for download/extract/unpack/inspect/replace-entry/apply-binary/pack/patch
cli/payloads.py              -> JSON payload helpers and variant argument mappers

bun_extract/                 -> Bun standalone parser, extract, same-size replacement, shared binary metadata types
binary_patcher/              -> Native binary patching, entry replacement, platform repack, theme/prompt patching, codesign, unpacked fallback
patches/                     -> Curated regex-tweak registry; each patch module exposes PATCH
patch_workflow.py            -> Native artifact workflows for patch packages and dashboard tweak builds
patcher.py                   -> Legacy extracted-text patch manifest workflow

providers/                   -> Provider registry package
providers/registry/*.json    -> Provider templates
providers/schema.py          -> Provider JSON schema validation/deserialization
providers/loader.py          -> Provider lookup, env building, theme/prompt overlay helpers
providers/config.py          -> Claude config merges for settings permissions and MCP servers

variants/                    -> Setup/variant lifecycle
variants/__init__.py         -> Action layer for create/apply/update/remove/doctor/run
variants/model.py            -> Variant dataclasses, manifest validation, provider list payloads
variants/builder.py          -> Source resolution, patch refs, entry JS patch helpers
variants/tweaks.py           -> Curated tweak application and env-only tweak handling
variants/wrapper.py          -> Wrapper script, config, and secrets file writing
variant_tweaks.py            -> Backwards-compatible shim over variants.tweaks

workspace/                   -> Workspace models, paths, artifact scanning, patch/tweak profile persistence, TUI settings
tui/                         -> TUI action layer, rendering, state, navigation, dashboard, setup actions, keys, themes
download_index.py            -> Cached live/seed version index
download_picker.py           -> Interactive version picker
downloader.py                -> Native and NPM download logic
extractor.py                 -> Compatibility wrapper over bun_extract
bundler.py                   -> Compatibility wrapper over binary_patcher.repack_binary
_utils.py                    -> stdlib-only helpers shared across modules
```

## TUI Notes

* The TUI tabs are: `Manage Setup`, `Dashboard`, `Inspect`, `Extract`, `Patch`.
* Startup routing:

  * if setups/variants exist, start in `setup-manager`;
  * if none exist, start in `first-run-setup`.
* `Manage Setup` owns setup lifecycle: create, run, upgrade, health check, delete, logs, tweak editing, and command/config copy actions.
* `Dashboard` is a guided native-binary tweak workflow: choose source, choose curated dashboard tweaks, manage tweak profiles, review, then build.
* `Patch` is for workspace patch packages under `.cc-extractor/patches/packages/`.
* `Tweaks` editing is scoped to an existing setup and rebuilds through `variants.apply_variant`.
* Keep action-layer functions that tests monkey-patch in `tui/__init__.py`. Pure rendering/options/navigation helpers belong in submodules.

## Workspace Layout

Default workspace root is `.cc-extractor/`, unless `CC_EXTRACTOR_WORKSPACE` is set.

```text
.cc-extractor/
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

* `patches/packages/` stores patch package manifests and operations.
* `patches/profiles/` stores patch-package profile refs.
* `patches/tweak-profiles/` stores Dashboard curated tweak profile refs.
* `variants/<id>/variant.json` is the setup manifest.
* `variants/<id>/secrets.env` may exist only when the user explicitly uses stored credentials.
* `bin/` stores wrapper commands.

## Behavior Notes

* `parse_bun_binary` is the single source of truth for binary layout.
* Use `info.entry_point_id` to find the entry module. Do not assume entry names like `claude` or `cli.js`.
* Bun module bytes use `cont_off` and `cont_len`; do not invent `data_offset` or `data_size`.
* `extractor.py` and `bundler.py` are compatibility wrappers, not independent implementations.
* Keep `patcher.py` separate from `binary_patcher`; it handles legacy extracted-text patch manifests.
* `cc_extractor.patches.apply_patches` applies curated regex tweaks.
* `cc_extractor.binary_patcher.index.apply_patches` applies binary theme/prompt patches.
* `patch_workflow.apply_patch_packages_to_native` extracts, applies workspace patch packages, repacks, and writes patched metadata.
* `patch_workflow.apply_dashboard_tweaks_to_native` applies curated tweak IDs directly for Dashboard builds.
* Theme anchor misses are fatal structured failures.
* Prompt anchor misses are recorded and non-fatal.
* On Mach-O, prompt overlays that grow the entry module must force the unpacked Node runtime fallback even if a later shrink tweak makes the final byte length fit. Do not let net shrinkage mask intermediate prompt-overlay growth.
* Bun CJS entry modules must keep a valid `// @bun ... @bun-cjs` function wrapper. Same-size shrink padding must not be appended after the closing wrapper.
* Mach-O signing is explicit and soft-failing through `binary_patcher/codesign.py`.
* Unpacked fallback supports both Python `.bundle_manifest.json` and TS-style `manifest.json`.
* Unpacked Node runtime entry JS must be passed through `binary_patcher.bun_compat.ensure_bun_node_compat` after stripping the Bun wrapper and after any later variant-only JS tweak writes. Preserve the `cc-extractor:bun-node-compat` marker.
* `variant doctor` includes a `node-bun-compat` check for stale Node-runtime entries that still reference `Bun.*` without the compat marker. Reapply or update the setup to regenerate the entry.
* PE resize requires `.bun` to be the last raw-data section.
* On non-Windows, written binaries/wrappers should be chmodded executable.

## Provider Notes

* Provider definitions live in `providers/registry/*.json`.
* Validate provider JSON through `providers/schema.py`.
* Build runtime env through `build_provider_env`; do not hand-roll provider env dictionaries.
* Provider auth modes are `apiKey`, `authToken`, and `none`.
* Provider templates may define model mappings, prompt overlays, themes, denied tools, MCP servers, setup links, and TUI metadata.
* `providers/config.py` is responsible for merging provider-specific Claude config into `settings.json` and `.claude.json`.

## Variant / Setup Notes

* Variants are addressable by name or id; `variant_id_from_name` derives lower-kebab-case ids.
* `validate_variant_manifest` is the manifest authority. Do not bypass it.
* Runtime may be `native` or `node`.
* Node runtime wrappers require a Node version with explicit resource management support and allow `NODE=/path/to/node` override.
* If a Node-runtime setup fails `node-bun-compat`, run `.venv/bin/python -m cc_extractor variant apply <name-or-id> --json` instead of hand-editing generated unpacked files.
* `DEFAULT_TWEAK_IDS` are selected on create.
* `ENV_TWEAK_IDS` affect wrapper environment rather than patching JS.
* In-place rebuild optimization applies only to supported theme/prompt/env tweak changes; otherwise rebuild from source.

## Development Notes

* Python target: 3.8+.
* TUI dependency is the holo-q `ratatui-py` shim imported as `ratatui_py`.
* Do not swap to `pyratatui` unless the TUI/test API is deliberately migrated.
* TUI changes should include widget-independent state tests and, when available, headless/smoke coverage.
* For TUI MCP/key tests, use single named keys like `Down`, `Up`, `Tab`, `Enter`, `Space`, and `q`. Avoid strings like `"Tab Tab"`.
* `Down`/`Up` are the expected named keys; `ArrowDown`/`ArrowUp` silently no-op in the current test harness.
* Keep monkey-patch-sensitive action functions in `tui/__init__.py` and `variants/__init__.py`.
* Keep `_utils.py` stdlib-only to avoid circular imports.
* Do not move `downloader.py` without updating tests that patch `cc_extractor.downloader.*`.
* Do not stage or commit submodule/vendor changes unless explicitly requested.


## Adding Curated Regex Tweaks

Curated tweaks live under `cc_extractor/patches/` and are registered explicitly in
`cc_extractor/patches/_registry.py`.

Use this flow when adding a new tweak:

1. Create a new module under `patches/` using snake_case, for example:

   ```text
   patches/my_new_tweak.py
   ```

2. Implement `_apply(js: str, ctx: PatchContext) -> PatchOutcome`.

   Required behavior:

   * Return `PatchOutcome(js=new_js, status="applied")` when the patch changed JS.
   * Return `PatchOutcome(js=js, status="skipped")` when the patch is already present or intentionally inactive.
   * Return `PatchOutcome(js=js, status="missed")` when the expected anchor cannot be found.
   * Make patches idempotent when possible by checking for a stable marker or already-patched shape.
   * Do not silently return `applied` when the output is identical.
   * Keep regex windows narrow enough to avoid unrelated minified code.

3. Define `PATCH = Patch(...)` at the bottom of the module.

   Required fields:

   * `id`: lower-kebab-case, stable public id.
   * `name`: short human-readable label.
   * `group`: one of `ui`, `thinking`, `prompts`, `tools`, or `system`.
   * `versions_supported`: broad compatible range, usually `>=2.0.0,<3`.
   * `versions_tested`: use `DEFAULT_VERSION_RANGES` unless the patch has narrower proven coverage.
   * `apply`: `_apply`.
   * `description`: one sentence explaining user-visible behavior.
   * `on_miss`: default is `fatal`; use `warn` only for optional/provider-dependent anchors.

4. Register the module in `patches/_registry.py`.

   Add the import and add the `PATCH` object to `REGISTRY`. Registry order controls display order inside groups, so place the patch near related tweaks.

5. If the patch should be selectable in the Dashboard default/recommended flow, update the relevant tweak list in `variant_tweaks.py` or `variants/tweaks.py`.
   Do not add risky or behavior-changing patches to defaults without explicit reason.

6. Add tests before widening `versions_tested`.

   Minimum tests:

   * anchor/applies test with a representative JS fixture;
   * idempotency test if the patch injects code;
   * miss test that verifies `missed` or the configured `on_miss` behavior;
   * registry test that confirms the patch id is registered and grouped correctly;
   * version-range test that confirms every `versions_tested` range is inside `versions_supported`.

7. Do not confuse curated tweaks with workspace patch packages.

   `cc_extractor.patches.apply_patches` is the regex-tweak registry.
   `cc_extractor.binary_patcher.index.apply_patches` is the binary theme/prompt patch API.
   `patch_workflow.apply_patch_packages_to_native` applies workspace patch packages.

## Patch Testing

Use layered validation for patch work.

```bash
# Fast unit/registry/anchor tests
.venv/bin/python -m pytest -q tests/patches/

# Show skip reasons while validating patch support
.venv/bin/python -m pytest -q -rs tests/patches/

# Full suite
.venv/bin/python -m pytest -q
```

Patch test expectations:

* L1 anchor tests should prove the regex finds the intended minified structure.
* L2 parse tests may use `node --check`, but Bun-bundled `cli.js` can fail under Node because of `bun:` imports. Pre-check the unpatched JS and skip L2 if the baseline does not parse.
* L3 real-binary boot smoke tests must be gated behind `CC_EXTRACTOR_REAL_BINARY=1`.
* L4 TUI/MCP behavioral tests must be gated behind `CC_EXTRACTOR_TUI_MCP=1`.
* Real download/patch/execute integration tests must be separately gated behind `CC_EXTRACTOR_RUN_REAL_BINARY_TEST=1`.
* Expected environment-gated skips are not failures. Use `pytest -q -rs` to verify skip reasons.

Before updating `versions_tested`, prove the patch against a concrete Claude Code version. Do not widen `versions_tested` just because `versions_supported` is broad.

## TUI Rendering Stability

Avoid full-screen clears in steady-state TUI render loops.

* Do not set `ratatui_py.App(clear_each_frame=True)` for `cc_extractor.tui.run_tui` or other idle-redrawing TUI flows without a measured reason.
* The `App` loop renders every tick. Clearing every frame causes visible flashing even when the user is idle.
* Prefer a startup clear through `on_start`, then normal redraws without per-frame clear.
* For flicker regressions, use PTY capture or TUI MCP smoke and count repeated full-clear escape sequences such as `ESC[2J` while idle.
* Keep constructor-flag tests for TUI entry points that use `ratatui_py.App`.

## TUI MCP Behavioral Testing

Use the TUI MCP testing tool for workflows that cannot be validated by pure state/render tests alone.

Use MCP smoke tests for:
- first-run setup flow;
- setup manager navigation;
- tweak selection/edit/apply flow;
- Dashboard source selection;
- Dashboard tweak profile save/load/rename/delete;
- patch package profile selection;
- focus, resize, and keyboard navigation regressions.

Always run MCP TUI tests with an isolated workspace:

```bash
CC_EXTRACTOR_WORKSPACE="$(mktemp -d)" \
CC_EXTRACTOR_TUI_MCP=1 \
.venv/bin/python -m pytest -q tests/patches_behavioral/
```

Rules for writing TUI MCP tests:

* Use a temporary `CC_EXTRACTOR_WORKSPACE`.
* Do not depend on the developer’s real `.cc-extractor` workspace.
* Prefer fixture-created variant manifests over real binaries for list/edit flows.
* Variant manifest stubs only need:

  * `schemaVersion`
  * `id`
  * `name`
  * `provider.key`
  * `source.version`
  * `paths`
  * `createdAt`
  * `updatedAt`
* Use named keys exactly as supported by the harness:

  * `Down`
  * `Up`
  * `Tab`
  * `Enter`
  * `Space`
  * `Esc`
  * `q`
* Do not use `ArrowDown` or `ArrowUp`; they silently no-op in the current harness.
* Each `send_keys` call sends one named key. Do not send `"Tab Tab"` because spaces and letters are interpreted as character input.
* Assert visible text and mode transitions, not implementation details.
* For layout changes, assert that key panels still render after resize and that important controls are not clipped.
* Pair MCP tests with widget-independent state tests. MCP should cover user workflow, not every state transition.

## Definition of Done for a New Tweak

A new curated tweak is not complete until:

- patch module exists under `patches/`;
- `PATCH.id` is stable lower-kebab-case;
- `PATCH.group` is valid;
- `_apply` is idempotent or intentionally documents why not;
- `_apply` returns only `applied`, `skipped`, or `missed`;
- patch is registered in `_registry.py`;
- registry grouping still works;
- tests cover apply, miss, and idempotency paths;
- version tests prove `versions_tested` is inside `versions_supported`;
- Dashboard/Tweaks visibility is intentional;
- TUI MCP smoke test exists if the patch changes visible UI behavior;
- real-binary smoke test is gated, not run by default.

## Patch Source Code

- When creating patches you can use @original as source of truth when creating patches. This is a reference only and will be to understand original code. Do not commit.
