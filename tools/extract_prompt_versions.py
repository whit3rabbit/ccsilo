#!/usr/bin/env python3
# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ccsilo.bun_extract import parse_bun_binary
from ccsilo.bun_extract.extract import extract_all as extract_bun_modules
from ccsilo.downloader import download_binary, list_available_binary_versions

from tools.prompt_extractor import extract_prompts


PromptData = Dict[str, Any]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class VersionResult:
    version: str
    ok: bool
    output_path: Optional[Path] = None
    prompt_count: int = 0
    named_count: int = 0
    unnamed_count: int = 0
    seed_path: Optional[Path] = None
    error: Optional[str] = None


def prompt_output_path(prompts_dir: Path, version: str) -> Path:
    return prompts_dir / f"{version}.json"


def bundle_scan_paths(extract_dir: Path) -> Tuple[List[str], List[str]]:
    """Split extracted bundle modules into literal-scan and whole-file inputs.

    Claude Code >= 2.1.242 ships a tiny entry module plus ~1400 JS modules, and
    bundles markdown/text assets as whole-file modules (manifest loader byte 13,
    left numeric by LOADER_NAMES). Loader "js" modules are scanned for string
    literals; loader 13 modules contribute their full text because that same
    content used to be embedded as literals in the monolithic entry.
    """
    js_paths: List[str] = []
    text_paths: List[str] = []
    manifest_path = extract_dir / ".bundle_manifest.json"
    if not manifest_path.exists():
        return js_paths, text_paths
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for module in manifest.get("modules", []):
        rel = module.get("rel_path") or module.get("sourceFile")
        if not rel:
            continue
        candidate = extract_dir / rel
        if not candidate.is_file():
            continue
        loader = module.get("loader")
        if loader == "js":
            js_paths.append(str(candidate))
        elif loader == 13:
            text_paths.append(str(candidate))
    return js_paths, text_paths


def bundled_cli_path(extract_dir: Path) -> Path:
    manifest_path = extract_dir / ".bundle_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry_point = manifest.get("entryPoint")
        if entry_point:
            candidate = extract_dir / entry_point
            if candidate.exists():
                return candidate

    candidate = extract_dir / "src" / "entrypoints" / "cli.js"
    if candidate.exists():
        return candidate

    raise FileNotFoundError(f"Could not locate cli.js in {extract_dir}")


def catalog_path(catalog_dir: Optional[Path], version: str) -> Optional[Path]:
    if catalog_dir is None:
        return None
    candidate = catalog_dir / f"prompts-{version}.json"
    return candidate if candidate.exists() else None


def load_existing_prompts(path: Optional[Path]) -> List[Dict[str, Any]]:
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("prompts", [])


def seed_named_count(path: Optional[Path]) -> int:
    if path is None or not path.exists():
        return 0
    try:
        return prompt_summary(json.loads(path.read_text(encoding="utf-8")))["named"]
    except (OSError, json.JSONDecodeError, TypeError, KeyError):
        return 0


def best_named_prompt_path(paths: Sequence[Optional[Path]]) -> Optional[Path]:
    best_path = None
    best_named = -1

    for path in paths:
        if path is None or not path.exists():
            continue
        named = seed_named_count(path)
        if best_path is None or named > best_named:
            best_path = path
            best_named = named

    return best_path


def prompt_summary(data: PromptData) -> Dict[str, int]:
    prompts = data.get("prompts", [])
    named = sum(1 for prompt in prompts if prompt.get("id") and prompt.get("name"))
    return {
        "total": len(prompts),
        "named": named,
        "unnamed": len(prompts) - named,
    }


def validate_prompt_data(data: PromptData, expected_version: str) -> None:
    if not isinstance(data, dict):
        raise ValueError("prompt data must be a JSON object")
    if data.get("version") != expected_version:
        raise ValueError(
            f"version mismatch: expected {expected_version}, got {data.get('version')!r}"
        )

    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise ValueError("prompts must be a list")
    if not prompts:
        raise ValueError("prompts must not be empty")

    for index, prompt in enumerate(prompts):
        validate_prompt(prompt, index)


def validate_prompt(prompt: Dict[str, Any], index: int) -> None:
    required = {
        "name",
        "id",
        "description",
        "pieces",
        "identifiers",
        "identifierMap",
        "version",
    }
    missing = required - set(prompt)
    if missing:
        raise ValueError(f"prompt {index} missing keys: {sorted(missing)}")

    for key in ("name", "id", "description"):
        if not isinstance(prompt[key], str):
            raise ValueError(f"prompt {index} {key} must be a string")

    pieces = prompt["pieces"]
    identifiers = prompt["identifiers"]
    identifier_map = prompt["identifierMap"]

    if not isinstance(pieces, list) or not all(isinstance(piece, str) for piece in pieces):
        raise ValueError(f"prompt {index} pieces must be a list of strings")
    if not pieces:
        raise ValueError(f"prompt {index} pieces must not be empty")
    if not isinstance(identifiers, list) or not all(isinstance(item, int) for item in identifiers):
        raise ValueError(f"prompt {index} identifiers must be a list of integers")
    if len(pieces) != len(identifiers) + 1:
        raise ValueError(
            f"prompt {index} pieces length must equal identifiers length plus one"
        )
    if not isinstance(identifier_map, dict):
        raise ValueError(f"prompt {index} identifierMap must be an object")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in identifier_map.items()
    ):
        raise ValueError(f"prompt {index} identifierMap must map strings to strings")
    if not isinstance(prompt["version"], str) and prompt["version"] is not None:
        raise ValueError(f"prompt {index} version must be a string or null")


