import json
from pathlib import Path

from tools import suggest_prompt_metadata


def prompt(
    text,
    *,
    name="",
    prompt_id="",
    description="",
    identifiers=None,
    identifier_map=None,
    version="2.1.9",
):
    identifiers = [] if identifiers is None else identifiers
    identifier_map = {} if identifier_map is None else identifier_map
    return {
        "name": name,
        "id": prompt_id,
        "description": description,
        "pieces": [text],
        "identifiers": identifiers,
        "identifierMap": identifier_map,
        "version": version,
    }


def named_prompt(prompt_id, text, *, name=None, identifiers=None, version="2.1.9"):
    return prompt(
        text,
        name=name or f"Prompt {prompt_id}",
        prompt_id=prompt_id,
        description=f"Description for {prompt_id}.",
        identifiers=identifiers,
        identifier_map={"0": "VALUE"} if identifiers else {},
        version=version,
    )


def write_catalog(path, version, prompts):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": version, "prompts": prompts}, indent=2) + "\n",
        encoding="utf-8",
    )


def run_report(tmp_path, target_prompts, history_prompts, *, apply_confidence=0.98):
    target = tmp_path / "prompts" / "2.1.10.json"
    vendor = tmp_path / "vendor"
    write_catalog(target, "2.1.10", target_prompts)
    write_catalog(vendor / "prompts-2.1.9.json", "2.1.9", history_prompts)
    target_version, target_data = suggest_prompt_metadata.load_target(target)
    assert target_version == "2.1.10"
    return suggest_prompt_metadata.suggest_candidates(
        target_data,
        target,
        tmp_path / "prompts",
        vendor,
        apply_confidence=apply_confidence,
    )


def report_entry(report):
    assert len(report["candidates"]) == 1
    return report["candidates"][0]


def fuzzy_text(suffix):
    return "## Shared Heading\n" + (
        "You should always follow the same stable workflow. " * 40
    ) + suffix


def test_exact_normalized_match_is_auto_applicable(tmp_path):
    text = "You should always follow instructions for version <<CCVERSION>>."
    report = run_report(
        tmp_path,
        [prompt(text, version="2.1.10")],
        [named_prompt("system-example", text)],
    )

    entry = report_entry(report)
    assert entry["status"] == "auto_applicable"
    assert entry["matchKind"] == "exact"
    assert entry["proposedId"] == "system-example"
    assert entry["confidence"] == 1.0
    assert report["summary"]["autoApplicable"] == 1


def test_js_escape_equivalent_match_is_auto_applicable(tmp_path):
    report = run_report(
        tmp_path,
        [prompt("Use \\u0041 mode. You should always keep this stable.")],
        [named_prompt("escaped-example", "Use A mode. You should always keep this stable.")],
    )

    entry = report_entry(report)
    assert entry["status"] == "auto_applicable"
    assert entry["matchKind"] == "exact"
    assert entry["proposedId"] == "escaped-example"


def test_fuzzy_match_with_same_identifiers_and_heading_is_auto_applicable(tmp_path):
    report = run_report(
        tmp_path,
        [prompt(fuzzy_text("Target ending."), identifiers=[0, 1])],
        [named_prompt("fuzzy-example", fuzzy_text("Source ending."), identifiers=[0, 1])],
    )

    entry = report_entry(report)
    assert entry["status"] == "auto_applicable"
    assert entry["matchKind"] == "fuzzy"
    assert entry["proposedId"] == "fuzzy-example"
    assert entry["confidence"] >= 0.98
    assert "same identifier sequence" in entry["reason"]


def test_fuzzy_match_rejects_identifier_mismatch(tmp_path):
    text = fuzzy_text("Shared ending.")
    report = run_report(
        tmp_path,
        [prompt(text, identifiers=[0, 1])],
        [named_prompt("wrong-identifiers", text, identifiers=[0])],
    )

    entry = report_entry(report)
    assert entry["status"] == "no_candidate"
    assert entry["matchKind"] == "none"


