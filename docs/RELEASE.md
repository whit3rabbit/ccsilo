# Release Checklist

`ccsilo` is intended to be installed by users with `pipx install ccsilo`
after a PyPI release. Releases are published by `.github/workflows/release.yml`
using PyPI Trusted Publishing, so no PyPI API token should be stored in GitHub.

## One-Time PyPI Setup

Configure Trusted Publishers before the first automated upload.

For TestPyPI:

- Project name: `ccsilo`
- Owner: `whit3rabbit`
- Repository: `ccsilo`
- Workflow: `release.yml`
- Environment: `testpypi`

For PyPI:

- Project name: `ccsilo`
- Owner: `whit3rabbit`
- Repository: `ccsilo`
- Workflow: `release.yml`
- Environment: `pypi`

Create matching GitHub environments named `testpypi` and `pypi`. Require manual
approval on the `pypi` environment before publishing public releases.

The PyPI `Workflow name` field is the workflow filename only, not the display
name. Use `release.yml`, because the file is
`.github/workflows/release.yml`.

Do not add a PyPI API token or password to GitHub. The publish jobs request
`id-token: write` and use `pypa/gh-action-pypi-publish`, which exchanges the
GitHub OIDC token with PyPI or TestPyPI.

## Build And Validate

```bash
.venv/bin/python -m pip install -e '.[dev]'
rm -rf dist build *.egg-info
.venv/bin/python -m pytest -q
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

## TestPyPI

Run the `Release` workflow manually with `repository=testpypi`.

From the GitHub UI:

1. Open `Actions`.
2. Select `Release`.
3. Choose `Run workflow`.
4. Set `Package index to publish to` to `testpypi`.
5. Run it from `main`.

From the GitHub CLI:

```bash
gh workflow run release.yml --ref main -f repository=testpypi
gh run list --workflow release.yml --limit 1
gh run watch
```

After it publishes, verify from a clean environment:

```bash
python -m venv /tmp/ccsilo-testpypi
/tmp/ccsilo-testpypi/bin/python -m pip install --upgrade pip
/tmp/ccsilo-testpypi/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  ccsilo
/tmp/ccsilo-testpypi/bin/ccsilo --help
/tmp/ccsilo-testpypi/bin/ccsilo variant providers --json
```

## PyPI

Publish to PyPI by manually dispatching the `Release` workflow with
`repository=pypi` from the version tag. The workflow validates that the tag
matches `pyproject.toml`, builds and checks the distributions, publishes to
PyPI through the protected `pypi` environment, then creates or updates the
matching GitHub Release. Creating or publishing a GitHub Release by itself does
not upload to PyPI.

Before publishing to PyPI:

1. Confirm the TestPyPI package installed and ran.
2. Confirm `pyproject.toml` has the intended version.
3. Confirm the tag is derived from the same version and points at the intended
   commit.

For a normal release, derive the tag from `pyproject.toml` instead of typing it
by hand:

```bash
VERSION="$(.venv/bin/python -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
TAG="v${VERSION}"
git tag -a "$TAG" -m "ccsilo ${VERSION}"
git push upstream "$TAG"
gh workflow run release.yml --ref "$TAG" -f repository=pypi
gh run list --workflow release.yml --limit 1
gh run watch
```

If a PyPI upload has already happened and only the GitHub tag/release is
missing, do not dispatch the PyPI workflow again. Create the matching tag and
GitHub Release manually. The tag commit must contain the current safe
`.github/workflows/release.yml` behavior and a matching `pyproject.toml`
version, because GitHub Release events run workflow files from the tagged
commit:

```bash
VERSION="$(.venv/bin/python -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
TAG="v${VERSION}"
git tag -a "$TAG" -m "ccsilo ${VERSION}" <commit-with-matching-version-and-safe-release-workflow>
git push upstream "$TAG"
gh release create "$TAG" --title "$TAG" --generate-notes --latest --verify-tag
```

Published GitHub Releases still run the release workflow's version/tag
validation and build checks, but they do not publish to PyPI.

After publishing:

```bash
pipx install ccsilo
ccsilo paths
ccsilo --help
```

After publishing, update the README only if the user install command or release
source changes.

## Version Rules

PyPI versions are immutable. If a real PyPI upload succeeds, fails after
creating the project, or partially uploads files for a version, do not retry the
same version blindly. Bump `pyproject.toml`, commit the bump, tag the new
version, and publish again.

The release tag must be `v<project.version>` from `pyproject.toml`. For PyPI
dispatches, the workflow fails unless `--ref` is that exact tag. If the tag or
GitHub Release is wrong after a successful upload, fix the tag/release metadata
only. Do not re-run the PyPI publish for the same version.

Do not create or publish a GitHub Release from a tag whose
`.github/workflows/release.yml` still publishes on `release.published`; that can
attempt to upload an already-immutable PyPI version. Move the tag to a commit
with the safe workflow and the same project version before publishing the
GitHub Release.

TestPyPI is also effectively immutable for a given filename. For repeated
TestPyPI dry runs, bump the version or use a local build and `twine check`
instead.
