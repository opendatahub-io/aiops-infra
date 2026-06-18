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
                "open_jira_tickets": [],
                "open_jira_label": "",
                "open_slack_threads": [],
                "open_slack_label": "",
                "next_steps": "Fix in code or request exception — see resolution guide",
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
                "open_jira_tickets": [],
                "open_jira_label": "",
                "open_slack_threads": [],
                "open_slack_label": "",
                "next_steps": "Fix in code or request exception — see resolution guide",
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
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "next_steps": "Use `conforma-violations-scan` AI skill or [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter/actions/workflows/conforma-reporter.yaml) to rerun validation and verify the violation is gone",
                    "status_label": "Exception granted, violation should disappear on next Conforma run",
                    "coverage": "fully_covered",
                    "coverage_label": "already covered",
                    "gate_status": "blocked",
                    "violation_count": 2,
                },
            ],
            "markdown_table": "| # | Rule |\n|---|------|\n| 1 | hermetic |",
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

        assert "**Exception granted** (expires 2026-07-15)" in content
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
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "next_steps": "Use `conforma-violations-scan` AI skill or [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter/actions/workflows/conforma-reporter.yaml) to rerun validation",
                    "coverage": "fully_covered",
                    "coverage_label": "already covered",
                    "gate_status": "blocked",
                    "violation_count": 1,
                },
            ],
            "markdown_table": "| # | Rule |\n|---|------|\n| 1 | rpm_sig |",
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

        assert "**Exception granted** (permanent" in content
        assert "Contact the component team" not in content


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
                    "open_jira_tickets": [],
                    "open_jira_label": "",
                    "open_slack_threads": [],
                    "open_slack_label": "",
                    "next_steps": "Fix in code or request exception",
                    "status_label": "Partially covered",
                    "coverage": "partially_covered",
                    "coverage_label": "partially covered",
                    "gate_status": "error",
                    "violation_count": 2,
                },
            ],
            "markdown_table": "| # | Rule |\n|---|------|\n| 1 | hermetic |",
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

        assert "**Partially covered**: 1/2 components have exceptions" in content
        assert "`comp-b-v3-5-ea-2`" in content
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
