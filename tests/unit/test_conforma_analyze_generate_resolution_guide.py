"""Tests for conforma-analyze generate_resolution_guide.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import conforma_context_ops
import generate_resolution_guide as mod
from guide_renderers import render_divergence_warning
from guide_renderers import render_resolution_guide
from guide_renderers import render_components_table
from guide_renderers import render_metadata_header
from guide_renderers import render_coverage_table
from guide_renderers import render_work_scope


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
        # Remedy MR !555 has no mr_components (by design) — excluded from per-component column
        # but the search URL containing its context is available
        assert "https://gitlab.example.com/search?hermetic" in content


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
        assert "| **Total violations** | 162 |" in header

    def test_omits_total_violations_when_none(self):
        header = render_metadata_header(
            release="rhoai-3.5",
            source_path="prod/report.csv",
            source_created_at="2026-06-10T05:19:05Z",
        )
        assert "Total violations" not in header


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
        assert "not found in rhai-release-data.yaml" in header

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
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            executive_summary_file=str(es_path),
        )

        assert es_path.exists()
        content = es_path.read_text()
        assert "# Conforma Status and Resolution Guide: rhoai-3.5-ea.2" in content
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
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
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
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
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
            source_path="prod/future/build_type_latest/conforma-violations-report.csv",
            source_created_at="2026-06-10T05:19:05Z",
            executive_summary_file=str(es_path),
            analysis_output_file=analysis_path,
        )

        content = es_path.read_text()
        assert f"**Analysis Output**: `{analysis_path}`" in content

    def test_full_guide_unchanged_with_executive_summary_flag(
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
        with patch("generate_resolution_guide.datetime") as mock_dt:
            mock_dt.now.return_value = frozen
            mock_dt.fromisoformat = datetime.fromisoformat
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            content_without = mod.generate_resolution_guide(**kwargs)
            content_with = mod.generate_resolution_guide(
                **kwargs,
                executive_summary_file=str(tmp_path / "es.md"),
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


# ---------------------------------------------------------------------------
# upcoming_release_date in executive summary
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

        assert "expire before the upcoming release date (2026-08-15) and not addressed by any open Merge Request" in content
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
        expiring_pos = content.index("expire before the upcoming release date")
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

        assert "**0 violations covered by currently active exceptions that expire before the upcoming release date (2026-06-01) and not addressed by any open Merge Request**" in content

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

        assert "**0 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) and not addressed by any open Merge Request**" in content

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

        assert "**0 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) and not addressed by any open Merge Request**" in content
        assert "**1 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) — addressed by open Merge Requests extending past the release date**" in content
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

        assert "**1 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) — open Merge Request exists but its proposed exception also expires before the release date**" in content
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

        uncovered_pos = content.index("violations without exception or open Merge Request")
        no_mr_pos = content.index("not addressed by any open Merge Request")
        insuf_pos = content.index("proposed exception also expires before the release date")
        suf_pos = content.index("extending past the release date")
        assert uncovered_pos < no_mr_pos < insuf_pos < suf_pos
        assert "comp-no-mr" in content
        assert "comp-insuf-mr" in content
        assert "comp-suf-mr" in content

    def test_always_shows_zero_count_headers(
        self, tmp_path, sample_violations_yaml, sample_catalog
    ):
        """All three expiring section headers appear even when counts are 0."""
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

        assert "**0 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) and not addressed by any open Merge Request**" in content
        assert "**0 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) — open Merge Request exists but its proposed exception also expires before the release date**" in content
        assert "**0 violations covered by currently active exceptions that expire before the upcoming release date (2026-08-15) — addressed by open Merge Requests extending past the release date**" in content
        assert "**1 violations without exception or open Merge Request**" in content
        assert "**0 violations addressed** by open Merge Requests (not yet merged)" in content


class TestExecutiveSummaryViolationLinks:
    """Violation titles in executive summary tables must link to their resolution guide sections."""

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
            exec_summary_section = content.split("## Executive Summary")[1].split("## Summary")[0]
            assert link in exec_summary_section, (
                f"Expected anchor link {link} in executive summary"
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
    """Coverage summary line in executive summary includes policy file links."""

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
        assert "covered** by exceptions in" in content

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
        assert (run_dir / "conforma-status-and-resolution-guide.md").is_file()
        assert (run_dir / "executive-summary.md").is_file()

    def test_updates_context_after_generation(self, tmp_path, monkeypatch, sample_catalog):
        run_dir = self._setup_run_with_artifacts(tmp_path, monkeypatch, sample_catalog)
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
        ])
        mod.main()
        ctx = conforma_context_ops.load(run_dir)
        assert ctx["steps"]["resolution_guide"]["status"] == "completed"
        assert ctx["steps"]["resolution_guide"]["guide_file"] == "conforma-status-and-resolution-guide.md"
        assert ctx["steps"]["resolution_guide"]["executive_summary_file"] == "executive-summary.md"

    def test_source_metadata_from_context(self, tmp_path, monkeypatch, sample_catalog):
        run_dir = self._setup_run_with_artifacts(tmp_path, monkeypatch, sample_catalog)
        monkeypatch.setattr("sys.argv", [
            "generate_resolution_guide.py",
            "--catalog", str(sample_catalog),
        ])
        mod.main()
        content = (run_dir / "conforma-status-and-resolution-guide.md").read_text()
        assert "2026-06-10" in content
        assert "abc123" in content

    def test_no_context_requires_explicit_args(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr("sys.argv", ["generate_resolution_guide.py"])
        rc = mod.main()
        assert rc == 1