def test_fuzzy_match_rejects_bad_length_ratio(tmp_path):
    report = run_report(
        tmp_path,
        [prompt(fuzzy_text("Short target."))],
        [named_prompt("too-long", fuzzy_text("Much longer. ") + ("Extra text. " * 200))],
    )

    entry = report_entry(report)
    assert entry["status"] == "no_candidate"
    assert entry["matchKind"] == "none"


def test_ambiguous_exact_match_is_review_only(tmp_path):
    text = "You should always keep this exact text stable."
    report = run_report(
        tmp_path,
        [prompt(text)],
        [
            named_prompt("first-id", text, name="First prompt"),
            named_prompt("second-id", text, name="Second prompt"),
        ],
    )

    entry = report_entry(report)
    assert entry["status"] == "review_only"
    assert entry["matchKind"] == "ambiguous_exact"
    assert entry["proposedId"] is None
    assert {item["id"] for item in entry["competingCandidates"]} == {
        "first-id",
        "second-id",
    }


def test_competing_fuzzy_candidates_are_review_only(tmp_path):
    report = run_report(
        tmp_path,
        [prompt(fuzzy_text("Target ending."))],
        [
            named_prompt("first-id", fuzzy_text("Source ending one.")),
            named_prompt("second-id", fuzzy_text("Source ending two.")),
        ],
    )

    entry = report_entry(report)
    assert entry["status"] == "review_only"
    assert entry["matchKind"] == "fuzzy"
    assert entry["proposedId"] in {"first-id", "second-id"}
    assert entry["competingCandidates"]


def test_report_only_mode_does_not_write_seed(tmp_path):
    target = tmp_path / "prompts" / "2.1.10.json"
    vendor = tmp_path / "vendor"
    out = tmp_path / "nested" / "report.json"
    seed = tmp_path / "seed.json"
    text = "You should always keep this metadata candidate."
    write_catalog(target, "2.1.10", [prompt(text, version="2.1.10")])
    write_catalog(vendor / "prompts-2.1.9.json", "2.1.9", [named_prompt("candidate", text)])

    status = suggest_prompt_metadata.main(
        [
            "--target",
            str(target),
            "--history-dir",
            str(tmp_path / "prompts"),
            "--catalog-dir",
            str(vendor),
            "--out",
            str(out),
        ]
    )

    assert status == 0
    assert out.exists()
    assert not seed.exists()


def test_seed_mode_writes_only_auto_applicable_metadata_and_preserves_pieces(tmp_path):
    target = tmp_path / "prompts" / "2.1.10.json"
    vendor = tmp_path / "vendor"
    out = tmp_path / "report.json"
    seed = tmp_path / "seed" / "2.1.10.json"
    exact_text = "You should always keep this exact candidate."
    ambiguous_text = "You should always leave ambiguous text for review."
    unmatched_text = "You should always leave unmatched text unnamed."
    write_catalog(
        target,
        "2.1.10",
        [
            prompt(exact_text, version="2.1.10"),
            prompt(ambiguous_text, version="2.1.10"),
            prompt(unmatched_text, version="2.1.10"),
        ],
    )
    write_catalog(
        vendor / "prompts-2.1.9.json",
        "2.1.9",
        [
            named_prompt("exact-id", exact_text),
            named_prompt("ambiguous-a", ambiguous_text),
            named_prompt("ambiguous-b", ambiguous_text),
        ],
    )

    status = suggest_prompt_metadata.main(
        [
            "--target",
            str(target),
            "--history-dir",
            str(tmp_path / "prompts"),
            "--catalog-dir",
            str(vendor),
            "--out",
            str(out),
            "--write-seed",
            str(seed),
        ]
    )

    assert status == 0
    data = json.loads(seed.read_text(encoding="utf-8"))
    assert data["prompts"][0]["id"] == "exact-id"
    assert data["prompts"][0]["pieces"] == [exact_text]
    assert data["prompts"][1]["id"] == ""
    assert data["prompts"][1]["pieces"] == [ambiguous_text]
    assert data["prompts"][2]["id"] == ""
    assert data["prompts"][2]["pieces"] == [unmatched_text]


