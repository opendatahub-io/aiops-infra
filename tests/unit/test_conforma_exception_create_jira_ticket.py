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
            "rhoaieng_jira_violation_url": "https://redhat.atlassian.net/browse/RHOAIENG-1",
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
            "rhoaieng_jira_violation_url": "https://example.com/plan",
        }
        result = cjt.resolve_template("hermetic_build", variables)
        assert result["risk"]
        assert result["remediation"]

    def test_unknown_category_raises(self):
        with pytest.raises(ValueError, match="Unknown template category"):
            cjt.resolve_template("nonexistent_category", {})


class TestBuildSummary:
    def test_approval_includes_components(self):
        result = cjt._build_summary(
            "RHOAIENG",
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3"],
            "rhoai-3.4",
            None,
            None,
        )
        assert result == "[Exception Approval] hermetic_task.hermetic - odh-mlflow-v3-3 - rhoai-3.4"

    def test_remediation_uses_code_fix_tag(self):
        result = cjt._build_summary(
            "RHOAIENG",
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3"],
            "rhoai-3.4",
            None,
            None,
            purpose="remediation",
        )
        assert result == "[Code Fix] hermetic_task.hermetic - odh-mlflow-v3-3 - rhoai-3.4"

    def test_multiple_components_truncated(self):
        comps = ["odh-a-v3-4", "odh-b-v3-4", "odh-c-v3-4", "odh-d-v3-4", "odh-e-v3-4"]
        result = cjt._build_summary("PSX", "rpm_signature.allowed", comps, "rhoai-3.4", None, None)
        assert "odh-a-v3-4, odh-b-v3-4, odh-c-v3-4 (+2 more)" in result

    def test_vendor_tag_prepended(self):
        result = cjt._build_summary(
            "PSX",
            "rpm_signature.allowed:abc",
            ["odh-vllm-cpu-v3-4"],
            "rhoai-3.4",
            "AMD RPM signing key exception",
            "AMD",
        )
        assert result.startswith("[AMD] [Exception Approval]")
        assert "odh-vllm-cpu-v3-4" in result
        assert "AMD RPM signing key exception" in result

    def test_summary_context_appended(self):
        result = cjt._build_summary(
            "RHOAIENG",
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3"],
            "rhoai-3.4",
            "hermetic build exception",
            None,
        )
        assert result.endswith("hermetic build exception")
        assert "odh-mlflow-v3-3" in result


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


