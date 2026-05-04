import hashlib
import logging
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

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
    provider_label: str = "cc-extractor"
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
            if patch.on_miss == "fatal":
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
