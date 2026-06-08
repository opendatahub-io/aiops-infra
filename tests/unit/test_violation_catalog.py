"""Validate the structure of skills/references/violation-catalog.yaml.

Ensures all entries have required fields, valid enums, and consistent references.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_PATH = REPO_ROOT / "skills" / "references" / "violation-catalog.yaml"

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