class TestBuildPsxFilledAdf:
    """Verify _build_psx_filled_adf uses template-resolved text, not hardcoded."""

    def _extract_all_text(self, adf: dict) -> str:
        """Recursively extract all text from an ADF document."""
        texts = []
        for node in adf.get("content", []):
            for child in node.get("content", []):
                if child.get("type") == "text":
                    texts.append(child["text"])
        return "\n".join(texts)

    def test_no_rpm_signing_key_note_for_unrelated_rule(self):
        adf = cjt._build_psx_filled_adf(
            rule="test.no_failed_tests:deprecated-image-check",
            components=["odh-training-cuda121-v3-5-ea-1"],
            rhoai_version="rhoai-3.5-ea.1",
            effective_until="2026-12-31T00:00:00Z",
            rhoaieng_url="https://redhat.atlassian.net/browse/RHOAIENG-67567",
            exception_scope="Stage exception for deprecated-image-check",
        )
        all_text = self._extract_all_text(adf)
        assert "signing key" not in all_text.lower()
        assert "third-party signed RPMs" not in all_text

    def test_no_code_freeze_assumption_for_non_frozen_release(self):
        adf = cjt._build_psx_filled_adf(
            rule="hermetic_task.hermetic",
            components=["odh-mlflow-v3-5-ea-1"],
            rhoai_version="rhoai-3.5-ea.1",
            effective_until="2026-12-31T00:00:00Z",
            rhoaieng_url="https://redhat.atlassian.net/browse/RHOAIENG-12345",
            exception_scope="Non-hermetic build for odh-mlflow",
        )
        all_text = self._extract_all_text(adf)
        assert "code-frozen" not in all_text
        assert "z-stream/sub-releases" not in all_text

    def test_uses_provided_scope_in_reason(self):
        custom_scope = "Custom scope: GPU driver packages from AMD"
        adf = cjt._build_psx_filled_adf(
            rule="rpm_signature.allowed:abc123",
            components=["odh-vllm-cpu-v3-4"],
            rhoai_version="rhoai-3.4",
            effective_until="2026-10-10T00:00:00Z",
            rhoaieng_url="https://redhat.atlassian.net/browse/RHOAIENG-99999",
            exception_scope=custom_scope,
        )
        all_text = self._extract_all_text(adf)
        assert custom_scope in all_text

    def test_includes_rule_and_components_in_reason(self):
        adf = cjt._build_psx_filled_adf(
            rule="sbom_spdx.allowed_package_sources:foo",
            components=["odh-dashboard-v3-4", "odh-notebook-v3-4"],
            rhoai_version="rhoai-3.4",
            effective_until="2026-10-10T00:00:00Z",
            rhoaieng_url="https://redhat.atlassian.net/browse/RHOAIENG-11111",
        )
        all_text = self._extract_all_text(adf)
        assert "sbom_spdx.allowed_package_sources:foo" in all_text
        assert "odh-dashboard-v3-4" in all_text
        assert "odh-notebook-v3-4" in all_text

    def test_adf_has_expected_panel_count(self):
        adf = cjt._build_psx_filled_adf(
            rule="hermetic_task.hermetic",
            components=["odh-mlflow-v3-3"],
            rhoai_version="rhoai-3.3",
            effective_until="2026-10-10T00:00:00Z",
            rhoaieng_url="https://redhat.atlassian.net/browse/RHOAIENG-12345",
        )
        panels = [n for n in adf["content"] if n.get("type") == "panel"]
        assert len(panels) == 6


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


class TestThreeTicketModel:
    """Tests for the three-ticket Jira model (violation_report, remediation, approval)."""

    def test_violation_report_purpose_tag(self):
        result = cjt._build_summary(
            "RHOAIENG",
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3"],
            "rhoai-3.3",
            None,
            None,
            purpose="violation_report",
        )
        assert "[Conforma Violation]" in result
        assert "odh-mlflow-v3-3" in result

    def test_remediation_is_blocker_bug(self):
        """Remediation should now be Blocker Bug (was regular Bug)."""
        result = cjt._build_summary(
            "RHOAIENG",
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3"],
            "rhoai-3.3",
            None,
            None,
            purpose="remediation",
        )
        assert "[Code Fix]" in result

    def test_approval_purpose_tag(self):
        result = cjt._build_summary(
            "RHOAIENG",
            "hermetic_task.hermetic",
            ["odh-mlflow-v3-3"],
            "rhoai-3.3",
            None,
            None,
            purpose="approval",
        )
        assert "[Exception Approval]" in result

    def test_violation_report_description(self):
        desc = cjt._build_rhoaieng_violation_report_description(
            rule="hermetic_task.hermetic",
            components=["odh-mlflow-v3-3"],
            rhoai_version="rhoai-3.3",
            effective_until="2026-10-10T00:00:00Z",
            fix_target_version="rhoai-3.4",
            exception_scope="Non-hermetic build for odh-mlflow",
        )
        assert desc["version"] == 1
        assert desc["type"] == "doc"
        text = desc["content"][0]["content"][0]["text"]
        assert "Conforma Violation Report" in text
        assert "hermetic_task.hermetic" in text
        assert "Fix Target Version: rhoai-3.4" in text
        assert "Non-hermetic build for odh-mlflow" in text

    def test_violation_report_description_no_fix_version(self):
        desc = cjt._build_rhoaieng_violation_report_description(
            rule="hermetic_task.hermetic",
            components=["odh-mlflow-v3-3"],
            rhoai_version="rhoai-3.3",
            effective_until="2026-10-10T00:00:00Z",
        )
        text = desc["content"][0]["content"][0]["text"]
        assert "Fix Target Version" not in text
