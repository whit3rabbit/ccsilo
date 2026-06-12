#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import difflib
import json
import re
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.prompt_extractor import (  # noqa: E402
    _decode_js_escapes_for_match,
    replace_build_time_in_string,
    replace_version_in_string,
)
from tools.extract_prompt_versions import validate_prompt_data  # noqa: E402


Prompt = Dict[str, Any]
PromptCatalog = Dict[str, Any]
Identifiers = Tuple[int, ...]

MIN_LENGTH_RATIO = 0.90
REPORT_SIMILARITY_FLOOR = 0.90
DIFF_CONTEXT_LINES = 2
DIFF_MAX_LINES = 30
DIFF_WRAP_WIDTH = 100
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class RawHistoryPrompt:
    prompt: Prompt
    source_version: str
    source_path: Path
    source_index: int
    source_kind: str


@dataclass(frozen=True)
class HistoryPrompt:
    prompt: Prompt
    source_version: str
    source_path: Path
    source_index: int
    source_kind: str
    normalized_text: str
    display_text: str
    first_heading: str
    identifiers: Identifiers

    @property
    def prompt_id(self) -> str:
        return str(self.prompt.get("id", ""))

    @property
    def prompt_name(self) -> str:
        return str(self.prompt.get("name", ""))


@dataclass(frozen=True)
class TargetPrompt:
    prompt: Prompt
    target_index: int
    normalized_text: str
    display_text: str
    first_heading: str
    identifiers: Identifiers


@dataclass(frozen=True)
class ScoredCandidate:
    history: HistoryPrompt
    score: float
    match_kind: str


def _version_tuple(version: str) -> Optional[Tuple[int, int, int]]:
    if not VERSION_RE.match(version):
        return None
    parts = version.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def _joined(prompt: Prompt) -> str:
    return "".join(prompt.get("pieces", []))


def _prompt_versions(prompt: Prompt, catalog_version: str) -> List[str]:
    versions = [catalog_version]
    prompt_version = prompt.get("version")
    if isinstance(prompt_version, str):
        versions.append(prompt_version)
    return list(dict.fromkeys(version for version in versions if version))


def _comparison_text(prompt: Prompt, catalog_version: str, *, collapse: bool) -> str:
    text = _decode_js_escapes_for_match(_joined(prompt))
    text = replace_build_time_in_string(text)
    for version in _prompt_versions(prompt, catalog_version):
        text = replace_version_in_string(text, version)
    if collapse:
        text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_prompt_text(prompt: Prompt, catalog_version: str) -> str:
    return _comparison_text(prompt, catalog_version, collapse=True)


def _display_text(prompt: Prompt, catalog_version: str) -> str:
    return _comparison_text(prompt, catalog_version, collapse=False)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line.strip())
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        return line
    return ""


def _identifiers(prompt: Prompt) -> Identifiers:
    identifiers = prompt.get("identifiers", [])
    return tuple(item for item in identifiers if isinstance(item, int))


def _pieces_key(prompt: Prompt) -> Tuple[str, ...]:
    pieces = prompt.get("pieces", [])
    if not isinstance(pieces, list):
        return ()
    return tuple(piece for piece in pieces if isinstance(piece, str))


