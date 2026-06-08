"""Tests for conforma-analyze analyze_csv_report.py."""

from __future__ import annotations


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


class TestFormatJson:
    def test_produces_valid_json(self, sample_records):
        import json

        result = analyze_csv_report.analyze(sample_records)
        json_str = analyze_csv_report.format_json(result)
        data = json.loads(json_str)
        assert data["summary"]["total_violations"] == 4
        assert "violations_by_code" in data
