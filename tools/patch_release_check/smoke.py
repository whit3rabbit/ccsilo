"""Runtime smoke helpers for patch release compatibility checks."""

import os
import subprocess
import tempfile
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ccsilo._utils import atomic_write_text_no_symlink, safe_child_path
from ccsilo.binary_patcher.codesign import try_adhoc_sign
from ccsilo.bundler import pack_bundle
from ccsilo.bun_extract import read_js_modules
from ccsilo.downloader import get_platform_key
from ccsilo.extractor import extract_all
from ccsilo.patch_workflow import _entry_path
from ccsilo.patches import Patch, PatchContext, apply_patches_to_modules
from ccsilo.patches._registry import REGISTRY

from .bundle import file_sha256
from .models import (
    DEFAULT_CONFIG,
    DEFAULT_OVERLAYS,
    DEFAULT_SMOKE_TIMEOUT_SECONDS,
    OUTPUT_LIMIT,
    SMOKE_ENV_DEFAULTS,
)
from .patches import smoke_patch_ids

def _sanitize_output(
    value: Optional[str],
    replacements: Sequence[Tuple[str, str]] = (),
) -> str:
    text = value or ""
    for old, new in replacements:
        if old:
            text = text.replace(old, new)
    if len(text) <= OUTPUT_LIMIT:
        return text
    return f"{text[:OUTPUT_LIMIT]}...<truncated>"

def smoke_environment(root: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key in ("PATH", "TMPDIR", "TEMP", "TMP", "SystemRoot", "WINDIR"):
        if key in os.environ:
            env[key] = os.environ[key]

    home = root / "home"
    config = root / "config"
    cache = root / "cache"
    data = root / "data"
    workspace = root / "workspace"
    for path in (home, config, cache, data, workspace):
        path.mkdir(parents=True, exist_ok=True)

    env.update(SMOKE_ENV_DEFAULTS)
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config),
            "XDG_CACHE_HOME": str(cache),
            "XDG_DATA_HOME": str(data),
            "CLAUDE_CONFIG_DIR": str(config / "claude"),
            "CLAUDE_CODE_CONFIG_DIR": str(config / "claude-code"),
            "CCSILO_WORKSPACE": str(workspace),
        }
    )
    return env

