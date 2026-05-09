"""Managed PATH command installs for variant wrappers."""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .._utils import utc_now
from ..workspace import read_json, workspace_root, write_json
from .constants import VARIANT_METADATA

MANAGED_BY = "ccsilo"


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
    install_dir = _resolve_install_dir(bin_dir, yes=yes)
    _prepare_install_dir(install_dir, yes=yes, create=True)
    target = Path(((variant.manifest or {}).get("paths") or {}).get("wrapper") or "")
    if not target.is_file():
        raise ValueError(f"Setup wrapper is missing: {target}")
    link_path = install_dir / command_name
    status = _validate_install_link(link_path, target)
    if status == "available":
        if not hasattr(os, "symlink"):
            raise ValueError("Symlinks are not supported on this platform")
        os.symlink(str(target), str(link_path))
        status = "installed"

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


def preflight_variant_command_install(
    variant_id: str,
    *,
    target: os.PathLike,
    alias: Optional[str] = None,
    bin_dir: Optional[os.PathLike] = None,
    yes: bool = False,
) -> InstallResult:
    result = inspect_variant_command_install(
        variant_id,
        target=target,
        alias=alias,
        bin_dir=bin_dir,
        yes=yes,
    )
    if result.status == "blocked":
        raise ValueError(result.warning)
    return result


def inspect_variant_command_install(
    variant_id: str,
    *,
    target: os.PathLike,
    alias: Optional[str] = None,
    bin_dir: Optional[os.PathLike] = None,
    yes: bool = False,
) -> InstallResult:
    command_name = _validate_alias(alias or variant_id)
    install_dir = _resolve_install_dir(bin_dir, yes=yes)
    dir_warning = ""
    try:
        _prepare_install_dir(install_dir, yes=yes, create=False)
    except ValueError as exc:
        dir_warning = str(exc)
    target_path = Path(target).expanduser()
    link_path = install_dir / command_name
    if dir_warning:
        status = "blocked"
        warning = dir_warning
    else:
        status, warning = _install_link_state(link_path, target_path)
    on_path = _path_on_path(install_dir)
    if not warning and not on_path:
        warning = _path_warning(install_dir)
    return InstallResult(
        alias=command_name,
        path=link_path,
        target=target_path,
        status=status,
        on_path=on_path,
        warning=warning,
    )


def remove_variant_managed_installs(variant) -> Tuple[List[SymlinkRemoval], List[SymlinkRemoval]]:
    manifest = variant.manifest or {}
    removed, skipped = _remove_manifest_installs(manifest)
    seen = {_path_key(Path(item.path)) for item in removed + skipped}
    targets = _variant_wrapper_targets(variant, manifest)
    for link_path in _inferred_variant_install_paths(variant, manifest):
        key = _path_key(link_path)
        if key in seen:
            continue
        if not link_path.exists() and not link_path.is_symlink():
            continue
        inferred_removed, inferred_skipped = _remove_inferred_install(link_path, targets)
        removed.extend(inferred_removed)
        skipped.extend(inferred_skipped)
        seen.add(key)
    return removed, skipped


def variant_install_cleanup_paths(variant) -> List[Path]:
    manifest = variant.manifest or {}
    paths: List[Path] = []
    seen = set()
    for item in manifest.get("installs", []) or []:
        if isinstance(item, dict) and item.get("managedBy") == MANAGED_BY and item.get("path"):
            path = Path(str(item["path"]))
            key = _path_key(path)
            if key not in seen:
                paths.append(path)
                seen.add(key)
    for path in _inferred_variant_install_paths(variant, manifest):
        key = _path_key(path)
        if key not in seen and (path.exists() or path.is_symlink()):
            paths.append(path)
            seen.add(key)
    return paths


def uninstall_workspace(*, yes: bool = False, root=None) -> UninstallResult:
    if not yes:
        raise ValueError("Pass --yes to uninstall the ccsilo workspace")
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


def _remove_inferred_install(link_path: Path, targets: List[Path]) -> Tuple[List[SymlinkRemoval], List[SymlinkRemoval]]:
    removed: List[SymlinkRemoval] = []
    skipped: List[SymlinkRemoval] = []
    target_label = str(targets[0]) if targets else ""
    if not targets:
        skipped.append(SymlinkRemoval(str(link_path), target_label, "skipped", "no setup wrapper target"))
        return removed, skipped
    if not link_path.is_symlink():
        skipped.append(SymlinkRemoval(str(link_path), target_label, "skipped", "not a symlink"))
        return removed, skipped
    current_target = _symlink_target(link_path)
    if not any(_same_path(current_target, target) for target in targets):
        skipped.append(SymlinkRemoval(str(link_path), target_label, "skipped", f"points to {current_target}"))
        return removed, skipped
    link_path.unlink()
    removed.append(SymlinkRemoval(str(link_path), str(current_target), "removed"))
    return removed, skipped


