from __future__ import annotations

from violation_section_ledger import (
    SECTION_COVERED,
    SECTION_EXPIRING_NO_MR,
    SECTION_EXPIRING_SOON,
    SECTION_NO_EXCEPTION,
    SECTION_OPEN_MR,
    AtomicViolationIdentity,
    build_violation_section_ledger,
    section_marker,
    violations_absent_from_latest,
)


def _coverage(*violations):
    return {"violations": list(violations)}


def _item(rule, component, *, covered=(), uncovered=(), merge_requests=(), coverage="not_covered"):
    return {
        "rule": rule,
        "all_components": sorted(set(covered) | set(uncovered)),
        "covered_components": list(covered),
        "uncovered_components": list(uncovered),
        "open_merge_requests": list(merge_requests),
        "coverage": coverage,
    }


def test_atomic_identity_preserves_full_code_and_semantic_detail():
    ledger = build_violation_section_ledger(
        [{
            "code": "rpm_repos.ids_known",
            "full_violation_code": "rpm_repos.ids_known:ubi-9",
            "component_name": "component-a",
            "semantic_detail": "ubi-9",
        }],
        _coverage(_item("rpm_repos.ids_known", "component-a", uncovered=("component-a",))),
    )

    identity = next(iter(ledger.entries))
    assert identity == AtomicViolationIdentity(
        "rpm_repos.ids_known", "rpm_repos.ids_known:ubi-9", "component-a", "ubi-9"
    )
    assert ledger.entries[identity].owner == SECTION_NO_EXCEPTION
    assert ledger.entries[identity].status == "TODO"


def test_policy_covered_identity_has_one_done_owner():
    ledger = build_violation_section_ledger(
        [{"code": "rule.a", "component_name": "component-a"}],
        _coverage(_item("rule.a", "component-a", covered=("component-a",), coverage="fully_covered")),
    )

    entry = next(iter(ledger.entries.values()))
    assert entry.owner == SECTION_COVERED
    assert entry.status == "DONE"
    assert ledger.entries_for(SECTION_COVERED) == [entry]


def test_open_merge_request_remains_todo_even_when_it_has_coverage_data():
    ledger = build_violation_section_ledger(
        [{"code": "rule.a", "component_name": "component-a"}],
        _coverage(
            _item(
                "rule.a",
                "component-a",
                uncovered=("component-a",),
                merge_requests=[{"mr_components": ["component-a"], "effective_until": "2099-01-01"}],
            )
        ),
        upcoming_release_date="2026-09-01",
    )

    entry = next(iter(ledger.entries.values()))
    assert entry.owner == SECTION_OPEN_MR
    assert entry.status == "TODO"


def test_missing_coverage_and_release_data_are_todo_not_done():
    ledger = build_violation_section_ledger(
        [{"code": "rule.a", "component_name": "component-a"}],
        {},
    )

    entry = next(iter(ledger.entries.values()))
    assert entry.status == "TODO"
    assert "coverage input is missing" in entry.evidence


def test_unknown_coverage_status_is_todo_even_when_component_list_claims_coverage():
    ledger = build_violation_section_ledger(
        [{"code": "rule.a", "component_name": "component-a"}],
        _coverage(_item("rule.a", "component-a", covered=("component-a",), coverage="unknown")),
    )

    entry = next(iter(ledger.entries.values()))
    assert entry.status == "TODO"
    assert "coverage status is unknown" in entry.evidence


def test_duplicate_source_rows_collapse_but_different_details_do_not():
    records = [
        {"code": "rule.a", "full_violation_code": "rule.a:x", "component_name": "component-a", "semantic_detail": "x"},
        {"code": "rule.a", "full_violation_code": "rule.a:x", "component_name": "component-a", "semantic_detail": "x"},
        {"code": "rule.a", "full_violation_code": "rule.a:y", "component_name": "component-a", "semantic_detail": "y"},
    ]
    ledger = build_violation_section_ledger(records, _coverage(_item("rule.a", "component-a", uncovered=("component-a",))))
    assert len(ledger.entries) == 2
    assert len(ledger.owned_identities) == len(ledger.source_identities)


def test_section_marker_is_stable():
    assert section_marker("tooling") == "<!-- conforma-section: tooling -->"


def test_latest_comparison_preserves_component_and_detail_identity():
    primary = [
        {
            "type": "violation",
            "code": "rule.a",
            "full_violation_code": "rule.a:x",
            "component_name": "component-a",
            "semantic_detail": "x",
        },
        {
            "type": "violation",
            "code": "rule.a",
            "full_violation_code": "rule.a:x",
            "component_name": "component-b",
            "semantic_detail": "x",
        },
        {
            "type": "violation",
            "code": "rule.a",
            "full_violation_code": "rule.a:y",
            "component_name": "component-a",
            "semantic_detail": "y",
        },
    ]
    latest = [primary[0]]

    assert violations_absent_from_latest(primary, latest) == [
        AtomicViolationIdentity("rule.a", "rule.a:x", "component-b", "x"),
        AtomicViolationIdentity("rule.a", "rule.a:y", "component-a", "y"),
    ]


def test_overlapping_expiry_memberships_are_secondary_references():
    ledger = build_violation_section_ledger(
        [{"code": "rule.a", "component_name": "component-a"}],
        _coverage(
            {
                **_item("rule.a", "component-a", covered=("component-a",), coverage="fully_covered"),
                "exception_expiry": {
                    "earliest_expiry": "2026-08-01",
                    "expiring_within_14_days": True,
                },
            }
        ),
        upcoming_release_date="2026-09-01",
    )

    entry = next(iter(ledger.entries.values()))
    assert entry.owner == SECTION_COVERED
    assert entry.secondary_references == {SECTION_EXPIRING_SOON, SECTION_EXPIRING_NO_MR}


def test_validation_rejects_duplicate_owner_records():
    identity = AtomicViolationIdentity("rule.a", "rule.a", "component-a", "")
    ledger = build_violation_section_ledger(
        [{"code": "rule.a", "component_name": "component-a"}],
        _coverage(_item("rule.a", "component-a", uncovered=("component-a",))),
    )
    ledger.entries[identity].secondary_references.add("duplicate-owner-test")
    ledger.validate()
    assert ledger.entries[identity].owner == SECTION_NO_EXCEPTION
