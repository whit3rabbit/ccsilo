"""Binary patching: theme, prompt, entry JS, and repack."""

from .codesign import AdhocSignResult, try_adhoc_sign
from .bun_compat import BUN_NODE_COMPAT_MARKER, ensure_bun_node_compat, has_bun_node_compat
from .index import PatchFailure, PatchInputs, PatchSuccess, apply_patches
from .prompts import OVERLAY_MARKERS, PromptResult, apply_prompts
from .replace_entry import ReplaceEntryResult, replace_entry_js
from .repack import RepackResult, repack_binary
from .strip_bun_wrapper import BunWrapperNotFound, strip_bun_wrapper
from .theme import ThemeAnchorNotFound, ThemeResult, apply_theme
from .js_patch import PatchUnpackedResult, UnpackedManifestError, patch_unpacked_entry, resolve_entry_path
from .unpack_and_patch import UnpackAndPatchError, UnpackAndPatchInputs, UnpackAndPatchResult, unpack_and_patch

__all__ = [
    "AdhocSignResult",
    "BunWrapperNotFound",
    "BUN_NODE_COMPAT_MARKER",
    "OVERLAY_MARKERS",
    "PatchFailure",
    "PatchInputs",
    "PatchSuccess",
    "PatchUnpackedResult",
    "PromptResult",
    "ReplaceEntryResult",
    "RepackResult",
    "ThemeAnchorNotFound",
    "ThemeResult",
    "UnpackAndPatchError",
    "UnpackAndPatchInputs",
    "UnpackAndPatchResult",
    "UnpackedManifestError",
    "apply_patches",
    "apply_prompts",
    "apply_theme",
    "ensure_bun_node_compat",
    "has_bun_node_compat",
    "patch_unpacked_entry",
    "replace_entry_js",
    "repack_binary",
    "resolve_entry_path",
    "strip_bun_wrapper",
    "try_adhoc_sign",
    "unpack_and_patch",
]
