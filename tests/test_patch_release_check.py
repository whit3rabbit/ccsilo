import argparse
import json

from cc_extractor.patches import Patch, PatchOutcome
from tools import check_patch_releases


def _patch(id_="compat", *, status="applied", tested=(">=2.1.0,<=2.1.122"), notes=()):
    def apply(js, ctx):
        return PatchOutcome(
            js=f"{js}:{id_}" if status == "applied" else js,
            status=status,
            notes=notes,
        )

    return Patch(
        id=id_,
        name=id_,
        group="ui",
        versions_supported=">=2.1.0,<3",
        versions_tested=tested,
        apply=apply,
    )


def test_versions_since_existing_latest_uses_report_files(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "2.1.122.json").write_text("{}", encoding="utf-8")
    (reports / "index.json").write_text("{}", encoding="utf-8")

    versions = check_patch_releases.versions_since_existing_latest(
        reports,
        ["2.1.128", "2.1.126", "2.1.122", "garbage"],
    )

    assert versions == ["2.1.128", "2.1.126"]


def test_check_patch_reports_untested_warning():
    patch = _patch()

    result = check_patch_releases.check_patch(
        "js",
        patch,
        "2.1.128",
        registry={patch.id: patch},
    )

    assert result.status == "applied"
    assert result.ok is True
    assert result.tested is False
    assert any("not tested against version 2.1.128" in item for item in result.warnings)


def test_check_patch_reports_anchor_miss_detail():
    patch = _patch(status="missed", notes=("missing token limits",))

    result = check_patch_releases.check_patch(
        "js",
        patch,
        "2.1.128",
        registry={patch.id: patch},
    )

    assert result.status == "missed"
    assert result.ok is False
    assert "missing token limits" in result.detail


def test_check_patch_reports_unsupported_without_failing_run():
    patch = _patch()

    result = check_patch_releases.check_patch(
        "js",
        patch,
        "3.0.0",
        registry={patch.id: patch},
    )

    assert result.status == "unsupported"
    assert result.ok is True
    assert result.supported is False


def test_check_version_omits_local_binary_path(tmp_path, monkeypatch):
    binary = tmp_path / "claude"
    binary.write_bytes(b"binary")
    patch = _patch(tested=(">=2.1.0,<=2.1.128",))

    monkeypatch.setattr(
        check_patch_releases,
        "extract_entry_js",
        lambda _path: ("js", {"entryModule": "cli.js", "entryBytes": 2}),
    )

    report = check_patch_releases.check_version(
        "2.1.128",
        registry={patch.id: patch},
        downloader=lambda version: str(binary),
    )

    assert report["ok"] is True
    assert report["binary"] == {"entryModule": "cli.js", "entryBytes": 2}
    assert "binaryPath" not in report
    assert "platform" not in report


def test_run_versions_writes_version_report_and_index(tmp_path, monkeypatch):
    report = {
        "schemaVersion": 1,
        "generatedAt": "2026-05-04T00:00:00Z",
        "version": "2.1.128",
        "ok": True,
        "summary": {"total": 1, "ok": 1, "failed": 0, "untested": 0, "applied": 1},
        "patches": [],
    }
    args = argparse.Namespace(
        versions=["2.1.128"],
        latest=False,
        missing=False,
        since_existing_latest=False,
        all=False,
        max_versions=None,
        reports_dir=tmp_path / "reports",
        stop_on_error=False,
    )

    monkeypatch.setattr(check_patch_releases, "check_version", lambda version: report)

    results = check_patch_releases.run_versions(args)

    assert results[0].ok is True
    version_report = json.loads((args.reports_dir / "2.1.128.json").read_text(encoding="utf-8"))
    index = json.loads((args.reports_dir / "index.json").read_text(encoding="utf-8"))
    assert version_report["version"] == "2.1.128"
    assert index["reports"][0]["path"] == "2.1.128.json"


def test_run_versions_with_no_new_versions_keeps_existing_index(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    index_path = reports_dir / "index.json"
    index_path.write_text('{"reports":[{"version":"2.1.128"}]}\n', encoding="utf-8")
    args = argparse.Namespace(
        versions=None,
        latest=False,
        missing=False,
        since_existing_latest=True,
        all=False,
        max_versions=None,
        reports_dir=reports_dir,
        stop_on_error=False,
    )

    monkeypatch.setattr(check_patch_releases, "resolve_versions", lambda _args: [])

    results = check_patch_releases.run_versions(args)

    assert results == []
    assert json.loads(index_path.read_text(encoding="utf-8")) == {
        "reports": [{"version": "2.1.128"}],
    }