def _inferred_variant_install_paths(variant, manifest: Dict) -> List[Path]:
    aliases = _variant_install_aliases(variant, manifest)
    dirs = _install_search_dirs()
    paths: List[Path] = []
    seen = set()
    for install_dir in dirs:
        for alias in aliases:
            path = install_dir / alias
            key = _path_key(path)
            if key not in seen:
                paths.append(path)
                seen.add(key)
    return paths


def _variant_install_aliases(variant, manifest: Dict) -> List[str]:
    values = [
        getattr(variant, "variant_id", ""),
        manifest.get("id", ""),
        (manifest.get("provider") or {}).get("key", ""),
    ]
    aliases: List[str] = []
    seen = set()
    for value in values:
        try:
            alias = _validate_alias(str(value or ""))
        except ValueError:
            continue
        if alias not in seen:
            aliases.append(alias)
            seen.add(alias)
    return aliases


def _variant_wrapper_targets(variant, manifest: Dict) -> List[Path]:
    values = [
        ((manifest.get("paths") or {}).get("wrapper") or ""),
        str(workspace_root() / "bin" / str(getattr(variant, "variant_id", "") or manifest.get("id") or "")),
    ]
    targets: List[Path] = []
    seen = set()
    for value in values:
        if not value:
            continue
        path = Path(str(value))
        key = _path_key(path)
        if key not in seen:
            targets.append(path)
            seen.add(key)
    return targets


def _install_search_dirs() -> List[Path]:
    env = os.environ
    home = _home_path(env=env, home=None)
    dirs = [home / ".local" / "bin", home / "bin"]
    dirs.extend(candidate.path for candidate in discover_install_candidates(env=env, home=home))
    results: List[Path] = []
    seen = set()
    for path in dirs:
        key = _path_key(path)
        if key not in seen:
            results.append(path)
            seen.add(key)
    return results


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


def _resolve_install_dir(bin_dir: Optional[os.PathLike], *, yes: bool) -> Path:
    install_dir = Path(bin_dir).expanduser() if bin_dir is not None else default_install_dir(allow_create=yes)
    if install_dir is None:
        raise ValueError(
            "No writable home PATH directory found. Pass --yes to create ~/.local/bin, "
            "pass --bin-dir /path/to/bin, or run pipx ensurepath if pipx installed ccsilo."
        )
    return install_dir


def _prepare_install_dir(install_dir: Path, *, yes: bool, create: bool) -> None:
    if install_dir.exists():
        if not install_dir.is_dir():
            raise ValueError(f"Install path is not a directory: {install_dir}")
        if not _is_writable_dir(install_dir):
            raise ValueError(f"Install directory is not writable: {install_dir}")
        return
    if not yes:
        raise ValueError(f"Install directory does not exist: {install_dir}. Pass --yes to create it.")
    if create:
        install_dir.mkdir(parents=True, exist_ok=True)


def _validate_install_link(link_path: Path, target: Path) -> str:
    status, reason = _install_link_state(link_path, target)
    if status == "blocked":
        raise ValueError(reason)
    return status


def _install_link_state(link_path: Path, target: Path) -> Tuple[str, str]:
    if link_path.exists() or link_path.is_symlink():
        if not link_path.is_symlink():
            return "blocked", f"Refusing to overwrite non-symlink command: {link_path}"
        current_target = _symlink_target(link_path)
        if not _same_path(current_target, target):
            return "blocked", f"Refusing to overwrite symlink pointing elsewhere: {link_path} -> {current_target}"
        return "already-installed", ""
    return "available", ""


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


def _path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False))
    except OSError:
        return str(path.expanduser().absolute())


def _symlink_target(path: Path) -> Path:
    raw = os.readlink(path)
    target = Path(raw)
    if target.is_absolute():
        return target
    return path.parent / target


def _path_warning(path: Path) -> str:
    return (
        f"Install directory is not on PATH: {path}. Add it to PATH to run the command by name, "
        "or run pipx ensurepath if pipx installed ccsilo."
    )
