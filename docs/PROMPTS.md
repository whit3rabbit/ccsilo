# Prompt Extraction

Prompt catalogs live in `prompts/<version>.json`. They describe prompt-like
strings found in a Claude Code bundled entry file and attach stable metadata
used by prompt patching workflows.

This process is a controlled extraction pipeline, not a deobfuscator. The
binary gives us prompt text. Names, IDs, descriptions, and friendly identifier
labels come from existing catalogs, usually the vendored tweakcc prompt data.

## Catalog Shape

Each catalog is:

```json
{
  "version": "2.1.123",
  "prompts": [
    {
      "name": "System Prompt: Example",
      "id": "system-prompt-example",
      "description": "Short human description.",
      "pieces": ["Hello ${", "}"],
      "identifiers": [0],
      "identifierMap": {"0": "NAME"},
      "version": "2.1.122"
    }
  ]
}
```

Fields:

| Field | Purpose |
| --- | --- |
| `name` | Human-readable catalog label. Empty means metadata was not recovered. |
| `id` | Stable public prompt ID. Empty means metadata was not recovered. |
| `description` | Human-readable purpose. Empty means metadata was not recovered. |
| `pieces` | Static text around template substitutions. |
| `identifiers` | Numeric references into `identifierMap`, one per substitution. |
| `identifierMap` | Friendly names for substitutions, recovered from existing catalogs. |
| `version` | Version where this prompt metadata/content was last known. |

For a template literal such as:

```js
`Hello ${name}`
```

the extractor emits:

```json
{
  "pieces": ["Hello ${", "}"],
  "identifiers": [0],
  "identifierMap": {"0": ""}
}
```

## Main Commands

Use `.venv/bin/python` from the repository root.

```bash
# Update all released versions newer than the newest local prompt catalog
.venv/bin/python tools/extract_prompt_versions.py --since-existing-latest

# Fill gaps in prompts/ without touching already-valid files
.venv/bin/python tools/extract_prompt_versions.py --missing

# Process only the newest five missing catalogs
.venv/bin/python tools/extract_prompt_versions.py --missing --max-versions 5

# Regenerate known versions intentionally
.venv/bin/python tools/extract_prompt_versions.py --versions 2.1.123 --force-prompts

# Release-prep mode, fail if any unnamed prompt still has a review-only metadata candidate
.venv/bin/python tools/extract_prompt_versions.py --versions 2.1.123 --force-prompts
.venv/bin/python tools/suggest_prompt_metadata.py \
  --target prompts/2.1.123.json \
  --out tmp/prompt-metadata-candidates-2.1.123.json \
  --update-target \
  --fail-on-review-needed
```

Useful options:

| Option | Purpose |
| --- | --- |
| `--catalog-dir` | Directory containing `prompts-<version>.json`, default `vendor/tweakcc/data/prompts`. |
| `--download-dir` | Binary cache directory, default `downloads`. |
| `--work-dir` | Extraction work directory, default `downloads`. |
| `--force-download` | Remove the cached binary before downloading. |
| `--force-extract` | Re-extract modules from the binary. |
| `--force-prompts` | Rebuild the catalog even if `prompts/<version>.json` exists. |
| `--fail-on-unnamed` | Mark a version failed if any prompt lacks `name` or `id`. This is stricter than normal release prep and requires explicit acceptance for documented no-candidate extras. |
| `--stop-on-error` | Stop after the first failed version. |

## Extraction Flow

`tools/extract_prompt_versions.py` owns version orchestration:

1. Resolve target versions from `--versions`, `--local`, `--missing`,
   `--since-existing-latest`, or `--all`.
2. Download or reuse the native Claude Code binary.
3. Parse the Bun standalone layout with `parse_bun_binary`.
4. Extract embedded modules with `ccsilo.bun_extract.extract_all`.
5. Locate the bundled CLI entry file from `.bundle_manifest.json` or
   `src/entrypoints/cli.js`.
6. Select a seed catalog for metadata recovery.
7. Run `tools.prompt_extractor.extract_prompts`.
8. Validate the JSON shape before writing `prompts/<version>.json`.

`tools/prompt_extractor.py` owns prompt extraction from JS:

1. Parse JavaScript with tree-sitter when available, otherwise use the fallback
   scanner.
2. Collect string literals and template literals that pass `validate_input`.
3. Convert normal string escape sequences to runtime text.
4. Preserve template literal static pieces as extracted source text.
5. Split template substitutions into `pieces` and numeric `identifiers`.
6. Apply placeholders for unstable values such as `<<CCVERSION>>` and
   `<<BUILD_TIME>>`.
7. Merge metadata from a seed catalog.
8. Recover short known prompts from the seed catalog even if they are below
   the normal minimum length.

## Metadata Recovery

Newly extracted prompt objects start with blank metadata. Metadata is recovered
from prior catalogs by matching prompt text plus identifier sequence.

Seed selection matters:

| Situation | Seed preference |
| --- | --- |
| Existing output and no `--force-prompts` | Keep and validate the existing local file. |
| No local output | Exact `--catalog-dir/prompts-<version>.json`, then nearest named seed. |
| `--force-prompts` with exact vendor catalog | Use the exact vendor catalog first. |
| `--force-prompts` without exact vendor catalog | Choose the available seed with the most named prompts from existing output, nearest vendor catalog, and nearest local catalog. |

Matching rules:

- Exact `joined(pieces) + identifiers` matches win first.
- If exact matching fails, the extractor compares JS-escape-equivalent text.
  This handles cases where extracted template source contains text like
  `\u2014`, while a seed catalog stores the decoded character.
- Normalization is used only for matching. The generated catalog preserves the
  original extracted `pieces`.
- Ambiguous normalized matches are ignored. Do not attach metadata when more
  than one seed prompt could match.
