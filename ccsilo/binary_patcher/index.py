"""Structured apply_patches API for native binaries."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ccsilo._utils import atomic_write_bytes_no_symlink
from ccsilo.bun_extract import parse_bun_binary, replace_module
from ccsilo.bun_extract.types import BunFormatError
from ccsilo.patches import (
    PatchAnchorMissError,
    PatchBlacklistedError,
    PatchContext,
    PatchUnsupportedVersionError,
    apply_patches as apply_regex_patches,
)

from .codesign import try_adhoc_sign
from .pe_resize import PeNotLastSectionError
from .prompts import apply_prompts
from .replace_entry import replace_entry_js
from .theme import ThemeAnchorNotFound, apply_theme, themes_from_config as _themes_from_config


@dataclass
class PatchInputs:
    binary_path: str
    config: dict = None
    overlays: dict = None
    regex_tweaks: list = None
    provider_label: str = "ccsilo"
    claude_version: str = None
    force: bool = False


@dataclass
class PatchSuccess:
    ok: Literal[True]
    bytes_changed: int
    resigned: bool
    missing_prompt_keys: list
    codesign_skipped: bool
    skipped_reason: str = None
    curated_applied: list = None
    curated_skipped: list = None
    curated_missed: list = None


@dataclass
class PatchFailure:
    ok: Literal[False]
    reason: Literal["anchor-not-found", "resize-bound-exceeded", "io-error", "tweak-failed"]
    detail: str


NATIVE_REGEX_TWEAK_IDS = {
    "hide-startup-banner",
    "hide-startup-clawd",
    "suppress-native-installer-warning",
    "suppress-prompt-caching-warning",
    "suppress-model-launch-notice",
    "anthropic-sse-error-surfacing",
    "mid-conversation-system-422-fallback",
    "mcp-non-blocking",
    "mcp-batch-size",
}


def _pad_shrunk_macho_entry(js: str, pad_len: int) -> bytes:
    encoded = js.encode("utf-8")
    if pad_len <= 0:
        return encoded

    stripped = js.rstrip()
    trailer = js[len(stripped):]
    if js.startswith("// @bun") and stripped.endswith("})"):
        # Bun's CJS wrapper check is sensitive to padding after the closing wrapper.
        padded = (stripped[:-2] + (" " * pad_len) + "})" + trailer).encode("utf-8")
        if len(padded) == len(encoded) + pad_len:
            return padded
    return encoded + (b" " * pad_len)


def apply_patches(inputs):
    """Apply theme and prompt patches to a native binary."""
    if isinstance(inputs, dict):
        inputs = PatchInputs(**inputs)

    binary_path = Path(inputs.binary_path)
    try:
        data = binary_path.read_bytes()
    except OSError as exc:
        return PatchFailure(ok=False, reason="io-error", detail=f"read {binary_path}: {exc}")

    try:
        info = parse_bun_binary(data)
    except Exception as exc:
        return PatchFailure(ok=False, reason="io-error", detail=f"parse {binary_path}: {exc}")

    if info.entry_point_id < 0 or info.entry_point_id >= len(info.modules):
        return PatchFailure(ok=False, reason="io-error", detail=f"entry module id {info.entry_point_id} out of range")

    entry = info.modules[info.entry_point_id]
    old_entry_len = entry.cont_len
    old_js = data[info.data_start + entry.cont_off : info.data_start + entry.cont_off + old_entry_len].decode("utf-8")

    try:
        theme_result = apply_theme(old_js, _themes_from_config(inputs.config or {}))
        new_js = theme_result.js
    except ThemeAnchorNotFound as exc:
        return PatchFailure(ok=False, reason="anchor-not-found", detail=str(exc))
    except Exception as exc:
        return PatchFailure(ok=False, reason="io-error", detail=f"apply_theme: {exc}")

    missing_prompt_keys = []
    skipped_reason = None
    if inputs.overlays:
        prompt_result = apply_prompts(new_js, inputs.overlays)
        new_js = prompt_result.js
        missing_prompt_keys = prompt_result.missing
        if info.platform == "macho" and len(new_js.encode("utf-8")) > old_entry_len:
            skipped_reason = "macho-grow-not-supported"

    curated_applied = []
    curated_skipped = []
    curated_missed = []
    regex_tweaks = list(inputs.regex_tweaks or [])
    unsupported = [tweak_id for tweak_id in regex_tweaks if tweak_id not in NATIVE_REGEX_TWEAK_IDS]
    if unsupported:
        return PatchFailure(
            ok=False,
            reason="tweak-failed",
            detail=f"unsupported native regex tweak(s): {', '.join(unsupported)}",
        )
    if regex_tweaks and not skipped_reason:
        try:
            regex_result = apply_regex_patches(
                new_js,
                regex_tweaks,
                PatchContext(
                    claude_version=inputs.claude_version,
                    provider_label=inputs.provider_label,
                    config=inputs.config or {},
                    overlays=inputs.overlays or {},
                    force=inputs.force,
                ),
            )
        except (PatchAnchorMissError, PatchUnsupportedVersionError, PatchBlacklistedError, KeyError, ValueError) as exc:
            return PatchFailure(ok=False, reason="tweak-failed", detail=str(exc))
        new_js = regex_result.js
        curated_applied = list(regex_result.applied)
        curated_skipped = list(regex_result.skipped)
        curated_missed = list(regex_result.missed)

    bytes_changed = 0
    write_data = None
    new_content = new_js.encode("utf-8")

    if info.platform == "macho":
        if not skipped_reason:
            delta = len(new_content) - old_entry_len
            if delta > 0:
                skipped_reason = "macho-grow-not-supported"
        if not skipped_reason:
            if delta < 0:
                new_content = _pad_shrunk_macho_entry(new_js, -delta)
            try:
                write_data = replace_module(data, info, entry.name, new_content).buf
            except Exception as exc:
                return PatchFailure(ok=False, reason="io-error", detail=f"replace_module: {exc}")
    else:
        try:
            result = replace_entry_js(data, info, new_content)
            write_data = result.buf
            bytes_changed = result.delta
        except PeNotLastSectionError as exc:
            return PatchFailure(ok=False, reason="resize-bound-exceeded", detail=str(exc))
        except BunFormatError as exc:
            return PatchFailure(ok=False, reason="io-error", detail=str(exc))
        except Exception as exc:
            return PatchFailure(ok=False, reason="io-error", detail=f"replace_entry_js: {exc}")

    resigned = False
    codesign_skipped = False
    if write_data is not None:
        try:
            atomic_write_bytes_no_symlink(binary_path, write_data, mode=0o755)
        except OSError as exc:
            return PatchFailure(ok=False, reason="io-error", detail=f"write {binary_path}: {exc}")
        except ValueError as exc:
            return PatchFailure(ok=False, reason="io-error", detail=f"write {binary_path}: {exc}")

        if info.platform == "macho" and info.has_code_signature:
            sign_result = try_adhoc_sign(str(binary_path))
            if sign_result.signed:
                resigned = True
            else:
                codesign_skipped = True

    return PatchSuccess(
        ok=True,
        bytes_changed=bytes_changed,
        resigned=resigned,
        missing_prompt_keys=missing_prompt_keys,
        codesign_skipped=codesign_skipped,
        skipped_reason=skipped_reason,
        curated_applied=curated_applied,
        curated_skipped=curated_skipped,
        curated_missed=curated_missed,
    )
