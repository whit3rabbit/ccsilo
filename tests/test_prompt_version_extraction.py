import json
from argparse import Namespace

import pytest

from tools import extract_prompt_versions


def build_prompt(version="1.2.3", name="Test Prompt", prompt_id="test-prompt"):
    return {
        "name": name,
        "id": prompt_id,
        "description": "A test prompt.",
        "pieces": ["Hello ${", "}"],
        "identifiers": [0],
        "identifierMap": {"0": "NAME"},
        "version": version,
    }


def test_prompt_output_path_uses_prompts_version_json(tmp_path):
    assert extract_prompt_versions.prompt_output_path(tmp_path / "prompts", "1.2.3") == (
        tmp_path / "prompts" / "1.2.3.json"
    )


def test_validate_prompt_data_accepts_tweakcc_shape():
    extract_prompt_versions.validate_prompt_data(
        {"version": "1.2.3", "prompts": [build_prompt()]},
        "1.2.3",
    )


def test_validate_prompt_data_rejects_identifier_piece_mismatch():
    prompt = build_prompt()
    prompt["pieces"] = ["Hello"]

    with pytest.raises(ValueError, match="pieces length"):
        extract_prompt_versions.validate_prompt_data(
            {"version": "1.2.3", "prompts": [prompt]},
            "1.2.3",
        )


def test_write_validated_prompt_data_round_trips_json(tmp_path):
    output_path = tmp_path / "prompts" / "1.2.3.json"
    data = {"version": "1.2.3", "prompts": [build_prompt()]}

    extract_prompt_versions.write_validated_prompt_data(data, output_path, "1.2.3")

    assert json.loads(output_path.read_text(encoding="utf-8")) == data


def test_local_versions_discovers_downloaded_binaries(tmp_path):
    (tmp_path / "2.1.9").mkdir()
    (tmp_path / "2.1.9" / "claude").write_text("", encoding="utf-8")
    (tmp_path / "2.1.10").mkdir()
    (tmp_path / "2.1.10" / "claude").write_text("", encoding="utf-8")

    assert extract_prompt_versions.local_versions(tmp_path) == ["2.1.10", "2.1.9"]


def test_sort_versions_filters_non_version_markers():
    assert extract_prompt_versions.sort_versions(["plugins", "2.1.10", "1.0.1"]) == [
        "2.1.10",
        "1.0.1",
    ]


def test_prompt_versions_discovers_local_catalogs_newest_first(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "2.1.9.json").write_text("{}", encoding="utf-8")
    (prompts_dir / "2.1.11.json").write_text("{}", encoding="utf-8")
    (prompts_dir / "notes.json").write_text("{}", encoding="utf-8")

    assert extract_prompt_versions.prompt_versions(prompts_dir) == ["2.1.11", "2.1.9"]
    assert extract_prompt_versions.latest_prompt_version(prompts_dir) == "2.1.11"


def test_missing_versions_returns_released_versions_without_catalogs(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "2.1.9.json").write_text("{}", encoding="utf-8")

    assert extract_prompt_versions.missing_versions(
        prompts_dir,
        ["2.1.11", "2.1.10", "2.1.9", "not-a-version"],
    ) == ["2.1.11", "2.1.10"]


def test_versions_since_existing_latest_ignores_older_gaps(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "2.1.10.json").write_text("{}", encoding="utf-8")

    assert extract_prompt_versions.versions_since_existing_latest(
        prompts_dir,
        ["2.1.12", "2.1.11", "2.1.9"],
    ) == ["2.1.12", "2.1.11"]


def test_nearest_existing_prompt_path_uses_closest_older_catalog(tmp_path):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    older = prompts_dir / "2.1.9.json"
    nearest = prompts_dir / "2.1.11.json"
    newer = prompts_dir / "2.1.13.json"
    older.write_text("{}", encoding="utf-8")
    nearest.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")

    assert (
        extract_prompt_versions.nearest_existing_prompt_path(prompts_dir, "2.1.12")
        == nearest
    )


