"""Tests for conforma-analyze generate_resolution_guide.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import conforma_context_ops
import release_dates
import generate_resolution_guide as mod
import guide_renderers as renderers
from guide_renderers import render_divergence_warning
from guide_renderers import render_resolution_guide
from guide_renderers import render_components_table
from guide_renderers import render_jira_tickets
from guide_renderers import render_metadata_header
from guide_renderers import render_coverage_table
from guide_renderers import render_work_scope
from guide_renderers import render_key_takeaways
from guide_renderers import write_todo_preview
from conforma_constants import TODO_PREVIEW_FILENAME
from guide_renderers import _find_covering_mr
from guide_renderers import _violation_count
from guide_renderers import _compute_violation_buckets
from guide_renderers import _build_jira_cell
from guide_renderers import render_cataloged_violation
from guide_renderers import render_csv_source_fields
from guide_renderers import render_known_false_alerts
from guide_renderers import render_tooling_health
from guide_renderers import render_warnings_section


@pytest.fixture
def sample_catalog(tmp_path):
    """Create a minimal violation catalog for testing."""
    catalog = {
        "violations": [
            {
                "id": "hermetic_task.hermetic",
                "type": "conforma_violation",
                "title": "Build task was not invoked with the hermetic parameter set",
                "conforma_rule_codes": ["hermetic_task.hermetic"],
                "classification": {
                    "resolution_path": "code_fix",
                    "typical_owner": "component_team",
                    "estimated_effort": "medium",
                    "requires_rebuild": True,
                },
                "fix_steps": [
                    {"action": "Set hermetic=true", "reference": "https://example.com/hermetic"},
                    {"action": "Enable prefetch-dependencies"},
                ],
                "exception_context": {
                    "when_to_exception": "Only if hermetic is genuinely not feasible.",
                },
            },
            {
                "id": "rpm_signature.allowed",
                "type": "conforma_violation",
                "title": "Signing key not allowed",
                "conforma_rule_codes": ["rpm_signature.allowed"],
                "classification": {
                    "resolution_path": "mixed",
                    "typical_owner": "component_team",
                    "estimated_effort": "high",
                    "requires_rebuild": True,
                },
                "fix_steps": [
                    {"action": "Contact the component team"},
                    {"action": "Install RPMs from Red Hat repo"},
                ],
            },
            {
                "id": "builtin.attestation.signature_check",
                "type": "conforma_violation",
                "title": "No image attestations found matching the given public key",
                "conforma_rule_codes": ["builtin.attestation.signature_check"],
                "classification": {
                    "resolution_path": "mixed",
                    "typical_owner": "devops",
                    "estimated_effort": "medium",
                    "requires_rebuild": True,
                },
                "fix_steps": [
                    {"action": "Confirm no .att artifact exists on quay.io"},
                    {"action": "Check chains.tekton.dev/signed annotation"},
                    {"action": "Rebuild the component in Konflux"},
                ],
                "exception_context": {
                    "when_to_exception": "Only if the image is not built through Konflux.",
                },
            },
        ],
        "known_false_alerts": [
            {
                "id": "test_false_alert",
                "title": "Known FBC false positive",
                "applies_to": "rhoai-fbc-fragment*",
                "conforma_rule_codes": ["test.no_failed_tests"],
                "action": "ignore",
                "condition": "Only for on-push builds.",
            },
        ],
        "fallback_references": [
            {
                "code_prefix": "sbom_spdx.disallowed_package_attributes",
                "title": "SBOM disallowed attributes",
                "doc_urls": ["https://example.com/sbom-rules"],
                "guidance": "Check Conforma policy for allowed attributes.",
            },
            {
                "code_prefix": "sbom_spdx",
                "title": "SBOM compliance",
                "doc_urls": ["https://example.com/sbom"],
                "guidance": "General SBOM guidance.",
            },
            {
                "code_prefix": "source_image",
                "title": "Source image",
                "doc_urls": ["https://example.com/source"],
                "guidance": "Rebuild the component.",
            },
            {
                "code_prefix": "builtin.attestation",
                "title": "Built-in attestation verification",
                "doc_urls": ["https://conforma.dev/docs/user-guide/cosign.html"],
                "guidance": "Check Tekton Chains signing status and rebuild.",
            },
            {
                "code_prefix": "builtin",
                "title": "Built-in Conforma checks",
                "doc_urls": ["https://conforma.dev/docs/user-guide/hitchhikers-guide.html"],
                "guidance": "Check Tekton Chains and rebuild.",
            },
        ],
    }
    path = tmp_path / "violation-catalog.yaml"
    path.write_text(yaml.dump(catalog), encoding="utf-8")
    return path


@pytest.fixture
def sample_violations_yaml(tmp_path):
    """Create a minimal violations YAML."""
    data = {
        "violation_data": {
            "releases": ["rhoai-3.5-ea.2"],
            "violations_by_rule": {
                "hermetic_task.hermetic": {
                    "base_code": "hermetic_task.hermetic",
                    "components": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                },
                "sbom_spdx.disallowed_package_attributes": {
                    "base_code": "sbom_spdx.disallowed_package_attributes",
                    "components": ["comp-a-v3-5-ea-2"],
                },
            },
            "violations_by_component": {
                "comp-a-v3-5-ea-2": {"jira_component": "AI Safety"},
                "comp-b-v3-5-ea-2": {"jira_component": "Model Runtimes"},
            },
        }
    }
    path = tmp_path / "violations.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


@pytest.fixture
def sample_coverage_json(tmp_path):
    """Create a minimal coverage JSON."""
    data = {
        "summary": {
            "fully_covered": 0,
            "partially_covered": 0,
            "not_covered": 2,
            "total_violations": 2,
        },
        "violations": [
            {
                "rule": "hermetic_task.hermetic",
                "title": "Task called with hermetic param set",
                "total_components": 2,
                "covered_components": [],
                "uncovered_components": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                "covered_count": 0,
                "uncovered_count": 2,
                "display_components": "comp-a-v3-5-ea-2 (AI Safety), comp-b-v3-5-ea-2 (Model Runtimes)",
                "open_merge_requests": [],
                "open_mr_label": "",
                "open_mr_search_url": "https://gitlab.example.com/search?hermetic_task.hermetic",
                "open_jira_tickets": [],
                "open_jira_label": "",
                "open_jira_search_url": "https://redhat.atlassian.net/issues/?jql=hermetic",
                "open_slack_threads": [],
                "open_slack_label": "",
                "open_slack_search_url": "https://slack.com/search/hermetic",
                "next_steps": "Fix in code or request exception — see resolution guide",
                "next_steps_short": "Fix in code — see guide below",
                "status_label": "No coverage",
                "coverage": "not_covered",
                "gate_status": "error",
            },
            {
                "rule": "sbom_spdx.disallowed_package_attributes",
                "title": "Disallowed package attributes",
                "total_components": 1,
                "covered_components": [],
                "uncovered_components": ["comp-a-v3-5-ea-2"],
                "covered_count": 0,
                "uncovered_count": 1,
                "display_components": "comp-a-v3-5-ea-2 (AI Safety)",
                "open_merge_requests": [],
                "open_mr_label": "",
                "open_mr_search_url": "https://gitlab.example.com/search?sbom",
                "open_jira_tickets": [],
                "open_jira_label": "",
                "open_jira_search_url": "https://redhat.atlassian.net/issues/?jql=sbom",
                "open_slack_threads": [],
                "open_slack_label": "",
                "open_slack_search_url": "https://slack.com/search/sbom",
                "next_steps": "Fix in code or request exception — see resolution guide",
                "next_steps_short": "Fix in code — see guide below",
                "status_label": "No coverage",
                "coverage": "not_covered",
                "gate_status": "error",
            },
        ],
        "markdown_table": "**Summary**: 2 unique rules\n\n| # | Rule |\n|---|------|\n| 1 | hermetic |\n| 2 | sbom |",
        "component_owners": {
            "comp-a-v3-5-ea-2": "AI Safety",
            "comp-b-v3-5-ea-2": "Model Runtimes",
        },
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestCatalogMatching:
    def test_exact_match(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        entry = mod._match_catalog_entry("hermetic_task.hermetic", catalog)
        assert entry is not None
        assert entry["id"] == "hermetic_task.hermetic"

    def test_match_with_suffix(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        entry = mod._match_catalog_entry("rpm_signature.allowed:9386b48a", catalog)
        assert entry is not None
        assert entry["id"] == "rpm_signature.allowed"

    def test_no_match(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        entry = mod._match_catalog_entry("completely_unknown.rule", catalog)
        assert entry is None

    def test_prefix_match(self):
        catalog = {"violations": [{"id": "prefix.rule", "conforma_rule_codes": ["prefix"]}]}
        assert mod._match_catalog_entry("prefix.rule.extra", catalog)["id"] == "prefix.rule"

    def test_find_default_catalog(self):
        assert mod._find_default_catalog().name == "violation-catalog.yaml"

    def test_find_default_catalog_fallback_and_missing(self):
        from unittest.mock import patch

        with patch.object(mod.Path, "exists", side_effect=[False, True]):
            assert mod._find_default_catalog().name == "violation-catalog.yaml"
        with patch.object(mod.Path, "exists", side_effect=[False, False]):
            with pytest.raises(FileNotFoundError, match="violation-catalog.yaml"):
                mod._find_default_catalog()

    def test_fallback_exact_prefix(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        fb = mod._match_fallback_reference("sbom_spdx.disallowed_package_attributes", catalog)
        assert fb is not None
        assert fb["code_prefix"] == "sbom_spdx.disallowed_package_attributes"

    def test_fallback_shorter_prefix(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        fb = mod._match_fallback_reference("sbom_spdx.some_new_rule", catalog)
        assert fb is not None
        assert fb["code_prefix"] == "sbom_spdx"

    def test_fallback_no_match(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        fb = mod._match_fallback_reference("completely_unknown.rule", catalog)
        assert fb is None

    def test_fallback_longest_prefix_wins(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        fb = mod._match_fallback_reference("source_image.exists", catalog)
        assert fb is not None
        assert fb["code_prefix"] == "source_image"

    def test_builtin_attestation_signature_check_exact_match(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        entry = mod._match_catalog_entry("builtin.attestation.signature_check", catalog)
        assert entry is not None
        assert entry["id"] == "builtin.attestation.signature_check"
        assert entry["classification"]["typical_owner"] == "devops"

    def test_builtin_attestation_fallback_for_unknown_builtin(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        fb = mod._match_fallback_reference("builtin.attestation.new_check", catalog)
        assert fb is not None
        assert fb["code_prefix"] == "builtin.attestation"

    def test_builtin_generic_fallback(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        fb = mod._match_fallback_reference("builtin.something.else", catalog)
        assert fb is not None
        assert fb["code_prefix"] == "builtin"


class TestKnownFalseAlerts:
    def test_matches_glob_pattern(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        alert = mod._match_known_false_alert("test.no_failed_tests", "rhoai-fbc-fragment-v3-5", catalog)
        assert alert is not None
        assert alert["id"] == "test_false_alert"

    def test_no_match_different_component(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        alert = mod._match_known_false_alert("test.no_failed_tests", "odh-vllm-v3-5", catalog)
        assert alert is None

    def test_no_match_different_rule(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        alert = mod._match_known_false_alert("hermetic_task.hermetic", "rhoai-fbc-fragment-v3-5", catalog)
        assert alert is None


class TestGenerateResolutionGuide:
    def test_generates_all_sections(self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Bad attrs",,sbom_spdx.disallowed_package_attributes,'
            "Disallowed attrs,desc,Fix attrs\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "# Conforma Status and Resolution Guide: rhoai-3.5-ea.2" in content
        assert "## Summary" in content
        assert "## Violations Coverage" in content
        assert "## Resolution Guide" in content
        assert "## Statistical Breakdown" in content
        assert "aiops-infra conforma-analyze skill" in content
        assert "prod/future/build_type_latest/conforma-violations-report.csv" in content

    def test_cataloged_violation_has_fix_steps(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "Set hermetic=true" in content
        assert "Exception only if" in content

    def test_uncataloged_violation_uses_fallback(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Bad attrs",,sbom_spdx.disallowed_package_attributes,'
            "Disallowed attrs,desc,Fix attrs\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "Not in violation catalog" in content
        assert "https://example.com/sbom-rules" in content
        assert "Check Conforma policy for allowed attributes" in content

    def test_missing_files_raise_errors(self, tmp_path, sample_catalog):
        with pytest.raises(FileNotFoundError, match="Violations YAML not found"):
            mod.generate_resolution_guide(
                violations_yaml_path=str(tmp_path / "nonexistent.yaml"),
                coverage_json_path=str(tmp_path / "coverage.json"),
                reports_dir=str(tmp_path),
                catalog_path=str(sample_catalog),
                release="rhoai-3.5-ea.2",
                source_path="prod/future/build_type_latest/conforma-violations-report.csv",
                source_created_at="2026-06-10T05:19:05Z",
            )


class TestFullyCoveredViolation:
    """Fully-excepted violations should show a compact block, not full remediation."""

    @pytest.fixture
    def fully_covered_coverage_json(self, tmp_path):
        data = {
            "summary": {
                "fully_covered": 1,
                "partially_covered": 0,
                "not_covered": 0,
                "total_violations": 1,
            },
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Task called with hermetic param set",
                    "total_components": 2,
                    "covered_components": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                    "uncovered_components": [],
                    "covered_count": 2,
                    "uncovered_count": 0,
                    "display_components": "comp-a-v3-5-ea-2, comp-b-v3-5-ea-2",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-15",
                        "latest_expiry": "2026-07-15",
                        "expiry_dates": ["2026-07-15"],
                        "display_expiry": "expires 2026-07-15",
                    },
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "https://gitlab.example.com/search?hermetic",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "https://redhat.atlassian.net/issues/?jql=hermetic",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "https://slack.com/search/hermetic",
                    "next_steps": "Use `conforma-violations-scan` AI skill or [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter/actions/workflows/conforma-reporter.yaml) to rerun validation and verify the violation is gone",
                    "next_steps_short": "Rerun validation to verify",
                    "status_label": "Exception granted, violation should disappear on next Conforma run",
                    "coverage": "fully_covered",
                    "coverage_label": "already covered",
                    "gate_status": "blocked",
                    "violation_count": 2,
                },
            ],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | hermetic |",
            "component_owners": {
                "comp-a-v3-5-ea-2": "AI Safety",
                "comp-b-v3-5-ea-2": "Model Runtimes",
            },
        }
        path = tmp_path / "coverage.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_shows_exception_granted_not_fix_steps(
        self, tmp_path, sample_violations_yaml, fully_covered_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(fully_covered_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "(2/2 have exceptions)" in content
        assert "conforma-violations-scan" in content
        assert "conforma-remedy" in content
        assert "Set hermetic=true" not in content
        assert "**Resolution:**" not in content
        assert "Exception only if" not in content

    def test_permanent_exception_label(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        data = {
            "summary": {"fully_covered": 1, "partially_covered": 0, "not_covered": 0, "total_violations": 1},
            "violations": [
                {
                    "rule": "rpm_signature.allowed:9386b48a1a693c5c",
                    "title": "Allowed RPM signature key",
                    "total_components": 1,
                    "covered_components": ["comp-a-v3-5-ea-2"],
                    "uncovered_components": [],
                    "covered_count": 1,
                    "uncovered_count": 0,
                    "display_components": "comp-a-v3-5-ea-2",
                    "exception_expiry": {
                        "is_permanent": True,
                        "earliest_expiry": None,
                        "latest_expiry": None,
                        "expiry_dates": [],
                        "display_expiry": "permanent (no expiry)",
                    },
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "",
                    "next_steps": "Use `conforma-violations-scan` AI skill or [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter/actions/workflows/conforma-reporter.yaml) to rerun validation",
                    "next_steps_short": "Rerun validation to verify",
                    "coverage": "fully_covered",
                    "coverage_label": "already covered",
                    "gate_status": "blocked",
                    "violation_count": 1,
                },
            ],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | rpm_sig |",
            "component_owners": {"comp-a-v3-5-ea-2": "AI Safety"},
        }
        cov_path = tmp_path / "coverage.json"
        cov_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Bad sig",,rpm_signature.allowed,'
            "RPM sig,desc,Fix sig\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(cov_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "(1/1 have exceptions)" in content
        assert "Contact the component team" not in content


class TestMergeRequestUrls:
    """Merge Request URLs must use the 'url' key from the data pipeline, not 'web_url'."""

    def test_mr_urls_are_populated(self, tmp_path, sample_violations_yaml, sample_catalog):
        data = {
            "summary": {
                "fully_covered": 0,
                "partially_covered": 0,
                "not_covered": 1,
                "total_violations": 1,
            },
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Task called with hermetic param set",
                    "total_components": 2,
                    "covered_components": [],
                    "uncovered_components": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                    "covered_count": 0,
                    "uncovered_count": 2,
                    "display_components": "comp-a-v3-5-ea-2 (AI Safety), comp-b-v3-5-ea-2 (Model Runtimes)",
                    "open_merge_requests": [
                        {
                            "iid": 19118,
                            "url": "https://gitlab.test-corp.fake/releng/konflux-release-data/-/merge_requests/19118",
                            "mr_type": "exception",
                            "suggestion": "extend_mr",
                            "covered": ["comp-a-v3-5-ea-2"],
                            "missing": ["comp-b-v3-5-ea-2"],
                            "mr_components": ["comp-a-v3-5-ea-2"],
                        },
                        {
                            "iid": 555,
                            "url": "https://gitlab.test-corp.fake/releng/konflux-release-data/-/merge_requests/555",
                            "mr_type": "remedy",
                            "suggestion": "no_overlap",
                            "covered": [],
                            "missing": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                        },
                    ],
                    "open_mr_label": "",
                    "open_mr_search_url": "https://gitlab.example.com/search?hermetic",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "https://redhat.atlassian.net/issues/?jql=hermetic",
                    "next_steps": "Fix in code or request exception",
                    "next_steps_short": "Fix in code — see guide below",
                    "status_label": "No coverage",
                    "coverage": "not_covered",
                    "gate_status": "passed",
                    "violation_count": 2,
                },
            ],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | hermetic |",
            "component_owners": {
                "comp-a-v3-5-ea-2": "AI Safety",
                "comp-b-v3-5-ea-2": "Model Runtimes",
            },
        }
        cov_path = tmp_path / "coverage.json"
        cov_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(cov_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        # Exception MR !19118 appears in the per-component table (has mr_components)
        assert "https://gitlab.test-corp.fake/releng/konflux-release-data/-/merge_requests/19118" in content
        assert "!19118" in content
        # Search links are no longer rendered in guide sections
        assert "[search GitLab]" not in content
        assert "[search Jira]" not in content


class TestPartiallyCoveredViolation:
    """Partially-covered violations should show a header + full remediation."""

    @pytest.fixture
    def partial_coverage_json(self, tmp_path):
        data = {
            "summary": {
                "fully_covered": 0,
                "partially_covered": 1,
                "not_covered": 0,
                "total_violations": 1,
            },
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Task called with hermetic param set",
                    "total_components": 2,
                    "covered_components": ["comp-a-v3-5-ea-2"],
                    "uncovered_components": ["comp-b-v3-5-ea-2"],
                    "covered_count": 1,
                    "uncovered_count": 1,
                    "display_components": "comp-a-v3-5-ea-2, comp-b-v3-5-ea-2",
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "https://gitlab.example.com/search?hermetic",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "https://redhat.atlassian.net/issues/?jql=hermetic",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "https://slack.com/search/hermetic",
                    "next_steps": "Fix in code or request exception",
                    "next_steps_short": "Fix remaining — see guide below",
                    "status_label": "Partially covered",
                    "coverage": "partially_covered",
                    "coverage_label": "partially covered",
                    "gate_status": "error",
                    "violation_count": 2,
                },
            ],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | hermetic |",
            "component_owners": {
                "comp-a-v3-5-ea-2": "AI Safety",
                "comp-b-v3-5-ea-2": "Model Runtimes",
            },
        }
        path = tmp_path / "coverage.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_shows_partial_header_and_fix_steps(
        self, tmp_path, sample_violations_yaml, partial_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-b-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(partial_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "| **Components** |" not in content  # now a separate table
        assert "**Components:**" in content
        assert "| Component | Team | Exception |" in content
        assert "(1/2 have exceptions)" in content
        assert "`comp-b-v3-5-ea-2`" in content
        assert "**Partially covered**: 1/2 components have exceptions" in content
        assert "Set hermetic=true" in content
        assert "Exception only if" in content


class TestMetadataHeader:
    def test_includes_release_and_source(self):
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        assert "rhoai-3.5-ea.2" in header
        assert "prod/future/build_type_latest/conforma-violations-report.csv" in header
        assert "2026-06-10T05:19:05Z" in header
        assert "conforma-reporter" in header


class TestMetadataTotalViolations:
    def test_includes_total_violations_row(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            total_violations=162,
        )
        assert "| **Total violations (deduplicated per image)** | 162 |" in header

    def test_omits_total_violations_when_none(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        # The row is still present so the structure matches the Step 2
        # confirmation table; its value carries a placeholder note.
        placeholder_row = (
            "| **Total violations (deduplicated per image)** | set after the violations are analyzed (step 6) |"
        )
        assert placeholder_row in header
        assert header.count("| **Total violations (deduplicated per image)** |") == 1


class TestMetadataSourceCsvRows:
    def test_includes_source_csv_rows_row(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_csv_rows=1055,
        )
        assert "| **Source CSV rows (raw, per-image)** | 1,055 |" in header

    def test_omits_source_csv_rows_when_none(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        # The row is still present so the structure matches the Step 2
        # confirmation table; its value carries a placeholder note.
        assert "| **Source CSV rows (raw, per-image)** | set after the source CSV is fetched (step 4) |" in header

    def test_source_csv_rows_precedes_deduplicated_total(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_csv_rows=1055,
            total_violations=162,
        )
        rows_row = "| **Source CSV rows (raw, per-image)** | 1,055 |"
        total_row = "| **Total violations (deduplicated per image)** | 162 |"
        assert rows_row in header
        assert total_row in header
        assert header.index(rows_row) < header.index(total_row)


class TestMetadataAiModelFooter:
    def test_includes_ai_model_footer(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            ai_model="claude-sonnet-4-5",
        )
        assert (
            "*Generated by: aiops-infra conforma-analyze skill (LLM: claude-sonnet-4-5)*"
            in header
        )

    def test_omits_ai_model_footer_when_empty(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        assert "*Generated by: aiops-infra conforma-analyze skill*" in header
        assert "(LLM:" not in header


class TestMetadataHeaderConfirmationDisplay:
    """Placeholder rows in the context confirmation are replaced in place."""

    DISPLAY = (
        "### Conforma Workflow \u2014 Context Confirmation\n"
        "\n"
        "| Field | Value |\n"
        "|-------|-------|\n"
        "| **Generated** | set when the resolution guide is generated (step 9) |\n"
        "| **User requested** | rhoai-3.5-ea.2 |\n"
        "| **Source CSV** | [conforma-violations-report.csv](https://example.com/report.csv) |\n"
        "| **Source CSV generated** | set after the source CSV is fetched (step 4) |\n"
        "| **Source CSV rows (raw, per-image)** | set after the source CSV is fetched (step 4) |\n"
        "| **Total violations (deduplicated per image)** | set after the violations are analyzed (step 6) |\n"
        "| **Konflux Application** | rhoai |\n"
        "\n"
        "*Source: GitLab tree (konflux-release-data, main branch)*"
    )

    def test_source_stat_rows_inserted_below_source_csv_row(self):
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            confirmation_display=self.DISPLAY,
            source_csv_rows=1055,
            total_violations=162,
        )
        src_idx = header.index("| **Source CSV** | [conforma-violations-report.csv]")
        generated_idx = header.index("| **Source CSV generated** |")
        rows_idx = header.index("| **Source CSV rows (raw, per-image)** | 1,055 |")
        total_idx = header.index("| **Total violations (deduplicated per image)** | 162 |")
        app_idx = header.index("| **Konflux Application** |")
        assert src_idx < generated_idx < rows_idx < total_idx < app_idx

    def test_generated_row_inserted_after_header_separator(self):
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            confirmation_display=self.DISPLAY,
            total_violations=162,
        )
        sep_idx = header.index("|-------|-------|")
        gen_idx = header.index("| **Generated** |")
        total_idx = header.index("| **Total violations (deduplicated per image)** | 162 |")
        assert sep_idx < gen_idx < total_idx

    def test_placeholder_values_replaced_in_place(self):
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            confirmation_display=self.DISPLAY,
            source_csv_rows=1055,
            total_violations=162,
        )
        # The pending-row notes must not survive in the final header: every
        # placeholder row that had a real value is replaced in place.
        assert "set when the resolution guide is generated" not in header
        assert "set after the source CSV is fetched" not in header
        assert "set after the violations are analyzed" not in header
        assert "| **Source CSV rows (raw, per-image)** | 1,055 |" in header
        assert "| **Total violations (deduplicated per image)** | 162 |" in header

    def test_table_structure_matches_step2_confirmation(self):
        """Row order in the guide header equals the Step 2 confirmation order."""
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            confirmation_display=self.DISPLAY,
            source_csv_rows=1055,
            total_violations=162,
        )
        expected_order = [
            "| **Generated** |",
            "| **User requested** |",
            "| **Source CSV** |",
            "| **Source CSV generated** |",
            "| **Source CSV rows (raw, per-image)** |",
            "| **Total violations (deduplicated per image)** |",
            "| **Konflux Application** |",
        ]
        indices = [header.index(label) for label in expected_order]
        assert indices == sorted(indices)
        # Exactly one occurrence of each row label (no duplicated rows).
        for label in expected_order:
            assert header.count(label) == 1, f"{label} appears more than once"

    def test_source_csv_generated_directly_under_source_csv_manual_table(self):
        """In the manually-built header (no confirmation display), the
        "Source CSV generated" row sits directly under the "Source CSV" row."""
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_csv_rows=1055,
            total_violations=162,
        )
        src_idx = header.index("| **Source CSV** |")
        generated_idx = header.index("| **Source CSV generated** |")
        rows_idx = header.index("| **Source CSV rows (raw, per-image)** |")
        total_idx = header.index("| **Total violations (deduplicated per image)** |")
        assert src_idx < generated_idx < rows_idx < total_idx


    def test_legacy_display_without_placeholder_rows_still_works(self):
        """A confirmation display generated before the placeholder rows were
        introduced still gets the rows inserted (backward compatibility)."""
        legacy_display = (
            "### Conforma Workflow \u2014 Context Confirmation\n"
            "\n"
            "| Field | Value |\n"
            "|-------|-------|\n"
            "| **User requested** | rhoai-3.5-ea.2 |\n"
            "| **Source CSV** | [conforma-violations-report.csv](https://example.com/report.csv) |\n"
            "| **Konflux Application** | rhoai |\n"
            "\n"
            "*Source: GitLab tree (konflux-release-data, main branch)*"
        )
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            confirmation_display=legacy_display,
            source_csv_rows=1055,
            total_violations=162,
        )
        # No pending-row note may leak into the final header; the rows that
        # were present are replaced with their real values in place.
        assert "set after the" not in header
        assert "| **Generated** |" in header
        assert "| **Source CSV rows (raw, per-image)** | 1,055 |" in header
        assert "| **Total violations (deduplicated per image)** | 162 |" in header
        for label in ("| **Generated** |", "| **Source CSV rows (raw, per-image)** |", "| **Total violations (deduplicated per image)** |"):
            assert header.count(label) == 1, f"{label} appears more than once"

    def test_ai_model_footer_rendered_with_confirmation_display(self):
        header = render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            confirmation_display=self.DISPLAY,
            ai_model="claude-sonnet-4-5",
        )
        assert (
            "*Generated by: aiops-infra conforma-analyze skill (LLM: claude-sonnet-4-5)*"
            in header
        )


class TestMetadataCodeFreezeDate:
    def test_includes_code_freeze_when_present(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            code_freeze_date="2026-07-24",
        )
        assert "Code freeze (RHOAI 3.5)" in header
        assert "2026-07-24" in header
        assert "Product Pages" in header

    def test_omits_code_freeze_when_empty(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            code_freeze_date="",
        )
        assert "Code freeze" not in header

    def test_omits_code_freeze_when_not_provided(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        assert "Code freeze" not in header

    def test_code_freeze_after_upcoming_release_shows_already_passed(self):
        header = render_metadata_header(
            release="rhoai-3.3",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            code_freeze_date="2026-07-31",
            upcoming_release_date="2026-07-09",
        )
        assert "Already passed" in header
        assert "next code freeze 2026-07-31 is for a future release" in header

    def test_code_freeze_empty_with_upcoming_release_shows_already_passed(self):
        header = render_metadata_header(
            release="rhoai-3.3",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            code_freeze_date="",
            upcoming_release_date="2026-07-09",
        )
        assert "Already passed" in header
        assert f"not found in {release_dates.RELEASE_DATA_LINK}" in header

    def test_code_freeze_before_upcoming_release_shows_date(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            code_freeze_date="2026-07-24",
            upcoming_release_date="2026-08-20",
        )
        assert "Code freeze (RHOAI 3.5)" in header
        assert "2026-07-24" in header
        assert "Already passed" not in header


class TestRenderWorkScope:
    def test_skipped_when_unique_items_is_one(self):
        lines = []
        work_scope_by_rule = {
            "hermetic_task.hermetic": {
                "unique_items": 1,
                "total_components": 34,
                "per_component_avg": 1,
                "per_component_max": 1,
                "per_component_min": 1,
                "sample_message": "Task is not hermetic",
            }
        }
        render_work_scope(lines, "hermetic_task.hermetic", work_scope_by_rule, "https://csv-url")
        assert lines == []

    def test_skipped_when_rule_not_in_scope_data(self):
        lines = []
        render_work_scope(lines, "unknown.rule", {}, "https://csv-url")
        assert lines == []

    def test_high_cardinality_shows_csv_link(self):
        lines = []
        work_scope_by_rule = {
            "sbom_spdx.disallowed_package_attributes": {
                "unique_items": 2625,
                "total_components": 29,
                "per_component_avg": 200,
                "per_component_max": 363,
                "per_component_min": 2,
                "sample_message": "Package pkg:pypi/foo@1.0 has the attribute...",
            }
        }
        render_work_scope(
            lines, "sbom_spdx.disallowed_package_attributes", work_scope_by_rule, "https://csv-url"
        )
        assert len(lines) == 2
        assert "2,625 unique work items" in lines[0]
        assert "29 components" in lines[0]
        assert "avg ~200 per component" in lines[0]
        assert "[source CSV](https://csv-url)" in lines[0]

    def test_low_cardinality_no_csv_link(self):
        lines = []
        work_scope_by_rule = {
            "rpm_repos.ids_known": {
                "unique_items": 4,
                "total_components": 2,
                "per_component_avg": 2,
                "per_component_max": 3,
                "per_component_min": 1,
                "sample_message": "RPM repo id check failed",
            }
        }
        render_work_scope(lines, "rpm_repos.ids_known", work_scope_by_rule, "https://csv-url")
        assert len(lines) == 2
        assert "4 unique work items" in lines[0]
        assert "source CSV" not in lines[0]

    def test_threshold_boundary(self):
        lines = []
        work_scope_by_rule = {
            "rule.x": {
                "unique_items": 6,
                "total_components": 3,
                "per_component_avg": 2,
                "per_component_max": 3,
                "per_component_min": 1,
                "sample_message": "msg",
            }
        }
        render_work_scope(lines, "rule.x", work_scope_by_rule, "https://csv-url")
        assert len(lines) == 2
        assert "source CSV" not in lines[0]

    def test_above_threshold_shows_csv_link(self):
        lines = []
        work_scope_by_rule = {
            "rule.x": {
                "unique_items": 7,
                "total_components": 3,
                "per_component_avg": 2,
                "per_component_max": 3,
                "per_component_min": 1,
                "sample_message": "msg",
            }
        }
        render_work_scope(lines, "rule.x", work_scope_by_rule, "https://csv-url")
        assert len(lines) == 2
        assert "[source CSV](https://csv-url)" in lines[0]


class TestComponentStem:
    """_component_stem must strip only the RHOAI version trailer."""

    def test_basic_ea_version(self):
        assert mod._component_stem("odh-vllm-cpu-v3-5-ea-2") == "odh-vllm-cpu"

    def test_basic_ga_version(self):
        assert mod._component_stem("odh-workbench-jupyter-minimal-v3-4") == "odh-workbench-jupyter-minimal"

    def test_two_digit_minor(self):
        assert mod._component_stem("odh-pipeline-runtime-py312-v2-25") == "odh-pipeline-runtime-py312"

    def test_no_version_suffix_unchanged(self):
        assert mod._component_stem("odh-generic-tool") == "odh-generic-tool"

    def test_vllm_mid_name_not_stripped(self):
        # "-vllm" is not a version trailer (letter after v, not digit)
        assert mod._component_stem("odh-vllm-cpu-v3-5") == "odh-vllm-cpu"

    def test_empty_string(self):
        assert mod._component_stem("") == ""

    def test_requires_two_digit_groups(self):
        # "-v3" alone (no second digit group) should NOT be stripped
        assert mod._component_stem("odh-comp-v3") == "odh-comp-v3"

    def test_stem_equality_across_versions(self):
        # Same component across releases must produce the same stem
        assert (
            mod._component_stem("odh-workbench-jupyter-minimal-cpu-py312-v3-4")
            == mod._component_stem("odh-workbench-jupyter-minimal-cpu-py312-v3-5-ea-2")
        )


class TestViolationAnchor:
    """_violation_anchor must produce safe, consistent HTML id values."""

    def test_simple_rule(self):
        assert mod._violation_anchor("hermetic_task.hermetic") == "violation-hermetic_task-hermetic"

    def test_rule_with_colon(self):
        anchor = mod._violation_anchor("rpm_signature.allowed:9386b48a1a693c5c")
        assert ":" not in anchor
        assert anchor == "violation-rpm_signature-allowed-9386b48a1a693c5c"

    def test_rule_with_dot_only(self):
        assert mod._violation_anchor("sbom_spdx.disallowed_package_attributes") == (
            "violation-sbom_spdx-disallowed_package_attributes"
        )

    def test_prefix_scoping(self):
        assert mod._violation_anchor("any.rule").startswith("violation-")

    def test_empty_rule(self):
        assert mod._violation_anchor("") == "violation-"

    def test_round_trip_consistency(self):
        # The anchor used in _render_coverage_table and in the section header must match
        rule = "test.no_failed_tests:fbc-target-index-pruning-check"
        assert mod._violation_anchor(rule) == mod._violation_anchor(rule)


class TestCoverageTableLinks:
    """_render_coverage_table must inject clickable links for each violation."""

    def _make_coverage(self, rules: list[str], table: str) -> dict:
        return {
            "violations": [{"rule": r} for r in rules],
            "markdown_table": table,
        }

    def test_rule_name_becomes_link(self):
        cov = self._make_coverage(
            ["hermetic_task.hermetic"],
            "| 1 | `hermetic_task.hermetic` | 105 | Covered |",
        )
        out = render_coverage_table(cov)
        anchor = mod._violation_anchor("hermetic_task.hermetic")
        assert f"[`hermetic_task.hermetic`](#{anchor})" in out

    def test_rule_with_colon_becomes_link(self):
        rule = "rpm_signature.allowed:9386b48a1a693c5c"
        cov = self._make_coverage(
            [rule],
            f"| 1 | `{rule}` | 3 | Not covered |",
        )
        out = render_coverage_table(cov)
        anchor = mod._violation_anchor(rule)
        assert f"[`{rule}`](#{anchor})" in out
        assert ":#" not in out  # colon must not leak into the fragment

    def test_multiple_rules_all_linked(self):
        rules = ["hermetic_task.hermetic", "sbom_spdx.disallowed_package_attributes"]
        table = "\n".join(f"| {i+1} | `{r}` | 1 | - |" for i, r in enumerate(rules))
        cov = self._make_coverage(rules, table)
        out = render_coverage_table(cov)
        for rule in rules:
            anchor = mod._violation_anchor(rule)
            assert f"[`{rule}`](#{anchor})" in out

    def test_unrelated_backtick_content_not_linked(self):
        # The word "conforma" in backticks should not be rewritten
        cov = self._make_coverage(
            ["hermetic_task.hermetic"],
            "| 1 | `hermetic_task.hermetic` | 105 | Use `conforma` skill |",
        )
        out = render_coverage_table(cov)
        assert "[`conforma`]" not in out

    def test_section_header_contains_matching_anchor(self, tmp_path, sample_violations_yaml, sample_catalog):
        """The <a id> in the section header must match the link in the coverage table."""
        cov = {
            "summary": {"fully_covered": 0, "partially_covered": 0, "not_covered": 1, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Hermetic",
                    "total_components": 1,
                    "covered_components": [],
                    "uncovered_components": ["comp-a-v3-5-ea-2"],
                    "covered_count": 0,
                    "uncovered_count": 1,
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "",
                    "next_steps": "Fix",
                    "next_steps_short": "Fix",
                    "status_label": "Not covered",
                    "coverage": "not_covered",
                    "coverage_label": "not covered",
                    "gate_status": "error",
                    "violation_count": 1,
                },
            ],
            "markdown_table": "| 1 | `hermetic_task.hermetic` | 1 | Not covered |",
            "component_owners": {"comp-a-v3-5-ea-2": "AI Safety"},
        }
        cov_path = tmp_path / "coverage.json"
        cov_path.write_text(json.dumps(cov))
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,H,d,fix\n'
        )
        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(cov_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        anchor = mod._violation_anchor("hermetic_task.hermetic")
        assert f'<a id="{anchor}"></a>' in content
        assert f"[`hermetic_task.hermetic`](#{anchor})" in content


class TestRenderDivergenceWarning:
    """_render_divergence_warning must explain the policy divergence in plain English."""

    def test_no_divergences_renders_nothing(self):
        lines: list[str] = []
        render_divergence_warning(lines, {"rule": "rule.x", "ec_divergences": []})
        assert lines == []

    def test_no_ec_divergences_key_renders_nothing(self):
        lines: list[str] = []
        render_divergence_warning(lines, {"rule": "rule.x"})
        assert lines == []

    def test_single_divergence_renders_warning(self):
        lines: list[str] = []
        violation = {
            "rule": "hermetic_task.hermetic",
            "ec_divergences": [
                {"component": "comp-a", "violation_code": "hermetic_task.hermetic", "reason": "..."},
            ],
        }
        render_divergence_warning(lines, violation)
        text = "\n".join(lines)
        assert "Policy divergence" in text
        assert "`hermetic_task.hermetic`" in text
        assert "`comp-a`" in text
        assert "source CSV report" in text
        assert "policy has changed" in text
        assert "checked manually" in text

    def test_multiple_divergences_lists_all_components(self):
        lines: list[str] = []
        violation = {
            "rule": "rule.x",
            "ec_divergences": [
                {"component": "comp-a", "violation_code": "rule.x", "reason": "..."},
                {"component": "comp-b", "violation_code": "rule.x", "reason": "..."},
            ],
        }
        render_divergence_warning(lines, violation)
        text = "\n".join(lines)
        assert "`comp-a`" in text
        assert "`comp-b`" in text
        assert "2 components" in text


class TestRenderComponentsTable:
    """_render_components_table must render all five columns correctly."""

    def _base_violation(self, **kwargs):
        base = {
            "uncovered_components": [],
            "covered_components": [],
            "exception_details_by_component": [],
            "open_merge_requests": [],
            "open_jira_tickets": [],
        }
        base.update(kwargs)
        return base

    def test_five_column_header(self):
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5"],
            exception_details_by_component=[{"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None}],
        )
        lines = []
        render_components_table(lines, v, {})
        header = "\n".join(lines)
        assert "| Component | Team | Exception | Merge Requests | JIRAs |" in header

    def test_mr_cell_populated_by_stem_match(self):
        v = self._base_violation(
            uncovered_components=["odh-vllm-cpu-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "odh-vllm-cpu-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
            open_merge_requests=[
                {
                    "mr_iid": 777, "iid": 777, "url": "https://gl/777",
                    "mr_type": "exception", "suggestion": "extend_mr",
                    "mr_components": ["odh-vllm-cpu-v3-4", "odh-vllm-cpu-v3-5"],
                    "covered": [], "missing": [],
                }
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        row = next(l for l in lines if "odh-vllm-cpu-v3-5-ea-2" in l)
        assert "[!777](https://gl/777)" in row

    def test_no_overlap_exception_mr_excluded_from_component_column(self):
        v = self._base_violation(
            uncovered_components=["odh-vllm-cpu-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "odh-vllm-cpu-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
            open_merge_requests=[
                {
                    "mr_iid": 99, "iid": 99, "url": "https://gl/99",
                    "mr_type": "exception", "suggestion": "no_overlap",
                    "mr_components": [],
                    "covered": [], "missing": [],
                }
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        row = next(l for l in lines if "odh-vllm-cpu-v3-5-ea-2" in l)
        assert "[!99]" not in row
        assert "| — |" in row

    def test_unscoped_jira_shows_possibly_related(self):
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5", "comp-b-v3-5"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
                {"component": "comp-b-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
            open_jira_tickets=[
                {"key": "PSX-1", "url": "https://jira/PSX-1", "matched_component_stems": []},
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        rows = [l for l in lines if l.startswith("| `")]
        assert len(rows) == 2
        assert all("[PSX-1](https://jira/PSX-1) (possibly related)" in r for r in rows)

    # ---- C9: JIRAs cell extended with jira_sync data -------------------
    def _row(self, v: dict, comp: str, **kwargs) -> str:
        lines = []
        render_components_table(lines, v, {}, **kwargs)
        return next(line for line in lines if f"`{comp}`" in line)

    def test_no_jira_sync_cell_is_dash(self):
        v = self._base_violation(
            rule="hermetic_task.hermetic",
            uncovered_components=["comp-a-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
        )
        assert self._row(v, "comp-a-v3-5-ea-2").endswith("| — |")

    def test_jira_sync_created_ticket_in_cell(self):
        v = self._base_violation(
            rule="hermetic_task.hermetic",
            uncovered_components=["comp-a-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
        )
        sync = _jira_sync_with_created("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-10", "https://jira/10")
        row = self._row(v, "comp-a-v3-5-ea-2", jira_sync=sync)
        assert "[RHOAIENG-10](https://jira/10)" in row

    def test_jira_sync_open_existing_in_cell(self):
        v = self._base_violation(
            rule="hermetic_task.hermetic",
            uncovered_components=["comp-a-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
        )
        sync = _jira_sync_with_open("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-20", "https://jira/20")
        row = self._row(v, "comp-a-v3-5-ea-2", jira_sync=sync)
        assert "[RHOAIENG-20](https://jira/20)" in row

    def test_jira_sync_prefill_link_in_cell(self):
        v = self._base_violation(
            rule="hermetic_task.hermetic",
            uncovered_components=["comp-a-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
        )
        sync = _jira_sync_with_prefill("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "https://jira/new?prefill")
        row = self._row(v, "comp-a-v3-5-ea-2", jira_sync=sync)
        assert "[Create](https://jira/new?prefill)" in row

    def test_jira_sync_dedup_by_key_no_duplicate(self):
        # Same ticket present as a coverage open ticket AND in jira_sync -> one link.
        v = self._base_violation(
            rule="hermetic_task.hermetic",
            uncovered_components=["comp-a-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
            open_jira_tickets=[{"key": "RHOAIENG-30", "url": "https://jira/30", "matched_component_stems": ["comp-a"]}],
        )
        sync = _jira_sync_with_created("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-30", "https://jira/30")
        row = self._row(v, "comp-a-v3-5-ea-2", jira_sync=sync)
        assert row.count("[RHOAIENG-30]") == 1

    def test_jira_sync_malformed_falls_back_to_dash(self):
        # Sync dict without a usable "violations" list -> entry is None, no crash.
        v = self._base_violation(
            rule="hermetic_task.hermetic",
            uncovered_components=["comp-a-v3-5-ea-2"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5-ea-2", "file": None, "line": None, "effective_until": None, "url": None}
            ],
        )
        row = self._row(v, "comp-a-v3-5-ea-2", jira_sync={"release": "x", "violations": None})
        assert row.endswith("| — |")

    def test_legacy_singular_matched_component_stem(self):
        """Backward compat: singular matched_component_stem still works."""
        v = self._base_violation(
            uncovered_components=["odh-feature-server-v3-5", "odh-other-tool-v3-5"],
            exception_details_by_component=[
                {"component": "odh-feature-server-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
                {"component": "odh-other-tool-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
            open_jira_tickets=[
                {"key": "RHOAIENG-1", "url": "https://jira/1", "matched_component_stem": "odh-feature-server"},
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        feature_row = next(l for l in lines if "odh-feature-server-v3-5" in l)
        other_row = next(l for l in lines if "odh-other-tool-v3-5" in l)
        assert "[RHOAIENG-1]" in feature_row
        assert "[RHOAIENG-1]" not in other_row

    def test_scoped_jira_appears_only_on_matched_components(self):
        """A ticket with matched_component_stems should only appear on matching rows."""
        v = self._base_violation(
            uncovered_components=["odh-feature-server-v3-5", "odh-other-tool-v3-5"],
            exception_details_by_component=[
                {"component": "odh-feature-server-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
                {"component": "odh-other-tool-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
            open_jira_tickets=[
                {"key": "RHOAIENG-1", "url": "https://jira/1", "matched_component_stems": ["odh-feature-server"]},
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        feature_row = next(l for l in lines if "odh-feature-server-v3-5" in l)
        other_row = next(l for l in lines if "odh-other-tool-v3-5" in l)
        assert "[RHOAIENG-1]" in feature_row
        assert "[RHOAIENG-1]" not in other_row

    def test_mr_deduplication_same_iid_across_versions(self):
        """Same MR covering multiple versions of a component should appear only once per row."""
        v = self._base_violation(
            uncovered_components=["odh-comp-v3-5"],
            exception_details_by_component=[
                {"component": "odh-comp-v3-5", "file": None, "line": None, "effective_until": None, "url": None}
            ],
            open_merge_requests=[
                {
                    "mr_iid": 42, "iid": 42, "url": "https://gl/42",
                    "mr_type": "exception", "suggestion": "extend_mr",
                    "mr_components": ["odh-comp-v3-4", "odh-comp-v3-5", "odh-comp-v2-25"],
                    "covered": [], "missing": [],
                }
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        row = next(l for l in lines if "odh-comp-v3-5" in l)
        assert row.count("[!42]") == 1

    def test_empty_components_renders_nothing(self):
        v = self._base_violation()
        lines = []
        render_components_table(lines, v, {})
        assert lines == []

    def test_component_rows_sorted_alphabetically(self):
        v = self._base_violation(
            uncovered_components=["odh-zzz-v3-5", "odh-aaa-v3-5"],
            exception_details_by_component=[
                {"component": "odh-zzz-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
                {"component": "odh-aaa-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        rows = [l for l in lines if l.startswith("| `")]
        assert "odh-aaa" in rows[0]
        assert "odh-zzz" in rows[1]

    def test_policy_files_linked_in_not_covered_cell(self):
        policy_files = [
            {"name": "fbc-rhoai-prod.yaml", "url": "https://gl/fbc"},
            {"name": "registry-rhoai-prod.yaml", "url": "https://gl/reg"},
        ]
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
        )
        lines = []
        render_components_table(lines, v, {}, policy_files=policy_files)
        row = next(l for l in lines if "comp-a-v3-5" in l)
        assert "[fbc-rhoai-prod.yaml](https://gl/fbc)" in row
        assert "[registry-rhoai-prod.yaml](https://gl/reg)" in row
        assert "not in " in row

    def test_policy_files_none_falls_back_to_plain_text(self):
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
        )
        lines = []
        render_components_table(lines, v, {}, policy_files=None)
        row = next(l for l in lines if "comp-a-v3-5" in l)
        assert "not in policy files" in row

    def test_slack_column_with_threads(self):
        slack_threads = [
            {"channel": "conforma", "permalink": "https://slack/t1", "date": "2026-06-20", "thread_reply_count": 5},
        ]
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
        )
        lines = []
        render_components_table(lines, v, {}, slack_threads=slack_threads, slack_search_url="https://slack/search")
        header = next(l for l in lines if l.startswith("| Component"))
        assert "| Slack |" in header
        row = next(l for l in lines if "comp-a-v3-5" in l)
        assert "[#conforma](https://slack/t1)" in row
        assert "5 replies" in row

    def test_slack_column_with_search_url_only(self):
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
        )
        lines = []
        render_components_table(lines, v, {}, slack_threads=[], slack_search_url="https://slack/search")
        row = next(l for l in lines if "comp-a-v3-5" in l)
        assert "[search Slack](https://slack/search)" in row

    def test_slack_column_omitted_when_not_required(self):
        v = self._base_violation(
            uncovered_components=["comp-a-v3-5"],
            exception_details_by_component=[
                {"component": "comp-a-v3-5", "file": None, "line": None, "effective_until": None, "url": None},
            ],
        )
        lines = []
        render_components_table(lines, v, {})
        header = next(l for l in lines if l.startswith("| Component"))
        assert "Slack" not in header

    def test_heading_contains_exception_coverage_fraction(self):
        coverage_data = {
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "total_components": 5,
                    "covered_count": 3,
                    "coverage": "partially_covered",
                    "covered_components": ["c1", "c2", "c3"],
                    "uncovered_components": ["c4", "c5"],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                },
            ],
            "component_owners": {},
        }
        catalog = {"violations": [], "fallback_references": []}
        out = render_resolution_guide(coverage_data, catalog)
        assert "(3/5 have exceptions)" in out

    def test_search_urls_rendered_inline(self):
        coverage_data = {
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "total_components": 1,
                    "covered_count": 0,
                    "coverage": "not_covered",
                    "covered_components": [],
                    "uncovered_components": ["c1"],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_mr_search_url": "https://gitlab.example.com/search",
                    "open_jira_search_url": "https://jira.example.com/search",
                },
            ],
            "component_owners": {},
        }
        catalog = {"violations": [], "fallback_references": []}
        out = render_resolution_guide(coverage_data, catalog)
        assert "[search GitLab]" not in out
        assert "[search Jira]" not in out


class TestTodoPreviewFile:
    """--todo-file flag produces a TODO preview for chat display."""

    def test_todo_preview_written_when_flag_provided(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        todo_path = tmp_path / TODO_PREVIEW_FILENAME
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            todo_file=str(todo_path),
        )

        assert todo_path.exists()
        content = todo_path.read_text()
        assert "## TODO" in content
        assert "| **Release branch**" in content

    def test_todo_preview_not_written_when_flag_omitted(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert not (tmp_path / TODO_PREVIEW_FILENAME).exists()

    def test_todo_preview_excludes_resolution_guide_content(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        todo_path = tmp_path / TODO_PREVIEW_FILENAME
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            todo_file=str(todo_path),
        )

        content = todo_path.read_text()
        assert "## Resolution Guide" not in content
        assert "## Statistical Breakdown" not in content
        assert "## Violations Coverage" not in content
        assert "## Summary" not in content
        assert "## Detailed Documents" not in content

    def test_full_guide_unchanged_with_todo_flag(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        from datetime import datetime, timezone
        from unittest.mock import patch

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        kwargs = dict(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        frozen = datetime(2026, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
        # All datetime usage (timestamp, expiry parsing) now lives in guide_renderers
        # (generate_resolution_guide no longer imports datetime), so patch there.
        with patch("guide_renderers.datetime") as mock_dt:
            mock_dt.now.return_value = frozen
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            content_without = mod.generate_resolution_guide(**kwargs)
            content_with = mod.generate_resolution_guide(
                **kwargs,
                todo_file=str(tmp_path / "todo.md"),
            )

        assert content_without == content_with


class TestMainAutoExtraction:
    """Tests for main() auto-extracting fields from --metadata-file and context.yaml."""

    def _run_main(self, args, monkeypatch):
        """Run main() with the given args list."""
        monkeypatch.setattr("sys.argv", ["generate_resolution_guide.py"] + args)
        return mod.main()

    def test_auto_extracts_source_from_metadata_file(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "no-conforma"))
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        metadata = {
            "releases": {
                "rhoai-3.5-ea.2": {
                    "source_path": "prod/future/build_type_latest/conforma-violations-report.csv",
                    "created_at": "2026-06-10T05:19:05Z",
                    "source_sha": "abc123def",
                }
            }
        }
        meta_file = tmp_path / "fetch-metadata.json"
        meta_file.write_text(json.dumps(metadata))

        output_file = tmp_path / "guide.md"
        rc = self._run_main([
            "--violations-yaml", str(sample_violations_yaml),
            "--coverage-json", str(sample_coverage_json),
            "--reports-dir", str(tmp_path),
            "--catalog", str(sample_catalog),
            "--release", "rhoai-3.5-ea.2",
            "--metadata-file", str(meta_file),
            "--output", str(output_file),
        ], monkeypatch)

        assert rc == 0
        content = output_file.read_text()
        assert "conforma-violations-report.csv" in content
        assert "abc123def" in content

    def test_auto_extracts_policy_from_context_yaml(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )

        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        conforma_context_ops.create(run_dir, {
            "application": {"name": "rhoai", "release": "rhoai-3.5-ea.2", "version": "3.5-ea.2", "konflux_app": "rhoai-v3-5-ea-2"},
            "environment": "prod",
            "resolve": {
                "end_of_support": "2027-01-15",
                "policy_files": ["policy-prod.yaml"],
                "links": {
                    "policy_dir": "https://gitlab.example.com/policy-dir",
                    "policy_files": [
                        {"name": "policy-prod.yaml", "url": "https://gitlab.example.com/policy-prod.yaml"},
                    ],
                },
            },
        })
        conforma_context_ops.update_step(run_dir, "fetch", "completed",
            csv_files=["rhoai-3.5-ea.2.csv"],
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_sha="abc123",
        )
        conforma_context_ops.update_step(run_dir, "parse", "completed", violations_yaml="violations.yaml")
        conforma_context_ops.update_step(run_dir, "coverage", "completed", coverage_json="coverage.json")
        conforma_context_ops.set_active(run_dir)

        (run_dir / "rhoai-3.5-ea.2.csv").write_text(csv_content)
        import shutil
        shutil.copy(str(sample_violations_yaml), str(run_dir / "violations.yaml"))
        shutil.copy(str(sample_coverage_json), str(run_dir / "coverage.json"))

        output_file = run_dir / "guide.md"
        rc = self._run_main([
            "--catalog", str(sample_catalog),
            "--output", str(output_file),
        ], monkeypatch)

        assert rc == 0
        content = output_file.read_text()
        assert "2027-01-15" in content
        assert "policy-prod.yaml" in content

    def test_cli_args_override_auto_extraction(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "no-conforma"))
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        metadata = {
            "releases": {
                "rhoai-3.5-ea.2": {
                    "source_path": "auto/path.csv",
                    "created_at": "2026-01-01T00:00:00Z",
                    "source_sha": "auto_sha",
                }
            }
        }
        meta_file = tmp_path / "fetch-metadata.json"
        meta_file.write_text(json.dumps(metadata))

        output_file = tmp_path / "guide.md"
        rc = self._run_main([
            "--violations-yaml", str(sample_violations_yaml),
            "--coverage-json", str(sample_coverage_json),
            "--reports-dir", str(tmp_path),
            "--catalog", str(sample_catalog),
            "--release", "rhoai-3.5-ea.2",
            "--metadata-file", str(meta_file),
            "--source-path", "explicit/path.csv",
            "--source-created-at", "2026-06-15T12:00:00Z",
            "--source-sha", "explicit_sha",
            "--output", str(output_file),
        ], monkeypatch)

        assert rc == 0
        content = output_file.read_text()
        assert "explicit/path.csv" in content
        assert "explicit_sha" in content
        assert "auto/path.csv" not in content

    def test_fails_without_source_path_or_metadata_file(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty-workdir"))
        output_file = tmp_path / "guide.md"
        rc = self._run_main([
            "--violations-yaml", str(sample_violations_yaml),
            "--coverage-json", str(sample_coverage_json),
            "--reports-dir", str(tmp_path),
            "--catalog", str(sample_catalog),
            "--release", "rhoai-3.5-ea.2",
            "--output", str(output_file),
        ], monkeypatch)

        assert rc == 1

    @pytest.mark.parametrize("missing", ["coverage", "reports", "catalog"])
    def test_generate_reports_missing_required_input(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, missing
    ):
        paths = {
            "violations": str(sample_violations_yaml),
            "coverage": str(sample_coverage_json),
            "reports": str(tmp_path),
            "catalog": str(sample_catalog),
        }
        if missing == "coverage":
            paths["coverage"] = str(tmp_path / "missing-coverage.json")
        elif missing == "reports":
            paths["reports"] = str(tmp_path / "missing-reports")
        else:
            paths["catalog"] = str(tmp_path / "missing-catalog.yaml")

        with pytest.raises(FileNotFoundError, match=missing):
            mod.generate_resolution_guide(
                violations_yaml_path=paths["violations"],
                coverage_json_path=paths["coverage"],
                reports_dir=paths["reports"],
                catalog_path=paths["catalog"],
                release="rhoai-3.5-ea.2",
                source_path="report.csv",
                source_created_at="2026-06-10T05:19:05Z",
            )

    def test_generate_ignores_invalid_tooling_health_and_reads_work_scope(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)
        invalid_health = tmp_path / "tooling-health.json"
        invalid_health.write_text("not-json")
        violations = yaml.safe_load(sample_violations_yaml.read_text())
        violations["violation_data"]["violations_by_rule"]["hermetic_task.hermetic"]["work_scope"] = {
            "team": "component-team"
        }
        violations_path = tmp_path / "violations.yaml"
        violations_path.write_text(yaml.safe_dump(violations))

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(violations_path),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            tooling_health_path=str(invalid_health),
        )

        assert "Conforma Status and Resolution Guide" in content


# ---------------------------------------------------------------------------
# upcoming_release_date in TODO preview
# ---------------------------------------------------------------------------


class TestUpcomingReleaseDate:
    """Tests for upcoming_release_date in key takeaways and metadata header."""

    @pytest.fixture
    def _coverage_with_expiring_exception(self, tmp_path):
        """Coverage data with a fully_covered violation whose exception expires before release."""
        data = {
            "summary": {"fully_covered": 1, "not_covered": 0, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Build hermetic",
                    "total_components": 1,
                    "all_components": ["comp-a"],
                    "covered_components": ["comp-a"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                        "display_expiry": "expires 2026-07-01",
                    },
                    "exception_details_by_component": [
                        {
                            "component": "comp-a",
                            "effective_until": "2026-07-01",
                            "file": "policy.yaml",
                            "line": 10,
                            "url": "https://gitlab.example.com/policy.yaml#L10",
                        },
                    ],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        path = tmp_path / "coverage_expiring.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    @pytest.fixture
    def _coverage_with_permanent_exception(self, tmp_path):
        """Coverage data with a fully_covered violation with permanent exception."""
        data = {
            "summary": {"fully_covered": 1, "not_covered": 0, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Build hermetic",
                    "total_components": 1,
                    "all_components": ["comp-a"],
                    "covered_components": ["comp-a"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {"is_permanent": True},
                    "exception_details_by_component": [
                        {
                            "component": "comp-a",
                            "effective_until": None,
                            "file": "policy.yaml",
                            "line": 10,
                            "url": "https://gitlab.example.com/policy.yaml#L10",
                        },
                    ],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        path = tmp_path / "coverage_permanent.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_shows_expiring_before_release_table(
        self, tmp_path, sample_violations_yaml, sample_catalog, _coverage_with_expiring_exception
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(_coverage_with_expiring_exception),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        assert "violations with expiring exceptions, no open Merge Request" in content
        assert "| # | Violation | Component | Violations | Effective Until in Existing Exception |" in content
        assert "comp-a" in content
        assert "2026-07-01" in content

    def test_expiring_before_release_appears_before_uncovered(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        data = {
            "summary": {"fully_covered": 1, "not_covered": 1, "total_violations": 2},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Build hermetic",
                    "total_components": 1,
                    "all_components": ["comp-a"],
                    "covered_components": ["comp-a"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                        "display_expiry": "expires 2026-07-01",
                    },
                    "exception_details_by_component": [
                        {
                            "component": "comp-a",
                            "effective_until": "2026-07-01",
                            "file": "policy.yaml",
                            "line": 10,
                            "url": "https://gitlab.example.com/policy.yaml#L10",
                        },
                    ],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
                {
                    "rule": "test.no_failed_tests",
                    "title": "No failed tests",
                    "total_components": 1,
                    "all_components": ["comp-b"],
                    "covered_components": [],
                    "uncovered_components": ["comp-b"],
                    "coverage": "not_covered",
                    "exception_expiry": {"is_permanent": False},
                    "exception_details_by_component": [],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-b,img:sha,"Test failed",,test.no_failed_tests,'
            "No failed tests,desc,Fix tests\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(coverage_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        uncovered_pos = content.index("violations without exception or open Merge Request")
        expiring_pos = content.index("violations with expiring exceptions, no open Merge Request")
        assert uncovered_pos < expiring_pos

    def test_zero_counts_when_exceptions_expire_after_release(
        self, tmp_path, sample_violations_yaml, sample_catalog, _coverage_with_expiring_exception
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(_coverage_with_expiring_exception),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-06-01",
        )

        assert "### TODO #2 — 0 violations with expiring exceptions, no open Merge Request" in content

    def test_no_bullet_when_upcoming_date_empty(
        self, tmp_path, sample_violations_yaml, sample_catalog, _coverage_with_expiring_exception
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(_coverage_with_expiring_exception),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="",
        )

        assert "expire before the upcoming release date" not in content

    def test_permanent_exceptions_excluded_from_count(
        self, tmp_path, sample_violations_yaml, sample_catalog, _coverage_with_permanent_exception
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(_coverage_with_permanent_exception),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        assert "### TODO #2 — 0 violations with expiring exceptions, no open Merge Request" in content

    def test_metadata_header_includes_upcoming_release_date_in_fallback(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        assert "Upcoming release date (RHOAI 3.5)" in header
        assert "2026-08-15" in header
        assert "Product Pages" in header

    def test_metadata_header_omits_upcoming_when_empty(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="",
        )

        assert "Upcoming release date" not in header

    def test_expiring_with_mr_sufficient_expiry(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        """Expiring exception + open Merge Request with expiry past release date → tier 1c."""
        data = {
            "summary": {"fully_covered": 1, "not_covered": 0, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Build hermetic",
                    "total_components": 1,
                    "all_components": ["comp-a"],
                    "covered_components": ["comp-a"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                        "display_expiry": "expires 2026-07-01",
                    },
                    "exception_details_by_component": [
                        {
                            "component": "comp-a",
                            "effective_until": "2026-07-01",
                            "file": "policy.yaml",
                            "line": 10,
                            "url": "https://gitlab.example.com/policy.yaml#L10",
                        },
                    ],
                    "open_merge_requests": [
                        {
                            "iid": 19385,
                            "url": "https://gitlab.example.com/-/merge_requests/19385",
                            "mr_type": "exception",
                            "mr_components": ["comp-a"],
                            "effective_until": "2026-09-01",
                            "suggestion": "fully_covered",
                        },
                    ],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(coverage_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        # Zero-count sections now appear at the end with ✓ marker (sorting puts non-zero first)
        assert "0 violations with expiring exceptions, no open Merge Request ✓ (no action needed)" in content
        assert "1 violations with expiring exceptions, Merge Request extends past release" in content
        assert "[!19385]" in content

    def test_expiring_with_mr_insufficient_expiry(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        """Expiring exception + open Merge Request with expiry also before release → tier 1b."""
        data = {
            "summary": {"fully_covered": 1, "not_covered": 0, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Build hermetic",
                    "total_components": 1,
                    "all_components": ["comp-a"],
                    "covered_components": ["comp-a"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                        "display_expiry": "expires 2026-07-01",
                    },
                    "exception_details_by_component": [
                        {
                            "component": "comp-a",
                            "effective_until": "2026-07-01",
                            "file": "policy.yaml",
                            "line": 10,
                            "url": "https://gitlab.example.com/policy.yaml#L10",
                        },
                    ],
                    "open_merge_requests": [
                        {
                            "iid": 19385,
                            "url": "https://gitlab.example.com/-/merge_requests/19385",
                            "mr_type": "exception",
                            "mr_components": ["comp-a"],
                            "effective_until": "2026-07-15",
                            "suggestion": "fully_covered",
                        },
                    ],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(coverage_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        # With sorting, non-zero sections appear first (no specific TODO number)
        assert "1 violations with expiring exceptions, Merge Request also expires before release" in content
        assert "| Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request |" in content
        assert "2026-07-15" in content
        assert "[!19385]" in content

    def test_expiring_tiers_ordering(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        """All three tiers appear in order: no MR → insufficient MR → sufficient MR."""
        data = {
            "summary": {"fully_covered": 3, "not_covered": 0, "total_violations": 3},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Build hermetic",
                    "total_components": 1,
                    "all_components": ["comp-no-mr"],
                    "covered_components": ["comp-no-mr"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                    },
                    "exception_details_by_component": [
                        {"component": "comp-no-mr", "effective_until": "2026-07-01",
                         "file": "p.yaml", "line": 1, "url": "https://example.com/p.yaml#L1"},
                    ],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
                {
                    "rule": "test.no_failed_tests",
                    "title": "No failed tests",
                    "total_components": 1,
                    "all_components": ["comp-insuf-mr"],
                    "covered_components": ["comp-insuf-mr"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                    },
                    "exception_details_by_component": [
                        {"component": "comp-insuf-mr", "effective_until": "2026-07-01",
                         "file": "p.yaml", "line": 2, "url": "https://example.com/p.yaml#L2"},
                    ],
                    "open_merge_requests": [
                        {"iid": 100, "url": "https://example.com/-/merge_requests/100",
                         "mr_type": "exception", "mr_components": ["comp-insuf-mr"],
                         "effective_until": "2026-07-10", "suggestion": "fully_covered"},
                    ],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
                {
                    "rule": "rpm_signature.allowed",
                    "title": "RPM signature",
                    "total_components": 1,
                    "all_components": ["comp-suf-mr"],
                    "covered_components": ["comp-suf-mr"],
                    "uncovered_components": [],
                    "coverage": "fully_covered",
                    "exception_expiry": {
                        "is_permanent": False,
                        "earliest_expiry": "2026-07-01",
                    },
                    "exception_details_by_component": [
                        {"component": "comp-suf-mr", "effective_until": "2026-07-01",
                         "file": "p.yaml", "line": 3, "url": "https://example.com/p.yaml#L3"},
                    ],
                    "open_merge_requests": [
                        {"iid": 200, "url": "https://example.com/-/merge_requests/200",
                         "mr_type": "exception", "mr_components": ["comp-suf-mr"],
                         "effective_until": "2026-12-31", "suggestion": "fully_covered"},
                    ],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-no-mr,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-insuf-mr,img:sha,"Test failed",,test.no_failed_tests,'
            "No failed,desc,Fix tests\n"
            'violation,comp-suf-mr,img:sha,"Bad sig",,rpm_signature.allowed,'
            "RPM sig,desc,Fix sig\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(coverage_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        # With sorting, check semantic ordering of expiring sections (all have violations)
        # "uncovered" section is zero-count and appears at end with ✓ marker
        no_mr_pos = content.index("expiring exceptions, no open Merge Request")
        insuf_pos = content.index("Merge Request also expires before release")
        suf_pos = content.index("Merge Request extends past release")
        assert no_mr_pos < insuf_pos < suf_pos, "Expiring sections should appear in priority order"

        # Zero-count "uncovered" section should be at end with marker
        assert "0 violations without exception or open Merge Request ✓ (no action needed)" in content

        assert "comp-no-mr" in content
        assert "comp-insuf-mr" in content
        assert "comp-suf-mr" in content

    def test_always_shows_zero_count_headers(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        """All expiring section headers appear even when counts are 0.

        This includes the "open Merge Request expiring before release" section:
        like its sibling expiring sections, it is always rendered (as a
        zero-count "no action needed" entry) whenever a release date is known,
        so the TODO numbering stays contiguous.
        """
        data = {
            "summary": {"fully_covered": 0, "not_covered": 1, "total_violations": 1},
            "violations": [
                {
                    "rule": "test.no_failed_tests",
                    "title": "No failed tests",
                    "total_components": 1,
                    "all_components": ["comp-b"],
                    "covered_components": [],
                    "uncovered_components": ["comp-b"],
                    "coverage": "not_covered",
                    "exception_expiry": {"is_permanent": False},
                    "exception_details_by_component": [],
                    "open_merge_requests": [],
                    "open_jira_tickets": [],
                    "open_slack_threads": [],
                },
            ],
        }
        coverage_path = tmp_path / "coverage.json"
        coverage_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-b,img:sha,"Test failed",,test.no_failed_tests,'
            "No failed tests,desc,Fix tests\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(coverage_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            upcoming_release_date="2026-08-15",
        )

        assert "### TODO #2 — 0 violations with expiring exceptions, no open Merge Request" in content
        assert "### TODO #3 — 0 violations with expiring exceptions, Merge Request also expires before release" in content
        assert "### TODO #4 — 0 violations with expiring exceptions, Merge Request extends past release" in content
        # The MR-expiring section is always rendered too (regression: it was
        # previously dropped when empty, breaking the contiguous numbering).
        assert "0 violations with open Merge Request expiring before release ✓ (no action needed)" in content
        assert "1 violations without exception or open Merge Request" in content
        assert "0 violations addressed by open Merge Requests (not yet merged)" in content


class TestViolationLinks:
    """Violation titles in violations breakdown tables must link to their resolution guide sections."""

    def test_violation_titles_are_anchor_links(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Bad attrs",,sbom_spdx.disallowed_package_attributes,'
            "Disallowed attrs,desc,Fix attrs\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        for rule in ["hermetic_task.hermetic", "sbom_spdx.disallowed_package_attributes"]:
            anchor = mod._violation_anchor(rule)
            link = f"[`{rule}`](#{anchor})"
            todo_section = content.split("\n## TODO\n")[1].split("\n## Summary")[0]
            assert link in todo_section, (
                f"Expected anchor link {link} in TODO section"
            )

    def test_anchor_links_match_resolution_guide_ids(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        anchor = mod._violation_anchor("hermetic_task.hermetic")
        assert f'<a id="{anchor}"></a>' in content
        assert f"[`hermetic_task.hermetic`](#{anchor})" in content


class TestCoverageSummaryPolicyFileLinks:
    """Coverage summary line includes policy file links."""

    def test_coverage_line_includes_file_links(
        self, tmp_path, sample_violations_yaml, sample_catalog,
    ):
        policy_files = [
            {"name": "registry-rhoai-stage.yaml", "url": "https://gitlab.example.com/policy/registry-rhoai-stage.yaml"},
            {"name": "exceptions/fbc-rhoai-stage.yaml", "url": "https://gitlab.example.com/exceptions/fbc-rhoai-stage.yaml"},
        ]
        data = {
            "summary": {
                "fully_covered": 1,
                "partially_covered": 0,
                "not_covered": 1,
                "total_violations": 2,
            },
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Task called with hermetic param set",
                    "total_components": 2,
                    "all_components": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                    "covered_components": ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"],
                    "uncovered_components": [],
                    "covered_count": 2,
                    "uncovered_count": 0,
                    "display_components": "comp-a-v3-5-ea-2, comp-b-v3-5-ea-2",
                    "exception_expiry": {"is_permanent": False, "earliest_expiry": None},
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "",
                    "next_steps": "Rerun",
                    "next_steps_short": "Rerun",
                    "status_label": "Covered",
                    "coverage": "fully_covered",
                    "coverage_label": "covered",
                    "gate_status": "passed",
                    "violation_count": 1,
                },
                {
                    "rule": "sbom_spdx.disallowed_package_attributes",
                    "title": "Disallowed package attributes",
                    "total_components": 1,
                    "all_components": ["comp-a-v3-5-ea-2"],
                    "covered_components": [],
                    "uncovered_components": ["comp-a-v3-5-ea-2"],
                    "covered_count": 0,
                    "uncovered_count": 1,
                    "display_components": "comp-a-v3-5-ea-2",
                    "exception_expiry": {},
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "",
                    "next_steps": "Fix",
                    "next_steps_short": "Fix",
                    "status_label": "No coverage",
                    "coverage": "not_covered",
                    "gate_status": "error",
                    "violation_count": 1,
                },
            ],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | hermetic |\n| 2 | sbom |",
            "component_owners": {
                "comp-a-v3-5-ea-2": "AI Safety",
                "comp-b-v3-5-ea-2": "Model Runtimes",
            },
        }
        cov_path = tmp_path / "coverage.json"
        cov_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-b-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Bad attrs",,sbom_spdx.disallowed_package_attributes,'
            "Disallowed attrs,desc,Fix attrs\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(cov_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            policy_files=policy_files,
        )

        assert "registry-rhoai-stage.yaml" in content
        assert "exceptions/fbc-rhoai-stage.yaml" in content

    def test_metadata_header_includes_self_service_file_links(
        self, tmp_path, sample_violations_yaml, sample_catalog,
    ):
        policy_files = [
            {"name": "registry-rhoai-stage.yaml", "url": "https://gitlab.example.com/policy/registry-rhoai-stage.yaml"},
            {"name": "exceptions/fbc-rhoai-stage.yaml", "url": "https://gitlab.example.com/exceptions/fbc-rhoai-stage.yaml"},
        ]
        data = {
            "summary": {"fully_covered": 0, "partially_covered": 0, "not_covered": 1, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Task called with hermetic param set",
                    "total_components": 1,
                    "all_components": ["comp-a-v3-5-ea-2"],
                    "covered_components": [],
                    "uncovered_components": ["comp-a-v3-5-ea-2"],
                    "covered_count": 0,
                    "uncovered_count": 1,
                    "display_components": "comp-a-v3-5-ea-2",
                    "exception_expiry": {},
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "",
                    "next_steps": "Fix",
                    "next_steps_short": "Fix",
                    "status_label": "No coverage",
                    "coverage": "not_covered",
                    "gate_status": "error",
                    "violation_count": 1,
                },
            ],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | hermetic |",
            "component_owners": {"comp-a-v3-5-ea-2": "AI Safety"},
        }
        cov_path = tmp_path / "coverage.json"
        cov_path.write_text(json.dumps(data), encoding="utf-8")

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(cov_path),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            policy_files=policy_files,
        )

        assert "Conforma policy config" in content
        assert "exceptions/fbc-rhoai-stage.yaml" in content
        assert "https://gitlab.example.com/exceptions/fbc-rhoai-stage.yaml" in content


class TestContextIntegration:
    """Tests for context.yaml auto-discovery and parameter resolution."""

    def _setup_run_with_artifacts(self, tmp_path, monkeypatch, sample_catalog, release="rhoai-3.5-ea.2"):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"

        violations_data = {
            "violation_data": {
                "releases": [release],
                "violations_by_rule": {
                    "hermetic_task.hermetic": {
                        "base_code": "hermetic_task.hermetic",
                        "components": ["comp-a-v3-5-ea-2"],
                    },
                },
                "violations_by_component": {
                    "comp-a-v3-5-ea-2": {"jira_component": "AI Safety"},
                },
            }
        }

        coverage_data = {
            "summary": {"fully_covered": 0, "partially_covered": 0, "not_covered": 1, "total_violations": 1},
            "violations": [{
                "rule": "hermetic_task.hermetic",
                "title": "Hermetic build required",
                "total_components": 1,
                "covered_components": [],
                "uncovered_components": ["comp-a-v3-5-ea-2"],
                "covered_count": 0,
                "uncovered_count": 1,
                "display_components": "comp-a-v3-5-ea-2",
                "open_merge_requests": [],
                "open_mr_label": "",
                "open_mr_search_url": "",
                "open_jira_tickets": [],
                "open_jira_label": "",
                "open_jira_search_url": "",
                "open_slack_threads": [],
                "open_slack_label": "",
                "open_slack_search_url": "",
                "next_steps": "Fix in code",
                "next_steps_short": "Fix in code",
                "status_label": "No coverage",
                "coverage": "not_covered",
                "gate_status": "error",
                "violation_count": 1,
            }],
            "markdown_table": "| # | Violation |\n|---|------|\n| 1 | hermetic |",
            "component_owners": {"comp-a-v3-5-ea-2": "AI Safety"},
        }

        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )

        conforma_context_ops.create(run_dir, {
            "application": {"name": "rhoai", "release": release, "version": "3.5-ea.2", "konflux_app": "rhoai-v3-5-ea-2"},
            "environment": "prod",
            "resolve": {
                "policy_files": ["registry-rhoai-prod.yaml"],
                "end_of_support": "2027-06-01",
            },
        })
        conforma_context_ops.update_step(run_dir, "fetch", "completed",
            csv_files=[f"{release}.csv"],
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_sha="abc123",
        )
        conforma_context_ops.update_step(run_dir, "parse", "completed", violations_yaml="violations.yaml")
        conforma_context_ops.update_step(run_dir, "coverage", "completed", coverage_json="coverage.json")
        conforma_context_ops.set_active(run_dir)

        (run_dir / "violations.yaml").write_text(yaml.dump(violations_data), encoding="utf-8")
        (run_dir / "coverage.json").write_text(json.dumps(coverage_data), encoding="utf-8")
        (run_dir / f"{release}.csv").write_text(csv_content)

        return run_dir

    def test_reads_all_params_from_context(self, tmp_path, monkeypatch, sample_catalog):
        run_dir = self._setup_run_with_artifacts(tmp_path, monkeypatch, sample_catalog)
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
        ])
        rc = mod.main()
        assert rc == 0
        assert (run_dir / "conforma-resolution-guide.md").is_file()
        assert (run_dir / TODO_PREVIEW_FILENAME).is_file()

    def test_updates_context_after_generation(self, tmp_path, monkeypatch, sample_catalog):
        run_dir = self._setup_run_with_artifacts(tmp_path, monkeypatch, sample_catalog)
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
        ])
        mod.main()
        ctx = conforma_context_ops.load(run_dir)
        assert ctx["steps"]["resolution_guide"]["status"] == "completed"
        assert ctx["steps"]["resolution_guide"]["guide_file"] == "conforma-resolution-guide.md"
        assert ctx["steps"]["resolution_guide"]["todo_file"] == TODO_PREVIEW_FILENAME

    def test_source_metadata_from_context(self, tmp_path, monkeypatch, sample_catalog):
        run_dir = self._setup_run_with_artifacts(tmp_path, monkeypatch, sample_catalog)
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
        ])
        mod.main()
        content = (run_dir / "conforma-resolution-guide.md").read_text()
        assert "2026-06-10" in content
        assert "abc123" in content

    def test_no_context_requires_explicit_args(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["generate_resolution_guide.py"])
        rc = mod.main()
        assert rc == 1

    def test_explicit_missing_run_dir_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--run-dir", str(tmp_path / "missing-run"),
        ])
        with pytest.raises(FileNotFoundError):
            mod.main()

    def test_module_entrypoint_help(self, monkeypatch):
        import runpy

        monkeypatch.setattr("sys.argv", ["generate_resolution_guide.py", "--help"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path(mod.__file__, run_name="__main__")
        assert exc_info.value.code == 0

    @pytest.mark.parametrize(
        ("extra_args", "message"),
        [
            (["--release", "rhoai-3.5-ea.2"], "--violations-yaml"),
            (["--release", "rhoai-3.5-ea.2", "--violations-yaml", "v.yaml"], "--coverage-json"),
            (["--release", "rhoai-3.5-ea.2", "--violations-yaml", "v.yaml", "--coverage-json", "c.json"], "--reports-dir"),
            (["--release", "rhoai-3.5-ea.2", "--violations-yaml", "v.yaml", "--coverage-json", "c.json", "--reports-dir", "r"], "--output"),
        ],
    )
    def test_main_requires_each_context_path(self, tmp_path, monkeypatch, extra_args, message):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["generate_resolution_guide.py", *extra_args])
        assert mod.main() == 1

    def test_main_handles_invalid_metadata_and_policy_json(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,Hermetic,desc,Fix\n'
        )
        bad_metadata = tmp_path / "metadata.json"
        bad_metadata.write_text("not-json")
        output = tmp_path / "guide.md"
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty-workdir"))
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--violations-yaml", str(sample_violations_yaml),
            "--coverage-json", str(sample_coverage_json),
            "--reports-dir", str(tmp_path),
            "--catalog", str(sample_catalog),
            "--release", "rhoai-3.5-ea.2",
            "--metadata-file", str(bad_metadata),
            "--policy-files-json", "not-json",
            "--source-path", "report.csv",
            "--source-created-at", "2026-06-10T05:19:05Z",
            "--output", str(output),
        ])

        assert mod.main() == 0
        assert output.exists()

    def test_main_uses_context_analysis_and_tooling_outputs(
        self, tmp_path, monkeypatch, sample_catalog
    ):
        run_dir = self._setup_run_with_artifacts(tmp_path, monkeypatch, sample_catalog)
        (run_dir / "conforma-analysis.md").write_text("analysis")
        (run_dir / "tooling-health.json").write_text(json.dumps({"tools": []}))
        conforma_context_ops.update_step(
            run_dir, "tooling_health", "completed", health_json="tooling-health.json"
        )
        (run_dir / "fetch-metadata.json").write_text(json.dumps({
            "releases": {
                "rhoai-3.5-ea.2": {
                    "source_path": "report.csv",
                    "created_at": "2026-06-10T05:19:05Z",
                    "source_sha": "context-sha",
                },
            },
        }))
        output = run_dir / "guide-with-context-outputs.md"
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
            "--output", str(output),
        ])

        assert mod.main() == 0
        assert output.exists()

    def test_main_reports_generation_file_error(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "rhoai-3.5-ea.2.csv").write_text(
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a,img:sha,"Not hermetic",,hermetic_task.hermetic,Hermetic,desc,Fix\n'
        )
        monkeypatch.setattr(mod, "generate_resolution_guide", lambda **_: (_ for _ in ()).throw(FileNotFoundError("missing")))
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--violations-yaml", str(sample_violations_yaml),
            "--coverage-json", str(sample_coverage_json),
            "--reports-dir", str(reports),
            "--catalog", str(sample_catalog),
            "--release", "rhoai-3.5-ea.2",
            "--source-path", "report.csv",
            "--source-created-at", "2026-06-10T05:19:05Z",
            "--output", str(tmp_path / "guide.md"),
        ])

        assert mod.main() == 1


# ---------------------------------------------------------------------------
# Helpers for TODO / violation-bucket tests
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field
import analyze_csv_report as analysis


def _make_analysis_result(**kwargs):
    """Create an AnalysisResult with sensible defaults, overridable by kwargs."""
    defaults = dict(
        total_violations=10,
        total_csv_rows=20,
        unique_codes=3,
        unique_components=2,
    )
    defaults.update(kwargs)
    return analysis.AnalysisResult(**defaults)


def _make_coverage_data(violations=None, ec_validation=None):
    """Build a minimal coverage_data dict."""
    d = {"violations": violations or []}
    if ec_validation:
        d["ec_validation"] = ec_validation
    return d


def _uncovered_violation(rule, components, open_mrs=None):
    """Create a not_covered violation entry for coverage_data."""
    return {
        "rule": rule,
        "coverage": "not_covered",
        "all_components": components,
        "uncovered_components": components,
        "open_merge_requests": open_mrs or [],
    }


def _covered_violation(rule, components, expiry_details=None, open_mrs=None,
                        is_permanent=False, earliest_expiry=None):
    """Create a fully_covered violation entry for coverage_data."""
    v = {
        "rule": rule,
        "coverage": "fully_covered",
        "all_components": components,
        "uncovered_components": [],
        "open_merge_requests": open_mrs or [],
        "exception_expiry": {
            "is_permanent": is_permanent,
        },
    }
    if earliest_expiry:
        v["exception_expiry"]["earliest_expiry"] = earliest_expiry
    if expiry_details:
        v["exception_details_by_component"] = expiry_details
    return v


def _mr(iid, url, components, effective_until=None):
    """Create an open merge request dict."""
    d = {"iid": iid, "url": url, "mr_components": components}
    if effective_until:
        d["effective_until"] = effective_until
    return d


# ---------------------------------------------------------------------------
# TestExtractedHelpers
# ---------------------------------------------------------------------------

class TestExtractedHelpers:
    """Tests for module-level helper functions extracted from render_key_takeaways."""

    def test_find_covering_mr_found(self):
        mrs = [_mr(1, "https://example.com/1", ["comp-a", "comp-b"])]
        result = _find_covering_mr(mrs, "comp-a")
        assert result is not None
        assert result["iid"] == 1

    def test_find_covering_mr_not_found(self):
        mrs = [_mr(1, "https://example.com/1", ["comp-a"])]
        result = _find_covering_mr(mrs, "comp-z")
        assert result is None

    def test_find_covering_mr_empty_list(self):
        assert _find_covering_mr([], "comp-a") is None

    def test_find_covering_mr_global_coverage(self):
        mrs = [_mr(1, "https://example.com/1", ["*"])]
        result = _find_covering_mr(mrs, "odh-workbench-jupyter-tensorflow-rocm-py312-v3-5")
        assert result is not None
        assert result["iid"] == 1

    def test_find_covering_mr_global_preferred_over_none(self):
        mrs = [
            _mr(1, "https://example.com/1", ["comp-x"]),
            _mr(2, "https://example.com/2", ["*"]),
        ]
        result = _find_covering_mr(mrs, "comp-y")
        assert result is not None
        assert result["iid"] == 2

    def test_violation_count_exact_match(self):
        by_cr = {("hermetic_task.hermetic", "comp-a"): 3}
        assert _violation_count("hermetic_task.hermetic", "comp-a", by_cr) == 3

    def test_violation_count_base_rule_fallback(self):
        by_cr = {("rpm_signature.allowed", "comp-a"): 5}
        assert _violation_count("rpm_signature.allowed:abc123", "comp-a", by_cr) == 5

    def test_violation_count_fallback_to_one(self):
        assert _violation_count("unknown.rule", "comp-x", {}) == 1


# ---------------------------------------------------------------------------
# TestComputeViolationBuckets
# ---------------------------------------------------------------------------

class TestComputeViolationBuckets:
    """Tests for _compute_violation_buckets shared data extraction."""

    def test_buckets_no_violations(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        buckets = _compute_violation_buckets(coverage, result, {})
        assert buckets["no_mr_entries"] == []
        assert buckets["has_mr_entries"] == []
        assert buckets["expiring_no_mr"] == []
        assert buckets["total_violations"] == 0

    def test_buckets_uncovered_no_mr(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("hermetic_task.hermetic", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("hermetic_task.hermetic", "comp-a"): 2}
        buckets = _compute_violation_buckets(coverage, result, by_cr)
        assert len(buckets["no_mr_entries"]) == 1
        assert buckets["no_mr_entries"][0]["violation_count"] == 2
        assert buckets["has_mr_entries"] == []

    def test_buckets_uncovered_with_mr(self):
        mr = _mr(100, "https://example.com/100", ["comp-a"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("hermetic_task.hermetic", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("hermetic_task.hermetic", "comp-a"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr)
        assert len(buckets["has_mr_entries"]) == 1
        assert buckets["no_mr_entries"] == []

    def test_todo_jira_column_keeps_jira_key_from_merge_request_title(self):
        mr = _mr(22104, "https://gitlab.example.com/-/merge_requests/22104", ["comp-a"])
        mr["title"] = "RHOAIENG-88509: Add prod EC policy exceptions"
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("hermetic_task.hermetic", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)

        output = render_key_takeaways(
            coverage,
            result,
            {("hermetic_task.hermetic", "comp-a"): 1},
        )

        assert "[RHOAIENG-88509](https://redhat.atlassian.net/browse/RHOAIENG-88509)" in output

    def test_buckets_expiring_tiers(self):
        mr_insuf = _mr(200, "https://example.com/200", ["comp-a"], effective_until="2026-07-01")
        mr_suf = _mr(201, "https://example.com/201", ["comp-b"], effective_until="2026-09-01")
        coverage = _make_coverage_data(violations=[
            _covered_violation(
                "rule-a", ["comp-a", "comp-b", "comp-c"],
                expiry_details=[
                    {"component": "comp-a", "effective_until": "2026-07-10"},
                    {"component": "comp-b", "effective_until": "2026-07-15"},
                    {"component": "comp-c", "effective_until": "2026-07-20"},
                ],
                open_mrs=[mr_insuf, mr_suf],
            ),
        ])
        result = _make_analysis_result(total_violations=3)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-a", "comp-b"): 1, ("rule-a", "comp-c"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr, upcoming_release_date="2026-08-01")
        assert len(buckets["expiring_no_mr"]) == 1  # comp-c has no MR
        assert buckets["expiring_no_mr"][0]["component"] == "comp-c"
        assert len(buckets["expiring_mr_insufficient"]) == 1  # comp-a MR expires before release
        assert len(buckets["expiring_mr_sufficient"]) == 1  # comp-b MR extends past release

    def test_buckets_counts_match_totals(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a", "comp-b"]),
        ])
        result = _make_analysis_result(total_violations=5)
        by_cr = {("rule-a", "comp-a"): 2, ("rule-a", "comp-b"): 3}
        buckets = _compute_violation_buckets(coverage, result, by_cr)
        assert buckets["covered_violations"] + buckets["not_covered_violations"] == 5

    def test_buckets_uncovered_mr_expires_before_release(self):
        mr = _mr(300, "https://example.com/300", ["*"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr, upcoming_release_date="2026-09-17")
        assert len(buckets["has_mr_expires_before_release"]) == 1
        assert buckets["has_mr_expires_before_release"][0]["mr_effective_until"] == "2026-08-12"
        assert len(buckets["has_mr_ok"]) == 0

    def test_buckets_uncovered_mr_extends_past_release(self):
        mr = _mr(301, "https://example.com/301", ["*"], effective_until="2026-10-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr, upcoming_release_date="2026-09-17")
        assert len(buckets["has_mr_expires_before_release"]) == 0
        assert len(buckets["has_mr_ok"]) == 1

    def test_buckets_uncovered_mr_no_expiry_treated_as_ok(self):
        mr = _mr(302, "https://example.com/302", ["*"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr, upcoming_release_date="2026-09-17")
        assert len(buckets["has_mr_expires_before_release"]) == 0
        assert len(buckets["has_mr_ok"]) == 1

    def test_buckets_uncovered_mr_split_by_expiry(self):
        mr_expiring = _mr(303, "https://example.com/303", ["comp-a"], effective_until="2026-08-12")
        mr_ok = _mr(304, "https://example.com/304", ["comp-b"], effective_until="2026-10-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
            _uncovered_violation("rule-b", ["comp-b"], open_mrs=[mr_ok]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr, upcoming_release_date="2026-09-17")
        assert len(buckets["has_mr_expires_before_release"]) == 1
        assert buckets["has_mr_expires_before_release"][0]["component"] == "comp-a"
        assert len(buckets["has_mr_ok"]) == 1
        assert buckets["has_mr_ok"][0]["component"] == "comp-b"

    def test_buckets_uncovered_mr_no_release_date_all_ok(self):
        mr = _mr(305, "https://example.com/305", ["*"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(coverage, result, by_cr)
        assert len(buckets["has_mr_expires_before_release"]) == 0
        assert len(buckets["has_mr_ok"]) == 1

    def test_buckets_mr21322_exact_scenario_two_components_wildcard(self):
        """Exact MR !21322 bug: wildcard MR effective_until=2026-08-12, release=2026-09-17."""
        mr = _mr(21322, "https://example.com/mr/21322", ["*"],
                 effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation(
                "tasks.required_untrusted_task_found",
                ["rhai-on-openshift-chart-v3-6-ea-1", "rhai-on-xks-chart-v3-6-ea-1"],
                open_mrs=[mr],
            ),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {
            ("tasks.required_untrusted_task_found", "rhai-on-openshift-chart-v3-6-ea-1"): 1,
            ("tasks.required_untrusted_task_found", "rhai-on-xks-chart-v3-6-ea-1"): 1,
        }
        buckets = _compute_violation_buckets(
            coverage, result, by_cr, upcoming_release_date="2026-09-17",
        )
        assert len(buckets["has_mr_expires_before_release"]) == 2
        assert len(buckets["has_mr_ok"]) == 0
        components = {e["component"] for e in buckets["has_mr_expires_before_release"]}
        assert components == {"rhai-on-openshift-chart-v3-6-ea-1", "rhai-on-xks-chart-v3-6-ea-1"}
        for e in buckets["has_mr_expires_before_release"]:
            assert e["mr_effective_until"] == "2026-08-12"

    def test_buckets_mr_effective_until_equals_release_date_is_ok(self):
        """MR effective_until == release date: not before, so treated as ok."""
        mr = _mr(400, "https://example.com/400", ["*"], effective_until="2026-09-17")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(
            coverage, result, by_cr, upcoming_release_date="2026-09-17",
        )
        assert len(buckets["has_mr_expires_before_release"]) == 0
        assert len(buckets["has_mr_ok"]) == 1

    def test_buckets_mr_effective_until_one_day_before_release(self):
        """MR effective_until is one day before release: must be flagged."""
        mr = _mr(401, "https://example.com/401", ["*"], effective_until="2026-09-16")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(
            coverage, result, by_cr, upcoming_release_date="2026-09-17",
        )
        assert len(buckets["has_mr_expires_before_release"]) == 1
        assert len(buckets["has_mr_ok"]) == 0

    def test_buckets_mr_malformed_effective_until_treated_as_ok(self):
        """MR with unparseable effective_until falls through to has_mr_ok."""
        mr = _mr(402, "https://example.com/402", ["*"], effective_until="not-a-date")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(
            coverage, result, by_cr, upcoming_release_date="2026-09-17",
        )
        assert len(buckets["has_mr_expires_before_release"]) == 0
        assert len(buckets["has_mr_ok"]) == 1

    def test_buckets_invalid_upcoming_release_date_all_ok(self):
        """Malformed upcoming_release_date: cannot compare, all go to has_mr_ok."""
        mr = _mr(403, "https://example.com/403", ["*"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        buckets = _compute_violation_buckets(
            coverage, result, by_cr, upcoming_release_date="invalid-date",
        )
        assert len(buckets["has_mr_expires_before_release"]) == 0
        assert len(buckets["has_mr_ok"]) == 1

    def test_buckets_mr_with_named_components_not_wildcard(self):
        """MR with explicit component list (not wildcard) matches only listed components."""
        mr = _mr(404, "https://example.com/404", ["comp-a"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a", "comp-b"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-a", "comp-b"): 1}
        buckets = _compute_violation_buckets(
            coverage, result, by_cr, upcoming_release_date="2026-09-17",
        )
        assert len(buckets["has_mr_expires_before_release"]) == 1
        assert buckets["has_mr_expires_before_release"][0]["component"] == "comp-a"
        assert len(buckets["no_mr_entries"]) == 1
        assert buckets["no_mr_entries"][0]["component"] == "comp-b"


# ---------------------------------------------------------------------------
# TestTodoPreamble — summary preamble in render_key_takeaways()
# ---------------------------------------------------------------------------

class TestTodoPreamble:
    """Tests for the TODO section header in render_key_takeaways()."""

    def test_todo_section_with_violations(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "## TODO" in output
        assert "TODO #1" in output

    def test_todo_section_multiple_actions(self):
        mr = _mr(100, "https://example.com/100", ["comp-b"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
            _uncovered_violation("rule-b", ["comp-b"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "TODO #1" in output
        import re
        todo_nums = re.findall(r"### TODO #(\d+)", output)
        assert len(todo_nums) >= 2

    def test_todo_section_no_actions(self):
        coverage = _make_coverage_data(violations=[
            _covered_violation("rule-a", ["comp-a"], is_permanent=True),
        ])
        result = _make_analysis_result(total_violations=0)
        output = render_key_takeaways(coverage, result, {})
        assert "No TODOs" in output

    def test_todo_section_unhealthy_tooling(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "unhealthy"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "TODO #0" in output
        assert "workflow is failing" in output

    def test_todo_section_with_warnings(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        warnings = [
            analysis.UpcomingViolation(component_name="comp-a", code="warn.a", title="W1", message="msg", effective_on="2026-08-01", days_until_effective=5),
            analysis.UpcomingViolation(component_name="comp-b", code="warn.b", title="W2", message="msg", effective_on="2026-08-02", days_until_effective=6),
        ]
        result = _make_analysis_result(total_violations=1, upcoming_violations=warnings)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "TODO #1" in output
        assert "warnings becoming violations" in output

    def test_todo_section_healthy_tooling(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"}}]}
        output = render_key_takeaways(coverage, result, by_cr, tooling_health_data=tooling)
        assert "Tooling status: healthy" in output
        assert "TODO #1" in output

    def test_todo_mr_expiring_before_release_gets_own_section(self):
        mr_expiring = _mr(400, "https://example.com/400", ["*"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        assert "open Merge Request expiring before release" in output
        assert "2026-08-12" in output
        assert "!400" in output

    def test_todo_mr_ok_expiry_stays_in_addressed_section(self):
        mr_ok = _mr(401, "https://example.com/401", ["*"], effective_until="2026-10-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_ok]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        # The MR's exception extends past release, so the expiring section is a
        # zero-count "no action needed" entry (rendered, not hidden) and the
        # violation stays in the "addressed" section.
        assert "0 violations with open Merge Request expiring before release" in output
        assert "1 violations addressed by open Merge Requests" in output
        assert "!401" in output

    def test_todo_mr_split_expiring_and_ok(self):
        mr_expiring = _mr(402, "https://example.com/402", ["comp-a"], effective_until="2026-08-12")
        mr_ok = _mr(403, "https://example.com/403", ["comp-b"], effective_until="2026-10-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
            _uncovered_violation("rule-b", ["comp-b"], open_mrs=[mr_ok]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        assert "1 violations with open Merge Request expiring before release" in output
        assert "1 violations addressed by open Merge Requests" in output
        assert "!402" in output
        assert "!403" in output

    def test_todo_mr_expiring_section_shown_with_no_action_when_empty(self):
        """When all MRs extend past release, the expiring-before-release TODO is
        still rendered as a zero-count "no action needed" section.

        Regression guard: the reorg that introduced TODO sorting made every
        section always render (zero-count marked "✓ (no action needed)"), but
        this section was left gated on a non-empty bucket, so it silently
        disappeared and the TODO list shrank (e.g. #0–#6 → #0–#5) as soon as
        per-component effectiveUntil dates moved violations into "addressed by
        open Merge Requests". An empty bucket must still produce the section.
        """
        mr_ok = _mr(500, "https://example.com/500", ["*"], effective_until="2026-12-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_ok]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        # The section is present (no longer hidden when empty)...
        assert "0 violations with open Merge Request expiring before release" in output
        # ...and is marked as needing no action, matching its sibling sections.
        assert "0 violations with open Merge Request expiring before release ✓ (no action needed)" in output
        # The MR's component correctly lands in the "addressed" section, not here.
        assert "addressed by open Merge Requests" in output
        assert "comp-a" in output

    def test_todo_numbering_full_set_with_empty_mr_expiring_section(self):
        """Regression guard for the #0-#6 TODO set.

        When the "open Merge Request expiring before release" bucket is empty,
        the full TODO set must still be contiguous 0-6 (7 sections): the
        always-present tooling section, the three expiring-exception sections,
        the empty MR-expiring section (marked no-action), and the addressed-MR
        section. Before the fix this section was conditionally dropped,
        shrinking the list to 0-5.
        """
        import re as _re

        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"}}]}
        # All uncovered violations are addressed by an MR whose exception extends
        # past the release, so the MR-expiring bucket is empty.
        mr_ok = _mr(600, "https://example.com/600", ["comp-a"], effective_until="2026-12-31")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_ok]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            tooling_health_data=tooling,
            upcoming_release_date="2026-09-17",
        )

        todo_nums = [int(n) for n in _re.findall(r"### TODO #(\d+)", output)]
        assert todo_nums == [0, 1, 2, 3, 4, 5, 6], f"expected contiguous TODO #0-#6, got {todo_nums}"

        # The empty MR-expiring section is present and flagged no-action.
        assert "open Merge Request expiring before release ✓ (no action needed)" in output
        # The other sections' presence is intact.
        assert "Tooling status: healthy" in output
        assert "violations without exception or open Merge Request" in output
        assert "violations with expiring exceptions, no open Merge Request" in output
        assert "violations addressed by open Merge Requests" in output

    def test_todo_numbering_with_expiring_mr_section(self):
        """TODO #5 = expiring MR, TODO #6 = addressed MR when both exist."""
        mr_expiring = _mr(501, "https://example.com/501", ["comp-a"], effective_until="2026-08-01")
        mr_ok = _mr(502, "https://example.com/502", ["comp-b"], effective_until="2026-12-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
            _uncovered_violation("rule-b", ["comp-b"], open_mrs=[mr_ok]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        import re as _re
        todo_nums = _re.findall(r"### TODO #(\d+)", output)
        int_nums = [int(n) for n in todo_nums]
        assert int_nums == sorted(int_nums), "TODO numbers must be sequential"
        expiring_todo = None
        addressed_todo = None
        for line in output.split("\n"):
            if "open Merge Request expiring before release" in line:
                expiring_todo = int(_re.search(r"TODO #(\d+)", line).group(1))
            if "addressed by open Merge Requests" in line:
                addressed_todo = int(_re.search(r"TODO #(\d+)", line).group(1))
        assert expiring_todo is not None
        assert addressed_todo is not None
        assert expiring_todo < addressed_todo

    def test_todo_mr_expiring_table_has_effective_until_column(self):
        """The expiring-MR table must include the 'Exception Effective Until in Open Merge Request' column."""
        mr_expiring = _mr(503, "https://example.com/503", ["*"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        assert "Exception Effective Until in Open Merge Request" in output
        assert "2026-08-12" in output

    def test_todo_mr_expiring_warns_even_if_merged(self):
        """Help text warns that merging alone won't fix the issue."""
        mr_expiring = _mr(504, "https://example.com/504", ["*"], effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        assert "Even if merged, the exception will not cover the release" in output

    def test_action_count_separate_for_expiring_and_ok_mr(self):
        """has_mr_expires_count and has_mr_ok_count each contribute to action_count."""
        mr_expiring = _mr(505, "https://example.com/505", ["comp-a"], effective_until="2026-08-01")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr_expiring]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        assert "No TODOs" not in output

    def test_todo_mr21322_rendered_output(self):
        """Full rendering of the exact MR !21322 scenario: 2 components, wildcard MR."""
        mr = _mr(21322, "https://example.com/mr/21322", ["*"],
                 effective_until="2026-08-12")
        coverage = _make_coverage_data(violations=[
            _uncovered_violation(
                "tasks.required_untrusted_task_found",
                ["rhai-on-openshift-chart-v3-6-ea-1", "rhai-on-xks-chart-v3-6-ea-1"],
                open_mrs=[mr],
            ),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {
            ("tasks.required_untrusted_task_found", "rhai-on-openshift-chart-v3-6-ea-1"): 1,
            ("tasks.required_untrusted_task_found", "rhai-on-xks-chart-v3-6-ea-1"): 1,
        }
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-09-17",
        )
        assert "2 violations with open Merge Request expiring before release" in output
        assert "!21322" in output
        assert "rhai-on-openshift-chart-v3-6-ea-1" in output
        assert "rhai-on-xks-chart-v3-6-ea-1" in output
        assert "2026-08-12" in output
        assert "0 violations addressed by open Merge Requests" in output


# ---------------------------------------------------------------------------
# TestKeyTakeawaysToolingTodo
# ---------------------------------------------------------------------------

class TestKeyTakeawaysToolingTodo:
    """Tests for the always-present TODO #0 tooling status section."""

    # --- Unhealthy / error tooling ---

    def test_unhealthy_tooling_emits_todo_0_failing(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "unhealthy"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "### TODO #0 — conforma-reporter workflow is failing" in output

    def test_error_status_emits_todo_0_failing(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "error"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "### TODO #0 — conforma-reporter workflow is failing" in output

    def test_unhealthy_todo_0_includes_actions_link(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "unhealthy"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "conforma-reporter GitHub Actions workflow" in output
        assert "conforma-reporter.yaml" in output

    def test_unhealthy_todo_0_includes_next_steps(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "error"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "**Next steps:**" in output
        assert "Check the latest failed run" in output
        assert "re-run this analysis" in output
        assert "Common failure causes:" in output

    def test_unhealthy_todo_0_stale_data_warning(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "unhealthy"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "violation data in this report may be stale" in output

    def test_unhealthy_todo_0_includes_executive_line(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{
            "name": "conforma-reporter",
            "health": {
                "status": "unhealthy",
                "last_success": {"url": "https://github.com/example/run/1", "completed_at": "2026-08-01T10:00:00Z"},
            },
            "latest_run": {"url": "https://github.com/example/run/2", "updated_at": "2026-08-05T08:00:00Z"},
        }]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "Tooling unhealthy" in output
        assert "last success:" in output

    def test_unhealthy_executive_line_without_previous_success(self):
        line = mod._tooling_health_executive_line({
            "tools": [{
                "name": "conforma-reporter",
                "health": {"status": "unhealthy"},
            }],
        })

        assert "last success: unknown" in line

    def test_multiple_unhealthy_tools_joined_in_heading(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [
            {"name": "conforma-reporter", "health": {"status": "unhealthy"}},
            {"name": "another-tool", "health": {"status": "error"}},
        ]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "### TODO #0 — conforma-reporter, another-tool workflow is failing" in output

    # --- Numbering ---

    def test_todo_0_always_present_shifts_subsequent_numbering(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "unhealthy"}}]}
        output = render_key_takeaways(coverage, result, by_cr, tooling_health_data=tooling)
        assert "### TODO #0" in output
        assert "### TODO #1" in output
        assert "### TODO #2" in output

    def test_healthy_numbering_matches_no_data_numbering(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        healthy_tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"}}]}
        out_healthy = render_key_takeaways(coverage, result, by_cr, tooling_health_data=healthy_tooling)
        out_no_data = render_key_takeaways(coverage, result, by_cr)
        import re
        nums_healthy = re.findall(r"### TODO #(\d+)", out_healthy)
        nums_no_data = re.findall(r"### TODO #(\d+)", out_no_data)
        assert nums_healthy == nums_no_data

    # --- Healthy tooling ---

    def test_healthy_tooling_shows_todo_0_healthy(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"},
                              "latest_run": {"url": "https://gh/run/1", "updated_at": "2026-08-05"}}]}
        output = render_key_takeaways(coverage, result, by_cr, tooling_health_data=tooling)
        assert "### TODO #0 — Tooling status: healthy" in output
        assert "is **healthy**" in output
        assert "### TODO #1" in output

    def test_healthy_todo_0_includes_workflow_link(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"},
                              "latest_run": {"url": "https://gh/run/1", "updated_at": "2026-08-05"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "conforma-reporter workflow](" in output
        assert "conforma-reporter.yaml" in output

    def test_healthy_todo_0_shows_latest_run_info(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"},
                              "latest_run": {"url": "https://gh/run/1", "updated_at": "2026-08-05T04:00:00Z"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "[latest run](https://gh/run/1)" in output
        assert "2026-08-05" in output

    def test_healthy_todo_0_includes_tooling_health_table(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {
            "status": "healthy", "consecutive_failures": 0,
            "last_success": {"id": 1, "url": "https://gh/run/1", "completed_at": "2026-08-05"},
        }, "latest_run": {"id": 2, "url": "https://gh/run/2", "conclusion": "success", "updated_at": "2026-08-06"}}]}

        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)

        assert "| Tool | Status | Latest Run | Consecutive Failures | Last Success |" in output
        assert "| conforma-reporter | HEALTHY | [#2](https://gh/run/2) -- success (2026-08-06) | 0 | [#1](https://gh/run/1) (2026-08-05) |" in output

    def test_healthy_todo_0_no_executive_line(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {"status": "healthy"},
                              "latest_run": {"url": "https://gh/run/1", "updated_at": "2026-08-05"}}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "Tooling unhealthy" not in output

    # --- In-progress tooling ---

    def test_in_progress_tooling_shows_last_success_and_monitor(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        tooling = {"tools": [{"name": "conforma-reporter", "health": {
            "status": "in_progress",
            "last_success": {"url": "https://gh/run/1", "completed_at": "2026-08-05T04:00:00Z"},
            "in_progress_run": {"url": "https://gh/run/2", "created_at": "2026-08-05T12:37:00Z"},
        }}]}
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=tooling)
        assert "last succeeded on 2026-08-05" in output
        assert "[run](https://gh/run/1)" in output
        assert "[more recent run](https://gh/run/2)" in output
        assert "in progress" in output
        assert "monitor" in output

    # --- No tooling data ---

    def test_no_tooling_data_shows_todo_0_healthy(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "### TODO #0 — Tooling status: healthy" in output
        assert "status is unknown" in output
        assert "### TODO #1" in output

    def test_none_tooling_data_shows_todo_0_healthy(self):
        coverage = _make_coverage_data()
        result = _make_analysis_result(total_violations=0)
        output = render_key_takeaways(coverage, result, {}, tooling_health_data=None)
        assert "### TODO #0 — Tooling status: healthy" in output
        assert "status is unknown" in output


# ---------------------------------------------------------------------------
# TestKeyTakeawaysHeading
# ---------------------------------------------------------------------------

class TestKeyTakeawaysHeading:
    """Tests that render_key_takeaways uses the correct heading."""

    def test_heading_is_todo(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert output.startswith("## TODO")
        assert "## Violations Breakdown" not in output
        assert "## Executive Summary" not in output


# ---------------------------------------------------------------------------
# TestKeyTakeawaysAnchors
# ---------------------------------------------------------------------------

class TestKeyTakeawaysAnchors:
    """Tests that render_key_takeaways output has HTML anchors for TODO links."""

    def test_table_anchors_present(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "### TODO #1" in output

    def test_table_anchors_with_expiring(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
            _covered_violation(
                "rule-b", ["comp-b"],
                expiry_details=[{"component": "comp-b", "effective_until": "2026-07-10"}],
            ),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr, upcoming_release_date="2026-08-01",
        )
        assert "### TODO #1" in output
        assert "### TODO #2" in output
        assert "### TODO #3" in output
        assert "### TODO #4" in output

    def test_table5_anchor_present(self):
        mr = _mr(100, "https://example.com/100", ["comp-a"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "### TODO #2" in output

    def test_warnings_todo_section_split_by_release_date(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        warnings = [
            analysis.UpcomingViolation(component_name="comp-a", code="warn.x", title="WX", message="msg", effective_on="2026-08-01", days_until_effective=5),
            analysis.UpcomingViolation(component_name="comp-b", code="warn.y", title="WY", message="msg", effective_on="2026-08-20", days_until_effective=15),
        ]
        result = _make_analysis_result(total_violations=1, upcoming_violations=warnings)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr, upcoming_release_date="2026-08-10")
        assert "warnings becoming violations before release date" in output
        assert "warnings becoming violations within 21 days (after release date)" in output
        assert "will block the release" in output
        assert "will not block this release" in output
        pre_pos = output.index("before release date")
        post_pos = output.index("after release date")
        assert pre_pos < post_pos
        # warn.x (2026-08-01) is before release date 2026-08-10
        pre_section = output[pre_pos:post_pos]
        assert "`warn.x`" in pre_section
        # warn.y (2026-08-20) is after release date 2026-08-10
        post_section = output[post_pos:]
        assert "`warn.y`" in post_section

    def test_warnings_todo_no_release_date_all_in_post(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        warnings = [
            analysis.UpcomingViolation(component_name="comp-a", code="warn.x", title="WX", message="msg", effective_on="2026-08-01", days_until_effective=5),
        ]
        result = _make_analysis_result(total_violations=1, upcoming_violations=warnings)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr, upcoming_release_date="")
        assert "0 warnings becoming violations before release date" in output
        assert "1 warnings becoming violations within 21 days (after release date)" in output

    def test_warnings_todo_table_grouped_and_sorted(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        warnings = [
            analysis.UpcomingViolation(component_name="comp-b", code="warn.late", title="WL", message="msg", effective_on="2026-08-10", days_until_effective=10),
            analysis.UpcomingViolation(component_name="comp-a", code="warn.urgent", title="WU", message="msg", effective_on="2026-07-31", days_until_effective=0),
            analysis.UpcomingViolation(component_name="comp-a", code="warn.late", title="WL", message="msg", effective_on="2026-08-10", days_until_effective=10),
        ]
        result = _make_analysis_result(total_violations=1, upcoming_violations=warnings)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr, upcoming_release_date="2026-08-15")
        assert "3 warnings becoming violations before release date" in output
        assert "**OVERDUE**" in output
        urgent_pos = output.index("warn.urgent")
        late_pos = output.index("warn.late")
        assert urgent_pos < late_pos

    def test_no_warnings_no_todo_section(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1, upcoming_violations=[])
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "warnings becoming violations" not in output

    def test_expiring_exceptions_line(self):
        from datetime import datetime, timezone
        from unittest.mock import patch

        now = datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc)
        coverage = _make_coverage_data(violations=[
            _covered_violation(
                "rule-a", ["comp-a"],
                is_permanent=False,
                earliest_expiry="2026-07-15T00:00:00Z",
            ),
            _uncovered_violation("rule-b", ["comp-b"]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        with patch("guide_renderers.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.strptime = datetime.strptime
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            output = render_key_takeaways(coverage, result, by_cr)
        assert "Exceptions expiring in next 14 days" in output


class TestTodoHelpText:
    """Each TODO section includes a help text paragraph below the header."""

    def test_todo1_help_text(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "click the violation code to see details and next steps" in output
        assert "Try to resolve the issue in code first" not in output

    def test_todo2_help_text_includes_version(self):
        coverage = _make_coverage_data(violations=[
            _covered_violation(
                "rule-a", ["comp-a"],
                expiry_details=[{"component": "comp-a", "effective_until": "2026-07-10"}],
            ),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr,
            upcoming_release_date="2026-08-15",
            release="rhoai-3.5",
        )
        assert "expire before the planned release date" in output
        assert "extend the exception past the release date" in output

    def test_todo3_help_text(self):
        mr = _mr(100, "https://example.com/100", ["comp-a"], effective_until="2026-07-20")
        coverage = _make_coverage_data(violations=[
            _covered_violation(
                "rule-a", ["comp-a"],
                expiry_details=[{"component": "comp-a", "effective_until": "2026-07-10"}],
                open_mrs=[mr],
            ),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr, upcoming_release_date="2026-08-15",
        )
        assert "proposed effective-until dates also expire before the release" in output

    def test_todo4_help_text(self):
        mr = _mr(200, "https://example.com/200", ["comp-a"], effective_until="2026-12-31")
        coverage = _make_coverage_data(violations=[
            _covered_violation(
                "rule-a", ["comp-a"],
                expiry_details=[{"component": "comp-a", "effective_until": "2026-07-10"}],
                open_mrs=[mr],
            ),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr, upcoming_release_date="2026-08-15",
        )
        assert "Track and ensure they get merged before the release" in output

    def test_todo5_help_text(self):
        mr = _mr(100, "https://example.com/100", ["comp-a"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "Track and ensure they get merged" in output
        assert "Click each violation for details" in output


class TestHorizontalRuleSeparators:
    """Sections are separated by horizontal rules, not &nbsp; spacers."""

    def test_horizontal_rules_present(self):
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
        ])
        result = _make_analysis_result(total_violations=1)
        by_cr = {("rule-a", "comp-a"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "\n---\n" in output

    def test_no_nbsp_separators(self):
        mr = _mr(100, "https://example.com/100", ["comp-a"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
            _uncovered_violation("rule-b", ["comp-b"], open_mrs=[mr]),
            _covered_violation(
                "rule-c", ["comp-c"],
                expiry_details=[{"component": "comp-c", "effective_until": "2026-07-10"}],
            ),
        ])
        result = _make_analysis_result(total_violations=3)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1, ("rule-c", "comp-c"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr, upcoming_release_date="2026-08-15",
        )
        assert "&nbsp;" not in output

    def test_todo_headings_preceded_by_rendered_gap(self):
        """Every TODO heading after the first must be preceded by a blank
        line and a rendered <br> so sections do not visually merge with the
        preceding --- horizontal rule."""
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
            _uncovered_violation("rule-b", ["comp-b"]),
            _covered_violation(
                "rule-c", ["comp-c"],
                expiry_details=[{"component": "comp-c", "effective_until": "2026-07-10"}],
            ),
        ])
        result = _make_analysis_result(total_violations=3)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1, ("rule-c", "comp-c"): 1}
        output = render_key_takeaways(
            coverage, result, by_cr, upcoming_release_date="2026-08-15",
        )
        headings = [line for line in output.split("\n") if line.startswith("### TODO #")]
        assert len(headings) >= 2
        # The first heading must not be preceded by a <br> gap.
        assert output.index("<br>") > output.index("### TODO #0")
        # Every subsequent heading is separated from the previous section
        # by a blank line and a rendered gap.
        for heading in headings[1:]:
            assert f"\n<br>\n{heading}" in output

    def test_no_doubled_trailing_horizontal_rule(self):
        """Each section body ends with ---; the breakdown must not append a
        second --- after the last section (no doubled rule)."""
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
            _uncovered_violation("rule-b", ["comp-b"]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "---\n---" not in output
        # Exactly one trailing rule after the last section body.
        assert output.rstrip("\n").endswith("---")


# ---------------------------------------------------------------------------
# TestTodoPreviewContent
# ---------------------------------------------------------------------------

class TestTodoPreviewContent:
    """Tests that write_todo_preview orders metadata before TODO."""

    def test_metadata_appears_before_todo(self, tmp_path):
        out_path = str(tmp_path / "todo.md")
        write_todo_preview(
            out_path,
            metadata_header="# Header\n",
            key_takeaways="## TODO\n\n### TODO #1 — 1 violation\n",
        )
        content = Path(out_path).read_text()
        header_pos = content.index("# Header")
        todo_pos = content.index("## TODO")
        assert header_pos < todo_pos

    def test_todo_anchors_resolve_within_key_takeaways(self, tmp_path):
        import re
        mr = _mr(100, "https://example.com/100", ["comp-b"])
        coverage = _make_coverage_data(violations=[
            _uncovered_violation("rule-a", ["comp-a"]),
            _uncovered_violation("rule-b", ["comp-b"], open_mrs=[mr]),
        ])
        result = _make_analysis_result(total_violations=2)
        by_cr = {("rule-a", "comp-a"): 1, ("rule-b", "comp-b"): 1}
        output = render_key_takeaways(coverage, result, by_cr)
        assert "### TODO #1" in output
        assert "### TODO #2" in output


# ---------------------------------------------------------------------------
# TestGuideSourceCsvRowsAndAiModel
# ---------------------------------------------------------------------------

class TestGuideSourceCsvRowsAndAiModel:
    """End-to-end: raw source-CSV row count and LLM model footer in the guide."""

    # Two raw rows sharing one (code, component, detail) triple:
    # raw source-CSV rows = 2, deduplicated violations = 1.
    CSV_CONTENT = (
        "type,component_name,image,message,effective_on,code,title,description,solution\n"
        'violation,comp-a-v3-5-ea-2,img1:sha,"Not hermetic",,hermetic_task.hermetic,'
        "Hermetic,desc,Enable hermetic\n"
        'violation,comp-a-v3-5-ea-2,img2:sha,"Not hermetic",,hermetic_task.hermetic,'
        "Hermetic,desc,Enable hermetic\n"
    )

    def _generate(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, **kwargs
    ):
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT)
        return mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            **kwargs,
        )

    def test_source_csv_rows_falls_back_to_raw_row_count(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        content = self._generate(
            tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
        )
        assert "| **Source CSV rows (raw, per-image)** | 2 |" in content
        assert "| **Total violations (deduplicated per image)** | 1 |" in content

    def test_source_csv_rows_override(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        content = self._generate(
            tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog,
            source_csv_rows=1055,
        )
        assert "| **Source CSV rows (raw, per-image)** | 1,055 |" in content

    def test_ai_model_footer_in_guide(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        content = self._generate(
            tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog,
            ai_model="claude-sonnet-4-5",
        )
        assert (
            "*Generated by: aiops-infra conforma-analyze skill (LLM: claude-sonnet-4-5)*"
            in content
        )

    def test_analysis_output_file_header_includes_ai_model(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT)
        analysis_file = tmp_path / "conforma-analysis.md"
        analysis_file.write_text(
            "**Report**: conforma-violations-report.csv\n"
            "# Conforma Violations Analysis: rhoai-3.5-ea.2\n"
            "\n"
            "Body content here.\n",
        )
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            analysis_output_file=str(analysis_file),
            ai_model="claude-sonnet-4-5",
        )
        new_analysis = analysis_file.read_text()
        assert "# Conforma Analysis: rhoai-3.5-ea.2" in new_analysis
        assert "(LLM: claude-sonnet-4-5)" in new_analysis
        assert "**Report**:" not in new_analysis
        assert "Body content here." in new_analysis

    def test_analysis_output_file_header_includes_source_statistics(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT)
        analysis_file = tmp_path / "conforma-analysis.md"
        analysis_file.write_text("Body content here.\n")
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            analysis_output_file=str(analysis_file),
        )
        new_analysis = analysis_file.read_text()
        # Same structure as the Step 9 guide header: source CSV statistics rows.
        assert "| **Source CSV rows (raw, per-image)** | 2 |" in new_analysis
        assert "| **Total violations (deduplicated per image)** | 1 |" in new_analysis

    def test_ai_model_cli_flag(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "no-conforma"))
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT)
        output_file = tmp_path / "guide.md"
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--violations-yaml", str(sample_violations_yaml),
            "--coverage-json", str(sample_coverage_json),
            "--reports-dir", str(tmp_path),
            "--catalog", str(sample_catalog),
            "--release", "rhoai-3.5-ea.2",
            "--source-path", "prod/future/build_type_latest/conforma-violations-report.csv",
            "--source-created-at", "2026-06-10T05:19:05Z",
            "--ai-model", "test-model-123",
            "--output", str(output_file),
        ])
        assert mod.main() == 0
        content = output_file.read_text()
        assert (
            "*Generated by: aiops-infra conforma-analyze skill (LLM: test-model-123)*"
            in content
        )

    def test_ai_model_from_context_yaml(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260703-120000"
        conforma_context_ops.create(run_dir, {
            "application": {
                "name": "rhoai",
                "release": "rhoai-3.5-ea.2",
                "version": "3.5-ea.2",
                "konflux_app": "rhoai-v3-5-ea-2",
            },
            "environment": "prod",
            "ai_model": "context-model-456",
        })
        conforma_context_ops.update_step(run_dir, "fetch", "completed",
            csv_files=["rhoai-3.5-ea.2.csv"],
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_sha="abc123",
        )
        conforma_context_ops.update_step(run_dir, "parse", "completed", violations_yaml="violations.yaml")
        conforma_context_ops.update_step(run_dir, "coverage", "completed", coverage_json="coverage.json")
        conforma_context_ops.set_active(run_dir)

        (run_dir / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT)
        import shutil
        shutil.copy(str(sample_violations_yaml), str(run_dir / "violations.yaml"))
        shutil.copy(str(sample_coverage_json), str(run_dir / "coverage.json"))

        output_file = run_dir / "guide.md"
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
            "--output", str(output_file),
        ])
        assert mod.main() == 0
        content = output_file.read_text()
        assert (
            "*Generated by: aiops-infra conforma-analyze skill (LLM: context-model-456)*"
            in content
        )


# ---------------------------------------------------------------------------
# C9 — Jira sync integration (jira_sync.json -> renderers)
# ---------------------------------------------------------------------------
def _jira_sync_with_created(rule: str, konflux_components: list[str], created_key: str, created_url: str) -> dict:
    """Build a minimal jira_sync.json-shaped dict with one created ticket."""
    return {
        "release": "rhoai-3.6-ea2",
        "violations": [
            {
                "rule": rule,
                "uncovered_components": konflux_components,
                "groups": [
                    {
                        "konflux_components": konflux_components,
                        "jira_component": "AI Safety",
                        "team": "AI Safety",
                        "existing": None,
                        "created": {"key": created_key, "url": created_url},
                    }
                ],
            }
        ],
        "dry_run": False,
    }


def _jira_sync_with_open(rule: str, konflux_components: list[str], open_key: str, open_url: str) -> dict:
    """Build a jira_sync.json-shaped dict where the group has an open ticket."""
    return {
        "release": "rhoai-3.6-ea2",
        "violations": [
            {
                "rule": rule,
                "uncovered_components": konflux_components,
                "groups": [
                    {
                        "konflux_components": konflux_components,
                        "jira_component": "AI Safety",
                        "team": "AI Safety",
                        "existing": {
                            "key": open_key,
                            "url": open_url,
                            "status": "In Progress",
                            "release_relevance": "same release",
                        },
                        "created": None,
                        "create_url": None,
                    }
                ],
            }
        ],
        "dry_run": False,
    }


def _jira_sync_with_prefill(rule: str, konflux_components: list[str], create_url: str) -> dict:
    """Build a jira_sync.json-shaped dict where the group has no ticket yet."""
    return {
        "release": "rhoai-3.6-ea2",
        "violations": [
            {
                "rule": rule,
                "uncovered_components": konflux_components,
                "groups": [
                    {
                        "konflux_components": konflux_components,
                        "jira_component": "AI Safety",
                        "team": "AI Safety",
                        "existing": None,
                        "created": None,
                    "create_url": create_url,
                    "related_search_url": "https://jira/issues/?jql=related",
                    "unique_labels": ["conforma-rhoai-3-6-ea-2-comp-a-hermetic-task-hermetic"],
                    }
                ],
            }
        ],
        "dry_run": False,
    }


class TestRenderJiraTickets:
    """render_jira_tickets per-violation block behavior."""

    def test_no_sync_is_noop(self):
        lines: list[str] = []
        render_jira_tickets(lines, {"rule": "hermetic_task.hermetic"}, None)
        assert lines == []

    def test_sync_without_matching_rule_is_noop(self):
        lines: list[str] = []
        sync = _jira_sync_with_created("other.rule", ["comp-a-v3-5-ea-2"], "RHOAIENG-1", "https://jira/1")
        render_jira_tickets(lines, {"rule": "hermetic_task.hermetic"}, sync)
        assert lines == []

    def test_created_ticket_rendered(self):
        lines: list[str] = []
        sync = _jira_sync_with_created("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-1", "https://jira/1")
        render_jira_tickets(lines, {"rule": "hermetic_task.hermetic"}, sync)
        joined = "\n".join(lines)
        assert "**Jira tickets:**" in joined
        assert "**Created this run:**" in joined
        assert "[RHOAIENG-1](https://jira/1)" in joined

    def test_open_ticket_rendered_with_status(self):
        lines: list[str] = []
        sync = _jira_sync_with_open("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-2", "https://jira/2")
        render_jira_tickets(lines, {"rule": "hermetic_task.hermetic"}, sync)
        joined = "\n".join(lines)
        assert "**Jira tickets:**" in joined
        assert "**Open tickets:**" in joined
        assert "[RHOAIENG-2](https://jira/2) (In Progress)" in joined
        assert "same release" in joined

    def test_prefill_create_link_rendered(self):
        lines: list[str] = []
        sync = _jira_sync_with_prefill("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "https://jira/new?prefill")
        render_jira_tickets(lines, {"rule": "hermetic_task.hermetic"}, sync)
        joined = "\n".join(lines)
        assert "**Jira tickets:**" in joined
        assert "**Create Jira ticket**" in joined
        assert "[create pre-filled](https://jira/new?prefill)" in joined

    def test_related_search_link_rendered_in_create_cell(self):
        sync = _jira_sync_with_prefill("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "https://jira/new?prefill")
        from guide_renderers import _sync_component_cells

        refs, create_url, search_url, label = _sync_component_cells(
            sync["violations"][0], "comp-a-v3-5-ea-2"
        )
        assert refs == []
        assert create_url == "https://jira/new?prefill"
        assert search_url == "https://jira/issues/?jql=related"
        assert label == "conforma-rhoai-3-6-ea-2-comp-a-hermetic-task-hermetic"
        assert "[Search related Jira (label: `conforma-rhoai-3-6-ea-2-comp-a-hermetic-task-hermetic`)](https://jira/issues/?jql=related)" in _build_jira_cell(
            [], [], refs, create_url, search_url, label
        )

    def test_rule_with_colon_matches_base_rule(self):
        lines: list[str] = []
        sync = _jira_sync_with_created("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-3", "https://jira/3")
        render_jira_tickets(lines, {"rule": "hermetic_task.hermetic:9386b48a"}, sync)
        joined = "\n".join(lines)
        assert "[RHOAIENG-3](https://jira/3)" in joined


class TestRenderResolutionGuideJira:
    """render_resolution_guide keeps Jira table columns stable across sync states."""

    @pytest.fixture
    def coverage_with_one_violation(self) -> dict:
        return {
            "summary": {"fully_covered": 0, "partially_covered": 0, "not_covered": 1, "total_violations": 1},
            "violations": [
                {
                    "rule": "hermetic_task.hermetic",
                    "title": "Hermetic",
                    "total_components": 1,
                    "covered_components": [],
                    "uncovered_components": ["comp-a-v3-5-ea-2"],
                    "covered_count": 0,
                    "uncovered_count": 1,
                    "display_components": "comp-a-v3-5-ea-2 (AI Safety)",
                    "open_merge_requests": [],
                    "open_mr_label": "",
                    "open_mr_search_url": "",
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_jira_search_url": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "open_slack_search_url": "",
                    "next_steps": "Fix",
                    "next_steps_short": "Fix",
                    "status_label": "Not covered",
                    "coverage": "not_covered",
                    "gate_status": "error",
                }
            ],
            "component_owners": {"comp-a-v3-5-ea-2": "AI Safety"},
        }

    def test_jira_sync_none_keeps_jira_columns_in_todo_tables(
        self, coverage_with_one_violation: dict, sample_catalog: Path
    ):
        catalog = mod._load_catalog(sample_catalog)
        baseline = render_resolution_guide(coverage_with_one_violation, catalog)
        with_none = render_resolution_guide(coverage_with_one_violation, catalog, jira_sync=None)
        assert baseline == with_none
        assert "**Jira tickets:**" not in baseline

    def test_jira_sync_with_created_renders_block(
        self, coverage_with_one_violation: dict, sample_catalog: Path
    ):
        catalog = mod._load_catalog(sample_catalog)
        sync = _jira_sync_with_created("hermetic_task.hermetic", ["comp-a-v3-5-ea-2"], "RHOAIENG-1", "https://jira/1")
        out = render_resolution_guide(coverage_with_one_violation, catalog, jira_sync=sync)
        assert "**Jira tickets:**" in out
        assert "[RHOAIENG-1](https://jira/1)" in out

    def test_jira_sync_unrelated_rule_is_noop(
        self, coverage_with_one_violation: dict, sample_catalog: Path
    ):
        catalog = mod._load_catalog(sample_catalog)
        sync = _jira_sync_with_created("other.rule", ["comp-a-v3-5-ea-2"], "RHOAIENG-9", "https://jira/9")
        out = render_resolution_guide(coverage_with_one_violation, catalog, jira_sync=sync)
        assert "**Jira tickets:**" not in out


class TestGenerateResolutionGuideWithJiraSync:
    """End-to-end: generate_resolution_guide reads jira_sync.json and renders the Jira block."""

    CSV_CONTENT = (
        "type,component_name,image,message,effective_on,code,title,description,solution\n"
        'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
        "Hermetic,desc,Enable hermetic\n"
    )

    def _generate(self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, jira_sync=None) -> str:
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT, encoding="utf-8")
        jira_sync_path = None
        if jira_sync is not None:
            jira_sync_path = tmp_path / "jira_sync.json"
            jira_sync_path.write_text(json.dumps(jira_sync), encoding="utf-8")
        return mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            jira_sync_path=jira_sync_path,
        )

    def test_absent_jira_sync_is_fallback(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        content = self._generate(tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog)
        assert "**Jira tickets:**" not in content
        assert "| # | Violation | Component | Violations | Jira |" in content
        assert "| 1 |" in content and "| — |" in content
        assert "## Resolution Guide" in content

    def test_jira_sync_renders_block(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        sync = _jira_sync_with_created(
            "hermetic_task.hermetic", ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"], "RHOAIENG-1", "https://jira/1"
        )
        content = self._generate(tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, sync)
        assert "**Jira tickets:**" in content
        assert "[RHOAIENG-1](https://jira/1)" in content

    def test_jira_sync_renders_components_table_cell(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        """End-to-end: the created ticket must land in the components-table JIRAS
        cell (jira_sync -> render_resolution_guide -> render_components_table), not
        only in the per-violation Jira tickets block."""
        sync = _jira_sync_with_created(
            "hermetic_task.hermetic", ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"], "RHOAIENG-1", "https://jira/1"
        )
        content = self._generate(tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, sync)
        cell_rows = [
            line
            for line in content.splitlines()
            if line.startswith("| `comp-a-v3-5-ea-2`") and "[RHOAIENG-1](https://jira/1)" in line
        ]
        assert cell_rows, "JIRAS cell should carry the created ticket in the components table"
        # comp-b is uncovered for the same rule -> its JIRAS cell carries the ticket too.
        cell_rows_b = [
            line
            for line in content.splitlines()
            if line.startswith("| `comp-b-v3-5-ea-2`") and "[RHOAIENG-1](https://jira/1)" in line
        ]
        assert cell_rows_b, "JIRAS cell should carry the created ticket for the second component"

    def test_malformed_jira_sync_is_fallback(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT, encoding="utf-8")
        bad = tmp_path / "jira_sync.json"
        bad.write_text("{not valid json", encoding="utf-8")
        content = mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            jira_sync_path=str(bad),
        )
        assert "**Jira tickets:**" not in content

    def test_main_reads_jira_sync_from_run_dir(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog, monkeypatch
    ):
        run_dir = tmp_path / "run"
        conforma_context_ops.create(run_dir, {
            "application": {"name": "rhoai", "release": "rhoai-3.5-ea.2", "version": "3.5-ea.2"},
            "environment": "prod",
        })
        conforma_context_ops.update_step(run_dir, "fetch", "completed",
            csv_files=["rhoai-3.5-ea.2.csv"],
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            source_sha="abc123",
        )
        (run_dir / "rhoai-3.5-ea.2.csv").write_text(self.CSV_CONTENT, encoding="utf-8")
        import shutil
        shutil.copy(str(sample_violations_yaml), str(run_dir / "violations.yaml"))
        shutil.copy(str(sample_coverage_json), str(run_dir / "coverage.json"))
        conforma_context_ops.update_step(run_dir, "parse", "completed", violations_yaml="violations.yaml")
        conforma_context_ops.update_step(run_dir, "coverage", "completed", coverage_json="coverage.json")
        sync = _jira_sync_with_created(
            "hermetic_task.hermetic", ["comp-a-v3-5-ea-2", "comp-b-v3-5-ea-2"], "RHOAIENG-7", "https://jira/7"
        )
        (run_dir / "jira_sync.json").write_text(json.dumps(sync), encoding="utf-8")

        # Isolate run-dir discovery to a tmp work dir (never touch ~/.conforma/.conforma-active).
        work_dir = tmp_path / ".conforma"
        work_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        (work_dir / ".conforma-active").symlink_to(run_dir)

        output_file = run_dir / "guide.md"
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
            "--output", str(output_file),
        ])
        assert mod.main() == 0
        content = output_file.read_text()
        assert "**Jira tickets:**" in content
        assert "[RHOAIENG-7](https://jira/7)" in content


class TestGuideRendererBranchCoverage:
    """Exercise the less common renderer inputs used by the report workflow."""

    def test_catalog_fallback_false_alert_and_detail_helpers(self, sample_catalog):
        catalog = mod._load_catalog(sample_catalog)
        assert renderers._match_catalog_entry("prefix.rule", {"violations": [{"conforma_rule_codes": ["prefix"]}]})
        assert renderers._match_fallback_reference("source_image.new", catalog)
        assert renderers._match_known_false_alert("test.no_failed_tests", "rhoai-fbc-fragment-v3-5", catalog)
        assert renderers._truncate_detail("short") == "short"
        long_text = "x" * 61
        assert renderers._truncate_detail(long_text).endswith("…")
        long_url = "https://example.com/" + "x" * 61
        assert renderers._truncate_detail(long_url).startswith("[https://")

    def test_metadata_header_optional_rows_and_policy_directory(self):
        output = render_metadata_header(
            "rhoai-3.6",
            "prod/report.csv",
            "",
            policy_dir_url="https://gitlab.example/policy",
        )
        assert "policy directory" in output
        assert "set after the source CSV is fetched" in output

    def test_bucket_date_variants(self):
        mr = _mr(10, "https://example/mr/10", ["comp-a"], "2026-10-01")
        mr["effective_until_by_component"] = {"comp-a": "2026-08-01"}
        covered = _covered_violation(
            "rule.a",
            ["comp-a", "comp-b", "comp-c"],
            expiry_details=[
                {"component": "comp-a", "effective_until": "2026-08-01"},
                {"component": "comp-b", "effective_until": "not-a-date"},
                {"component": "comp-c", "effective_until": "2026-08-01"},
            ],
            open_mrs=[mr],
            earliest_expiry="2999-01-01",
        )
        covered["exception_details_by_component"].append(
            {"component": "comp-c", "effective_until": "2026-08-01", "exception_value": "rule.other"}
        )
        uncovered_mr = _uncovered_violation("rule.b", ["comp-a"], open_mrs=[mr])
        no_date = _covered_violation(
            "rule.c", ["comp-d"], expiry_details=[
                {"component": "comp-d"},
                {"component": "comp-d", "effective_until": "2026-08-01"},
            ],
        )
        malformed_mr = _mr(11, "https://example/mr/11", ["comp-d"], "not-a-date")
        no_date["open_merge_requests"] = [malformed_mr]
        covered["exception_expiry"]["earliest_expiry"] = "2026-09-18"
        invalid_expiry = _covered_violation(
            "rule.d", ["comp-e"], earliest_expiry="not-a-date",
        )
        result = _make_analysis_result(total_violations=3)
        buckets = _compute_violation_buckets(
            _make_coverage_data([covered, uncovered_mr, no_date, invalid_expiry]), result,
            {("rule.a", "comp-a"): 1, ("rule.a", "comp-b"): 1, ("rule.a", "comp-c"): 1,
             ("rule.b", "comp-a"): 1, ("rule.c", "comp-d"): 1},
            upcoming_release_date="2026-09-01",
        )
        assert buckets["expiring_mr_insufficient"]
        assert buckets["expiring_no_mr"]
        assert buckets["expiring_soon"]

    def test_key_takeaways_renders_single_and_multiple_semantic_details(self, monkeypatch):
        details = [f"detail-{i}" for i in range(16)]
        monkeypatch.setattr(
            renderers,
            "build_semantic_detail_lookup",
            lambda _: ({("rule.a", "comp-a"): details}, {"rule.a": "detail"}),
        )
        coverage = _make_coverage_data([_uncovered_violation("rule.a", ["comp-a"])])
        output = render_key_takeaways(
            coverage,
            _make_analysis_result(total_violations=1),
            {("rule.a", "comp-a"): 1},
            violations_yaml_data={"anything": True},
        )
        assert "detail-0" in output
        assert "+1 more details" in output

        monkeypatch.setattr(
            renderers,
            "build_semantic_detail_lookup",
            lambda _: ({("rule.a", "comp-a"): ["one detail"]}, {"rule.a": "detail"}),
        )
        output = render_key_takeaways(
            coverage,
            _make_analysis_result(total_violations=1),
            {("rule.a", "comp-a"): 1},
            violations_yaml_data={"anything": True},
        )
        assert "one detail" in output

    def test_key_takeaways_renders_jira_create_and_divergence(self):
        sync = _jira_sync_with_prefill("rule.a", ["comp-a"], "https://jira/create")
        coverage = _make_coverage_data([_uncovered_violation("rule.a", ["comp-a"])])
        coverage["ec_validation"] = {"divergence_count": 1}
        output = render_key_takeaways(
            coverage,
            _make_analysis_result(total_violations=1),
            {("rule.a", "comp-a"): 1},
            jira_sync=sync,
        )
        assert "[Create](https://jira/create)" in output
        assert "Search related Jira" in output

    def test_warning_and_resolution_renderers_cover_optional_fields(self):
        warning_one = analysis.UpcomingViolation(
            component_name="comp-a", code="rule.a", title="A", message="m",
            effective_on="2026-09-01", days_until_effective=0, semantic_detail="detail",
        )
        warning_two = analysis.UpcomingViolation(
            component_name="comp-b", code="rule.a", title="A", message="m",
            effective_on="2026-09-02", days_until_effective=5, semantic_detail="later",
        )
        warning_three = analysis.UpcomingViolation(
            component_name="comp-a", code="rule.a", title="A", message="m",
            effective_on="2026-08-31", days_until_effective=-1, semantic_detail="detail",
        )
        result = _make_analysis_result(
            total_violations=1,
            upcoming_violations=[warning_one, warning_two, warning_three],
            upcoming_by_code={
                "rule.a": {
                    "count": 2,
                    "min_days_remaining": 0,
                    "earliest_effective_on": "2026-09-01",
                    "affected_components": [f"comp-{i}" for i in range(7)],
                }
            },
        )
        warnings = render_warnings_section(result, {})
        assert "Warnings Becoming Violations" in warnings
        assert "+2 more" in warnings
        summary = renderers.render_summary(_make_coverage_data(), result, {})
        assert "Warnings becoming violations" in summary
        render_key_takeaways(
            _make_coverage_data(), result, {}, upcoming_release_date="2026-09-01"
        )
        guide = renderers.render_resolution_guide(
            {"violations": [{
                "rule": "rule.a", "total_components": 1, "covered_count": 0,
                "coverage": "not_covered", "all_components": ["comp-a"],
                "uncovered_components": ["comp-a"], "covered_components": [],
                "open_merge_requests": [], "open_jira_tickets": [],
            }]},
            {"violations": []},
            detail_lookup={("rule.a", "comp-a"): ["detail"]},
        )
        assert "(detail)" in guide

        lines = []
        render_csv_source_fields(
            lines,
            {"descriptions": ["description"], "messages": ["message"], "solution": "solution"},
        )
        assert "**Solution**" in "\n".join(lines)
        render_cataloged_violation(
            lines,
            {
                "triage_note": "triage",
                "fix_steps": [{"action": "fix", "reference": "https://docs", "where": "file.yaml"}],
            },
            {},
        )
        assert "(in: file.yaml)" in "\n".join(lines)

    def test_components_and_false_alerts_cover_slack_and_exception_variants(self, sample_catalog):
        violation = {
            "rule": "test.no_failed_tests",
            "uncovered_components": ["rhoai-fbc-fragment-v3-5"],
            "covered_components": ["comp-b-v3-6"],
            "exception_details_by_component": [
                {"component": "rhoai-fbc-fragment-v3-5", "effective_until": "2026-10-01"},
                {"component": "comp-b-v3-6"},
            ],
            "open_merge_requests": [
                {
                    "iid": 1, "url": "https://gitlab/1", "mr_components": ["rhoai-fbc-fragment-v3-5"],
                    "discrepancy": "code_only",
                }
            ],
            "open_jira_tickets": [],
        }
        lines = []
        renderers.render_components_table(
            lines,
            violation,
            {},
            slack_threads=[{"channel": "c", "permalink": "https://slack/1", "date": "today"}] * 4,
        )
        output = "\n".join(lines)
        assert "+1 more" in output
        assert "⚠️" in output
        assert "covered (expires 2026-10-01)" in output

        false_alert_lines = []
        render_known_false_alerts(false_alert_lines, "test.no_failed_tests", violation, mod._load_catalog(sample_catalog))
        assert "Known false alerts" in "\n".join(false_alert_lines)

    def test_jira_prior_issue_and_empty_entry_paths(self):
        lines = []
        sync = {
            "violations": [{
                "rule": "rule.a",
                "uncovered_components": ["comp-a"],
                "groups": [{"prior_issues": [{"key": "RHOAIENG-1", "url": "https://jira/1"}]}],
            }],
        }
        render_jira_tickets(lines, {"rule": "rule.a"}, sync)
        assert "Prior issues" in "\n".join(lines)
        lines = []
        render_jira_tickets(
            lines,
            {"rule": "rule.a"},
            {"violations": [{"rule": "rule.a", "uncovered_components": ["comp-a"], "groups": [{}]}]},
        )
        assert lines == []

    def test_coverage_empty_rule_and_tooling_missing_runs(self):
        assert "## Violations Coverage" in render_coverage_table({"violations": [{"rule": ""}], "markdown_table": ""})
        output = render_tooling_health({
            "tools": [
                {"name": "reporter", "health": {"status": "unhealthy"}},
                {
                    "name": "complete",
                    "health": {
                        "status": "healthy",
                        "last_success": {"id": 2, "url": "https://run/2", "completed_at": "2026-09-17"},
                    },
                    "latest_run": {"id": 3, "url": "https://run/3", "conclusion": "success", "updated_at": "2026-09-17"},
                },
            ],
        })
        assert "N/A" in output
        assert "None found" in output
        assert "may be stale" in output
        assert render_tooling_health({"display": "ready"}) == "## Tooling Health\n\nready"
        assert render_tooling_health({}) == ""
        assert renderers._tooling_health_executive_line({"tools": [{"health": {"status": "healthy"}}]}) is None
