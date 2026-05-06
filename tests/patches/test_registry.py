"""Cross-patch invariants. Runs against the live registry; passes against
an empty registry too."""

from cc_extractor.patches._registry import REGISTRY
from cc_extractor.patches._pinned_default import DEFAULT_VERSION_RANGES
from cc_extractor.patches._versions import (
    SemverRangeError,
    parse_range,
    range_contains_range,
    resolve_range_to_version,
    version_in_range,
)


def test_no_duplicate_ids():
    assert len(REGISTRY) == len(set(REGISTRY.keys()))


def test_each_versions_supported_parses():
    for patch in REGISTRY.values():
        parse_range(patch.versions_supported)  # raises on invalid


def test_each_versions_tested_entry_parses():
    for patch in REGISTRY.values():
        for tested in patch.versions_tested:
            parse_range(tested)


def test_versions_tested_is_non_empty():
    for patch in REGISTRY.values():
        assert patch.versions_tested, f"{patch.id} has empty versions_tested"


def test_default_versions_do_not_auto_claim_newer_2_1_releases():
    assert not any(version_in_range("2.1.128", tested) for tested in DEFAULT_VERSION_RANGES)


def test_versions_tested_subset_of_versions_supported():
    for patch in REGISTRY.values():
        for tested in patch.versions_tested:
            assert range_contains_range(patch.versions_supported, tested), (
                f"{patch.id}: tested range {tested!r} not contained in "
                f"supported range {patch.versions_supported!r}"
            )


def test_blacklisted_versions_do_not_satisfy_tested():
    from cc_extractor.patches._versions import version_in_range
    for patch in REGISTRY.values():
        for blacklisted in patch.versions_blacklisted:
            for tested in patch.versions_tested:
                try:
                    in_range = version_in_range(blacklisted, tested)
                except SemverRangeError:
                    continue
                assert not in_range, (
                    f"{patch.id}: blacklisted version {blacklisted} satisfies "
                    f"tested range {tested!r}"
                )


def test_each_versions_tested_resolves_to_concrete_version():
    from cc_extractor.download_index import load_seed_download_index
    index = load_seed_download_index()
    if not index.get("binary", {}).get("versions"):
        return  # empty index: pre-flight succeeded; nothing else to assert
    for patch in REGISTRY.values():
        any_resolved = any(
            resolve_range_to_version(tested, index=index) is not None
            for tested in patch.versions_tested
        )
        assert any_resolved, (
            f"{patch.id}: no entry in versions_tested resolves to a concrete "
            f"version in the current download index"
        )
