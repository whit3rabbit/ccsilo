"""Managed PATH command installs for variant wrappers."""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .._utils import utc_now
from ..workspace import read_json, workspace_root, write_json
from .constants import VARIANT_METADATA

MANAGED_BY = "cc-extractor"


@dataclass
class InstallCandidate:
    path: Path
    on_path: bool
    writable: bool


@dataclass
class InstallResult:
    alias: str
    path: Path
    target: Path
    status: str
    on_path: bool
    warning: str = ""


@dataclass
class SymlinkRemoval:
    path: str
    target: str
    status: str
    reason: str = ""


@dataclass
class UninstallResult:
    workspace: Path
    removed_workspace: bool
    removed_symlinks: List[SymlinkRemoval] = field(default_factory=list)
    skipped_symlinks: List[SymlinkRemoval] = field(default_factory=list)


def discover_install_candidates(*, env: Optional[Dict[str, str]] = None, home: Optional[Path] = None) -> List[InstallCandidate]:
    env = env or os.environ
    home_path = _home_path(env=env, home=home)
    preferred = [home_path / ".local" / "bin", home_path / "bin"]
    path_entries = [_expand_path_entry(entry, home_path) for entry in _path_entries(env)]
    candidates: List[Path] = []
    for path in preferred:
        if path.is_dir() and _is_writable_dir(path):
            candidates.append(path)
    for path in path_entries:
        if not _is_under(path, home_path):
            continue
        if path in candidates:
            continue
        if path.is_dir() and _is_writable_dir(path):
            candidates.append(path)
    return [
        InstallCandidate(path=path, on_path=_path_on_path(path, env=env, home=home_path), writable=True)
        for path in candidates
    ]


def default_install_dir(
    *,
    env: Optional[Dict[str, str]] = None,
    home: Optional[Path] = None,
    allow_create: bool = False,
) -> Optional[Path]:
    candidates = discover_install_candidates(env=env, home=home)
    if candidates:
        return candidates[0].path
    if allow_create:
        return _home_path(env=env or os.environ, home=home) / ".local" / "bin"
    return None


def install_variant_command(
    variant,
    *,
    alias: Optional[str] = None,
    bin_dir: Optional[os.PathLike] = None,
    yes: bool = False,
    root=None,
) -> InstallResult:
    setup_id = str(getattr(variant, "variant_id", "") or "")
    command_name = _validate_alias(alias or setup_id)
    install_dir = Path(bin_dir).expanduser() if bin_dir is not None else default_install_dir(allow_create=yes)
    if install_dir is None:
        raise ValueError("No writable home PATH directory found. Pass --bin-dir or --yes to create ~/.local/bin.")
    if install_dir.exists():
        if not install_dir.is_dir():
            raise ValueError(f"Install path is not a directory: {install_dir}")
        if not _is_writable_dir(install_dir):
            raise ValueError(f"Install directory is not writable: {install_dir}")
    else:
        if not yes:
            raise ValueError(f"Install directory does not exist: {install_dir}. Pass --yes to create it.")
        install_dir.mkdir(parents=True, exist_ok=True)

    target = Path(((variant.manifest or {}).get("paths") or {}).get("wrapper") or "")
    if not target.is_file():
        raise ValueError(f"Setup wrapper is missing: {target}")
    link_path = install_dir / command_name
    status = "installed"
    if link_path.exists() or link_path.is_symlink():
        if not link_path.is_symlink():
            raise ValueError(f"Refusing to overwrite non-symlink command: {link_path}")
        current_target = _symlink_target(link_path)
        if not _same_path(current_target, target):
            raise ValueError(f"Refusing to overwrite symlink pointing elsewhere: {link_path} -> {current_target}")
        status = "already-installed"
    else:
        if not hasattr(os, "symlink"):
            raise ValueError("Symlinks are not supported on this platform")
        os.symlink(str(target), str(link_path))

    on_path = _path_on_path(install_dir)
    result = InstallResult(
        alias=command_name,
        path=link_path,
        target=target,
        status=status,
        on_path=on_path,
        warning="" if on_path else _path_warning(install_dir),
    )
    _record_install(variant, result, root=root)
    return result


def remove_variant_managed_installs(variant) -> Tuple[List[SymlinkRemoval], List[SymlinkRemoval]]:
    manifest = variant.manifest or {}
    return _remove_manifest_installs(manifest)


def uninstall_workspace(*, yes: bool = False, root=None) -> UninstallResult:
    if not yes:
        raise ValueError("Pass --yes to uninstall the cc-extractor workspace")
    workspace = workspace_root(root)
    removed, skipped = remove_workspace_managed_installs(root=root)
    removed_workspace = False
    if workspace.exists():
        shutil.rmtree(workspace)
        removed_workspace = True
    return UninstallResult(
        workspace=workspace,
        removed_workspace=removed_workspace,
        removed_symlinks=removed,
        skipped_symlinks=skipped,
    )


