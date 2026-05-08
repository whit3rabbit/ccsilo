"""Fetch Claude Code binaries from Google Cloud Storage or NPM tarballs."""

import functools
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from importlib import import_module
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ._utils import version_sort_key as _version_sort_key
from .workspace import (
    ensure_workspace,
    file_sha256,
    native_download_path,
    npm_download_path,
    store_native_download,
    store_npm_download,
    workspace_root,
)

GCS_BUCKET_NAME = "claude-code-dist-86c565f3-f756-42ad-8dfa-d59b1c096819"
GCS_RELEASE_PREFIX = "claude-code-releases"
GCS_BUCKET = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{GCS_RELEASE_PREFIX}"
GCS_LIST_API = f"https://storage.googleapis.com/storage/v1/b/{GCS_BUCKET_NAME}/o"
PACKAGE_NAME = "@anthropic-ai/claude-code"
NPM_REGISTRY_URL = f"https://registry.npmjs.org/{PACKAGE_NAME}"
REQUEST_TIMEOUT = 30
HTTP_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
DOWNLOAD_BLOCK_SIZE = 8192
LIST_PAGE_SIZE = 1000


class _NoopProgressBar:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, amount):
        return None


def _get_tqdm():
    try:
        return import_module("tqdm").tqdm
    except ImportError:
        return None


def _open_url(url):
    request = Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    try:
        return urlopen(request, timeout=REQUEST_TIMEOUT)
    except (URLError, HTTPError) as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc


def _make_progress(total_size, desc):
    tqdm = _get_tqdm()
    if tqdm is None:
        return _NoopProgressBar()
    return tqdm(total=total_size, unit="B", unit_scale=True, desc=desc)


def _sort_versions(versions):
    unique_versions = {version for version in versions if version}
    return sorted(unique_versions, key=_version_sort_key, reverse=True)


def _binary_list_url(page_token=None):
    params = {
        "prefix": f"{GCS_RELEASE_PREFIX}/",
        "delimiter": "/",
        "fields": "prefixes,nextPageToken",
        "maxResults": str(LIST_PAGE_SIZE),
    }
    if page_token:
        params["pageToken"] = page_token
    return f"{GCS_LIST_API}?{urlencode(params)}"


def _parse_binary_versions(payload):
    root = f"{GCS_RELEASE_PREFIX}/"
    versions = []
    for prefix in payload.get("prefixes", []):
        if not prefix.startswith(root):
            continue
        version = prefix[len(root):].strip("/")
        if version:
            versions.append(version)
    return versions


def _select_version_interactively(versions, latest_version, npm):
    from .download_picker import select_version

    if npm:
        title = "Select Claude Code NPM download"
    else:
        title = "Select Claude Code binary download"
    return select_version(versions, latest_version=latest_version, title=title)


def fetch_text(url):
    """Fetch a URL and return the decoded text body."""
    try:
        with _open_url(url) as response:
            return response.read().decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Non-UTF-8 response from {url}: {exc}") from exc


def fetch_json(url):
    """Fetch a URL and return the parsed JSON response."""
    text = fetch_text(url)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Malformed JSON from {url}: {exc}") from exc


def fetch_latest_binary_version():
    """Fetch the latest native binary version from GCS."""
    return fetch_text(f"{GCS_BUCKET}/latest")


def fetch_latest_npm_version():
    """Fetch the latest NPM version from the registry."""
    metadata = fetch_json(NPM_REGISTRY_URL)
    latest_version = metadata.get("dist-tags", {}).get("latest")
    if not latest_version:
        raise RuntimeError("NPM registry did not report a latest Claude Code version")
    return latest_version


@functools.lru_cache(maxsize=1)
def list_available_binary_versions():
    """List all native binary versions published to GCS."""
    versions = []
    page_token = None

    while True:
        payload = fetch_json(_binary_list_url(page_token))
        versions.extend(_parse_binary_versions(payload))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break

    return _sort_versions(versions)


