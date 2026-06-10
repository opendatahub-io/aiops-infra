"""Tests for conforma-analyze analyze_csv_report.py."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import analyze_csv_report


@pytest.fixture
def sample_records():
    """Create a list of ViolationRecords for testing."""
    return [
        analyze_csv_report.ViolationRecord(
            type="violation",
            component_name="comp-a",
            image="img:sha",
            message='Task "prefetch-dependencies" is not trusted',
            effective_on="2026-01-01",
            code="trusted_task.trusted",
            title="Task must be trusted",
            description="desc",
            solution="Upgrade task",
            release="rhoai-3.4",
        ),
        analyze_csv_report.ViolationRecord(
            type="violation",
            component_name="comp-a",
            image="img:sha",
            message="Task is not hermetic",
            effective_on="2026-01-01",
            code="hermetic_task.hermetic",
            title="Hermetic build required",
            description="desc",
            solution="Enable hermetic builds",
            release="rhoai-3.4",
        ),
        analyze_csv_report.ViolationRecord(
            type="violation",
            component_name="comp-b",
            image="img:sha",
            message="RPM not signed with key 1234567890abcdef",
            effective_on="2026-02-01",
            code="rpm_signature.allowed",
            title="RPM signing required",
            description="desc",
            solution="Sign RPMs",
            release="rhoai-3.4",
        ),
        analyze_csv_report.ViolationRecord(
            type="violation",
            component_name="comp-c",
            image="img:sha",
            message='Task "prefetch-dependencies" is not trusted',
            effective_on="2026-01-01",
            code="trusted_task.trusted",
            title="Task must be trusted",
            description="desc",
            solution="Upgrade task",
            release="rhoai-3.4",
        ),
    ]


class TestLoadCsv:
    def test_filters_violations_only(self, tmp_csv):
        records = analyze_csv_report.load_csv(tmp_csv)
        assert len(records) == 3
        assert all(r.type == "violation" for r in records)

    def test_sets_release_from_stem(self, tmp_csv):
        records = analyze_csv_report.load_csv(tmp_csv)
        assert all(r.release == "rhoai-3.4" for r in records)

    def test_explicit_release(self, tmp_csv):
        records = analyze_csv_report.load_csv(tmp_csv, release="custom-release")
        assert all(r.release == "custom-release" for r in records)


class TestLoadReportsDir:
    def test_loads_all_csvs(self, tmp_reports_dir):
        records = analyze_csv_report.load_reports_dir(tmp_reports_dir)
        assert len(records) == 3

    def test_empty_dir(self, tmp_path):
        records = analyze_csv_report.load_reports_dir(tmp_path)
        assert records == []


class TestExtractUntrustedTasks:
    def test_extracts_task_names(self, sample_records):
        tasks = analyze_csv_report.extract_untrusted_tasks(sample_records)
        assert "prefetch-dependencies" in tasks
        assert tasks["prefetch-dependencies"] == 2

    def test_no_trusted_task_violations(self):
        records = [
            analyze_csv_report.ViolationRecord(
                type="violation",
                component_name="comp",
                image="img",
                message="not hermetic",
                effective_on="2026-01-01",
                code="hermetic_task.hermetic",
                title="t",
                description="d",
                solution="s",
            ),
        ]
        tasks = analyze_csv_report.extract_untrusted_tasks(records)
        assert tasks == {}


class TestExtractRpmSignatureDetails:
    def test_extracts_details(self, sample_records):
        details = analyze_csv_report.extract_rpm_signature_details(sample_records)
        assert len(details) == 1
        assert details[0]["component"] == "comp-b"

    def test_deduplicates(self):
        records = [
            analyze_csv_report.ViolationRecord(
                type="violation",
                component_name="comp-a",
                image="img",
                message="key 1234",
                effective_on="",
                code="rpm_signature.allowed",
                title="t",
                description="d",
                solution="s",
            ),
            analyze_csv_report.ViolationRecord(
                type="violation",
                component_name="comp-a",
                image="img",
                message="key 1234",
                effective_on="",
                code="rpm_signature.allowed",
                title="t",
                description="d",
                solution="s",
            ),
        ]
        details = analyze_csv_report.extract_rpm_signature_details(records)
        assert len(details) == 1


class TestComputeComponentPatterns:
    def test_identifies_patterns(self, sample_records):
        patterns = analyze_csv_report.compute_component_patterns(sample_records)
        assert len(patterns) > 0
        all_components = []
        for p in patterns:
            all_components.extend(p["components"])
        assert "comp-a" in all_components

    def test_groups_same_code_combos(self):
        records = [
            analyze_csv_report.ViolationRecord(
                type="violation",
                component_name="comp-a",
                image="img",
                message="msg",
                effective_on="",
                code="code.one",
                title="t",
                description="d",
                solution="s",
            ),
            analyze_csv_report.ViolationRecord(
                type="violation",
                component_name="comp-b",
                image="img",
                message="msg",
                effective_on="",
                code="code.one",
                title="t",
                description="d",
                solution="s",
            ),
        ]
        patterns = analyze_csv_report.compute_component_patterns(records)
        assert len(patterns) == 1
        assert patterns[0]["count"] == 2


class TestComputeEffectiveDates:
    def test_counts_by_date(self, sample_records):
        dates = analyze_csv_report.compute_effective_dates(sample_records)
        assert "2026-01-01" in dates
        assert dates["2026-01-01"] == 3
        assert "2026-02-01" in dates


class TestAnalyze:
    def test_full_analysis(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        assert result.total_violations == 4
        assert result.unique_codes == 3
        assert result.unique_components == 3
        assert len(result.violations_by_code) == 3
        assert len(result.violations_by_component) == 3

    def test_recommendations_generated(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        assert len(result.priority_recommendations) > 0
        actions = {r["action"] for r in result.priority_recommendations}
        assert "Upgrade prefetch-dependencies task" in actions


class TestFormatText:
    def test_produces_output(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        text = analyze_csv_report.format_text(result)
        assert "CONFORMA VIOLATIONS ANALYSIS" in text
        assert "VIOLATIONS BY CODE" in text
        assert "PRIORITY RECOMMENDATIONS" in text
        assert str(result.total_violations) in text


class TestFormatMarkdown:
    def test_produces_markdown(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        md = analyze_csv_report.format_markdown(result)
        assert "# Conforma Violations Analysis" in md
        assert "## Violations by Code" in md
        assert "|" in md


class TestLoadWarningsCsv:
    def test_loads_upcoming_warnings(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        warnings = analyze_csv_report.load_warnings_csv(tmp_warnings_csv, threshold_days=21, reference_date=ref)
        codes = {w.code for w in warnings}
        assert "prefetch_dependencies.mode_not_permissive" in codes
        assert "hermetic_task.hermetic" in codes
        assert "future_rule.check" not in codes

    def test_days_until_effective(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        warnings = analyze_csv_report.load_warnings_csv(tmp_warnings_csv, threshold_days=21, reference_date=ref)
        hermetic = [w for w in warnings if w.code == "hermetic_task.hermetic"]
        assert len(hermetic) == 1
        assert hermetic[0].days_until_effective == 10

    def test_sets_release_from_stem(self, tmp_warnings_csv):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        warnings = analyze_csv_report.load_warnings_csv(tmp_warnings_csv, threshold_days=21, reference_date=ref)
        assert all(w.release == "rhoai-3.4" for w in warnings)


class TestLoadWarningsDir:
    def test_loads_from_dir(self, tmp_reports_dir):
        ref = datetime(2026, 6, 10, tzinfo=timezone.utc)
        warnings = analyze_csv_report.load_warnings_dir(tmp_reports_dir, threshold_days=21, reference_date=ref)
        assert len(warnings) > 0

    def test_empty_dir(self, tmp_path):
        warnings = analyze_csv_report.load_warnings_dir(tmp_path)
        assert warnings == []


class TestAnalyzeWithUpcoming:
    def test_includes_upcoming(self, sample_records):
        upcoming = [
            analyze_csv_report.UpcomingViolation(
                component_name="comp-d",
                code="new_rule.check",
                title="New rule",
                message="Will be enforced soon",
                effective_on="2026-06-25",
                days_until_effective=15,
                release="rhoai-3.4",
            ),
        ]
        result = analyze_csv_report.analyze(sample_records, upcoming=upcoming)
        assert len(result.upcoming_violations) == 1
        assert "new_rule.check" in result.upcoming_by_code

    def test_no_upcoming(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        assert result.upcoming_violations == []
        assert result.upcoming_by_code == {}


class TestFormatTextWithUpcoming:
    def test_includes_upcoming_section(self, sample_records):
        upcoming = [
            analyze_csv_report.UpcomingViolation(
                component_name="comp-d",
                code="new_rule.check",
                title="New rule",
                message="msg",
                effective_on="2026-06-25",
                days_until_effective=15,
                release="rhoai-3.4",
            ),
        ]
        result = analyze_csv_report.analyze(sample_records, upcoming=upcoming)
        text = analyze_csv_report.format_text(result)
        assert "WARNINGS BECOMING VIOLATIONS" in text
        assert "new_rule.check" in text
        assert "15 days" in text


class TestFormatMarkdownWithUpcoming:
    def test_includes_upcoming_section(self, sample_records):
        upcoming = [
            analyze_csv_report.UpcomingViolation(
                component_name="comp-d",
                code="new_rule.check",
                title="New rule",
                message="msg",
                effective_on="2026-06-25",
                days_until_effective=15,
                release="rhoai-3.4",
            ),
        ]
        result = analyze_csv_report.analyze(sample_records, upcoming=upcoming)
        md = analyze_csv_report.format_markdown(result)
        assert "Warnings Becoming Violations" in md
        assert "new_rule.check" in md


class TestAnnotateComp:
    def test_annotates_with_owner(self):
        owners = {"comp-a": "ModelMesh", "comp-b": None}
        assert analyze_csv_report._annotate_comp("comp-a", owners) == "comp-a (ModelMesh)"

    def test_no_annotation_when_none(self):
        owners = {"comp-b": None}
        assert analyze_csv_report._annotate_comp("comp-b", owners) == "comp-b"

    def test_no_annotation_when_missing(self):
        owners = {}
        assert analyze_csv_report._annotate_comp("comp-x", owners) == "comp-x"


class TestLoadComponentOwners:
    def test_loads_from_yaml(self, tmp_path):
        import yaml

        data = {
            "violation_data": {
                "violations_by_component": {
                    "comp-a": {"rules": ["rule.one"], "jira_component": "ModelMesh"},
                    "comp-b": {"rules": ["rule.two"], "jira_component": None},
                }
            }
        }
        yaml_path = tmp_path / "violations.yaml"
        yaml_path.write_text(yaml.dump(data))
        owners = analyze_csv_report._load_component_owners(str(yaml_path))
        assert owners["comp-a"] == "ModelMesh"
        assert owners["comp-b"] is None

    def test_returns_empty_for_missing_file(self, tmp_path):
        owners = analyze_csv_report._load_component_owners(str(tmp_path / "nonexistent.yaml"))
        assert owners == {}


class TestFormatTextWithOwnership:
    def test_annotates_upcoming_components(self, sample_records):
        upcoming = [
            analyze_csv_report.UpcomingViolation(
                component_name="comp-d",
                code="new_rule.check",
                title="New rule",
                message="msg",
                effective_on="2026-06-25",
                days_until_effective=15,
                release="rhoai-3.4",
            ),
        ]
        result = analyze_csv_report.analyze(sample_records, upcoming=upcoming)
        owners = {"comp-d": "Dashboard"}
        text = analyze_csv_report.format_text(result, component_owners=owners)
        assert "comp-d (Dashboard)" in text

    def test_no_annotation_without_owners(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        text = analyze_csv_report.format_text(result)
        assert "(Dashboard)" not in text


class TestFormatMarkdownWithOwnership:
    def test_annotates_recommendation_components(self, sample_records):
        result = analyze_csv_report.analyze(sample_records)
        owners = {"comp-a": "Training", "comp-b": "vLLM"}
        md = analyze_csv_report.format_markdown(result, component_owners=owners)
        assert "Training" in md


class TestFormatJson:
    def test_produces_valid_json(self, sample_records):
        import json

        result = analyze_csv_report.analyze(sample_records)
        json_str = analyze_csv_report.format_json(result)
        data = json.loads(json_str)
        assert data["summary"]["total_violations"] == 4
        assert "violations_by_code" in data

    def test_includes_upcoming_in_json(self, sample_records):
        import json

        upcoming = [
            analyze_csv_report.UpcomingViolation(
                component_name="comp-d",
                code="new_rule.check",
                title="New rule",
                message="msg",
                effective_on="2026-06-25",
                days_until_effective=15,
                release="rhoai-3.4",
            ),
        ]
        result = analyze_csv_report.analyze(sample_records, upcoming=upcoming)
        json_str = analyze_csv_report.format_json(result)
        data = json.loads(json_str)
        assert "upcoming_violations" in data
        assert data["upcoming_violations"]["total"] == 1

    def test_includes_component_owners_in_json(self, sample_records):
        import json

        result = analyze_csv_report.analyze(sample_records)
        owners = {"comp-a": "Training", "comp-b": "vLLM", "comp-c": None}
        json_str = analyze_csv_report.format_json(result, component_owners=owners)
        data = json.loads(json_str)
        assert "component_owners" in data
        assert data["component_owners"]["comp-a"] == "Training"
        assert "comp-c" not in data["component_owners"]
