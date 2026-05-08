import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ccsilo.downloader import (
    download_file,
    download_binary,
    download_npm,
    fetch_text,
    get_platform_key,
    list_available_binary_versions,
    resolve_requested_version,
    verify_checksum,
)


class DummyProgressBar:
    def __init__(self):
        self.updates = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, amount):
        self.updates.append(amount)


class FakeHttpResponse:
    def __init__(self, data, headers=None):
        self._data = data
        self._offset = 0
        self.headers = headers or {}

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._data) - self._offset
        chunk = self._data[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGetPlatformKey:
    @patch("ccsilo.downloader.platform.system", return_value="Darwin")
    @patch("ccsilo.downloader.platform.machine", return_value="x86_64")
    def test_darwin_x64(self, mock_machine, mock_system):
        assert get_platform_key() == "darwin-x64"

    @patch("ccsilo.downloader.platform.system", return_value="Darwin")
    @patch("ccsilo.downloader.platform.machine", return_value="arm64")
    def test_darwin_arm64(self, mock_machine, mock_system):
        assert get_platform_key() == "darwin-arm64"

    @patch("ccsilo.downloader.platform.system", return_value="Linux")
    @patch("ccsilo.downloader.platform.machine", return_value="x86_64")
    @patch("ccsilo.downloader._linux_uses_musl", return_value=False)
    def test_linux_x64_glibc(self, mock_musl, mock_machine, mock_system):
        assert get_platform_key() == "linux-x64"

    @patch("ccsilo.downloader.platform.system", return_value="Linux")
    @patch("ccsilo.downloader.platform.machine", return_value="x86_64")
    @patch("ccsilo.downloader._linux_uses_musl", return_value=True)
    def test_linux_x64_musl(self, mock_musl, mock_machine, mock_system):
        assert get_platform_key() == "linux-x64-musl"

    @patch("ccsilo.downloader.platform.system", return_value="Windows")
    @patch("ccsilo.downloader.platform.machine", return_value="x86_64")
    def test_windows(self, mock_machine, mock_system):
        assert get_platform_key() == "win32-x64"

    @patch("ccsilo.downloader.platform.system", return_value="FreeBSD")
    @patch("ccsilo.downloader.platform.machine", return_value="x86_64")
    def test_unsupported_system(self, mock_machine, mock_system):
        with pytest.raises(ValueError, match="Unsupported system"):
            get_platform_key()

    @patch("ccsilo.downloader.platform.system", return_value="Darwin")
    @patch("ccsilo.downloader.platform.machine", return_value="i386")
    def test_unsupported_arch(self, mock_machine, mock_system):
        with pytest.raises(ValueError, match="Unsupported architecture"):
            get_platform_key()


class TestVerifyChecksum:
    def test_checksum_matches(self, tmp_path):
        file_path = tmp_path / "data.bin"
        file_path.write_bytes(b"test data")
        expected = hashlib.sha256(b"test data").hexdigest()

        assert verify_checksum(str(file_path), expected) is True

    def test_checksum_mismatch(self, tmp_path):
        file_path = tmp_path / "data.bin"
        file_path.write_bytes(b"test data")

        assert verify_checksum(str(file_path), "wronghash") is False


class TestFetchText:
    def test_fetch_text_success(self):
        response = FakeHttpResponse(b"v1.2.3\n")

        with patch("ccsilo.downloader._open_url", return_value=response) as mock_open:
            assert fetch_text("http://example.com/version") == "v1.2.3"

        mock_open.assert_called_once_with("http://example.com/version")


class TestDownloadFile:
    def test_download_file_supports_basename_output(self, tmp_path, monkeypatch):
        response = FakeHttpResponse(b"hello", headers={"content-length": "5"})

        progress_instances = []

        def make_progress(**kwargs):
            progress = DummyProgressBar()
            progress_instances.append((progress, kwargs))
            return progress

        monkeypatch.chdir(tmp_path)

        with patch("ccsilo.downloader._open_url", return_value=response), \
             patch("ccsilo.downloader._get_tqdm", return_value=make_progress), \
             patch("ccsilo.downloader.os.makedirs") as mock_makedirs:
            download_file("http://example.com/artifact", "artifact.bin")

        assert not mock_makedirs.called
        assert (tmp_path / "artifact.bin").read_bytes() == b"hello"
        progress_bar, kwargs = progress_instances[0]
        assert kwargs == {
            "total": 5,
            "unit": "B",
            "unit_scale": True,
            "desc": "artifact.bin",
        }
        assert progress_bar.updates == [5]


class TestDownloadBinary:
    def test_download_binary_default_uses_central_workspace(self, tmp_path, monkeypatch):
        payload = b"native-binary"
        checksum = hashlib.sha256(payload).hexdigest()
        manifest = {
            "platforms": {
                "darwin-arm64": {
                    "checksum": checksum,
                }
            }
        }

        root = tmp_path / ".ccsilo"
        monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
        monkeypatch.setattr("ccsilo.downloader.fetch_latest_binary_version", lambda: "1.2.3")
        monkeypatch.setattr("ccsilo.downloader.fetch_json", lambda url: manifest)
        monkeypatch.setattr("ccsilo.downloader.get_platform_key", lambda: "darwin-arm64")
        monkeypatch.setattr("ccsilo.downloader.platform.system", lambda: "Darwin")

        def fake_download_file(url, out_path):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as handle:
                handle.write(payload)

        monkeypatch.setattr("ccsilo.downloader.download_file", fake_download_file)

        result = download_binary("latest")

        expected = root / "downloads" / "native" / "1.2.3" / "darwin-arm64" / checksum / "claude"
        assert result == str(expected)
        assert expected.read_bytes() == payload
        assert os.access(expected, os.X_OK)

    def test_download_binary_explicit_outdir_keeps_legacy_layout(self, tmp_path, monkeypatch):
        payload = b"native-binary"
        checksum = hashlib.sha256(payload).hexdigest()
        manifest = {
            "platforms": {
                "darwin-arm64": {
                    "checksum": checksum,
                }
            }
        }

        monkeypatch.setattr("ccsilo.downloader.fetch_json", lambda url: manifest)
        monkeypatch.setattr("ccsilo.downloader.get_platform_key", lambda: "darwin-arm64")
        monkeypatch.setattr("ccsilo.downloader.platform.system", lambda: "Darwin")

        def fake_download_file(url, out_path):
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as handle:
                handle.write(payload)

        monkeypatch.setattr("ccsilo.downloader.download_file", fake_download_file)

        result = download_binary("1.2.3", out_dir=str(tmp_path / "downloads"))

        expected = tmp_path / "downloads" / "1.2.3" / "claude"
        assert result == str(expected)
        assert expected.read_bytes() == payload


class TestListAvailableBinaryVersions:
    def test_list_available_binary_versions_paginates_and_sorts(self):
        pages = [
            {
                "prefixes": [
                    "claude-code-releases/2.1.2/",
                    "claude-code-releases/1.9.9/",
                ],
                "nextPageToken": "page-2",
            },
            {
                "prefixes": [
                    "claude-code-releases/2.1.10/",
                    "claude-code-releases/2.1.1/",
                ],
            },
        ]

        with patch("ccsilo.downloader.fetch_json", side_effect=pages) as mock_fetch:
            assert list_available_binary_versions() == [
                "2.1.10",
                "2.1.2",
                "2.1.1",
                "1.9.9",
            ]

        urls = [call.args[0] for call in mock_fetch.call_args_list]
        assert "pageToken=page-2" in urls[1]


class TestResolveRequestedVersion:
    def test_resolve_requested_version_rejects_conflicting_args(self):
        with pytest.raises(ValueError, match="either a version or --latest"):
            resolve_requested_version("2.1.10", latest=True)

    def test_resolve_requested_version_latest_alias(self):
        with patch(
            "ccsilo.downloader.fetch_latest_binary_version",
            return_value="2.1.116",
        ):
            assert resolve_requested_version("latest") == "2.1.116"

    def test_resolve_requested_version_uses_picker_for_binaries(self):
        with patch(
            "ccsilo.downloader.list_available_binary_versions",
            return_value=["2.1.116", "2.1.115"],
        ), patch(
            "ccsilo.downloader.fetch_latest_binary_version",
            return_value="2.1.116",
        ), patch(
            "ccsilo.downloader._select_version_interactively",
            return_value="2.1.115",
        ) as mock_select:
            assert resolve_requested_version() == "2.1.115"

        mock_select.assert_called_once_with(["2.1.116", "2.1.115"], "2.1.116", False)

    def test_resolve_requested_version_uses_picker_for_npm(self):
        with patch(
            "ccsilo.downloader.list_available_npm_versions",
            return_value=["2.1.116", "2.1.115"],
        ), patch(
            "ccsilo.downloader.fetch_latest_npm_version",
            return_value="2.1.116",
        ), patch(
            "ccsilo.downloader._select_version_interactively",
            return_value="2.1.115",
        ) as mock_select:
            assert resolve_requested_version(npm=True) == "2.1.115"

        mock_select.assert_called_once_with(["2.1.116", "2.1.115"], "2.1.116", True)


class TestDownloadNpm:
    @patch("ccsilo.downloader.subprocess.run")
    def test_download_npm_default_uses_central_workspace(self, mock_run, tmp_path, monkeypatch):
        root = tmp_path / ".ccsilo"
        monkeypatch.setenv("CCSILO_WORKSPACE", str(root))
        monkeypatch.setattr("ccsilo.downloader.fetch_latest_npm_version", lambda: "1.2.3")

        def run(cmd, cwd, capture_output, text, check):
            assert cmd == ["npm", "pack", "--json", "@anthropic-ai/claude-code@1.2.3"]
            tarball = "anthropic-ai-claude-code-1.2.3.tgz"
            (Path(cwd) / tarball).write_bytes(b"npm-tarball")
            return MagicMock(returncode=0, stdout=json.dumps([{"filename": tarball}]))

        mock_run.side_effect = run

        result = download_npm("latest")
        checksum = hashlib.sha256(b"npm-tarball").hexdigest()
        expected = root / "downloads" / "npm" / "1.2.3" / checksum / "anthropic-ai-claude-code-1.2.3.tgz"

        assert result == str(expected)
        assert expected.read_bytes() == b"npm-tarball"

    @patch("ccsilo.downloader.subprocess.run")
    def test_download_npm_success(self, mock_run, tmp_path):
        out_dir = tmp_path / "npm"

        def run(cmd, cwd, capture_output, text, check):
            tarball = "anthropic-ai-claude-code-1.2.3.tgz"
            (Path(cwd) / tarball).write_bytes(b"npm-tarball")
            return MagicMock(returncode=0, stdout=json.dumps([{"filename": tarball}]))

        mock_run.side_effect = run

        result = download_npm("1.2.3", str(out_dir))

        assert result == str(out_dir / "anthropic-ai-claude-code-1.2.3.tgz")
        assert (out_dir / "anthropic-ai-claude-code-1.2.3.tgz").read_bytes() == b"npm-tarball"

    @patch("ccsilo.downloader.subprocess.run")
    def test_download_npm_failure(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="npm error")

        with pytest.raises(RuntimeError, match="npm pack failed"):
            download_npm("latest", str(tmp_path / "npm"))

    @patch("ccsilo.downloader.subprocess.run")
    def test_download_npm_missing_tarball_name(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")

        with pytest.raises(RuntimeError, match="did not report an output tarball"):
            download_npm("latest", str(tmp_path / "npm"))

    @patch("ccsilo.downloader.subprocess.run")
    def test_download_npm_rejects_unsafe_tarball_name(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps([{"filename": "../evil.tgz"}]))

        with pytest.raises(RuntimeError, match="unsafe tarball name"):
            download_npm("1.2.3", str(tmp_path / "npm"))
