"""Tests for the anyllm provider, its localProxy capability, and anyllm-proxy install."""

import stat
import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from ccsilo.providers import find_anyllm_proxy_binary, get_provider
from ccsilo.providers.local_integrations import (
    ANYLLM_PROXY_LOCAL_BIN,
    ANYLLM_PROXY_VERSION,
    _anyllm_proxy_deb_url,
)
from ccsilo.providers.schema import ProviderSchemaError, provider_from_json
from ccsilo.variants.wrapper import _local_proxy_config, _local_proxy_runtime_lines


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\necho anyllm_proxy\n")
    path.chmod(path.stat().st_mode | 0o111)


def test_provider_anyllm_parses_with_local_proxy():
    provider = get_provider("anyllm")
    assert provider.base_url == "http://localhost:3000"
    assert provider.local_proxy
    assert provider.local_proxy["binary"] == "anyllm-proxy"
    assert provider.local_proxy["port"] == 3000
    assert provider.local_proxy["credentialEnv"] == "ANYLLM_PROXY_KEY"
    # Gateway model discovery is enabled so Claude Code lists proxy models.
    assert (provider.tui.get("modelDiscovery") or {}).get("enabled") is True


def test_schema_local_proxy_unknown_key_rejected():
    payload = {
        "schemaVersion": 1,
        "key": "x",
        "label": "X",
        "description": "x",
        "displayOrder": 1,
        "baseUrl": "http://localhost:9000",
        "localProxy": {"binary": "x", "port": 9000, "bogus": True},
    }
    with pytest.raises(ProviderSchemaError):
        provider_from_json(payload)


def test_schema_local_proxy_bad_port_rejected():
    payload = {
        "schemaVersion": 1,
        "key": "x",
        "label": "X",
        "description": "x",
        "displayOrder": 1,
        "localProxy": {"binary": "x", "port": 70000},
    }
    with pytest.raises(ProviderSchemaError):
        provider_from_json(payload)


def test_schema_local_proxy_parsed():
    payload = {
        "schemaVersion": 1,
        "key": "x",
        "label": "X",
        "description": "x",
        "displayOrder": 1,
        "localProxy": {
            "binary": "myproxy",
            "args": ["--webui"],
            "port": 1234,
            "adminUrl": "http://127.0.0.1:1235/admin/",
            "credentialEnv": "MY_KEY",
        },
    }
    provider = provider_from_json(payload)
    assert provider.local_proxy["binary"] == "myproxy"
    assert provider.local_proxy["args"] == ["--webui"]
    assert provider.local_proxy["adminUrl"] == "http://127.0.0.1:1235/admin/"
    assert provider.local_proxy["credentialEnv"] == "MY_KEY"


def test_find_anyllm_proxy_binary_from_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(bin_dir / "anyllm-proxy")
    env = {"PATH": str(bin_dir), "HOME": str(tmp_path)}
    assert find_anyllm_proxy_binary(env=env) == str(bin_dir / "anyllm-proxy")


def test_find_anyllm_proxy_binary_from_homebrew(tmp_path, monkeypatch):
    prefix = tmp_path / "opt" / "homebrew"
    candidate = prefix / "opt" / "anyllm-proxy" / "bin" / "anyllm-proxy"
    candidate.parent.mkdir(parents=True)
    _make_executable(candidate)
    monkeypatch.setattr(
        "ccsilo.providers.local_integrations.ANYLLM_PROXY_HOMEBREW_DIRS", str(prefix)
    )
    env = {"PATH": "/nonexistent", "HOME": str(tmp_path)}
    assert find_anyllm_proxy_binary(env=env) == str(candidate)


def test_find_anyllm_proxy_binary_from_local_bin(tmp_path):
    home_bin = tmp_path / ANYLLM_PROXY_LOCAL_BIN / "anyllm-proxy"
    home_bin.parent.mkdir(parents=True)
    _make_executable(home_bin)
    env = {"PATH": "/nonexistent", "HOME": str(tmp_path)}
    assert find_anyllm_proxy_binary(env=env) == str(home_bin)


def test_find_anyllm_proxy_binary_missing(tmp_path):
    env = {"PATH": "/nonexistent", "HOME": str(tmp_path)}
    assert find_anyllm_proxy_binary(env=env) is None


def test_local_proxy_config_requires_binary_and_port():
    assert _local_proxy_config({"localProxy": {}}) is None
    assert _local_proxy_config({"localProxy": {"binary": "x"}}) is None
    assert _local_proxy_config({"localProxy": {"binary": "x", "port": 3000}}) is not None


def test_local_proxy_runtime_lines_emit_key_and_launch():
    config = {
        "binary": "anyllm-proxy",
        "args": ["--webui"],
        "port": 3000,
        "adminUrl": "http://127.0.0.1:3001/admin/",
        "credentialEnv": "ANYLLM_PROXY_KEY",
        "key": "sk-test-key",
        "logPath": "/tmp/anyllm-proxy.log",
    }
    lines = _local_proxy_runtime_lines({"id": "ccanyllm"}, config)
    text = "\n".join(lines)
    # Generated inbound key is set as both the proxy's PROXY_API_KEYS and Claude's auth token.
    assert "export PROXY_API_KEYS=sk-test-key" in text
    assert "export ANTHROPIC_AUTH_TOKEN=sk-test-key" in text
    assert "export ANTHROPIC_BASE_URL=http://127.0.0.1:3000" in text
    # Launch + cleanup scoping.
    assert "anyllm-proxy --webui" in text
    assert "cleanup_local_proxy()" in text
    assert "trap cleanup_local_proxy EXIT INT TERM" in text
    # Skips launching when the port is already bound.
    assert "AnyLLM proxy already listening" in text


def test_anyllm_proxy_deb_url():
    url = _anyllm_proxy_deb_url()
    assert url.startswith("https://github.com/whit3rabbit/anyllm-proxy/releases/download/")
    assert f"anyllm-proxy_{ANYLLM_PROXY_VERSION}-1_" in url
    assert url.endswith(".deb")


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        if n == -1:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


@pytest.mark.parametrize("arch,asset", [("arm64", "macos-arm64"), ("amd64", "macos-x86_64")])
def test_install_anyllm_proxy_tarball_fallback(tmp_path, monkeypatch, arch, asset):
    # Force the macOS tarball path: no brew, no binary on PATH.
    monkeypatch.setattr("ccsilo.providers.local_integrations.sys.platform", "darwin")
    monkeypatch.setattr(
        "ccsilo.providers.local_integrations.shutil.which", lambda name, path=None: None
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    # Build an in-memory tarball containing the anyllm_proxy binary.
    payload = BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tf:
        data = b"#!/bin/sh\necho anyllm_proxy\n"
        info = tarfile.TarInfo(name="anyllm-proxy")
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, BytesIO(data))
    payload.seek(0)

    def fake_urlopen(request, timeout=None):
        return _FakeResponse(payload.getvalue())

    monkeypatch.setattr("ccsilo.providers.local_integrations.urllib.request.urlopen", fake_urlopen)

    from ccsilo.providers.local_integrations import install_anyllm_proxy

    result = install_anyllm_proxy(env={"HOME": str(tmp_path)})
    assert result.changed is True
    binary = tmp_path / ANYLLM_PROXY_LOCAL_BIN / "anyllm-proxy"
    assert binary.is_file()
    assert bool(binary.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
