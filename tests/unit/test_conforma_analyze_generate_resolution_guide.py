"""Tests for conforma-analyze generate_resolution_guide.py."""

from __future__ import annotations

import json

import pytest
import yaml

import generate_resolution_guide as mod


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
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "# Conforma Resolution Guide: rhoai-3.5-ea.2" in content
        assert "## Summary" in content
        assert "## Violations Coverage" in content
        assert "## Resolution Guide" in content
        assert "## Statistical Breakdown" in content
        assert "**Generated by**: aiops-infra conforma-analyze skill" in content
        assert "prod/release_day/conforma-violations-report.csv" in content

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
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert "Set hermetic=true" in content
        assert "code_fix" in content
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
            source_path="prod/release_day/conforma-violations-report.csv",
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
                source_path="prod/release_day/conforma-violations-report.csv",
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
            source_path="prod/release_day/conforma-violations-report.csv",
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
            source_path="prod/release_day/conforma-violations-report.csv",
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
                            "url": "https://gitlab.cee.redhat.com/releng/konflux-release-data/-/merge_requests/19118",
                            "mr_type": "exception",
                            "suggestion": "extend_mr",
                            "covered": ["comp-a-v3-5-ea-2"],
                            "missing": ["comp-b-v3-5-ea-2"],
                            "mr_components": ["comp-a-v3-5-ea-2"],
                        },
                        {
                            "iid": 555,
                            "url": "https://gitlab.cee.redhat.com/releng/konflux-release-data/-/merge_requests/555",
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
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        # Exception MR !19118 appears in the per-component table (has mr_components)
        assert 'href="https://gitlab.cee.redhat.com/releng/konflux-release-data/-/merge_requests/19118"' in content
        assert ">!19118</a>" in content
        # Remedy MR !555 has no mr_components (by design) — excluded from per-component column
        # but the search URL containing its context is available
        assert 'href="https://gitlab.example.com/search?hermetic"' in content


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
            source_path="prod/release_day/conforma-violations-report.csv",
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
        header = mod._render_metadata_header(
            release="rhoai-3.5-ea.2",
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        assert "rhoai-3.5-ea.2" in header
        assert "prod/release_day/conforma-violations-report.csv" in header
        assert "2026-06-10T05:19:05Z" in header
        assert "conforma-reporter" in header


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
        mod._render_work_scope(lines, "hermetic_task.hermetic", work_scope_by_rule, "https://csv-url")
        assert lines == []

    def test_skipped_when_rule_not_in_scope_data(self):
        lines = []
        mod._render_work_scope(lines, "unknown.rule", {}, "https://csv-url")
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
        mod._render_work_scope(
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
        mod._render_work_scope(lines, "rpm_repos.ids_known", work_scope_by_rule, "https://csv-url")
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
        mod._render_work_scope(lines, "rule.x", work_scope_by_rule, "https://csv-url")
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
        mod._render_work_scope(lines, "rule.x", work_scope_by_rule, "https://csv-url")
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
        out = mod._render_coverage_table(cov)
        anchor = mod._violation_anchor("hermetic_task.hermetic")
        assert f"[`hermetic_task.hermetic`](#{anchor})" in out

    def test_rule_with_colon_becomes_link(self):
        rule = "rpm_signature.allowed:9386b48a1a693c5c"
        cov = self._make_coverage(
            [rule],
            f"| 1 | `{rule}` | 3 | Not covered |",
        )
        out = mod._render_coverage_table(cov)
        anchor = mod._violation_anchor(rule)
        assert f"[`{rule}`](#{anchor})" in out
        assert ":#" not in out  # colon must not leak into the fragment

    def test_multiple_rules_all_linked(self):
        rules = ["hermetic_task.hermetic", "sbom_spdx.disallowed_package_attributes"]
        table = "\n".join(f"| {i+1} | `{r}` | 1 | - |" for i, r in enumerate(rules))
        cov = self._make_coverage(rules, table)
        out = mod._render_coverage_table(cov)
        for rule in rules:
            anchor = mod._violation_anchor(rule)
            assert f"[`{rule}`](#{anchor})" in out

    def test_unrelated_backtick_content_not_linked(self):
        # The word "conforma" in backticks should not be rewritten
        cov = self._make_coverage(
            ["hermetic_task.hermetic"],
            "| 1 | `hermetic_task.hermetic` | 105 | Use `conforma` skill |",
        )
        out = mod._render_coverage_table(cov)
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
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        anchor = mod._violation_anchor("hermetic_task.hermetic")
        assert f'<a id="{anchor}"></a>' in content
        assert f"[`hermetic_task.hermetic`](#{anchor})" in content


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
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {})
        rows = [l for l in lines if l.startswith("| `")]
        assert len(rows) == 2
        assert all("[PSX-1](https://jira/PSX-1) (possibly related)" in r for r in rows)

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
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {})
        row = next(l for l in lines if "odh-comp-v3-5" in l)
        assert row.count("[!42]") == 1

    def test_empty_components_renders_nothing(self):
        v = self._base_violation()
        lines = []
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {})
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
        mod._render_components_table(lines, v, {}, policy_files=policy_files)
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
        mod._render_components_table(lines, v, {}, policy_files=None)
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
        mod._render_components_table(lines, v, {}, slack_threads=slack_threads, slack_search_url="https://slack/search")
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
        mod._render_components_table(lines, v, {}, slack_threads=[], slack_search_url="https://slack/search")
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
        mod._render_components_table(lines, v, {})
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
        out = mod._render_resolution_guide(coverage_data, catalog)
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
        out = mod._render_resolution_guide(coverage_data, catalog)
        assert "[search GitLab](https://gitlab.example.com/search)" in out
        assert "[search Jira](https://jira.example.com/search)" in out


