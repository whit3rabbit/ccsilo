"""Patch extracted entry JS with theme and prompt replacements."""

import json
from dataclasses import dataclass
from pathlib import Path

from .._utils import atomic_write_text_no_symlink, safe_child_path
from .bun_compat import ensure_bun_node_compat
from .prompts import apply_prompts
from .strip_bun_wrapper import strip_bun_wrapper
from .theme import apply_theme, themes_from_config as _themes_from_config


class UnpackedManifestError(Exception):
    def __init__(self, message):
        super().__init__(f"unpacked manifest: {message}")


@dataclass
class PatchUnpackedResult:
    entry_path: str
    theme_replaced: int
    prompt_replaced: list
    prompt_missing: list


def resolve_entry_path(unpacked_dir):
    root = Path(unpacked_dir)
    manifest_path = _find_manifest_path(root)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise UnpackedManifestError(f"read {manifest_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UnpackedManifestError(f"parse {manifest_path}: {exc}") from exc

    entry_name = manifest.get("entryPoint")
    entry_module = None
    if not entry_name:
        for module in manifest.get("modules") or []:
            if module.get("isEntry"):
                entry_module = module
                entry_name = module.get("sourceFile") or module.get("rel_path") or module.get("name")
                break
    if entry_name and entry_module is None:
        entry_module = _module_for_entry(manifest, entry_name)
        if entry_module:
            entry_name = entry_module.get("sourceFile") or entry_module.get("rel_path") or entry_module.get("name") or entry_name

    if not entry_name:
        raise UnpackedManifestError("no entry module in manifest")

    return str(_safe_join(root, entry_name))


def patch_unpacked_entry(unpacked_dir, config, overlays=None):
    entry_path = Path(resolve_entry_path(unpacked_dir))
    try:
        raw = entry_path.read_text(encoding="latin1")
    except OSError as exc:
        raise UnpackedManifestError(f"read {entry_path}: {exc}") from exc

    body = strip_bun_wrapper(raw)
    themed = apply_theme(body, _themes_from_config(config))
    js = themed.js

    prompt_replaced = []
    prompt_missing = []
    if overlays:
        prompt_result = apply_prompts(js, overlays)
        js = prompt_result.js
        prompt_replaced = prompt_result.replaced_targets
        prompt_missing = prompt_result.missing

    js = ensure_bun_node_compat(js)
    atomic_write_text_no_symlink(entry_path, js, encoding="latin1")
    return PatchUnpackedResult(
        entry_path=str(entry_path),
        theme_replaced=themed.replaced,
        prompt_replaced=prompt_replaced,
        prompt_missing=prompt_missing,
    )


def _find_manifest_path(root):
    for name in (".bundle_manifest.json", "manifest.json"):
        path = root / name
        if path.exists():
            return path
    raise UnpackedManifestError(f"read {root / '.bundle_manifest.json'}: file not found")


def _module_for_entry(manifest, entry_name):
    for module in manifest.get("modules") or []:
        if module.get("name") == entry_name or module.get("sourceFile") == entry_name or module.get("rel_path") == entry_name:
            return module
    return None


def _safe_join(root, rel_path):
    try:
        return safe_child_path(root, rel_path, label="entry module path")
    except ValueError:
        raise UnpackedManifestError(f"unsafe entry module path: {rel_path}")