- Unmatched strings stay unnamed. Do not invent names, IDs, descriptions, or
  identifier labels.

## Metadata Candidate Reports

Use `tools/suggest_prompt_metadata.py` when a generated catalog has unnamed
prompts and no exact seed catalog is available. The tool builds a historical
index from local `prompts/` and vendored `vendor/tweakcc/data/prompts/`, then
writes a review report without changing `prompts/<version>.json`.

```bash
.venv/bin/python tools/suggest_prompt_metadata.py \
  --target prompts/2.1.123.json \
  --history-dir prompts \
  --catalog-dir vendor/tweakcc/data/prompts \
  --out tmp/prompt-metadata-candidates-2.1.123.json
```

The report classifies unnamed prompts as `auto_applicable`, `review_only`, or
`no_candidate`. Exact normalized matches and very high-confidence fuzzy matches
can become auto-applicable only when the identifier sequence matches and no
competing historical prompt ID exists. Ambiguous exact matches, competing fuzzy
matches, and low-confidence matches stay review-only.

To write a reviewed seed-shaped catalog, pass `--write-seed`:

```bash
.venv/bin/python tools/suggest_prompt_metadata.py \
  --target prompts/2.1.123.json \
  --out tmp/prompt-metadata-candidates-2.1.123.json \
  --write-seed tmp/prompt-seed-2.1.123.json
```

Seed output copies metadata only for `auto_applicable` candidates. It preserves
the target prompt `pieces`, and leaves every review-only or unresolved prompt
unnamed.

The scheduled prompt-update CI runs this suggestion pass for prompt catalogs
changed by extraction. It uses `--update-target` to write only auto-applicable
metadata back to those changed catalogs, then `--fail-on-review-needed` to block
review-only candidates before committing. `no_candidate` entries remain unnamed
unless a verified catalog match is added later.

## Bun-Specific Issues

Bun standalone binaries store a `StandaloneModuleGraph` in a platform-specific
location:

| Platform | Embedded data location |
| --- | --- |
| macOS | `__BUN` Mach-O segment |
| Linux | Appended ELF payload |
| Windows | `.bun` PE section |

Important Bun behavior for this repo:

- The full JavaScript source is still embedded, even when bytecode is present.
  Bytecode is a startup optimization, not a useful prompt-hiding layer.
- Source maps are not included by default for `bun build --compile`.
- Production builds minify identifiers. Local variable names, wrapper names,
  function parameters, and internal import bindings are generally lost.
- String literals, property names, object keys, export alias strings, and many
  user-facing names survive minification.
- Bundled modules may be CommonJS-wrapped, ESM-wrapped, or unwrapped. Entry
  modules are commonly unwrapped, so visible module boundaries are incomplete.
- Minified bundles strip useful comments and import statements, so source file
  names and import relationships cannot be trusted unless recovered elsewhere.

Reference: `https://raw.githubusercontent.com/vicnaum/bun-demincer/refs/heads/master/docs/BUN.md`.

## Limitations

Be strict about what the extractor can prove:

- It can find prompt-like strings. It cannot prove every string is used as a
  runtime prompt.
- It cannot recover prompt names, IDs, descriptions, or friendly interpolation
  names from minified Bun locals. Those come from seed catalogs.
- It can normalize JS escapes for matching. It does not perform semantic fuzzy
  matching or rewrite generated `pieces`.
- It can recover short prompts only when a seed catalog already knows them.
- It may extract docs, HTML, API references, or tool text that are not in the
  upstream prompt catalog. Leave those unnamed unless there is a verified
  catalog match.
- It may miss prompts that are dynamically assembled from many short literals
  or non-obvious data structures.
- `node --check` is not a reliable parse test for every extracted Claude Code
  entry file because Bun-specific imports and bundle constructs can fail under
  Node.
- Catalogs generated from a degraded seed can propagate missing metadata. Use
  exact vendor catalogs or nearest named seeds when regenerating.
- No network fetch is performed by default. Update `vendor/tweakcc/data/prompts`
  separately if newer vendor catalogs are needed.

## Validation Checklist

Before committing prompt catalog changes:

1. Run the metadata suggestion pass with `--fail-on-review-needed`.
2. Review the summary output, especially `named`, `unnamed`, and `review-only` counts.
3. Compare against the nearest vendor catalog when available.
4. Run focused tests:

   ```bash
   .venv/bin/python -m pytest -q tests/test_prompt_extractor.py tests/test_prompt_version_extraction.py
   ```

5. Run the full suite before landing extractor changes:

   ```bash
   .venv/bin/python -m pytest -q
   ```

6. Commit prompt JSON updates separately from extractor, patch, or TUI changes.

## Troubleshooting

| Symptom | Likely cause | Next step |
| --- | --- | --- |
| Many prompts have empty metadata after `2.1.110` | Seed catalog did not match escaped template text or was already degraded. | Regenerate with current extractor and an exact or nearest named vendor catalog. |
| A newer version has all prompts unnamed | No exact vendor catalog exists and the nearest local seed is degraded. | Update `vendor/tweakcc/data/prompts` or use the nearest named vendor seed. |
| A known short prompt is missing | It is below `min_length` and not present in the seed catalog. | Add or update the seed catalog, then regenerate. |
| Extracted count is higher than vendor count | The extractor found extra prompt-like docs or embedded references. | Leave unmatched extras unnamed unless a verified catalog match exists. |
| Prompt names attach to the wrong item | Matching is too broad or ambiguous. | Add a regression test and require exact or unambiguous normalized matching. |
| Parse/extraction fails for a binary | Bun layout parser or entry-point detection changed. | Inspect `.bundle_manifest.json`, `info.entry_point_id`, and `ccsilo/bun_extract`. |
