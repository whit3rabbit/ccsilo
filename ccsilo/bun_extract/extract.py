"""Write extracted Bun modules and manifest to disk."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .._utils import atomic_write_bytes_no_symlink, atomic_write_text_no_symlink, safe_child_path, safe_relative_path
from .types import BunFormatError

MAX_EXTRACT_FILES = 100_000
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXTRACT_SINGLE_FILE_BYTES = 512 * 1024 * 1024


@dataclass
class ExtractAllResult:
    written: List[str]
    manifest_path: Optional[str] = None
    manifest: Optional[dict] = None


def read_js_modules(
    extract_dir: Path,
    manifest_data: Optional[dict],
) -> tuple:
    """Read loader-js module sources back from an extracted bundle tree.

    Returns (entry_rel_path, {rel_path: js}). Claude Code >= 2.1.242 spreads
    patch anchors across many JS modules, so callers patch every JS module and
    keep entry_rel_path for positional entry-scoped patches. Legacy monolithic
    bundles return a single-entry map and behave exactly like entry-only
    patching.
    """
    if manifest_data is None:
        manifest_path = Path(extract_dir) / ".bundle_manifest.json"
        if not manifest_path.is_file():
            return None, {}
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    modules: dict = {}
    entry_rel = None
    entry_id = manifest_data.get("entryPointId")
    for module in manifest_data.get("modules", []):
        rel = module.get("rel_path") or module.get("sourceFile")
        if not rel:
            continue
        if entry_id is not None and module.get("index") == entry_id:
            entry_rel = rel
        if module.get("loader") != "js":
            continue
        path = Path(extract_dir) / rel
        if path.is_file():
            modules[rel] = path.read_text(encoding="utf-8", errors="replace")
    return entry_rel, modules


def extract_all(data, info, out_dir, write_sourcemaps=False, manifest=True):
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    written = []

    manifest_data = _build_manifest(info)
    emitted_files = 0
    emitted_bytes = 0

    for module in info.modules:
        rel_path = _sanitize_rel_path(module.name)
        module_info = manifest_data["modules"][module.index]
        module_info["rel_path"] = rel_path

        if module.cont_len > 0:
            out_path = _safe_extract_path(out_root, rel_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            emitted_files, emitted_bytes = _account_emitted(
                emitted_files,
                emitted_bytes,
                module.cont_len,
                rel_path,
            )
            atomic_write_bytes_no_symlink(
                out_path,
                data[info.data_start + module.cont_off : info.data_start + module.cont_off + module.cont_len],
            )
            module_info["sourceFile"] = rel_path
            written.append(str(out_path))

        if write_sourcemaps and module.smap_len > 0:
            smap_rel = rel_path + ".map"
            smap_path = _safe_extract_path(out_root, smap_rel)
            smap_path.parent.mkdir(parents=True, exist_ok=True)
            emitted_files, emitted_bytes = _account_emitted(
                emitted_files,
                emitted_bytes,
                module.smap_len,
                smap_rel,
            )
            atomic_write_bytes_no_symlink(
                smap_path,
                data[info.data_start + module.smap_off : info.data_start + module.smap_off + module.smap_len]
            )
            module_info["sourcemapFile"] = smap_rel
            written.append(str(smap_path))

        if module.bc_len > 0:
            bc_rel = rel_path + ".bc"
            bc_path = _safe_extract_path(out_root, bc_rel)
            bc_path.parent.mkdir(parents=True, exist_ok=True)
            emitted_files, emitted_bytes = _account_emitted(
                emitted_files,
                emitted_bytes,
                module.bc_len,
                bc_rel,
            )
            atomic_write_bytes_no_symlink(
                bc_path,
                data[info.data_start + module.bc_off : info.data_start + module.bc_off + module.bc_len],
            )
            module_info["bytecodeFile"] = bc_rel
            written.append(str(bc_path))

    manifest_path = None
    if manifest:
        manifest_path = out_root / ".bundle_manifest.json"
        atomic_write_text_no_symlink(manifest_path, json.dumps(manifest_data, indent=2) + "\n")

    return ExtractAllResult(
        written=written,
        manifest_path=str(manifest_path) if manifest_path is not None else None,
        manifest=manifest_data,
    )


def _build_manifest(info):
    entry = info.modules[info.entry_point_id].name if 0 <= info.entry_point_id < len(info.modules) else None
    return {
        "platform": info.platform,
        "isMacho": info.platform == "macho",
        "moduleSize": info.module_size,
        "bunVersionHint": info.bun_version_hint,
        "entryPoint": entry,
        "entryPointId": info.entry_point_id,
        "byteCount": info.byte_count,
        "flags": info.flags,
        "execArgvOffset": info.exec_argv_offset,
        "execArgvLength": info.exec_argv_length,
        "sectionOffset": info.section_offset,
        "sectionSize": info.section_size,
        "hasCodeSignature": info.has_code_signature,
        "modules": [
            {
                "index": module.index,
                "name": module.name,
                "rawName": module.raw_name,
                "isEntry": module.is_entry,
                "sourceSize": module.cont_len,
                "bytecodeSize": module.bc_len,
                "sourcemapSize": module.smap_len,
                "nameOffset": module.name_off,
                "nameSize": module.name_len,
                "contentOffset": module.cont_off,
                "sourcemapOffset": module.smap_off,
                "bytecodeOffset": module.bc_off,
                "encoding": module.encoding,
                "loader": module.loader,
                "format": module.format,
                "side": module.side,
            }
            for module in info.modules
        ],
    }


def _sanitize_rel_path(rel_path):
    try:
        return safe_relative_path(rel_path, label="module path")
    except ValueError as exc:
        raise BunFormatError(f"Refusing to extract module with unsafe path: {rel_path}") from exc


def _safe_extract_path(out_root: Path, rel_path: str) -> Path:
    try:
        return safe_child_path(out_root, rel_path, label="module path")
    except ValueError as exc:
        raise BunFormatError(f"Refusing to extract module with unsafe path: {rel_path}") from exc


def _account_emitted(file_count: int, byte_count: int, size: int, rel_path: str):
    if size > MAX_EXTRACT_SINGLE_FILE_BYTES:
        raise BunFormatError(f"Refusing to extract oversized module: {rel_path} ({size} bytes)")
    next_file_count = file_count + 1
    if next_file_count > MAX_EXTRACT_FILES:
        raise BunFormatError(f"Refusing to extract too many files: {next_file_count}")
    next_byte_count = byte_count + size
    if next_byte_count > MAX_EXTRACTED_BYTES:
        raise BunFormatError(f"Refusing to extract too many bytes: {next_byte_count}")
    return next_file_count, next_byte_count