def test_update_target_applies_auto_metadata_in_place(tmp_path):
    target = tmp_path / "prompts" / "2.1.10.json"
    vendor = tmp_path / "vendor"
    out = tmp_path / "report.json"
    exact_text = "You should always update this target in place."
    ambiguous_text = "You should always leave this ambiguous target unnamed."
    write_catalog(
        target,
        "2.1.10",
        [
            prompt(exact_text, version="2.1.10"),
            prompt(ambiguous_text, version="2.1.10"),
        ],
    )
    write_catalog(
        vendor / "prompts-2.1.9.json",
        "2.1.9",
        [
            named_prompt("exact-id", exact_text),
            named_prompt("ambiguous-a", ambiguous_text),
            named_prompt("ambiguous-b", ambiguous_text),
        ],
    )

    status = suggest_prompt_metadata.main(
        [
            "--target",
            str(target),
            "--history-dir",
            str(tmp_path / "prompts"),
            "--catalog-dir",
            str(vendor),
            "--out",
            str(out),
            "--update-target",
        ]
    )

    assert status == 0
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["prompts"][0]["id"] == "exact-id"
    assert data["prompts"][0]["pieces"] == [exact_text]
    assert data["prompts"][1]["id"] == ""
    assert data["prompts"][1]["pieces"] == [ambiguous_text]
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["summary"]["autoApplicable"] == 1
    assert report["summary"]["reviewOnly"] == 1


def test_fail_on_review_needed_blocks_review_only_candidates(tmp_path, capsys):
    target = tmp_path / "prompts" / "2.1.10.json"
    vendor = tmp_path / "vendor"
    out = tmp_path / "report.json"
    text = "You should always leave this ambiguous target for review."
    write_catalog(target, "2.1.10", [prompt(text, version="2.1.10")])
    write_catalog(
        vendor / "prompts-2.1.9.json",
        "2.1.9",
        [
            named_prompt("first-id", text),
            named_prompt("second-id", text),
        ],
    )

    status = suggest_prompt_metadata.main(
        [
            "--target",
            str(target),
            "--history-dir",
            str(tmp_path / "prompts"),
            "--catalog-dir",
            str(vendor),
            "--out",
            str(out),
            "--fail-on-review-needed",
        ]
    )

    assert status == 1
    assert out.exists()
    captured = capsys.readouterr()
    assert "1 prompt metadata candidates need review" in captured.err


def test_cli_returns_useful_json_and_creates_parent_output_dirs(tmp_path, capsys):
    target = tmp_path / "prompts" / "2.1.10.json"
    vendor = tmp_path / "vendor"
    out = tmp_path / "a" / "b" / "report.json"
    text = "You should always write a useful CLI report."
    write_catalog(target, "2.1.10", [prompt(text, version="2.1.10")])
    write_catalog(vendor / "prompts-2.1.9.json", "2.1.9", [named_prompt("cli-id", text)])

    status = suggest_prompt_metadata.main(
        [
            "--target",
            str(target),
            "--history-dir",
            str(tmp_path / "prompts"),
            "--catalog-dir",
            str(vendor),
            "--out",
            str(out),
        ]
    )

    assert status == 0
    printed = capsys.readouterr().out
    assert "auto-applicable" in printed
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["targetVersion"] == "2.1.10"
    assert data["summary"]["autoApplicable"] == 1
    assert data["candidates"][0]["proposedId"] == "cli-id"


def test_update_prompts_workflow_applies_suggested_metadata_to_changed_catalogs():
    workflow = Path(".github/workflows/update-prompts.yml").read_text(encoding="utf-8")

    assert "tools/suggest_prompt_metadata.py" in workflow
    assert "--update-target" in workflow
    assert "--fail-on-review-needed" in workflow
    assert "tests/test_suggest_prompt_metadata.py" in workflow
