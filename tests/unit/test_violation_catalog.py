"""Validate the structure of skills/references/violation-catalog.yaml.

Ensures all entries have required fields, valid enums, and consistent references.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = REPO_ROOT / "skills" / "references" / "violation-catalog.yaml"

sys.path.insert(0, str(REPO_ROOT / "tests"))
from check_no_internal_refs import FORBIDDEN_PATTERNS  # noqa: E402

VALID_TYPES = {"conforma_violation", "operational_issue"}
VALID_RESOLUTION_PATHS = {"code_fix", "operational", "exception_likely", "mixed"}
VALID_OWNERS = {"component_team", "devops", "konflux_team"}
VALID_EFFORTS = {"low", "medium", "high"}
VALID_ACTIONS = {"ignore"}


@pytest.fixture(scope="module")
def catalog():
    assert CATALOG_PATH.exists(), f"Catalog not found at {CATALOG_PATH}"
    with open(CATALOG_PATH) as f:
        return yaml.safe_load(f)


class TestCatalogTopLevel:
    def test_has_violations(self, catalog):
        assert "violations" in catalog
        assert isinstance(catalog["violations"], list)
        assert len(catalog["violations"]) > 0

    def test_has_known_false_alerts(self, catalog):
        assert "known_false_alerts" in catalog
        assert isinstance(catalog["known_false_alerts"], list)

    def test_has_metadata(self, catalog):
        assert "source_url" in catalog
        assert "last_synced_from_doc" in catalog


class TestViolationEntries:
    def test_all_have_required_fields(self, catalog):
        required = {"id", "type", "title", "description", "classification", "symptoms", "fix_steps"}
        for entry in catalog["violations"]:
            missing = required - set(entry.keys())
            assert not missing, f"Violation '{entry.get('id', '?')}' missing fields: {missing}"

    def test_valid_type_enum(self, catalog):
        for entry in catalog["violations"]:
            assert entry["type"] in VALID_TYPES, f"Violation '{entry['id']}' has invalid type '{entry['type']}'"

    def test_conforma_violations_have_rule_codes(self, catalog):
        for entry in catalog["violations"]:
            if entry["type"] == "conforma_violation":
                assert "conforma_rule_codes" in entry and len(entry["conforma_rule_codes"]) > 0, (
                    f"Conforma violation '{entry['id']}' must have non-empty conforma_rule_codes"
                )

    def test_valid_classification_fields(self, catalog):
        for entry in catalog["violations"]:
            cls = entry["classification"]
            assert cls["resolution_path"] in VALID_RESOLUTION_PATHS, (
                f"Violation '{entry['id']}' has invalid resolution_path '{cls['resolution_path']}'"
            )
            assert cls["typical_owner"] in VALID_OWNERS, (
                f"Violation '{entry['id']}' has invalid typical_owner '{cls['typical_owner']}'"
            )
            assert cls["estimated_effort"] in VALID_EFFORTS, (
                f"Violation '{entry['id']}' has invalid estimated_effort '{cls['estimated_effort']}'"
            )
            assert isinstance(cls["requires_rebuild"], bool), f"Violation '{entry['id']}' requires_rebuild must be bool"

    def test_unique_ids(self, catalog):
        ids = [e["id"] for e in catalog["violations"]]
        duplicates = [x for x in ids if ids.count(x) > 1]
        assert not duplicates, f"Duplicate violation IDs: {set(duplicates)}"

    def test_fix_steps_are_non_empty(self, catalog):
        for entry in catalog["violations"]:
            assert len(entry["fix_steps"]) > 0, f"Violation '{entry['id']}' has empty fix_steps"
            for step in entry["fix_steps"]:
                assert "action" in step, f"Violation '{entry['id']}' has a fix_step without 'action'"

    def test_symptoms_are_non_empty(self, catalog):
        for entry in catalog["violations"]:
            assert len(entry["symptoms"]) > 0, f"Violation '{entry['id']}' has empty symptoms"

    def test_aliases_are_list_if_present(self, catalog):
        for entry in catalog["violations"]:
            if "aliases" in entry:
                assert isinstance(entry["aliases"], list), f"Violation '{entry['id']}' aliases must be a list"

    def test_exception_context_has_category(self, catalog):
        for entry in catalog["violations"]:
            if "exception_context" in entry:
                ctx = entry["exception_context"]
                assert "when_to_exception" in ctx, (
                    f"Violation '{entry['id']}' exception_context missing when_to_exception"
                )
                assert "exception_template_category" in ctx, (
                    f"Violation '{entry['id']}' exception_context missing exception_template_category"
                )


class TestSymptomQuality:
    """Symptoms must match real violation messages — no placeholders, no too-short strings."""

    def test_no_placeholder_patterns_in_symptoms(self, catalog):
        import re
        placeholder = re.compile(r"\bX{3,}\b|\bY{3,}\b|\bZ{3,}\b", re.IGNORECASE)
        for entry in catalog["violations"]:
            for symptom in entry.get("symptoms", []):
                assert not placeholder.search(symptom), (
                    f"Violation '{entry['id']}' symptom has placeholder: '{symptom}'. "
                    "Use a generic fragment instead (e.g., 'did not complete successfully' "
                    "instead of 'Task \"XXXX\" did not complete successfully')."
                )

    def test_symptoms_meet_minimum_length(self, catalog):
        min_len = 10
        for entry in catalog["violations"]:
            for symptom in entry.get("symptoms", []):
                assert len(symptom) >= min_len, (
                    f"Violation '{entry['id']}' symptom too short ({len(symptom)} chars): "
                    f"'{symptom}'. Minimum is {min_len} for substring matching."
                )


class TestNoDuplicateAliases:
    """Each alias should map to exactly one violation — duplicates cause silent shadowing."""

    def test_no_duplicate_aliases_across_entries(self, catalog):
        alias_to_id = {}
        duplicates = []
        for entry in catalog["violations"]:
            for alias in entry.get("aliases", []):
                key = alias.lower()
                if key in alias_to_id:
                    duplicates.append(
                        f"alias '{alias}' in both '{alias_to_id[key]}' and '{entry['id']}'"
                    )
                alias_to_id[key] = entry["id"]
        assert not duplicates, (
            f"Duplicate aliases cause silent shadowing (first match wins): {duplicates}"
        )


class TestReferenceURLs:
    """Reference URLs must be public — no private repos or internal URLs."""

    def test_no_internal_urls_in_fix_steps(self, catalog):
        violations_with_internal = []
        for entry in catalog["violations"]:
            for step in entry.get("fix_steps", []):
                ref = step.get("reference", "")
                for pattern, desc in FORBIDDEN_PATTERNS:
                    if pattern.search(ref):
                        violations_with_internal.append(
                            f"'{entry['id']}' fix_step ref contains [{desc}]: {ref}"
                        )
        assert not violations_with_internal, (
            f"Internal URLs found in fix_steps (this is a public repo): {violations_with_internal}"
        )

    def test_no_internal_urls_in_false_alerts(self, catalog):
        alerts_with_internal = []
        for entry in catalog.get("known_false_alerts", []):
            ref = entry.get("reference", "")
            for pattern, desc in FORBIDDEN_PATTERNS:
                if pattern.search(ref):
                    alerts_with_internal.append(
                        f"'{entry['id']}' reference contains [{desc}]: {ref}"
                    )
        assert not alerts_with_internal, (
            f"Internal URLs found in known_false_alerts: {alerts_with_internal}"
        )

    def test_no_internal_urls_in_fallback_references(self, catalog):
        refs_with_internal = []
        for entry in catalog.get("fallback_references", []):
            ref = entry.get("reference", "")
            for pattern, desc in FORBIDDEN_PATTERNS:
                if pattern.search(ref):
                    refs_with_internal.append(
                        f"'{entry.get('code_prefix', '?')}' reference contains [{desc}]: {ref}"
                    )
        assert not refs_with_internal, (
            f"Internal URLs found in fallback_references: {refs_with_internal}"
        )


class TestRuleCodeShadowing:
    """When multiple entries share a conforma_rule_code, each must be reachable via unique id, symptoms, or aliases."""

    def test_shared_rule_codes_have_distinguishing_symptoms_or_aliases(self, catalog):
        from collections import defaultdict
        code_to_entries = defaultdict(list)
        for entry in catalog["violations"]:
            for code in entry.get("conforma_rule_codes", []):
                code_to_entries[code].append(entry)

        problems = []
        for code, entries in code_to_entries.items():
            if len(entries) <= 1:
                continue
            for entry in entries[1:]:
                has_unique_alias = bool(entry.get("aliases"))
                has_unique_symptom = bool(entry.get("symptoms"))
                unique_id = entry["id"] != code
                if not (has_unique_alias or has_unique_symptom or unique_id):
                    problems.append(
                        f"'{entry['id']}' shares rule_code '{code}' but has no unique "
                        "id, aliases, or symptoms to match via alternative paths"
                    )
        assert not problems, (
            f"Entries shadowed by rule_code matching with no alternative path: {problems}"
        )


class TestKnownFalseAlerts:
    def test_all_have_required_fields(self, catalog):
        required = {"id", "title", "description", "applies_to", "action", "condition"}
        for entry in catalog["known_false_alerts"]:
            missing = required - set(entry.keys())
            assert not missing, f"False alert '{entry.get('id', '?')}' missing fields: {missing}"

    def test_valid_action_enum(self, catalog):
        for entry in catalog["known_false_alerts"]:
            assert entry["action"] in VALID_ACTIONS, (
                f"False alert '{entry['id']}' has invalid action '{entry['action']}'"
            )

    def test_unique_ids(self, catalog):
        ids = [e["id"] for e in catalog["known_false_alerts"]]
        duplicates = [x for x in ids if ids.count(x) > 1]
        assert not duplicates, f"Duplicate false alert IDs: {set(duplicates)}"