def remove_workspace_managed_installs(*, root=None) -> Tuple[List[SymlinkRemoval], List[SymlinkRemoval]]:
    removed: List[SymlinkRemoval] = []
    skipped: List[SymlinkRemoval] = []
    for manifest in _workspace_variant_manifests(root=root):
        manifest_removed, manifest_skipped = _remove_manifest_installs(manifest)
        removed.extend(manifest_removed)
        skipped.extend(manifest_skipped)
    return removed, skipped


def workspace_managed_install_records(*, root=None) -> List[SymlinkRemoval]:
    records: List[SymlinkRemoval] = []
    for manifest in _workspace_variant_manifests(root=root):
        for item in manifest.get("installs", []) or []:
            if not isinstance(item, dict) or item.get("managedBy") != MANAGED_BY:
                continue
            records.append(
                SymlinkRemoval(
                    str(item.get("path") or ""),
                    str(item.get("target") or ""),
                    "planned",
                )
            )
    return records


def _record_install(variant, result: InstallResult, *, root=None) -> None:
    manifest = dict(variant.manifest or {})
    installs = [
        dict(item)
        for item in manifest.get("installs", [])
        if isinstance(item, dict)
        and not (
            str(item.get("alias") or "") == result.alias
            and _same_path(Path(str(item.get("path") or "")), result.path)
        )
    ]
    installs.append(
        {
            "managedBy": MANAGED_BY,
            "alias": result.alias,
            "path": str(result.path),
            "target": str(result.target),
            "createdAt": utc_now(),
        }
    )
    manifest["installs"] = installs
    variant.manifest = manifest
    metadata_path = Path(getattr(variant, "path", workspace_root(root) / "variants" / getattr(variant, "variant_id", ""))) / VARIANT_METADATA
    write_json(metadata_path, manifest)


def _remove_manifest_installs(manifest: Dict) -> Tuple[List[SymlinkRemoval], List[SymlinkRemoval]]:
    removed: List[SymlinkRemoval] = []
    skipped: List[SymlinkRemoval] = []
    for item in manifest.get("installs", []) or []:
        if not isinstance(item, dict) or item.get("managedBy") != MANAGED_BY:
            continue
        link_path = Path(str(item.get("path") or ""))
        target = Path(str(item.get("target") or ""))
        if not link_path.exists() and not link_path.is_symlink():
            skipped.append(SymlinkRemoval(str(link_path), str(target), "missing", "already absent"))
            continue
        if not link_path.is_symlink():
            skipped.append(SymlinkRemoval(str(link_path), str(target), "skipped", "not a symlink"))
            continue
        current_target = _symlink_target(link_path)
        if not _same_path(current_target, target):
            skipped.append(
                SymlinkRemoval(
                    str(link_path),
                    str(target),
                    "skipped",
                    f"points to {current_target}",
                )
            )
            continue
        link_path.unlink()
        removed.append(SymlinkRemoval(str(link_path), str(target), "removed"))
    return removed, skipped


def _workspace_variant_manifests(*, root=None) -> Iterable[Dict]:
    base = workspace_root(root) / "variants"
    if not base.exists():
        return []
    manifests = []
    for metadata_path in base.glob(f"*/{VARIANT_METADATA}"):
        try:
            manifests.append(read_json(metadata_path))
        except Exception:
            continue
    return manifests


def _validate_alias(alias: str) -> str:
    value = str(alias or "").strip()
    if not value or value in {".", ".."}:
        raise ValueError("command alias must be non-empty")
    if "/" in value or "\\" in value or "\0" in value:
        raise ValueError("command alias must be a single filename")
    return value


def _home_path(*, env: Dict[str, str], home: Optional[Path]) -> Path:
    if home is not None:
        return Path(home).expanduser()
    return Path(env.get("HOME") or "~").expanduser()


def _path_entries(env: Dict[str, str]) -> List[str]:
    return [entry for entry in str(env.get("PATH") or os.defpath).split(os.pathsep) if entry]


def _expand_path_entry(entry: str, home: Path) -> Path:
    if entry.startswith("~/"):
        return home / entry[2:]
    return Path(entry).expanduser()


def _path_on_path(path: Path, *, env: Optional[Dict[str, str]] = None, home: Optional[Path] = None) -> bool:
    env = env or os.environ
    home_path = _home_path(env=env, home=home)
    return any(_same_path(_expand_path_entry(entry, home_path), path) for entry in _path_entries(env))


def _is_writable_dir(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)
    except OSError:
        return left.expanduser().absolute() == right.expanduser().absolute()


def _symlink_target(path: Path) -> Path:
    raw = os.readlink(path)
    target = Path(raw)
    if target.is_absolute():
        return target
    return path.parent / target


def _path_warning(path: Path) -> str:
    return f"Install directory is not on PATH: {path}. Add it to PATH to run the command by name."
