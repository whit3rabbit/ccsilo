#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cc_extractor.bun_extract import parse_bun_binary
from cc_extractor.downloader import (
    download_binary,
    fetch_latest_binary_version,
    list_available_binary_versions,
)
from cc_extractor.patches import (
    Patch,
    PatchAnchorMissError,
    PatchBlacklistedError,
    PatchContext,
    PatchUnsupportedVersionError,
    apply_patches,
)
from cc_extractor.patches._registry import REGISTRY
from cc_extractor.patches._versions import SemverRangeError, version_in_range


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DEFAULT_REPORTS_DIR = Path("reports") / "patch-compat"
DEFAULT_CONFIG = {
    "settings": {
        "themes": [
            {"id": "compat-dark", "name": "Compat Dark", "colors": {"bashBorder": "#ffffff"}},
            {"id": "compat-provider", "name": "Compat Provider", "colors": {"bashBorder": "#dadada"}},
        ],
        "misc": {
            "tokenCountRounding": 1000,
            "statusLineUpdateThrottleMs": 300,
            "mcpServerConnectionBatchSize": 10,
        },
        "claudeMdAltNames": ["AGENTS.md", "CLAUDE.md"],
    },
}
DEFAULT_OVERLAYS = {"webfetch": "Patch compatibility smoke overlay."}


@dataclass
class PatchCheck:
    id: str
    name: str
    group: str
    status: str
    ok: bool
    supported: bool
    tested: bool
    warnings: List[str]
    notes: List[str]
    detail: str = ""


@dataclass
class VersionReport:
    version: str
    ok: bool
    output_path: Path
    summary: Dict[str, int]
    error: Optional[str] = None


def is_version(value: str) -> bool:
    return bool(VERSION_RE.match(value))


def version_tuple(version: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def newer_than(version: str, baseline: str) -> bool:
    return version_tuple(version) > version_tuple(baseline)


def sort_versions(versions: Iterable[str]) -> List[str]:
    return sorted(
        {version for version in versions if is_version(version)},
        key=version_tuple,
        reverse=True,
    )


def report_path(reports_dir: Path, version: str) -> Path:
    return reports_dir / f"{version}.json"


def report_versions(reports_dir: Path) -> List[str]:
    return sort_versions(path.stem for path in reports_dir.glob("*.json") if path.stem != "index")


def latest_report_version(reports_dir: Path) -> Optional[str]:
    versions = report_versions(reports_dir)
    return versions[0] if versions else None


def missing_versions(reports_dir: Path, available_versions: Sequence[str]) -> List[str]:
    existing = set(report_versions(reports_dir))
    return [
        version
        for version in sort_versions(available_versions)
        if version not in existing
    ]


def versions_since_existing_latest(
    reports_dir: Path,
    available_versions: Sequence[str],
) -> List[str]:
    latest_existing = latest_report_version(reports_dir)
    if latest_existing is None:
        return sort_versions(available_versions)
    return [
        version
        for version in sort_versions(available_versions)
        if newer_than(version, latest_existing)
    ]


def resolve_versions(args: argparse.Namespace) -> List[str]:
    if args.versions:
        return sort_versions(args.versions)
    if args.latest:
        return [fetch_latest_binary_version()]
    if args.missing:
        return missing_versions(args.reports_dir, list_available_binary_versions())
    if args.since_existing_latest:
        return versions_since_existing_latest(
            args.reports_dir,
            list_available_binary_versions(),
        )
    if args.all:
        return sort_versions(list_available_binary_versions())
    raise ValueError("Pass --versions, --latest, --missing, --since-existing-latest, or --all")


def extract_entry_js(binary_path: Path) -> Tuple[str, Dict[str, Any]]:
    data = binary_path.read_bytes()
    info = parse_bun_binary(data)
    if 0 <= info.entry_point_id < len(info.modules):
        module = info.modules[info.entry_point_id]
    else:
        module = next(
            (item for item in info.modules if item.name and item.name.endswith("cli.js")),
            None,
        )
        if module is None:
            raise RuntimeError(f"entry module not found inside {binary_path}")
    start = info.data_start + module.cont_off
    entry_bytes = data[start : start + module.cont_len]
    return entry_bytes.decode("utf-8", errors="replace"), {
        "entryModule": module.name,
        "entryBytes": len(entry_bytes),
    }


def patch_supported(patch: Patch, version: str) -> bool:
    try:
        return version_in_range(version, patch.versions_supported)
    except SemverRangeError:
        return False


def patch_tested(patch: Patch, version: str) -> bool:
    for tested_range in patch.versions_tested:
        try:
            if version_in_range(version, tested_range):
                return True
        except SemverRangeError:
            continue
    return False


def check_patch(
    js: str,
    patch: Patch,
    version: str,
    *,
    registry: Mapping[str, Patch],
    config: Optional[Mapping[str, Any]] = None,
    overlays: Optional[Mapping[str, str]] = None,
) -> PatchCheck:
    ctx = PatchContext(
        claude_version=version,
        provider_label="Patch compatibility",
        config=config or DEFAULT_CONFIG,
        overlays=overlays or DEFAULT_OVERLAYS,
    )
    caught_warnings: List[str] = []
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                result = apply_patches(js, [patch.id], ctx, registry=registry)
            finally:
                caught_warnings = [str(item.message) for item in caught]
    except PatchAnchorMissError as exc:
        return PatchCheck(
            patch.id,
            patch.name,
            patch.group,
            "missed",
            False,
            patch_supported(patch, version),
            patch_tested(patch, version),
            caught_warnings,
            [],
            str(exc),
        )
    except PatchUnsupportedVersionError as exc:
        return PatchCheck(
            patch.id,
            patch.name,
            patch.group,
            "unsupported",
            True,
            False,
            patch_tested(patch, version),
            caught_warnings,
            [],
            str(exc),
        )
    except PatchBlacklistedError as exc:
        return PatchCheck(
            patch.id,
            patch.name,
            patch.group,
            "blacklisted",
            True,
            patch_supported(patch, version),
            False,
            caught_warnings,
            [],
            str(exc),
        )
    except Exception as exc:
        return PatchCheck(
            patch.id,
            patch.name,
            patch.group,
            "error",
            False,
            patch_supported(patch, version),
            patch_tested(patch, version),
            caught_warnings,
            [],
            str(exc),
        )

    if result.applied:
        status = "applied"
        ok = True
    elif result.skipped:
        status = "skipped"
        ok = True
    elif result.missed:
        status = "missed"
        ok = False
    else:
        status = "no-op"
        ok = False
    return PatchCheck(
        patch.id,
        patch.name,
        patch.group,
        status,
        ok,
        patch_supported(patch, version),
        patch_tested(patch, version),
        caught_warnings,
        list(result.notes),
    )


def summarize_checks(checks: Sequence[PatchCheck]) -> Dict[str, int]:
    summary = {
        "total": len(checks),
        "ok": sum(1 for check in checks if check.ok),
        "failed": sum(1 for check in checks if not check.ok),
        "untested": sum(1 for check in checks if not check.tested),
    }
    for check in checks:
        summary[check.status] = summary.get(check.status, 0) + 1
    return summary


def check_version(
    version: str,
    *,
    registry: Mapping[str, Patch] = REGISTRY,
    downloader=download_binary,
) -> Dict[str, Any]:
    binary_path = Path(downloader(version=version))
    js, binary = extract_entry_js(binary_path)
    checks = [
        check_patch(js, patch, version, registry=registry)
        for patch in registry.values()
    ]
    summary = summarize_checks(checks)
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "version": version,
        "binary": binary,
        "summary": summary,
        "ok": summary["failed"] == 0,
        "patches": [
            {
                "id": check.id,
                "name": check.name,
                "group": check.group,
                "status": check.status,
                "ok": check.ok,
                "supported": check.supported,
                "tested": check.tested,
                "warnings": check.warnings,
                "notes": check.notes,
                "detail": check.detail,
            }
            for check in checks
        ],
    }


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_run_index(reports_dir: Path, reports: Sequence[Dict[str, Any]]) -> None:
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports": [
            {
                "version": report["version"],
                "ok": report["ok"],
                "summary": report["summary"],
                "path": f"{report['version']}.json",
            }
            for report in reports
        ],
    }
    write_json(reports_dir / "index.json", payload)


