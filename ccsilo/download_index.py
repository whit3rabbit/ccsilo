"""Cached version index for available Claude Code downloads."""

from pathlib import Path
from typing import Dict, List, Optional

from ._utils import version_sort_key
from .downloader import (
    GCS_BUCKET,
    NPM_REGISTRY_URL,
    PACKAGE_NAME,
    fetch_latest_binary_version,
    fetch_latest_npm_version,
    get_platform_key,
    list_available_binary_versions,
    list_available_npm_versions,
)
from .workspace import ensure_workspace, read_json, write_json, workspace_root


DOWNLOAD_INDEX_FILENAME = "download-index.json"
SEED_INDEX_PATH = Path(__file__).parent / "data" / "download-index.seed.json"


def download_index_path(root=None) -> Path:
    return workspace_root(root) / DOWNLOAD_INDEX_FILENAME


def load_download_index(root=None) -> Dict:
    path = download_index_path(root)
    if path.exists():
        return read_json(path)
    return load_seed_download_index()


def load_seed_download_index() -> Dict:
    if not SEED_INDEX_PATH.exists():
        return _empty_index(source="seed")
    return read_json(SEED_INDEX_PATH)


def refresh_download_index(root=None, include_npm=True, platform_key: Optional[str] = None) -> Dict:
    platform_key = platform_key or get_platform_key()
    binary_versions = list_available_binary_versions()
    binary_latest = fetch_latest_binary_version()

    npm_versions = []
    npm_latest = None
    if include_npm:
        npm_versions = list_available_npm_versions()
        npm_latest = fetch_latest_npm_version()

    index = {
        "schemaVersion": 1,
        "source": "live",
        "platform": platform_key,
        "binary": {
            "latest": binary_latest,
            "versions": [_binary_entry(version, platform_key) for version in binary_versions],
        },
        "npm": {
            "latest": npm_latest,
            "versions": [_npm_entry(version) for version in npm_versions],
        },
    }
    ensure_workspace(root)
    write_json(download_index_path(root), index)
    return index


def download_versions(index: Dict, kind: str = "binary") -> List[str]:
    versions = index.get(kind, {}).get("versions", [])
    result = []
    for item in versions:
        if isinstance(item, dict) and isinstance(item.get("version"), str):
            result.append(item["version"])
    return result


def effective_latest_download_version(index: Dict, kind: str = "binary") -> str:
    marker = str((index.get(kind, {}) or {}).get("latest") or "")
    versions = download_versions(index, kind)
    candidates = [version for version in [marker, *versions] if version]
    if not candidates:
        return ""
    return sorted(candidates, key=version_sort_key, reverse=True)[0]


def download_version_entry(index: Dict, version: str, kind: str = "binary") -> Optional[Dict]:
    for item in index.get(kind, {}).get("versions", []):
        if isinstance(item, dict) and item.get("version") == version:
            return item
    return None


def _binary_entry(version: str, platform_key: Optional[str] = None) -> Dict:
    entry = {
        "version": version,
        "manifestUrl": f"{GCS_BUCKET}/{version}/manifest.json",
        "downloadPrefix": f"{GCS_BUCKET}/{version}",
    }
    if platform_key:
        binary_name = "claude.exe" if platform_key.startswith("win32") else "claude"
        entry["platform"] = platform_key
        entry["downloadUrl"] = f"{GCS_BUCKET}/{version}/{platform_key}/{binary_name}"
    return entry


def _npm_entry(version: str) -> Dict:
    return {
        "version": version,
        "registryUrl": NPM_REGISTRY_URL,
        "packageSpec": f"{PACKAGE_NAME}@{version}",
    }


def _empty_index(source: str) -> Dict:
    return {
        "schemaVersion": 1,
        "source": source,
        "platform": None,
        "binary": {
            "latest": None,
            "versions": [],
        },
        "npm": {
            "latest": None,
            "versions": [],
        },
    }