def run_smoke_command(
    binary_path: Path,
    temp_root: Path,
    *,
    timeout: int,
    label: str,
    replacements: Sequence[Tuple[str, str]],
    expected_version: Optional[str] = None,
) -> Dict[str, Any]:
    proc = subprocess.run(
        [str(binary_path), "--version"],
        env=smoke_environment(temp_root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    stdout = _sanitize_output(proc.stdout, replacements)
    stderr = _sanitize_output(proc.stderr, replacements)
    version_matched = expected_version is None or expected_version in (proc.stdout or "")
    ok = proc.returncode == 0 and bool((proc.stdout or "").strip()) and version_matched
    return {
        "ok": ok,
        "command": [label, "--version"],
        "exitCode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "expectedVersion": expected_version,
        "versionMatched": version_matched,
    }

def run_binary_smoke(
    binary_path: Path,
    version: str,
    *,
    registry: Mapping[str, Patch] = REGISTRY,
    timeout: int = DEFAULT_SMOKE_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    started = time.monotonic()
    stage = "prepare"
    replacements: List[Tuple[str, str]] = []
    patch_ids = smoke_patch_ids(registry, version)
    platform_key = get_platform_key()
    if not patch_ids:
        return {
            "ok": False,
            "status": "failed",
            "stage": stage,
            "platformKey": platform_key,
            "detail": "no supported patches selected for smoke",
            "durationMs": int((time.monotonic() - started) * 1000),
            "patchIds": [],
        }

    try:
        with tempfile.TemporaryDirectory(prefix=f"patch-smoke-{version}-") as temp_dir:
            temp_root = Path(temp_dir)
            extract_dir = temp_root / "bundle"
            baseline_binary = temp_root / f"baseline-{binary_path.name}"
            patched_binary = temp_root / binary_path.name
            replacements = [
                (str(baseline_binary), "<baseline-binary>"),
                (str(patched_binary), "<patched-binary>"),
                (str(temp_root), "<temp>"),
            ]

            stage = "extract"
            manifest_data = extract_all(
                str(binary_path),
                str(extract_dir),
                source_version=version,
            )
            _entry_path(extract_dir, manifest_data)
            entry_rel, js_modules = read_js_modules(extract_dir, manifest_data)

            stage = "baseline-pack"
            pack_bundle(str(extract_dir), str(baseline_binary), str(binary_path))
            if os.name != "nt":
                os.chmod(baseline_binary, 0o755)

            stage = "baseline-codesign"
            baseline_sign_result = try_adhoc_sign(str(baseline_binary))
            baseline_sign_detail = _sanitize_output(baseline_sign_result.detail, replacements)
            if baseline_sign_result.reason == "failed":
                return {
                    "ok": None,
                    "status": "blocked",
                    "stage": stage,
                    "platformKey": platform_key,
                    "detail": baseline_sign_detail,
                    "durationMs": int((time.monotonic() - started) * 1000),
                    "outputSha256": file_sha256(baseline_binary),
                    "codesign": {
                        "signed": baseline_sign_result.signed,
                        "reason": baseline_sign_result.reason,
                        "detail": baseline_sign_detail,
                    },
                    "patchIds": patch_ids,
                }

            stage = "baseline-run"
            baseline = run_smoke_command(
                baseline_binary,
                temp_root,
                timeout=timeout,
                label="<baseline-binary>",
                replacements=replacements,
                expected_version=version,
            )
            if not baseline["ok"]:
                return {
                    "ok": None,
                    "status": "blocked",
                    "stage": stage,
                    "platformKey": platform_key,
                    "detail": "unpatched repack failed before patch smoke",
                    "baseline": baseline,
                    "durationMs": int((time.monotonic() - started) * 1000),
                    "outputSha256": file_sha256(baseline_binary),
                    "codesign": {
                        "signed": baseline_sign_result.signed,
                        "reason": baseline_sign_result.reason,
                        "detail": baseline_sign_detail,
                    },
                    "patchIds": patch_ids,
                }

            stage = "patch"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                patch_result = apply_patches_to_modules(
                    js_modules,
                    patch_ids,
                    PatchContext(
                        claude_version=version,
                        provider_label="Patch compatibility smoke",
                        config=DEFAULT_CONFIG,
                        overlays=DEFAULT_OVERLAYS,
                    ),
                    entry_path=entry_rel,
                    registry=registry,
                )
            for rel_path, patched_js in patch_result.js_by_path.items():
                module_path = safe_child_path(extract_dir, rel_path, label="module path")
                atomic_write_text_no_symlink(module_path, patched_js)

            stage = "pack"
            pack_bundle(str(extract_dir), str(patched_binary), str(binary_path))
            if os.name != "nt":
                os.chmod(patched_binary, 0o755)

            stage = "codesign"
            sign_result = try_adhoc_sign(str(patched_binary))
            sign_detail = _sanitize_output(sign_result.detail, replacements)
            if sign_result.reason == "failed":
                return {
                    "ok": None,
                    "status": "blocked",
                    "stage": stage,
                    "platformKey": platform_key,
                    "detail": sign_detail,
                    "durationMs": int((time.monotonic() - started) * 1000),
                    "outputSha256": file_sha256(patched_binary),
                    "codesign": {
                        "signed": sign_result.signed,
                        "reason": sign_result.reason,
                        "detail": sign_detail,
                    },
                    "patches": {
                        "attempted": patch_ids,
                        "applied": list(patch_result.applied),
                        "skipped": list(patch_result.skipped),
                        "missed": list(patch_result.missed),
                        "warnings": [str(item.message) for item in caught],
                    },
                }

            stage = "run"
            run_result = run_smoke_command(
                patched_binary,
                temp_root,
                timeout=timeout,
                label="<patched-binary>",
                replacements=replacements,
                expected_version=version,
            )
            ok = bool(run_result["ok"])
            return {
                "ok": ok,
                "status": "passed" if ok else "failed",
                "stage": stage,
                "platformKey": platform_key,
                **run_result,
                "durationMs": int((time.monotonic() - started) * 1000),
                "outputSha256": file_sha256(patched_binary),
                "codesign": {
                    "signed": sign_result.signed,
                    "reason": sign_result.reason,
                    "detail": sign_detail,
                },
                "baselineCodesign": {
                    "signed": baseline_sign_result.signed,
                    "reason": baseline_sign_result.reason,
                    "detail": baseline_sign_detail,
                },
                "patches": {
                    "attempted": patch_ids,
                    "applied": list(patch_result.applied),
                    "skipped": list(patch_result.skipped),
                    "missed": list(patch_result.missed),
                    "warnings": [str(item.message) for item in caught],
                },
            }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "status": "timeout",
            "stage": stage,
            "platformKey": platform_key,
            "command": ["<patched-binary>", "--version"],
            "timeoutSeconds": timeout,
            "stdout": _sanitize_output(
                exc.stdout if isinstance(exc.stdout, str) else "",
                replacements,
            ),
            "stderr": _sanitize_output(
                exc.stderr if isinstance(exc.stderr, str) else "",
                replacements,
            ),
            "durationMs": int((time.monotonic() - started) * 1000),
            "patchIds": patch_ids,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "stage": stage,
            "platformKey": platform_key,
            "detail": _sanitize_output(str(exc), replacements),
            "durationMs": int((time.monotonic() - started) * 1000),
            "patchIds": patch_ids,
        }