def run_versions(args: argparse.Namespace) -> List[VersionReport]:
    versions = resolve_versions(args)
    if args.max_versions is not None:
        versions = versions[: args.max_versions]

    reports = []
    results = []
    for version in versions:
        print(f"[*] Checking patches against Claude Code {version}")
        output_path = report_path(args.reports_dir, version)
        try:
            report = check_version(version)
            write_json(output_path, report)
            reports.append(report)
            results.append(
                VersionReport(
                    version=version,
                    ok=bool(report["ok"]),
                    output_path=output_path,
                    summary=dict(report["summary"]),
                )
            )
            print_result_summary(results[-1])
            if args.stop_on_error and not report["ok"]:
                break
        except Exception as exc:
            error_report = {
                "schemaVersion": 1,
                "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "version": version,
                "ok": False,
                "error": str(exc),
                "summary": {"total": 0, "ok": 0, "failed": 1, "untested": 0},
                "patches": [],
            }
            write_json(output_path, error_report)
            reports.append(error_report)
            result = VersionReport(
                version=version,
                ok=False,
                output_path=output_path,
                summary=dict(error_report["summary"]),
                error=str(exc),
            )
            results.append(result)
            print(f"[!] {version}: {exc}", file=sys.stderr)
            if args.stop_on_error:
                break

    if reports:
        write_run_index(args.reports_dir, reports)
    return results


def print_result_summary(result: VersionReport) -> None:
    summary = result.summary
    status = "ok" if result.ok else "failed"
    print(
        f"[+] {result.version}: {status}, "
        f"{summary.get('ok', 0)}/{summary.get('total', 0)} patches ok, "
        f"{summary.get('untested', 0)} untested -> {result.output_path}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check curated regex patches against Claude Code releases"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--all", action="store_true", help="Process all available binary versions")
    source.add_argument("--latest", action="store_true", help="Process the latest binary version")
    source.add_argument("--versions", nargs="+", help="Specific versions to process")
    source.add_argument(
        "--missing",
        action="store_true",
        help="Process released versions missing from --reports-dir",
    )
    source.add_argument(
        "--since-existing-latest",
        action="store_true",
        help="Process released versions newer than the newest report JSON",
    )
    parser.add_argument("--max-versions", type=int, help="Limit processed version count")
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(argv)

    results = run_versions(args)
    failed = [result for result in results if not result.ok]
    print(f"[*] Complete: {len(results) - len(failed)} ok, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
