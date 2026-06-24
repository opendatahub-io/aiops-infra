"""Tests for conforma_counting.py — violation counting model."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import conforma_counting


class TestCountFromRecords:
    """count_from_records deduplicates on (code, component, semantic_detail)."""

    def test_same_violation_different_images_collapses_to_one(self):
        records = [
            {"code": "hermetic_task.hermetic", "component_name": "comp-a", "semantic_detail": "", "full_violation_code": "hermetic_task.hermetic"},
            {"code": "hermetic_task.hermetic", "component_name": "comp-a", "semantic_detail": "", "full_violation_code": "hermetic_task.hermetic"},
            {"code": "hermetic_task.hermetic", "component_name": "comp-a", "semantic_detail": "", "full_violation_code": "hermetic_task.hermetic"},
        ]
        counts = conforma_counting.count_from_records(records)
        assert counts.violations == 1
        assert counts.image_occurrences == 3

    def test_different_semantic_details_are_different_violations(self):
        records = [
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-baseos-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/acl@1"},
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-appstream-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/glib@2"},
        ]
        counts = conforma_counting.count_from_records(records)
        assert counts.violations == 2
        assert counts.image_occurrences == 2

    def test_same_semantic_detail_different_full_codes_collapses(self):
        records = [
            {"code": "sbom_spdx.disallowed_package_attributes", "component_name": "comp-a", "semantic_detail": "hermeto:pip:package:binary=true", "full_violation_code": "sbom_spdx.disallowed_package_attributes:pkg:pypi/foo@1.0"},
            {"code": "sbom_spdx.disallowed_package_attributes", "component_name": "comp-a", "semantic_detail": "hermeto:pip:package:binary=true", "full_violation_code": "sbom_spdx.disallowed_package_attributes:pkg:pypi/bar@2.0"},
            {"code": "sbom_spdx.disallowed_package_attributes", "component_name": "comp-a", "semantic_detail": "hermeto:pip:package:binary=true", "full_violation_code": "sbom_spdx.disallowed_package_attributes:pkg:pypi/baz@3.0"},
        ]
        counts = conforma_counting.count_from_records(records)
        assert counts.violations == 1
        assert counts.full_violation_code_count == 3
        assert counts.image_occurrences == 3

    def test_by_component_rule_sums_to_violations(self):
        records = [
            {"code": "hermetic_task.hermetic", "component_name": "comp-a", "semantic_detail": "", "full_violation_code": "hermetic_task.hermetic"},
            {"code": "hermetic_task.hermetic", "component_name": "comp-a", "semantic_detail": "", "full_violation_code": "hermetic_task.hermetic"},
            {"code": "hermetic_task.hermetic", "component_name": "comp-b", "semantic_detail": "", "full_violation_code": "hermetic_task.hermetic"},
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-baseos-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/acl@1"},
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-appstream-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/glib@2"},
        ]
        counts = conforma_counting.count_from_records(records)
        assert counts.violations == 4
        assert sum(counts.by_component_rule.values()) == counts.violations
        assert counts.by_component_rule[("hermetic_task.hermetic", "comp-a")] == 1
        assert counts.by_component_rule[("hermetic_task.hermetic", "comp-b")] == 1
        assert counts.by_component_rule[("rpm_repos.ids_known", "comp-a")] == 2

    def test_works_with_dataclass_records(self):
        from dataclasses import dataclass

        @dataclass
        class Record:
            code: str
            component_name: str
            semantic_detail: str
            full_violation_code: str = ""

        records = [
            Record(code="hermetic_task.hermetic", component_name="comp-a", semantic_detail=""),
            Record(code="hermetic_task.hermetic", component_name="comp-a", semantic_detail=""),
        ]
        counts = conforma_counting.count_from_records(records)
        assert counts.violations == 1
        assert counts.image_occurrences == 2

    def test_empty_records(self):
        counts = conforma_counting.count_from_records([])
        assert counts.violations == 0
        assert counts.image_occurrences == 0
        assert counts.full_violation_code_count == 0
        assert counts.by_component_rule == {}

    def test_full_violation_code_count_tracks_policy_granularity(self):
        records = [
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-baseos-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/acl@1?repository_id=ubi-9-baseos-rpms"},
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-baseos-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/glib@2?repository_id=ubi-9-baseos-rpms"},
            {"code": "rpm_repos.ids_known", "component_name": "comp-a", "semantic_detail": "ubi-9-baseos-rpms", "full_violation_code": "rpm_repos.ids_known:pkg:rpm/dbus@3?repository_id=ubi-9-baseos-rpms"},
        ]
        counts = conforma_counting.count_from_records(records)
        assert counts.violations == 1
        assert counts.full_violation_code_count == 3


class TestViolationsForComponents:
    """violations_for_components looks up exact per-group counts."""

    def test_exact_lookup(self):
        by_component_rule = {
            ("hermetic_task.hermetic", "comp-a"): 1,
            ("hermetic_task.hermetic", "comp-b"): 1,
            ("sbom_spdx.allowed_package_sources", "comp-a"): 9,
        }
        result = conforma_counting.violations_for_components(
            "hermetic_task.hermetic",
            ["comp-a", "comp-b"],
            by_component_rule,
        )
        assert result == 2

    def test_sbom_multiple_violations_per_component(self):
        by_component_rule = {
            ("sbom_spdx.allowed_package_sources", "comp-a"): 9,
            ("sbom_spdx.allowed_package_sources", "comp-b"): 3,
        }
        result = conforma_counting.violations_for_components(
            "sbom_spdx.allowed_package_sources",
            ["comp-a", "comp-b"],
            by_component_rule,
        )
        assert result == 12

    def test_falls_back_to_base_code_lookup(self):
        by_component_rule = {
            ("rpm_signature.allowed", "comp-a"): 2,
        }
        result = conforma_counting.violations_for_components(
            "rpm_signature.allowed:9386b48a",
            ["comp-a"],
            by_component_rule,
        )
        assert result == 2

    def test_falls_back_to_one_when_not_found(self):
        result = conforma_counting.violations_for_components(
            "unknown_rule",
            ["comp-a", "comp-b"],
            {},
        )
        assert result == 2
