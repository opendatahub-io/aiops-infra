"""Tests for conforma-exception create_jira_ticket.py template helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import create_jira_ticket as cjt


class TestLoadTemplates:
    def test_load_templates_returns_categories_and_justifications(self):
        data = cjt._load_templates()
        assert "categories" in data
        assert "justifications" in data
        assert isinstance(data["categories"], dict)
        assert isinstance(data["justifications"], dict)

    def test_load_templates_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cjt, "_TEMPLATES_FILE", tmp_path / "missing.yaml")
        with pytest.raises(FileNotFoundError, match="Template file not found"):
            cjt._load_templates()


class TestListTemplateCategories:
    def test_returns_list_with_expected_keys(self):
        categories = cjt.list_template_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0
        first = categories[0]
        assert "id" in first
        assert "display_name" in first
        assert "matches_rules" in first
        assert "applicable_justifications" in first

    def test_includes_hermetic_build_category(self):
        ids = {c["id"] for c in cjt.list_template_categories()}
        assert "hermetic_build" in ids


class TestListJustifications:
    def test_returns_list_with_expected_keys(self):
        justifications = cjt.list_justifications()
        assert isinstance(justifications, list)
        assert len(justifications) > 0
        first = justifications[0]
        assert "id" in first
        assert "display_name" in first

    def test_includes_dev_preview(self):
        ids = {j["id"] for j in cjt.list_justifications()}
        assert "dev_preview" in ids


class TestMatchTemplateCategory:
    def test_matches_hermetic_rule(self):
        assert cjt.match_template_category("hermetic_task.hermetic") == "hermetic_build"

    def test_matches_glob_pattern(self):
        assert cjt.match_template_category("sbom_spdx.allowed_package_sources:foo") == ("sbom_package_sources")

    def test_unknown_rule_falls_back_to_other(self):
        assert cjt.match_template_category("totally.unknown.rule.xyz") == "other"


class TestLookupRuleInCatalog:
    def test_finds_known_rule(self):
        entry = cjt.lookup_rule_in_catalog("hermetic_task.hermetic")
        assert entry is not None
        assert entry["code"] == "hermetic_task.hermetic"
        assert "name" in entry
        assert "docs" in entry

    def test_colon_suffixed_rule_matches_base_code(self):
        entry = cjt.lookup_rule_in_catalog("rpm_signature.allowed:abc123")
        assert entry is not None
        assert entry["code"] == "rpm_signature.allowed"

    def test_unknown_rule_returns_none(self):
        assert cjt.lookup_rule_in_catalog("nonexistent.rule.code") is None

    def test_missing_catalog_returns_none(self):
        with patch("pathlib.Path.is_file", return_value=False):
            assert cjt.lookup_rule_in_catalog("hermetic_task.hermetic") is None


class TestResolveTemplate:
    def test_resolves_hermetic_build_with_variables(self):
        variables = {
            "rule": "hermetic_task.hermetic",
            "components": "odh-mlflow-v3-3",
            "component_count": "1",
            "versions": "rhoai-3.3",
            "version_count": "1",
            "remediation_plan_url": "https://redhat.atlassian.net/browse/RHOAIENG-1",
        }
        result = cjt.resolve_template("hermetic_build", variables, justification_id="dev_preview")
        assert "summary_context" in result
        assert "scope" in result
        assert "risk" in result
        assert "remediation" in result
        assert "impact" in result
        assert "odh-mlflow-v3-3" in result["scope"]
        assert "RHOAIENG-1" in result["remediation"]

    def test_uses_first_applicable_justification_by_default(self):
        variables = {
            "rule": "hermetic_task.hermetic",
            "components": "odh-mlflow-v3-3",
            "component_count": "1",
            "versions": "rhoai-3.3",
            "version_count": "1",
            "remediation_plan_url": "https://example.com/plan",
        }
        result = cjt.resolve_template("hermetic_build", variables)
        assert result["risk"]
        assert result["remediation"]

    def test_unknown_category_raises(self):
        with pytest.raises(ValueError, match="Unknown template category"):
            cjt.resolve_template("nonexistent_category", {})


class TestBuildExceptionLabel:
    def test_uses_first_component(self):
        label = cjt.build_exception_label(
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3", "odh-dashboard-v3-3"],
        )
        assert label == "Exception - hermetic_task.hermetic:odh-mlflow-v3-3"

    def test_empty_components_uses_unknown(self):
        label = cjt.build_exception_label("hermetic_task.hermetic", [])
        assert label == "Exception - hermetic_task.hermetic:unknown"


class TestBuildProvenanceFooter:
    def test_includes_repo_and_user(self):
        with (
            patch("create_jira_ticket.getpass.getuser", return_value="testuser"),
            patch("create_jira_ticket.platform.node", return_value="testhost"),
        ):
            footer = cjt.build_provenance_footer()
        assert "---" in footer
        assert cjt.PROVENANCE_REPO in footer
        assert "conforma-exception" in footer
        assert "testuser@testhost" in footer
