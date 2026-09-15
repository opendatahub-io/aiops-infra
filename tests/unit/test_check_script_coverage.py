"""Tests for tests/check_script_coverage.py (pure functions only — no subprocess)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_script_coverage as hook


def _report(*entries: tuple[str, float]) -> dict:
    """Build a synthetic coverage JSON report from (path, pct) pairs.

    Usage: _report(("scripts/a.py", 99.0), ("scripts/b.py", 50.0))
    """
    files = {}
    for path, pct in entries:
        files[path] = {
            "summary": {
                "percent_covered": pct,
                "covered_lines": int(round(pct / 100.0 * 100)),
                "num_statements": 100,
            }
        }
    return {"files": files}


class TestFindFileInReport:
    def test_finds_by_suffix(self):
        report = _report(("scripts/jira_ops.py", 99.0))
        match = hook.find_file_in_report(report, "scripts/jira_ops.py")
        assert match is not None
        assert match[0] == "scripts/jira_ops.py"

    def test_not_found(self):
        report = _report(("scripts/jira_ops.py", 99.0))
        assert hook.find_file_in_report(report, "scripts/nope.py") is None

    def test_matches_on_suffix_for_nested(self):
        report = _report(("some/deep/path/target_script.py", 50.0))
        assert hook.find_file_in_report(report, "target_script.py") is not None


class TestCoveragePct:
    def test_returns_float(self):
        entry = {"summary": {"percent_covered": 98.5}}
        assert hook.coverage_pct(entry) == 98.5

    def test_none_when_absent(self):
        assert hook.coverage_pct({"summary": {}}) is None


class TestCheckTargets:
    def test_pass_above_threshold(self):
        report = _report(("scripts/jira_ops.py", 98.0))
        results = hook.check_targets(report, ["scripts/jira_ops.py"], 97.0)
        assert results[0]["status"] == "PASS"
        assert results[0]["pct"] == 98.0

    def test_fail_below_threshold(self):
        report = _report(("scripts/jira_ops.py", 90.0))
        results = hook.check_targets(report, ["scripts/jira_ops.py"], 97.0)
        assert results[0]["status"] == "FAIL"

    def test_skip_when_absent(self):
        report = _report(("scripts/other.py", 99.0))
        results = hook.check_targets(report, ["scripts/missing.py"], 97.0)
        assert results[0]["status"] == "skip"

    def test_skip_when_zero_statements(self):
        # A file that exists but has 0 statements should skip, not fail.
        report = {
            "files": {
                "scripts/empty.py": {"summary": {"percent_covered": 100.0, "covered_lines": 0, "num_statements": 0}}
            }
        }
        results = hook.check_targets(report, ["scripts/empty.py"], 97.0)
        assert results[0]["status"] == "skip"

    def test_boundary_97_is_fail(self):
        # Threshold is strict: pct must be > min. 97.0 is not > 97.0.
        report = _report(("scripts/jira_ops.py", 97.0))
        results = hook.check_targets(report, ["scripts/jira_ops.py"], 97.0)
        assert results[0]["status"] == "FAIL"

    def test_multiple_targets_mixed(self):
        report = _report(("scripts/a.py", 99.0), ("scripts/b.py", 50.0))
        results = hook.check_targets(report, ["scripts/a.py", "scripts/b.py", "scripts/c.py"], 97.0)
        assert [r["status"] for r in results] == ["PASS", "FAIL", "skip"]


class TestFormatReport:
    def test_includes_all_statuses(self):
        results = [
            {"target": "scripts/a.py", "status": "PASS", "pct": 99.0, "covered": 99, "total": 100},
            {"target": "scripts/b.py", "status": "FAIL", "pct": 50.0, "covered": 50, "total": 100},
            {"target": "scripts/c.py", "status": "skip", "pct": None, "covered": 0, "total": 0},
        ]
        text = hook.format_report(results, 97.0)
        assert "scripts/a.py" in text
        assert "PASS" in text
        assert "FAIL" in text
        assert "skip" in text

    def test_threshold_shown(self):
        text = hook.format_report([], 95.5)
        assert "95.5" in text


class TestPlanCoverageTargets:
    def test_manifest_lists_four_scripts(self):
        assert len(hook.PLAN_COVERAGE_TARGETS) == 4
        assert "scripts/jira_ops.py" in hook.PLAN_COVERAGE_TARGETS
        assert "scripts/conforma_jira_ticket_ops.py" in hook.PLAN_COVERAGE_TARGETS
