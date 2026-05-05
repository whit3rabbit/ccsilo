# Patches

Patches rewrite Claude Code's bundled JS to add custom behavior. Each
patch lives in `cc_extractor/patches/<id>.py` and is registered in
`cc_extractor/patches/_registry.py`.

## Authoring a new patch

1. Find the upstream tweakcc patch in `vendor/tweakcc/src/patches/<name>.ts`.
2. Create `cc_extractor/patches/<id>.py` with a `_apply(js, ctx)` function
   and a `PATCH = Patch(...)` constant. Mirror the regex shape from the
   tweakcc TS file. Use `[$\w]+` not `\w+` for identifiers.
3. Add a synthetic snippet for `<id>` to `tests/patches/fixtures/synthetic.py`.
4. Add `tests/patches/test_<id>.py` covering synthetic + real fixtures.
5. Register in `cc_extractor/patches/_registry.py`.
6. If users should be able to select it, add the ID to `CURATED_TWEAK_IDS` in
   `cc_extractor/variants/tweaks.py`.
7. If it is safe for Dashboard one-click use, leave it out of
   `DASHBOARD_EXCLUDED_TWEAK_IDS`; otherwise add it there.
8. Run `pytest -q tests/patches/test_<id>.py` until green.

The TUI does not have a separate patch registry. The setup wizard Tweaks step
auto-populates from `CURATED_TWEAK_IDS`. The two-pane Tweaks editor uses the
same curated IDs, including env-backed tweaks. The Dashboard Patches step
auto-populates from `DASHBOARD_TWEAK_IDS`, which is derived from curated IDs
minus dashboard exclusions and filtered against `_registry.REGISTRY`.

## Patch metadata fields

| Field | Type | Purpose |
|---|---|---|
| `id` | str | Stable kebab-case identifier |
| `name` | str | Human-readable label |
| `group` | str | One of: ui, thinking, prompts, tools, system |
| `versions_supported` | SemVer range | Versions where the patch is allowed |
| `versions_tested` | tuple of SemVer ranges | Each entry = one test matrix bucket |
| `versions_blacklisted` | tuple of exact versions | Known-broken versions |
| `on_miss` | "fatal" \| "skip" \| "warn" | What happens if anchor not found |
| `apply` | callable | `(js, ctx) -> PatchOutcome` |

## Version support policy

`versions_supported` and `versions_tested` are deliberately different:

- `versions_supported` is the broad range where the patch is allowed to run.
- `versions_tested` is the concrete release coverage proven by real fixture tests.

Do not use an open-ended minor range such as `>=2.1.0,<2.2` in
`versions_tested` unless every future `2.1.x` release should be treated as
already verified. That is usually wrong for regex anchors. Prefer a pinned upper
bound, for example `>=2.1.0,<=2.1.122`, and widen it only after testing against
the new release.

`DEFAULT_VERSION_RANGES` is intentionally pinned to the latest release proven by
the checked-in seed index. If a live or manually refreshed download index finds a
newer Claude Code release, patch application still runs when the version is in
`versions_supported`, but it emits an untested-version warning. Treat that
warning as feedback that the patch needs validation before release.

When an anchor is missing, include a useful `PatchOutcome.notes` entry:

```python
return PatchOutcome(js=js, status="missed", notes=("missing token limits",))
```

Fatal and warning misses surface those notes to setup and variant workflows, so
users can tell which sub-anchor failed. If upstream removed a sub-feature, either
narrow `versions_tested` or explicitly skip that obsolete sub-anchor with a note.
Do not return `applied` for a no-op.

## Release compatibility reports

Use the patch release checker to validate curated regex patches against newly
released Claude Code binaries:

```bash
# Check releases newer than the newest existing report
.venv/bin/python tools/check_patch_releases.py --since-existing-latest

# Check the latest release only
.venv/bin/python tools/check_patch_releases.py --latest

# Check specific releases
.venv/bin/python tools/check_patch_releases.py --versions 2.1.128
```

Reports are written to `reports/patch-compat/<version>.json`, with a run index at
`reports/patch-compat/index.json`. Each report records per-patch status,
supported/tested flags, warnings, notes, and failure details. A patch can apply
successfully and still be marked untested when the release is outside
`versions_tested`; treat that as a validation task before widening metadata.
Patches outside `versions_supported` are reported as `unsupported`, but they do
not fail the run because the metadata already says not to apply them.

## Test tiers

- **L1 (anchor):** regex matches expected pattern. Run via `pytest tests/patches/`.
- **L2 (parse):** patched JS parses cleanly under `node --check`. Same command; skipped if Node missing.
- **L3 (boot smoke):** built variant binary boots and exits cleanly.
  Run with `CC_EXTRACTOR_REAL_BINARY=1 pytest tests/patches_smoke/`.
- **L4 (behavioral):** TUI MCP drives the variant, screen state captured
  and diffed against snapshots.
  Run with `CC_EXTRACTOR_TUI_MCP=1 pytest tests/patches_behavioral/`.

## Updating L4 snapshots

```bash
CC_EXTRACTOR_TUI_MCP=1 CC_EXTRACTOR_UPDATE_SNAPSHOTS=1 \
  pytest tests/patches_behavioral/test_<id>_snapshot.py
```

## Running everything

```bash
CC_EXTRACTOR_REAL_BINARY=1 CC_EXTRACTOR_TUI_MCP=1 \
  .venv/bin/python -m pytest -q
```