def write_validated_prompt_data(data: PromptData, output_path: Path, expected_version: str) -> None:
    validate_prompt_data(data, expected_version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=output_path.parent,
        delete=False,
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(output_path)

    written = json.loads(output_path.read_text(encoding="utf-8"))
    validate_prompt_data(written, expected_version)


def extract_binary(binary_path: Path, extract_dir: Path, version: str, force: bool = False) -> Path:
    cli_path = extract_dir / "src" / "entrypoints" / "cli.js"
    manifest_path = extract_dir / ".bundle_manifest.json"
    if not force and cli_path.exists() and manifest_path.exists():
        return bundled_cli_path(extract_dir)

    if force and extract_dir.exists():
        shutil.rmtree(extract_dir)

    data = binary_path.read_bytes()
    info = parse_bun_binary(data)
    extract_bun_modules(data, info, extract_dir, manifest=True)
    (extract_dir / ".bundle_source.json").write_text(
        json.dumps({"binary": str(binary_path), "sourceVersion": version}, indent=2) + "\n",
        encoding="utf-8",
    )
    return bundled_cli_path(extract_dir)


def extract_version_prompts(
    version: str,
    prompts_dir: Path,
    download_dir: Path,
    work_dir: Path,
    catalog_dir_value: Optional[Path] = None,
    force_download: bool = False,
    force_extract: bool = False,
    force_prompts: bool = False,
) -> VersionResult:
    output_path = prompt_output_path(prompts_dir, version)
    if output_path.exists() and not force_prompts:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        validate_prompt_data(data, version)
        summary = prompt_summary(data)
        return VersionResult(
            version,
            True,
            output_path,
            summary["total"],
            summary["named"],
            summary["unnamed"],
        )

    binary_name = "claude.exe" if sys.platform.startswith("win") else "claude"
    binary_path = download_dir / version / binary_name
    if force_download and binary_path.exists():
        binary_path.unlink()
    binary_path = Path(download_binary(version, str(download_dir)))

    extract_dir = work_dir / version / "extracted"
    cli_path = extract_binary(binary_path, extract_dir, version, force=force_extract)
    existing_path = prompt_seed_path(
        prompts_dir,
        catalog_dir_value,
        version,
        output_path,
        force_prompts,
    )
    scan_paths, text_paths = bundle_scan_paths(extract_dir)
    data = extract_prompts(
        str(cli_path),
        version=version,
        existing_prompts=load_existing_prompts(existing_path),
        scan_paths=scan_paths,
        text_paths=text_paths,
    )
    write_validated_prompt_data(data, output_path, version)
    summary = prompt_summary(data)
    return VersionResult(
        version,
        True,
        output_path,
        summary["total"],
        summary["named"],
        summary["unnamed"],
        existing_path,
    )


def local_versions(download_dir: Path) -> List[str]:
    versions = []
    for binary in download_dir.glob("*/claude"):
        versions.append(binary.parent.name)
    for binary in download_dir.glob("*/claude.exe"):
        versions.append(binary.parent.name)
    return sort_versions(versions)


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


def prompt_versions(prompts_dir: Path) -> List[str]:
    return sort_versions(path.stem for path in prompts_dir.glob("*.json"))


def latest_prompt_version(prompts_dir: Path) -> Optional[str]:
    versions = prompt_versions(prompts_dir)
    return versions[0] if versions else None


def missing_versions(prompts_dir: Path, available_versions: Sequence[str]) -> List[str]:
    existing = set(prompt_versions(prompts_dir))
    return [
        version
        for version in sort_versions(available_versions)
        if version not in existing
    ]


def versions_since_existing_latest(
    prompts_dir: Path,
    available_versions: Sequence[str],
) -> List[str]:
    latest_existing = latest_prompt_version(prompts_dir)
    if latest_existing is None:
        return sort_versions(available_versions)
    return [
        version
        for version in sort_versions(available_versions)
        if newer_than(version, latest_existing)
    ]


def nearest_existing_prompt_path(prompts_dir: Path, version: str) -> Optional[Path]:
    candidates = []
    target = version_tuple(version)

    for path in prompts_dir.glob("*.json"):
        if not is_version(path.stem):
            continue
        candidate_tuple = version_tuple(path.stem)
        if candidate_tuple < target:
            candidates.append((candidate_tuple, path))

    if not candidates:
        return None

    return max(candidates, key=lambda item: item[0])[1]


def nearest_catalog_prompt_path(catalog_dir: Optional[Path], version: str) -> Optional[Path]:
    if catalog_dir is None:
        return None

    candidates = []
    target = version_tuple(version)

    for path in catalog_dir.glob("prompts-*.json"):
        candidate_version = path.stem[len("prompts-") :]
        if not is_version(candidate_version):
            continue
        candidate_tuple = version_tuple(candidate_version)
        if candidate_tuple < target:
            candidates.append((candidate_tuple, path))

    if not candidates:
        return None

    return max(candidates, key=lambda item: item[0])[1]


def prompt_seed_path(
    prompts_dir: Path,
    catalog_dir_value: Optional[Path],
    version: str,
    output_path: Path,
    force_prompts: bool,
) -> Optional[Path]:
    exact_catalog = catalog_path(catalog_dir_value, version)
    if force_prompts:
        if exact_catalog is not None:
            return exact_catalog
        return best_named_prompt_path(
            [
                output_path if output_path.exists() else None,
                nearest_catalog_prompt_path(catalog_dir_value, version),
                nearest_existing_prompt_path(prompts_dir, version),
            ]
        )

    if output_path.exists():
        return output_path
    if exact_catalog is not None:
        return exact_catalog
    return best_named_prompt_path(
        [
            nearest_catalog_prompt_path(catalog_dir_value, version),
            nearest_existing_prompt_path(prompts_dir, version),
        ]
    )


def resolve_versions(args: argparse.Namespace) -> List[str]:
    if args.versions:
        return sort_versions(args.versions)
    if args.local:
        return local_versions(args.download_dir)
    if args.missing:
        return missing_versions(args.prompts_dir, list_available_binary_versions())
    if args.since_existing_latest:
        return versions_since_existing_latest(
            args.prompts_dir,
            list_available_binary_versions(),
        )
    if args.all:
        return sort_versions(list_available_binary_versions())
    raise ValueError(
        "Pass --versions, --local, --missing, --since-existing-latest, or --all"
    )


def print_result_summary(result: VersionResult) -> None:
    print(f"[+] {result.version}: {result.prompt_count} prompts -> {result.output_path}")
    seed = str(result.seed_path) if result.seed_path else "none"
    print(f"    seed: {seed}")
    print(f"    named: {result.named_count}/{result.prompt_count}")
    print(f"    unnamed: {result.unnamed_count}")


def run_versions(args: argparse.Namespace) -> List[VersionResult]:
    versions = resolve_versions(args)
    if args.max_versions is not None:
        versions = versions[: args.max_versions]

    results = []
    for version in versions:
        print(f"[*] Extracting prompts for {version}")
        try:
            result = extract_version_prompts(
                version,
                args.prompts_dir,
                args.download_dir,
                args.work_dir,
                catalog_dir_value=args.catalog_dir,
                force_download=args.force_download,
                force_extract=args.force_extract,
                force_prompts=args.force_prompts,
            )
            print_result_summary(result)
            if args.fail_on_unnamed and result.unnamed_count:
                result.ok = False
                result.error = f"{result.unnamed_count} unnamed prompts"
                print(f"[!] {version}: {result.error}", file=sys.stderr)
        except Exception as exc:
            result = VersionResult(version, False, error=str(exc))
            print(f"[!] {version}: {exc}", file=sys.stderr)
            if args.stop_on_error:
                results.append(result)
                break
        results.append(result)

    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract prompt JSON files to prompts/<version>.json"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--all", action="store_true", help="Process all available binary versions")
    source.add_argument(
        "--local",
        action="store_true",
        help="Process versions already in --download-dir",
    )
    source.add_argument("--versions", nargs="+", help="Specific versions to process")
    source.add_argument(
        "--missing",
        action="store_true",
        help="Process released versions missing from --prompts-dir",
    )
    source.add_argument(
        "--since-existing-latest",
        action="store_true",
        help="Process released versions newer than the newest prompts/<version>.json",
    )
    parser.add_argument("--max-versions", type=int, help="Limit processed version count")
    parser.add_argument("--prompts-dir", type=Path, default=Path("prompts"))
    parser.add_argument("--download-dir", type=Path, default=Path("downloads"))
    parser.add_argument("--work-dir", type=Path, default=Path("downloads"))
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path("vendor/tweakcc/data/prompts"),
        help="Existing prompt catalog directory for metadata and short-prompt recovery",
    )
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-extract", action="store_true")
    parser.add_argument("--force-prompts", action="store_true")
    parser.add_argument("--fail-on-unnamed", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args(argv)

    results = run_versions(args)
    failed = [result for result in results if not result.ok]
    print(f"[*] Complete: {len(results) - len(failed)} ok, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
