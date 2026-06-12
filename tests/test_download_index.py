from ccsilo import download_index


def test_load_download_index_uses_seed_when_cache_missing(tmp_path):
    index = download_index.load_download_index(tmp_path / ".ccsilo")

    assert index["schemaVersion"] == 1
    assert index["source"] == "seed"
    assert "2.1.122" in download_index.download_versions(index, "binary")


def test_refresh_download_index_writes_workspace_cache(tmp_path, monkeypatch):
    root = tmp_path / ".ccsilo"
    monkeypatch.setattr(download_index, "get_platform_key", lambda: "darwin-arm64")
    monkeypatch.setattr(download_index, "list_available_binary_versions", lambda: ["2.1.4", "2.1.3"])
    monkeypatch.setattr(download_index, "fetch_latest_binary_version", lambda: "2.1.4")
    monkeypatch.setattr(download_index, "list_available_npm_versions", lambda: ["2.1.4"])
    monkeypatch.setattr(download_index, "fetch_latest_npm_version", lambda: "2.1.4")

    index = download_index.refresh_download_index(root=root)

    assert (root / "download-index.json").exists()
    assert index["source"] == "live"
    assert index["platform"] == "darwin-arm64"
    assert index["binary"]["versions"][0]["downloadUrl"].endswith("/2.1.4/darwin-arm64/claude")
    assert download_index.load_download_index(root)["binary"]["latest"] == "2.1.4"


def test_effective_latest_download_version_prefers_highest_listed_version():
    index = {
        "binary": {
            "latest": "2.1.175",
            "versions": [
                {"version": "2.1.176"},
                {"version": "2.1.175"},
            ],
        },
    }

    assert download_index.effective_latest_download_version(index) == "2.1.176"


def test_effective_latest_download_version_falls_back_to_marker():
    index = {"binary": {"latest": "2.1.175", "versions": []}}

    assert download_index.effective_latest_download_version(index) == "2.1.175"