def test_extract_version_prompts_uses_nearest_local_catalog_as_seed(tmp_path, monkeypatch):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    seed_path = prompts_dir / "2.1.9.json"
    seed_prompt = build_prompt(version="2.1.9", name="Seed Prompt", prompt_id="seed")
    seed_path.write_text(
        json.dumps({"version": "2.1.9", "prompts": [seed_prompt]}),
        encoding="utf-8",
    )
    binary_path = tmp_path / "downloads" / "2.1.10" / "claude"
    cli_path = tmp_path / "work" / "2.1.10" / "extracted" / "cli.js"
    captured = {}

    def fake_download_binary(version, download_dir):
        binary_path.parent.mkdir(parents=True)
        binary_path.write_text("binary", encoding="utf-8")
        return str(binary_path)

    def fake_extract_binary(binary, extract_dir, version, force=False):
        cli_path.parent.mkdir(parents=True)
        cli_path.write_text("prompt source", encoding="utf-8")
        return cli_path

    def fake_extract_prompts(
        input_path, version=None, existing_prompts=None, scan_paths=None, text_paths=None
    ):
        captured["existing_prompts"] = existing_prompts
        return {
            "version": version,
            "prompts": [build_prompt(version=version, name="Seed Prompt", prompt_id="seed")],
        }

    monkeypatch.setattr(extract_prompt_versions, "download_binary", fake_download_binary)
    monkeypatch.setattr(extract_prompt_versions, "extract_binary", fake_extract_binary)
    monkeypatch.setattr(extract_prompt_versions, "extract_prompts", fake_extract_prompts)

    result = extract_prompt_versions.extract_version_prompts(
        "2.1.10",
        prompts_dir,
        tmp_path / "downloads",
        tmp_path / "work",
        catalog_dir_value=tmp_path / "vendor",
    )

    assert captured["existing_prompts"] == [seed_prompt]
    assert result.seed_path == seed_path
    assert result.prompt_count == 1
    assert result.named_count == 1
    assert result.unnamed_count == 0


def test_force_prompts_prefers_exact_vendor_catalog_over_existing_output(
    tmp_path,
    monkeypatch,
):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    output_path = prompts_dir / "2.1.10.json"
    bad_prompt = build_prompt(version="2.1.10", name="", prompt_id="")
    output_path.write_text(
        json.dumps({"version": "2.1.10", "prompts": [bad_prompt]}),
        encoding="utf-8",
    )

    catalog_dir = tmp_path / "vendor"
    catalog_dir.mkdir()
    vendor_prompt = build_prompt(
        version="2.1.10",
        name="Vendor Prompt",
        prompt_id="vendor-prompt",
    )
    vendor_path = catalog_dir / "prompts-2.1.10.json"
    vendor_path.write_text(
        json.dumps({"version": "2.1.10", "prompts": [vendor_prompt]}),
        encoding="utf-8",
    )

    binary_path = tmp_path / "downloads" / "2.1.10" / "claude"
    cli_path = tmp_path / "work" / "2.1.10" / "extracted" / "cli.js"
    captured = {}

    def fake_download_binary(version, download_dir):
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        binary_path.write_text("binary", encoding="utf-8")
        return str(binary_path)

    def fake_extract_binary(binary, extract_dir, version, force=False):
        cli_path.parent.mkdir(parents=True, exist_ok=True)
        cli_path.write_text("prompt source", encoding="utf-8")
        return cli_path

    def fake_extract_prompts(
        input_path, version=None, existing_prompts=None, scan_paths=None, text_paths=None
    ):
        captured["existing_prompts"] = existing_prompts
        return {
            "version": version,
            "prompts": [build_prompt(version=version, name="Result", prompt_id="result")],
        }

    monkeypatch.setattr(extract_prompt_versions, "download_binary", fake_download_binary)
    monkeypatch.setattr(extract_prompt_versions, "extract_binary", fake_extract_binary)
    monkeypatch.setattr(extract_prompt_versions, "extract_prompts", fake_extract_prompts)

    result = extract_prompt_versions.extract_version_prompts(
        "2.1.10",
        prompts_dir,
        tmp_path / "downloads",
        tmp_path / "work",
        catalog_dir_value=catalog_dir,
        force_prompts=True,
    )

    assert captured["existing_prompts"] == [vendor_prompt]
    assert result.seed_path == vendor_path


