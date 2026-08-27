"""Shared fixtures and helpers for patch tests."""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List

import pytest

from ccsilo.bun_extract import parse_bun_binary
from ccsilo.download_index import load_download_index
from ccsilo.downloader import download_binary
from ccsilo.patches._versions import resolve_range_to_version


def resolve_tested_versions(patch) -> List[str]:
    """Resolve every range in patch.versions_tested to its highest concrete
    version in the local download index. Returns deduplicated list. Ranges
    that resolve to None are dropped (parametrize will skip those buckets
    via pytest.skip in the test body if needed)."""
    index = load_download_index()
    out: List[str] = []
    for range_expr in patch.versions_tested:
        version = resolve_range_to_version(range_expr, index=index)
        if version is not None and version not in out:
            out.append(version)
    return out


_CLI_JS_CACHE = {}


def _extract_cli_js(binary_path: Path) -> str:
    """Extract the patchable JS surface from a Claude Code Bun binary.

    Entry module name varies across versions: 2.0.x uses `claude`, 2.1.x
    uses `cli.js`. Use `info.entry_point_id` as the source of truth.

    Claude Code >= 2.1.242 splits the bundle into many JS modules with a tiny
    entry, so single-module bundles return their entry source while split
    bundles return every loader-js module joined into one string. Real
    single-js patch semantics for split bundles are covered by the module-set
    application path and Docker runtime smoke; L1 here proves anchors exist
    and the patch rewrites them.
    """
    data = binary_path.read_bytes()
    info = parse_bun_binary(data)
    sources = [
        data[info.data_start + module.cont_off : info.data_start + module.cont_off + module.cont_len]
        .decode("utf-8", errors="replace")
        for module in info.modules
        if module.loader == "js"
    ]
    if not sources:
        raise RuntimeError(f"no JS modules found inside {binary_path}")
    if len(sources) == 1:
        return sources[0]
    return "\n;\n".join(sources)


@pytest.fixture(scope="session")
def cli_js_real() -> Callable[[str], str]:
    def loader(version: str) -> str:
        if version in _CLI_JS_CACHE:
            return _CLI_JS_CACHE[version]
        binary_path = download_binary(version=version)
        js = _extract_cli_js(Path(binary_path))
        _CLI_JS_CACHE[version] = js
        return js
    return loader


@pytest.fixture(scope="session")
def parse_js() -> Callable[[str], None]:
    node = shutil.which("node")
    if node is None:
        def _skip(_js: str) -> None:
            pytest.skip("node not on PATH; skipping L2 parse check")
        return _skip

    def runner(js: str) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fp:
            fp.write(js)
            tmp_path = fp.name
        try:
            result = subprocess.run(
                [node, "--check", tmp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                raise AssertionError(
                    f"node --check failed: {result.stderr.strip() or result.stdout.strip()}"
                )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    return runner


@pytest.fixture
def cli_js_synthetic():
    from tests.patches.fixtures.synthetic import SYNTHETIC

    def loader(patch_id: str) -> str:
        if patch_id not in SYNTHETIC:
            raise KeyError(f"no synthetic snippet for patch {patch_id!r}")
        return SYNTHETIC[patch_id]
    return loader