@functools.lru_cache(maxsize=1)
def list_available_npm_versions():
    """List all NPM versions published to the registry."""
    metadata = fetch_json(NPM_REGISTRY_URL)
    return _sort_versions(metadata.get("versions", {}).keys())


def _clear_version_cache():
    list_available_binary_versions.cache_clear()
    list_available_npm_versions.cache_clear()


def resolve_requested_version(version=None, latest=False, npm=False, selector=None):
    """Resolve a version string, --latest flag, or interactive selection."""
    if version and latest:
        raise ValueError("Pass either a version or --latest, not both")

    if version:
        if version == "latest":
            return fetch_latest_npm_version() if npm else fetch_latest_binary_version()
        return version

    if latest:
        return fetch_latest_npm_version() if npm else fetch_latest_binary_version()

    versions = list_available_npm_versions() if npm else list_available_binary_versions()
    if not versions:
        raise RuntimeError("No Claude Code downloads were found")

    latest_version = fetch_latest_npm_version() if npm else fetch_latest_binary_version()
    select = selector or _select_version_interactively
    return select(versions, latest_version, npm)


def _linux_uses_musl():
    # musl libc identifies itself in ldd --version stderr; glibc does not
    try:
        with subprocess.Popen(
            ["ldd", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ) as process:
            stdout, stderr = process.communicate()
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return False

    version_output = b" ".join(part for part in (stdout, stderr) if part)
    return b"musl" in version_output.lower()


def get_platform_key():
    """Return the platform key for the current OS and architecture."""
    system = platform.system().lower()
    arch = platform.machine().lower()

    if system == "darwin":
        os_key = "darwin"
    elif system == "linux":
        os_key = "linux"
    elif system == "windows":
        return "win32-x64"
    else:
        raise ValueError(f"Unsupported system: {system}")

    if arch in ["x86_64", "amd64"]:
        arch_key = "x64"
    elif arch in ["arm64", "aarch64"]:
        arch_key = "arm64"
    else:
        raise ValueError(f"Unsupported architecture: {arch}")

    if os_key == "linux" and _linux_uses_musl():
        return f"{os_key}-{arch_key}-musl"

    return f"{os_key}-{arch_key}"


def download_file(url, out_path):
    """Download a file from URL to out_path with optional progress bar."""
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with _open_url(url) as response:
        total_size = int(response.headers.get("content-length", 0))
        with _make_progress(total_size, os.path.basename(out_path)) as progress:
            with open(out_path, "wb") as handle:
                while True:
                    chunk = response.read(DOWNLOAD_BLOCK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    progress.update(len(chunk))


def verify_checksum(file_path, expected_checksum):
    """Verify a file's SHA-256 checksum against an expected hex digest."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while True:
            data = handle.read(65536)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest() == expected_checksum


def download_binary(version="latest", out_dir=None):
    """Download a Claude Code native binary for the current platform."""
    use_workspace = out_dir is None
    if version == "latest":
        version = fetch_latest_binary_version()

    manifest_url = f"{GCS_BUCKET}/{version}/manifest.json"
    manifest = fetch_json(manifest_url)

    platform_key = get_platform_key()
    plat_info = manifest.get("platforms", {}).get(platform_key)
    if not plat_info:
        raise ValueError(f"Platform {platform_key} not found in manifest for version {version}")

    checksum = plat_info["checksum"]
    binary_name = "claude.exe" if platform.system() == "Windows" else "claude"
    binary_url = f"{GCS_BUCKET}/{version}/{platform_key}/{binary_name}"

    if use_workspace:
        ensure_workspace()
        out_path = native_download_path(version, platform_key, checksum, filename=binary_name)
    else:
        out_path = os.path.join(out_dir, version, binary_name)

    if os.path.exists(out_path):
        if verify_checksum(out_path, checksum):
            if use_workspace:
                store_native_download(
                    out_path,
                    version,
                    platform_key,
                    checksum,
                    source_url=binary_url,
                    filename=binary_name,
                )
            print(f"[*] Already have valid binary at {out_path}")
            return str(out_path)

    print(f"[*] Downloading {binary_url}...")
    if use_workspace:
        tmp_dir = workspace_root() / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        handle, staged_path = tempfile.mkstemp(
            prefix=f"claude-{version}-{platform_key}-",
            suffix=".download",
            dir=str(tmp_dir),
        )
        os.close(handle)
        try:
            download_file(binary_url, staged_path)
            if not verify_checksum(staged_path, checksum):
                os.remove(staged_path)
                raise ValueError("Checksum verification failed")
            if platform.system() != "Windows":
                os.chmod(staged_path, 0o755)
            out_path = store_native_download(
                staged_path,
                version,
                platform_key,
                checksum,
                source_url=binary_url,
                filename=binary_name,
            )
        except Exception:
            if os.path.exists(staged_path):
                os.remove(staged_path)
            raise
    else:
        download_file(binary_url, out_path)

        if not verify_checksum(out_path, checksum):
            os.remove(out_path)
            raise ValueError("Checksum verification failed")

        if platform.system() != "Windows":
            os.chmod(out_path, 0o755)

    print(f"[+] Downloaded to {out_path}")
    return str(out_path)


def download_npm(version="latest", out_dir=None):
    """Download a Claude Code NPM tarball via npm pack."""
    use_workspace = out_dir is None
    if version == "latest":
        version = fetch_latest_npm_version()

    if use_workspace:
        ensure_workspace()
        out_dir = str(workspace_root() / "tmp")
    os.makedirs(out_dir, exist_ok=True)

    target = f"{PACKAGE_NAME}@{version}"
    cmd = ["npm", "pack", "--json", target]
    print(f"[*] Running {' '.join(cmd)}...")
    with tempfile.TemporaryDirectory(prefix=".npm-pack-", dir=out_dir) as pack_dir:
        try:
            result = subprocess.run(cmd, cwd=pack_dir, capture_output=True, text=True, check=False)
        except (FileNotFoundError, OSError) as exc:
            raise RuntimeError("npm is required to download the NPM tarball") from exc

        if result.returncode != 0:
            raise RuntimeError(f"npm pack failed: {result.stderr}")

        tarball = _npm_pack_tarball_name(result.stdout)
        tar_path_obj = (Path(pack_dir) / tarball).resolve()
        pack_root = Path(pack_dir).resolve()
        if tar_path_obj.parent != pack_root:
            raise RuntimeError("npm pack reported a tarball outside its temporary directory")
        if not tar_path_obj.is_file():
            raise RuntimeError(f"npm pack tarball is missing: {tarball}")
        if use_workspace:
            sha256 = file_sha256(tar_path_obj)
            existing_path = npm_download_path(version, sha256, tarball)
            if existing_path.exists():
                tar_path = str(existing_path)
            else:
                tar_path = str(store_npm_download(tar_path_obj, version, sha256))
        else:
            final_path = Path(out_dir) / tarball
            if tar_path_obj != final_path:
                shutil.move(str(tar_path_obj), str(final_path))
            tar_path = str(final_path)
    print(f"[+] Downloaded NPM tarball to {tar_path}")
    return tar_path


def _npm_pack_tarball_name(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("npm pack did not report JSON output") from exc
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeError("npm pack did not report an output tarball")
    filename = str(payload[0].get("filename") or "").strip()
    if not filename:
        raise RuntimeError("npm pack did not report an output tarball")
    path = Path(filename)
    if path.is_absolute() or path.name != filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise RuntimeError("npm pack reported an unsafe tarball name")
    if ".." in path.parts:
        raise RuntimeError("npm pack reported an unsafe tarball name")
    return filename


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "npm":
            download_npm(sys.argv[2] if len(sys.argv) > 2 else "latest")
        else:
            download_binary(sys.argv[1])
    else:
        download_binary("latest")