class TestExecutiveSummaryFile:
    """--executive-summary-file flag produces a compact summary for chat display."""

    def test_executive_summary_written_when_flag_provided(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        es_path = tmp_path / "executive-summary.md"
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            executive_summary_file=str(es_path),
        )

        assert es_path.exists()
        content = es_path.read_text()
        assert "# Conforma Resolution Guide: rhoai-3.5-ea.2" in content
        assert "## Executive Summary" in content
        assert "## Summary" in content
        assert "## Detailed Documents" in content

    def test_executive_summary_not_written_when_flag_omitted(
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
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        assert not (tmp_path / "executive-summary.md").exists()

    def test_executive_summary_excludes_resolution_guide_content(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        es_path = tmp_path / "executive-summary.md"
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            executive_summary_file=str(es_path),
        )

        content = es_path.read_text()
        assert "## Resolution Guide" not in content
        assert "## Statistical Breakdown" not in content
        assert "## Violations Coverage" not in content

    def test_executive_summary_includes_analysis_output_link(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
        csv_content = (
            "type,component_name,image,message,effective_on,code,title,description,solution\n"
            'violation,comp-a-v3-5-ea-2,img:sha,"Not hermetic",,hermetic_task.hermetic,'
            "Hermetic,desc,Enable hermetic\n"
        )
        (tmp_path / "rhoai-3.5-ea.2.csv").write_text(csv_content)

        es_path = tmp_path / "executive-summary.md"
        analysis_path = str(tmp_path / "conforma-analysis.md")
        mod.generate_resolution_guide(
            violations_yaml_path=str(sample_violations_yaml),
            coverage_json_path=str(sample_coverage_json),
            reports_dir=str(tmp_path),
            catalog_path=str(sample_catalog),
            release="rhoai-3.5-ea.2",
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            executive_summary_file=str(es_path),
            analysis_output_file=analysis_path,
        )

        content = es_path.read_text()
        assert f"**Analysis Output**: `{analysis_path}`" in content

    def test_full_guide_unchanged_with_executive_summary_flag(
        self, tmp_path, sample_violations_yaml, sample_coverage_json, sample_catalog
    ):
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
            source_path="prod/release_day/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )

        content_without = mod.generate_resolution_guide(**kwargs)
        content_with = mod.generate_resolution_guide(
            **kwargs,
            executive_summary_file=str(tmp_path / "es.md"),
        )

        assert content_without == content_with


class TestOpenLinksInNewTab:
    def test_converts_external_http_links(self):
        content = "See [docs](https://example.com/docs) for details."
        result = mod._open_links_in_new_tab(content)
        assert '<a href="https://example.com/docs" target="_blank">docs</a>' in result

    def test_converts_https_links(self):
        content = "[GitHub](https://github.com/org/repo)"
        result = mod._open_links_in_new_tab(content)
        assert '<a href="https://github.com/org/repo" target="_blank">GitHub</a>' in result

    def test_preserves_internal_anchor_links(self):
        content = "[section](#violation-hermetic_task-hermetic)"
        result = mod._open_links_in_new_tab(content)
        assert result == content

    def test_preserves_image_links(self):
        content = "![alt](https://example.com/image.png)"
        result = mod._open_links_in_new_tab(content)
        assert result == content

    def test_handles_mixed_link_types(self):
        content = (
            "[anchor](#summary) and "
            "[external](https://example.com) and "
            "![img](https://example.com/img.png)"
        )
        result = mod._open_links_in_new_tab(content)
        assert "[anchor](#summary)" in result
        assert '<a href="https://example.com" target="_blank">external</a>' in result
        assert "![img](https://example.com/img.png)" in result

    def test_handles_inline_code_labels(self):
        content = "[`hermetic_task.hermetic`](https://github.com/org/repo/blob/main/file.yaml)"
        result = mod._open_links_in_new_tab(content)
        assert 'target="_blank"' in result
        assert "`hermetic_task.hermetic`" in result

    def test_no_links_unchanged(self):
        content = "Just plain text without any links."
        result = mod._open_links_in_new_tab(content)
        assert result == content

    def test_multiple_links_on_same_line(self):
        content = "[a](https://a.com), [b](https://b.com)"
        result = mod._open_links_in_new_tab(content)
        assert '<a href="https://a.com" target="_blank">a</a>' in result
        assert '<a href="https://b.com" target="_blank">b</a>' in result
