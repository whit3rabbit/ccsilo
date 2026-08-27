"""Binary bundle inspection helpers for patch release checks."""

from pathlib import Path
from typing import Any, Dict, Tuple

from ccsilo.bun_extract import parse_bun_binary

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

def extract_js_modules(binary_path: Path) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
    """Read every loader-js module source directly from the binary.

    Claude Code >= 2.1.242 splits the bundle into many JS modules, so patch
    anchor checks must scan all of them. Returns (entry_module_name, sources,
    binary meta). Legacy monolithic bundles return a single-entry map and keep
    the old entry-only behavior.
    """
    data = binary_path.read_bytes()
    info = parse_bun_binary(data)
    entry = None
    if 0 <= info.entry_point_id < len(info.modules):
        entry = info.modules[info.entry_point_id].name
    sources: Dict[str, str] = {}
    total_bytes = 0
    for module in info.modules:
        if module.loader != "js":
            continue
        start = info.data_start + module.cont_off
        source = data[start : start + module.cont_len].decode("utf-8", errors="replace")
        sources[module.name] = source
        total_bytes += len(source)
    if not sources:
        raise RuntimeError(f"no JS modules found inside {binary_path}")
    return entry or "", sources, {
        "entryModule": entry or "",
        "moduleCount": len(sources),
        "moduleBytes": total_bytes,
    }

def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
