import hashlib
import logging
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ._versions import SemverRangeError, version_in_range


class PatchResult:
    def __init__(self, id: str, name: str, group: str, applied: bool, failed: bool = False, skipped: bool = False, details: str = ""):
        self.id = id
        self.name = name
        self.group = group
        self.applied = applied
        self.failed = failed
        self.skipped = skipped
        self.details = details

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "group": self.group,
            "applied": self.applied,
            "failed": self.failed,
            "skipped": self.skipped,
            "details": self.details
        }

def compute_md5(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def escape_regex(text: str) -> str:
    return re.escape(text)

def build_regex_from_pieces(pieces: List[str]) -> str:
    pattern = ""
    for i, piece in enumerate(pieces):
        pattern += re.escape(piece)
        if i < len(pieces) - 1:
            pattern += r'([\s\S]*?)'
    return pattern


@dataclass(frozen=True)
class PatchContext:
    claude_version: Optional[str] = None
    provider_label: str = "ccsilo"
    config: Mapping[str, Any] = field(default_factory=dict)
    overlays: Mapping[str, str] = field(default_factory=dict)
    force: bool = False


@dataclass(frozen=True)
class PatchOutcome:
    js: str
    status: str  # "applied" | "skipped" | "missed"
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class AggregateResult:
    js: str
    applied: Tuple[str, ...]
    skipped: Tuple[str, ...]
    missed: Tuple[str, ...]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class ModuleSetResult:
    # Changed module JS keyed by module path; unchanged modules are omitted.
    js_by_path: Mapping[str, str]
    applied: Tuple[str, ...]
    skipped: Tuple[str, ...]
    missed: Tuple[str, ...]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class ModuleSetOutcome:
    # Cross-module patch outcome: changed module JS keyed by module path.
    js_by_path: Mapping[str, str]
    status: str  # "applied" | "skipped" | "missed"
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Patch:
    id: str
    name: str
    group: str  # "ui" | "thinking" | "prompts" | "tools" | "system"
    versions_supported: str  # SemVer range
    versions_tested: Tuple[str, ...]  # tuple of SemVer ranges, one per matrix bucket
    apply: Callable[[str, "PatchContext"], "PatchOutcome"] = field(repr=False)
    versions_blacklisted: Tuple[str, ...] = ()
    on_miss: str = "fatal"  # "fatal" | "skip" | "warn"
    description: str = ""
    # "any": anchor-driven, safe wherever the anchor lives (split bundles move
    # anchors between modules). "entry": positional patch that must target the
    # entry module only, such as prepend-style runtime shims.
    module_scope: str = "any"  # "any" | "entry"
    # Optional cross-module application hook for patches whose anchors span
    # several JS modules in split bundles (e.g. theme registry + picker).
    apply_modules: Optional[Callable[[Mapping[str, str], "PatchContext"], Any]] = field(default=None, repr=False)


class PatchAnchorMissError(ValueError):
    def __init__(self, patch_id: str, detail: str = ""):
        self.patch_id = patch_id
        self.detail = detail
        super().__init__(f"{patch_id}: anchor not found{(': ' + detail) if detail else ''}")


class PatchUnsupportedVersionError(ValueError):
    def __init__(self, patch_id: str, version: str, supported: str):
        self.patch_id = patch_id
        self.version = version
        self.supported = supported
        super().__init__(f"{patch_id}: version {version} not in supported range {supported!r}")


class PatchBlacklistedError(ValueError):
    def __init__(self, patch_id: str, version: str):
        self.patch_id = patch_id
        self.version = version
        super().__init__(f"{patch_id}: version {version} is blacklisted")


_log = logging.getLogger(__name__)


def apply_patches(
    js: str,
    ids: Sequence[str],
    ctx: "PatchContext",
    *,
    registry: Optional[Mapping[str, "Patch"]] = None,
    fatal_miss: str = "raise",
) -> "AggregateResult":
    if registry is None:
        from ._registry import REGISTRY as _REGISTRY  # late import: avoids cycle
        registry = _REGISTRY

    applied: List[str] = []
    skipped: List[str] = []
    missed: List[str] = []
    notes: List[str] = []

    for patch_id in ids:
        if patch_id not in registry:
            raise KeyError(f"unknown patch: {patch_id!r}")
        patch = registry[patch_id]
        _preflight(patch, ctx)
        outcome = patch.apply(js, ctx)
        if outcome.status == "applied":
            applied.append(patch_id)
            js = outcome.js
        elif outcome.status == "skipped":
            skipped.append(patch_id)
        elif outcome.status == "missed":
            detail = "; ".join(outcome.notes)
            if patch.on_miss == "fatal" and fatal_miss == "raise":
                raise PatchAnchorMissError(patch_id, detail)
            if patch.on_miss == "warn":
                warning = f"patch {patch_id!r}: anchor not found"
                if detail:
                    warning = f"{warning}: {detail}"
                warnings.warn(
                    warning,
                    UserWarning,
                    stacklevel=2,
                )
            missed.append(patch_id)
        else:
            raise ValueError(f"patch {patch_id!r} returned unknown status {outcome.status!r}")
        notes.extend(outcome.notes)

    return AggregateResult(
        js=js,
        applied=tuple(applied),
        skipped=tuple(skipped),
        missed=tuple(missed),
        notes=tuple(notes),
    )


def apply_patches_to_modules(
    modules: Mapping[str, str],
    ids: Sequence[str],
    ctx: "PatchContext",
    *,
    entry_path: Optional[str] = None,
    registry: Optional[Mapping[str, "Patch"]] = None,
) -> "ModuleSetResult":
    """Apply patches across a split bundle's JS modules.

    Claude Code >= 2.1.242 spreads patch anchors over many JS modules instead
    of one monolithic entry. Each patch is attempted on every module
    (entry-scoped patches only on the entry module) and counts as applied when
    it applies anywhere. Per-module misses are expected, so miss notes are kept
    only for patches that missed everywhere.
    """
    if registry is None:
        from ._registry import REGISTRY as _REGISTRY  # late import: avoids cycle
        registry = _REGISTRY

    for patch_id in ids:
        if patch_id not in registry:
            raise KeyError(f"unknown patch: {patch_id!r}")
        _preflight(registry[patch_id], ctx)

    entry_ids = {
        patch_id
        for patch_id in ids
        if registry[patch_id].module_scope == "entry"
    }
    module_set_ids = {
        patch_id
        for patch_id in ids
        if registry[patch_id].apply_modules is not None
    }

    applied_anywhere: set = set()
    skipped_anywhere: set = set()
    miss_notes: Dict[str, Tuple[str, ...]] = {}
    js_by_path: Dict[str, str] = {}
    current: Dict[str, str] = dict(modules)

    for patch_id in sorted(module_set_ids):
        outcome = registry[patch_id].apply_modules(current, ctx)
        if outcome.status == "applied":
            applied_anywhere.add(patch_id)
            current.update(outcome.js_by_path)
            js_by_path.update(outcome.js_by_path)
        elif outcome.status == "skipped":
            skipped_anywhere.add(patch_id)
        elif outcome.status == "missed":
            if outcome.notes:
                miss_notes.setdefault(patch_id, outcome.notes)
        else:
            raise ValueError(
                f"patch {patch_id!r} returned unknown status {outcome.status!r}"
            )

    for path, original_js in current.items():
        js = original_js
        for patch_id in ids:
            if patch_id in entry_ids and path != entry_path:
                continue
            if patch_id in module_set_ids:
                continue
            outcome = registry[patch_id].apply(js, ctx)
            if outcome.status == "applied":
                applied_anywhere.add(patch_id)
                js = outcome.js
            elif outcome.status == "skipped":
                skipped_anywhere.add(patch_id)
            elif outcome.status == "missed":
                if patch_id not in miss_notes and outcome.notes:
                    miss_notes[patch_id] = outcome.notes
            else:
                raise ValueError(
                    f"patch {patch_id!r} returned unknown status {outcome.status!r}"
                )
        if js != original_js:
            js_by_path[path] = js

    applied: List[str] = []
    skipped: List[str] = []
    missed: List[str] = []
    notes: List[str] = []
    for patch_id in ids:
        if patch_id in applied_anywhere:
            applied.append(patch_id)
        elif patch_id in skipped_anywhere:
            skipped.append(patch_id)
        else:
            missed.append(patch_id)
            notes.extend(miss_notes.get(patch_id, ()))
            if registry[patch_id].on_miss == "warn":
                warning = f"patch {patch_id!r}: anchor not found"
                detail = "; ".join(miss_notes.get(patch_id, ()))
                if detail:
                    warning = f"{warning}: {detail}"
                warnings.warn(warning, UserWarning, stacklevel=2)

    return ModuleSetResult(
        js_by_path=js_by_path,
        applied=tuple(applied),
        skipped=tuple(skipped),
        missed=tuple(missed),
        notes=tuple(notes),
    )


def _preflight(patch: "Patch", ctx: "PatchContext") -> None:
    version = ctx.claude_version
    if version is None:
        _log.debug("apply_patches: no claude_version provided, skipping pre-flight for %s", patch.id)
        return

    if version in patch.versions_blacklisted and not ctx.force:
        raise PatchBlacklistedError(patch.id, version)

    try:
        in_supported = version_in_range(version, patch.versions_supported)
    except SemverRangeError as exc:
        raise PatchUnsupportedVersionError(patch.id, version, patch.versions_supported) from exc

    if not in_supported and not ctx.force:
        raise PatchUnsupportedVersionError(patch.id, version, patch.versions_supported)

    in_tested = False
    for tested_range in patch.versions_tested:
        try:
            if version_in_range(version, tested_range):
                in_tested = True
                break
        except SemverRangeError:
            continue
    if not in_tested:
        warnings.warn(
            f"patch {patch.id!r} not tested against version {version}; "
            f"tested ranges: {list(patch.versions_tested)}",
            UserWarning,
            stacklevel=2,
        )