def test_force_prompts_without_exact_catalog_prefers_nearest_named_vendor_seed(
    tmp_path,
    monkeypatch,
):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    output_path = prompts_dir / "2.1.123.json"
    output_path.write_text(
        json.dumps(
            {
                "version": "2.1.123",
                "prompts": [build_prompt(version="2.1.123", name="", prompt_id="")],
            }
        ),
        encoding="utf-8",
    )
    local_seed = prompts_dir / "2.1.122.json"
    local_seed.write_text(
        json.dumps(
            {
                "version": "2.1.122",
                "prompts": [build_prompt(version="2.1.122", name="", prompt_id="")],
            }
        ),
        encoding="utf-8",
    )

    catalog_dir = tmp_path / "vendor"
    catalog_dir.mkdir()
    vendor_prompt = build_prompt(
        version="2.1.122",
        name="Nearest Vendor Prompt",
        prompt_id="nearest-vendor-prompt",
    )
    vendor_seed = catalog_dir / "prompts-2.1.122.json"
    vendor_seed.write_text(
        json.dumps({"version": "2.1.122", "prompts": [vendor_prompt]}),
        encoding="utf-8",
    )

    binary_path = tmp_path / "downloads" / "2.1.123" / "claude"
    cli_path = tmp_path / "work" / "2.1.123" / "extracted" / "cli.js"
    captured = {}

    def fake_download_binary(version, download_dir):
        binary_path.parent.mkdir(parents=True, exist_ok=True)
        binary_path.write_text("binary", encoding="utf-8")
        return str(binary_path)

    def fake_extract_binary(binary, extract_dir, version, force=False):
        cli_path.parent.mkdir(parents=True, exist_ok=True)
        cli_path.write_text("prompt source", encoding="utf-8")
        return cli_path

    def fake_extract_prompts(
        input_path, version=None, existing_prompts=None, scan_paths=None, text_paths=None
    ):
        captured["existing_prompts"] = existing_prompts
        return {
            "version": version,
            "prompts": [build_prompt(version=version, name="Result", prompt_id="result")],
        }

    monkeypatch.setattr(extract_prompt_versions, "download_binary", fake_download_binary)
    monkeypatch.setattr(extract_prompt_versions, "extract_binary", fake_extract_binary)
    monkeypatch.setattr(extract_prompt_versions, "extract_prompts", fake_extract_prompts)

    result = extract_prompt_versions.extract_version_prompts(
        "2.1.123",
        prompts_dir,
        tmp_path / "downloads",
        tmp_path / "work",
        catalog_dir_value=catalog_dir,
        force_prompts=True,
    )

    assert captured["existing_prompts"] == [vendor_prompt]
    assert result.seed_path == vendor_seed


def test_prompt_summary_counts_unnamed_prompts():
    named = build_prompt()
    unnamed = build_prompt(name="", prompt_id="")

    assert extract_prompt_versions.prompt_summary(
        {"version": "1.2.3", "prompts": [named, unnamed]}
    ) == {"total": 2, "named": 1, "unnamed": 1}


def test_run_versions_fails_when_unnamed_prompts_are_blocked(monkeypatch, tmp_path):
    output_path = tmp_path / "prompts" / "1.2.3.json"

    monkeypatch.setattr(extract_prompt_versions, "resolve_versions", lambda args: ["1.2.3"])
    monkeypatch.setattr(
        extract_prompt_versions,
        "extract_version_prompts",
        lambda *args, **kwargs: extract_prompt_versions.VersionResult(
            "1.2.3",
            True,
            output_path,
            prompt_count=2,
            named_count=1,
            unnamed_count=1,
        ),
    )

    results = extract_prompt_versions.run_versions(
        Namespace(
            max_versions=None,
            prompts_dir=tmp_path / "prompts",
            download_dir=tmp_path / "downloads",
            work_dir=tmp_path / "work",
            catalog_dir=None,
            force_download=False,
            force_extract=False,
            force_prompts=False,
            fail_on_unnamed=True,
            stop_on_error=False,
        )
    )

    assert len(results) == 1
    assert not results[0].ok
    assert results[0].error == "1 unnamed prompts"