def _length_ratio(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return min(len(left), len(right)) / max(len(left), len(right))


def _is_named(prompt: Prompt) -> bool:
    return bool(prompt.get("id") and prompt.get("name"))


def _is_unnamed(prompt: Prompt) -> bool:
    return not _is_named(prompt)


def _load_json(path: Path) -> PromptCatalog:
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_version(path: Path, data: PromptCatalog, *, vendor: bool) -> str:
    version = data.get("version")
    if isinstance(version, str) and version:
        return version
    stem = path.stem
    return stem[len("prompts-") :] if vendor and stem.startswith("prompts-") else stem


def _iter_catalog_paths(history_dir: Path, catalog_dir: Path) -> Iterable[Tuple[Path, str, bool]]:
    seen: Set[Path] = set()

    for path in sorted(catalog_dir.glob("prompts-*.json")):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path, "vendor", True

    for path in sorted(history_dir.glob("*.json")):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield path, "local", False


def _is_past_version(source_version: str, target_version: str) -> bool:
    source_tuple = _version_tuple(source_version)
    target_tuple = _version_tuple(target_version)
    if source_tuple is None or target_tuple is None:
        return source_version != target_version
    return source_tuple < target_tuple


def load_target(path: Path) -> Tuple[str, PromptCatalog]:
    data = _load_json(path)
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{path} is missing a string version")
    prompts = data.get("prompts")
    if not isinstance(prompts, list):
        raise ValueError(f"{path} is missing a prompts list")
    return version, data


def load_history_prompts(
    history_dir: Path,
    catalog_dir: Path,
    target_path: Path,
    target_version: str,
) -> List[HistoryPrompt]:
    raw_prompts: Dict[Tuple[str, Tuple[str, ...], Identifiers], RawHistoryPrompt] = {}
    target_resolved = target_path.resolve()

    for path, source_kind, vendor in _iter_catalog_paths(history_dir, catalog_dir):
        if path.resolve() == target_resolved:
            continue
        data = _load_json(path)
        source_version = _catalog_version(path, data, vendor=vendor)
        if not _is_past_version(source_version, target_version):
            continue

        for index, prompt in enumerate(data.get("prompts", [])):
            if not isinstance(prompt, dict) or not _is_named(prompt):
                continue
            raw = RawHistoryPrompt(
                prompt=prompt,
                source_version=source_version,
                source_path=path,
                source_index=index,
                source_kind=source_kind,
            )
            key = (str(prompt.get("id", "")), _pieces_key(prompt), _identifiers(prompt))
            current = raw_prompts.get(key)
            if current is None or _raw_source_rank(raw) > _raw_source_rank(current):
                raw_prompts[key] = raw

    prompts: List[HistoryPrompt] = []
    for raw in raw_prompts.values():
        display_text = _display_text(raw.prompt, raw.source_version)
        prompts.append(
            HistoryPrompt(
                prompt=raw.prompt,
                source_version=raw.source_version,
                source_path=raw.source_path,
                source_index=raw.source_index,
                source_kind=raw.source_kind,
                normalized_text=normalize_prompt_text(raw.prompt, raw.source_version),
                display_text=display_text,
                first_heading=_first_heading(display_text),
                identifiers=_identifiers(raw.prompt),
            )
        )

    return prompts


def _raw_source_rank(raw: RawHistoryPrompt) -> Tuple[Tuple[int, int, int], int, int]:
    version = _version_tuple(raw.source_version) or (0, 0, 0)
    source_priority = 1 if raw.source_kind == "vendor" else 0
    return version, source_priority, -raw.source_index


def _source_rank(history: HistoryPrompt) -> Tuple[Tuple[int, int, int], int, int]:
    version = _version_tuple(history.source_version) or (0, 0, 0)
    source_priority = 1 if history.source_kind == "vendor" else 0
    return version, source_priority, -history.source_index


def _best_source(candidates: Sequence[ScoredCandidate]) -> ScoredCandidate:
    return max(candidates, key=lambda item: (item.score, _source_rank(item.history)))


def _candidate_summary(candidate: ScoredCandidate) -> Dict[str, Any]:
    history = candidate.history
    return {
        "id": history.prompt_id,
        "name": history.prompt_name,
        "sourceVersion": history.source_version,
        "sourcePromptVersion": history.prompt.get("version"),
        "sourcePath": str(history.source_path),
        "sourceIndex": history.source_index,
        "confidence": round(candidate.score, 6),
        "matchKind": candidate.match_kind,
    }


def _diff_excerpt(source_text: str, target_text: str) -> str:
    source_lines = _diff_lines(source_text)
    target_lines = _diff_lines(target_text)
    diff = list(
        difflib.unified_diff(
            source_lines,
            target_lines,
            fromfile="source",
            tofile="target",
            n=DIFF_CONTEXT_LINES,
            lineterm="",
        )
    )
    if not diff:
        return ""
    if len(diff) > DIFF_MAX_LINES:
        diff = diff[:DIFF_MAX_LINES] + ["... diff truncated ..."]
    return "\n".join(diff)


def _diff_lines(text: str) -> List[str]:
    lines = text.splitlines() or [text]
    wrapped: List[str] = []
    for line in lines:
        if len(line) <= DIFF_WRAP_WIDTH:
            wrapped.append(line)
        else:
            wrapped.extend(textwrap.wrap(line, width=DIFF_WRAP_WIDTH) or [""])
    return wrapped


def _blank_metadata_entry(
    target_version: str,
    target_index: int,
    target: TargetPrompt,
    *,
    match_kind: str,
    status: str,
    reason: str,
    confidence: float = 0.0,
    competing: Optional[Sequence[ScoredCandidate]] = None,
) -> Dict[str, Any]:
    return {
        "targetVersion": target_version,
        "targetIndex": target_index,
        "status": status,
        "proposedId": None,
        "proposedName": None,
        "proposedDescription": None,
        "proposedIdentifierMap": None,
        "sourceVersion": None,
        "sourcePromptVersion": None,
        "sourcePath": None,
        "sourceIndex": None,
        "confidence": round(confidence, 6),
        "matchKind": match_kind,
        "reason": reason,
        "identifierSequence": list(target.identifiers),
        "targetLength": len(target.normalized_text),
        "sourceLength": None,
        "firstHeading": target.first_heading,
        "diffExcerpt": "",
        "competingCandidates": [
            _candidate_summary(candidate)
            for candidate in _unique_candidates_by_id(competing or [])
        ],
    }


def _metadata_entry(
    target_version: str,
    target_index: int,
    target: TargetPrompt,
    candidate: ScoredCandidate,
    *,
    status: str,
    reason: str,
    competing: Optional[Sequence[ScoredCandidate]] = None,
) -> Dict[str, Any]:
    history = candidate.history
    return {
        "targetVersion": target_version,
        "targetIndex": target_index,
        "status": status,
        "proposedId": history.prompt_id,
        "proposedName": history.prompt_name,
        "proposedDescription": history.prompt.get("description", ""),
        "proposedIdentifierMap": history.prompt.get("identifierMap", {}),
        "sourceVersion": history.source_version,
        "sourcePromptVersion": history.prompt.get("version"),
        "sourcePath": str(history.source_path),
        "sourceIndex": history.source_index,
        "confidence": round(candidate.score, 6),
        "matchKind": candidate.match_kind,
        "reason": reason,
        "identifierSequence": list(target.identifiers),
        "targetLength": len(target.normalized_text),
        "sourceLength": len(history.normalized_text),
        "firstHeading": target.first_heading,
        "diffExcerpt": _diff_excerpt(history.display_text, target.display_text),
        "competingCandidates": [
            _candidate_summary(item)
            for item in _unique_candidates_by_id(competing or [])
            if item.history.prompt_id != history.prompt_id
        ],
    }


def _unique_candidates_by_id(candidates: Sequence[ScoredCandidate]) -> List[ScoredCandidate]:
    by_id: Dict[str, ScoredCandidate] = {}
    for candidate in candidates:
        prompt_id = candidate.history.prompt_id
        current = by_id.get(prompt_id)
        if current is None or (
            candidate.score,
            _source_rank(candidate.history),
        ) > (
            current.score,
            _source_rank(current.history),
        ):
            by_id[prompt_id] = candidate
    return sorted(by_id.values(), key=lambda item: (-item.score, item.history.prompt_id))


def _compatible_heading(target: TargetPrompt, history: HistoryPrompt) -> bool:
    return bool(target.first_heading and target.first_heading == history.first_heading)


def _fuzzy_candidates(
    target: TargetPrompt,
    histories: Sequence[HistoryPrompt],
) -> List[ScoredCandidate]:
    candidates: List[ScoredCandidate] = []
    for history in histories:
        if not _compatible_heading(target, history):
            continue
        if _length_ratio(target.normalized_text, history.normalized_text) < MIN_LENGTH_RATIO:
            continue
        score = difflib.SequenceMatcher(
            None,
            target.normalized_text,
            history.normalized_text,
            autojunk=False,
        ).ratio()
        if score >= REPORT_SIMILARITY_FLOOR:
            candidates.append(ScoredCandidate(history, score, "fuzzy"))
    return candidates


def _target_prompt(prompt: Prompt, index: int, target_version: str) -> TargetPrompt:
    display_text = _display_text(prompt, target_version)
    return TargetPrompt(
        prompt=prompt,
        target_index=index,
        normalized_text=normalize_prompt_text(prompt, target_version),
        display_text=display_text,
        first_heading=_first_heading(display_text),
        identifiers=_identifiers(prompt),
    )


def suggest_candidates(
    target_data: PromptCatalog,
    target_path: Path,
    history_dir: Path,
    catalog_dir: Path,
    apply_confidence: float = 0.98,
) -> Dict[str, Any]:
    target_version = str(target_data["version"])
    histories = load_history_prompts(history_dir, catalog_dir, target_path, target_version)
    exact_index: DefaultDict[Tuple[str, Identifiers], List[HistoryPrompt]] = defaultdict(list)
    by_identifiers: DefaultDict[Identifiers, List[HistoryPrompt]] = defaultdict(list)
    by_identifier_heading: DefaultDict[
        Tuple[Identifiers, str],
        List[HistoryPrompt],
    ] = defaultdict(list)

    for history in histories:
        exact_index[(history.normalized_text, history.identifiers)].append(history)
        by_identifiers[history.identifiers].append(history)
        if history.first_heading:
            by_identifier_heading[(history.identifiers, history.first_heading)].append(history)

    entries = []
    prompts = target_data.get("prompts", [])
    for index, prompt in enumerate(prompts):
        if not isinstance(prompt, dict) or not _is_unnamed(prompt):
            continue
        target = _target_prompt(prompt, index, target_version)
        exact_histories = exact_index.get((target.normalized_text, target.identifiers), [])
        exact_candidates = [
            ScoredCandidate(history, 1.0, "exact")
            for history in exact_histories
        ]
        unique_exact = _unique_candidates_by_id(exact_candidates)

        if len(unique_exact) == 1:
            entries.append(
                _metadata_entry(
                    target_version,
                    index,
                    target,
                    unique_exact[0],
                    status="auto_applicable",
                    reason="Exact normalized text and identifier sequence match a single historical prompt ID.",
                )
            )
            continue

        if len(unique_exact) > 1:
            entries.append(
                _blank_metadata_entry(
                    target_version,
                    index,
                    target,
                    match_kind="ambiguous_exact",
                    status="review_only",
                    reason="Exact normalized text matched multiple historical prompt IDs.",
                    confidence=1.0,
                    competing=unique_exact,
                )
            )
            continue

        fuzzy_histories = by_identifier_heading.get(
            (target.identifiers, target.first_heading),
            by_identifiers.get(target.identifiers, []),
        )
        fuzzy = _fuzzy_candidates(target, fuzzy_histories)
        unique_fuzzy = _unique_candidates_by_id(fuzzy)
        if not unique_fuzzy:
            entries.append(
                _blank_metadata_entry(
                    target_version,
                    index,
                    target,
                    match_kind="none",
                    status="no_candidate",
                    reason="No historical prompt passed identifier, heading, length, and similarity checks.",
                )
            )
            continue

        best = _best_source(unique_fuzzy)
        if len(unique_fuzzy) > 1:
            entries.append(
                _metadata_entry(
                    target_version,
                    index,
                    target,
                    best,
                    status="review_only",
                    reason="Fuzzy matching found competing historical prompt IDs.",
                    competing=unique_fuzzy,
                )
            )
            continue

        status = "auto_applicable" if best.score >= apply_confidence else "review_only"
        reason = (
            "Fuzzy match passed threshold with same identifier sequence, compatible heading, and no competing prompt ID."
            if status == "auto_applicable"
            else "Fuzzy match passed report checks but is below the auto-apply confidence threshold."
        )
        entries.append(
            _metadata_entry(
                target_version,
                index,
                target,
                best,
                status=status,
                reason=reason,
            )
        )

    summary = _summary(prompts, histories, entries)
    return {
        "target": str(target_path),
        "targetVersion": target_version,
        "historyDir": str(history_dir),
        "catalogDir": str(catalog_dir),
        "applyConfidence": apply_confidence,
        "summary": summary,
        "candidates": entries,
    }


def _summary(
    prompts: Sequence[Any],
    histories: Sequence[HistoryPrompt],
    entries: Sequence[Dict[str, Any]],
) -> Dict[str, int]:
    statuses = defaultdict(int)
    for entry in entries:
        statuses[entry["status"]] += 1
    return {
        "targetPrompts": len(prompts),
        "unnamedPrompts": len(entries),
        "historyPrompts": len(histories),
        "autoApplicable": statuses["auto_applicable"],
        "reviewOnly": statuses["review_only"],
        "noCandidate": statuses["no_candidate"],
    }


def write_json(path: Path, data: PromptCatalog) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def seed_catalog_from_report(target_data: PromptCatalog, report: PromptCatalog) -> PromptCatalog:
    seed = copy.deepcopy(target_data)
    prompts = seed.get("prompts", [])
    for entry in report.get("candidates", []):
        if entry.get("status") != "auto_applicable":
            continue
        index = entry.get("targetIndex")
        if not isinstance(index, int) or index < 0 or index >= len(prompts):
            continue
        prompt = prompts[index]
        prompt["id"] = entry.get("proposedId") or ""
        prompt["name"] = entry.get("proposedName") or ""
        prompt["description"] = entry.get("proposedDescription") or ""
        prompt["identifierMap"] = entry.get("proposedIdentifierMap") or {}
        prompt["version"] = entry.get("sourcePromptVersion") or entry.get("sourceVersion")
    return seed


def write_validated_catalog(path: Path, data: PromptCatalog, expected_version: str) -> None:
    validate_prompt_data(data, expected_version)
    write_json(path, data)
    validate_prompt_data(_load_json(path), expected_version)


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Suggest safe metadata candidates for unnamed prompt catalog entries."
    )
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path, default=Path("prompts"))
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path("vendor/tweakcc/data/prompts"),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--write-seed", type=Path)
    parser.add_argument(
        "--update-target",
        action="store_true",
        help="Apply auto-applicable metadata candidates back to --target after writing the report.",
    )
    parser.add_argument(
        "--fail-on-review-needed",
        action="store_true",
        help="Exit non-zero when any unnamed prompt still has a review-only metadata candidate.",
    )
    parser.add_argument("--apply-confidence", type=float, default=0.98)
    args = parser.parse_args(argv)
    if not 0.0 <= args.apply_confidence <= 1.0:
        parser.error("--apply-confidence must be between 0 and 1")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    target_version, target_data = load_target(args.target)
    if target_data["version"] != target_version:
        raise AssertionError("unreachable version mismatch")

    report = suggest_candidates(
        target_data,
        args.target,
        args.history_dir,
        args.catalog_dir,
        apply_confidence=args.apply_confidence,
    )
    write_json(args.out, report)

    updated_catalog = None
    if args.write_seed:
        updated_catalog = seed_catalog_from_report(target_data, report)
        write_validated_catalog(args.write_seed, updated_catalog, target_version)

    if args.update_target:
        if updated_catalog is None:
            updated_catalog = seed_catalog_from_report(target_data, report)
        write_validated_catalog(args.target, updated_catalog, target_version)

    summary = report["summary"]
    print(
        "[+] {version}: {auto} auto-applicable, {review} review-only, {none} no candidate -> {out}".format(
            version=target_version,
            auto=summary["autoApplicable"],
            review=summary["reviewOnly"],
            none=summary["noCandidate"],
            out=args.out,
        )
    )
    if args.write_seed:
        print(f"[+] wrote seed candidate catalog -> {args.write_seed}")
    if args.update_target:
        print(f"[+] updated target catalog with auto-applicable candidates -> {args.target}")
    if args.fail_on_review_needed and summary["reviewOnly"]:
        print(
            f"[!] {target_version}: {summary['reviewOnly']} prompt metadata candidates need review",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
