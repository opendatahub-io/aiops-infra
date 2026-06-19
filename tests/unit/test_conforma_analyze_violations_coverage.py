"""Tests for conforma-analyze violations_coverage.py."""

from __future__ import annotations

import pytest

import conforma_mr_ops
import conforma_policy_ops
import violations_coverage as mod


class TestBuildSearchUrls:
    def test_builds_all_urls(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.example.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        urls = mod._build_search_urls("hermetic_task.hermetic", "https://test.slack.com")
        assert "gitlab.example.com" in urls["mr"]
        assert "hermetic_task.hermetic" in urls["jira"]
        assert "test.slack.com" in urls["slack"]

    def test_no_slack_url_without_team(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.example.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "test/project")
        urls = mod._build_search_urls("test.rule", "")
        assert urls["slack"] == ""
        assert urls["mr"] != ""

    def test_no_mr_url_without_gitlab(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "")
        urls = mod._build_search_urls("test.rule", "https://test.slack.com")
        assert urls["mr"] == ""
        assert urls["jira"] != ""


class TestRenderViolationsMarkdownTable:
    def _make_row(self, **overrides):
        row = {
            "rule": "test.rule",
            "display_components": "comp-v1",
            "exception_expiry": {},
            "exception_details_by_component": [],
            "covered_count": 0,
            "total_components": 1,
            "coverage": "not_covered",
            "open_mr_label": "",
            "open_jira_label": "",
            "status_label": "No coverage",
            "next_steps": "Fix in code or request exception — see resolution guide",
        }
        row.update(overrides)
        return row

    def test_includes_slack_column_when_enabled(self):
        results = [self._make_row(
            open_slack_label="[#conforma](https://slack.com/p1)",
        )]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary, include_slack=True)
        assert "Slack" in md
        assert "#conforma" in md

    def test_excludes_slack_column_when_disabled(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary, include_slack=False)
        assert "Slack" not in md

    def test_next_steps_renders_in_table(self):
        results = [self._make_row(
            next_steps="Fix in code or request exception — see resolution guide",
        )]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "see resolution guide" in md

    def test_footer_references_violation_guide(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "Resolution Guide" in md

    def test_violation_count_column(self):
        results = [self._make_row(violation_count=5)]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "| 5 |" in md

    def test_column_header_says_merge_requests(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "Open Merge Requests" in md
        assert "Open MRs" not in md

    def test_status_column_present(self):
        results = [self._make_row(status_label="Exception granted, violation should disappear on next Conforma run")]
        summary = {"total_violations": 1, "fully_covered": 1, "partially_covered": 0, "not_covered": 0}
        md = mod._render_violations_markdown_table(results, summary)
        assert "| Status |" in md
        assert "Exception granted, violation should disappear on next Conforma run" in md

    def test_report_header_with_metadata(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        meta = {"release": "rhoai-3.5-ea.1", "source_path": "prod/release_day/report.csv"}
        md = mod._render_violations_markdown_table(results, summary, report_meta=meta)
        assert "`rhoai-3.5-ea.1`" in md
        assert "prod/release_day/report.csv" in md

    def test_report_header_without_metadata(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "`unknown`" in md


class TestDetermineStatusAndNextSteps:
    """Tests for _determine_status_and_next_steps."""

    def test_fully_covered(self):
        status, next_steps = mod._determine_status_and_next_steps("fully_covered", [], [], 0)
        assert status == "Exception granted, violation should disappear on next Conforma run"
        assert "rerun" in next_steps.lower()

    def test_not_covered_no_mr_no_jira(self):
        status, next_steps = mod._determine_status_and_next_steps("not_covered", [], [], 3)
        assert status == "No coverage"
        assert "Fix in code or request exception" in next_steps

    def test_not_covered_with_jira(self):
        tickets = [{"key": "RHOAIENG-1", "status": "Open"}]
        status, next_steps = mod._determine_status_and_next_steps("not_covered", [], tickets, 3)
        assert "Jira" in status
        assert "Fix in code or request exception" in next_steps

    def test_not_covered_with_exception_mr(self):
        mrs = [{"suggestion": "fully_covered", "mr_type": "exception", "iid": 1}]
        status, next_steps = mod._determine_status_and_next_steps("not_covered", mrs, [], 3)
        assert "Exception Merge Request pending" in status
        assert "ProdSec" in next_steps

    def test_not_covered_with_remedy_mr(self):
        mrs = [{"suggestion": "no_overlap", "mr_type": "remedy", "iid": 2}]
        status, next_steps = mod._determine_status_and_next_steps("not_covered", mrs, [], 3)
        assert "Remedy Merge Request pending" in status
        assert "rebuild" in next_steps.lower()

    def test_not_covered_with_both_mr_types(self):
        mrs = [
            {"suggestion": "fully_covered", "mr_type": "exception", "iid": 1},
            {"suggestion": "no_overlap", "mr_type": "remedy", "iid": 2},
        ]
        status, next_steps = mod._determine_status_and_next_steps("not_covered", mrs, [], 3)
        assert "Exception + remedy" in status
        assert "ProdSec" in next_steps

    def test_partially_covered_with_exception_mr(self):
        mrs = [{"suggestion": "extend_mr", "mr_type": "exception", "iid": 1}]
        status, next_steps = mod._determine_status_and_next_steps("partially_covered", mrs, [], 5)
        assert "Partially covered" in status
        assert "exception Merge Request" in status
        assert "5 component(s) uncovered" in next_steps

    def test_partially_covered_no_mr(self):
        status, next_steps = mod._determine_status_and_next_steps("partially_covered", [], [], 2)
        assert "2 uncovered" in status
        assert "Fix in code or request exception" in next_steps

    def test_fully_covered_does_not_mention_resolution_guide(self):
        _, next_steps = mod._determine_status_and_next_steps("fully_covered", [], [], 0)
        assert "resolution guide" not in next_steps.lower()

    def test_not_covered_mentions_resolution_guide(self):
        _, next_steps = mod._determine_status_and_next_steps("not_covered", [], [], 1)
        assert "resolution guide" in next_steps.lower()


class TestGateStatusMapping:
    """Every gate status from check_existing_exception_gate must be handled.

    Regression guard: if a new status is added to the gate function but not
    mapped in _GATE_STATUS_MAP, the coverage script will raise ValueError
    instead of silently misclassifying as "not_covered".
    """

    @staticmethod
    def _extract_gate_statuses() -> set[str]:
        """Extract all 'status' string values returned by check_existing_exception_gate.

        Scans the source AST for dict literals like ``"status": "..."`` to
        find every status the gate can return.
        """
        import ast
        import inspect
        import re

        source = inspect.getsource(conforma_policy_ops.check_existing_exception_gate)
        return set(re.findall(r'"status":\s*"(\w+)"', source))

    def test_all_gate_statuses_are_mapped(self):
        gate_statuses = self._extract_gate_statuses()
        assert gate_statuses, "Could not extract any gate statuses from source"
        for status in gate_statuses:
            assert status in mod._GATE_STATUS_MAP, (
                f"Gate status '{status}' is not handled in _GATE_STATUS_MAP. "
                f"Add it to violations_coverage.py."
            )

    def test_unknown_gate_status_raises(self):
        with pytest.raises(ValueError, match="Unknown gate status"):
            mod._map_gate_status({"status": "totally_new_status"}, "test.rule", [], [])

    def test_permanent_maps_to_fully_covered(self):
        cov, label = mod._map_gate_status(
            {"status": "permanent"}, "test.rule", [], []
        )
        assert cov == "fully_covered"

    def test_passed_maps_to_not_covered(self):
        cov, label = mod._map_gate_status(
            {"status": "passed"}, "test.rule", [], []
        )
        assert cov == "not_covered"


class TestReleaseOverride:
    """Layer 3 defense: --release overrides auto-detected release in the report header."""

    def test_report_header_uses_explicit_release(self):
        meta = mod._load_report_metadata("rhoai-3.5-ea.1", None)
        assert meta["release"] == "rhoai-3.5-ea.1"

    def test_report_header_with_metadata_file(self, tmp_path):
        import json

        meta_file = tmp_path / "fetch-metadata.json"
        meta_data = {
            "releases": {
                "rhoai-3.5-ea.1": {
                    "source_path": "prod/release_day/conforma-violations-report.csv",
                    "created_at": "2026-06-18T00:00:00Z",
                    "source_sha": "abc123",
                }
            }
        }
        meta_file.write_text(json.dumps(meta_data))

        result = mod._load_report_metadata("rhoai-3.5-ea.1", str(meta_file))
        assert result["release"] == "rhoai-3.5-ea.1"
        assert "source_url" in result
        assert "rhoai-3.5-ea.1" not in result["source_url"]
        assert "abc123" in result["source_url"]

    def test_markdown_table_shows_correct_release(self):
        results = [{
            "rule": "test.rule",
            "display_components": "comp-v1",
            "exception_expiry": {},
            "exception_details_by_component": [],
            "covered_count": 0,
            "total_components": 1,
            "coverage": "not_covered",
            "open_mr_label": "",
            "open_jira_label": "",
            "status_label": "No coverage",
            "next_steps": "Fix in code",
        }]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        meta = {"release": "rhoai-3.5-ea.1", "source_path": "prod/release_day/report.csv"}
        md = mod._render_violations_markdown_table(results, summary, report_meta=meta)
        assert "`rhoai-3.5-ea.1`" in md
        assert "`rhoai-2.25`" not in md


class TestExtractExceptionExpiry:
    """Tests for _extract_exception_expiry."""

    def test_permanent_exclusion(self):
        gate = {"status": "permanent", "permanent_exclusions": [{"file": "f.yaml", "line": 1}], "active_exceptions": []}
        result = mod._extract_exception_expiry(gate)
        assert result["is_permanent"] is True
        assert result["display_expiry"] == "permanent (no expiry)"
        assert result["earliest_expiry"] is None

    def test_single_expiry_date(self):
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"effectiveUntil": "2026-09-30T00:00:00Z", "covers_components": ["comp-a"]},
            ],
        }
        result = mod._extract_exception_expiry(gate)
        assert result["is_permanent"] is False
        assert result["earliest_expiry"] == "2026-09-30"
        assert result["display_expiry"] == "expires 2026-09-30"

    def test_multiple_expiry_dates(self):
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"effectiveUntil": "2026-09-30T00:00:00Z", "covers_components": ["comp-a"]},
                {"effectiveUntil": "2027-01-15T00:00:00Z", "covers_components": ["comp-b"]},
            ],
        }
        result = mod._extract_exception_expiry(gate)
        assert result["earliest_expiry"] == "2026-09-30"
        assert result["latest_expiry"] == "2027-01-15"
        assert result["display_expiry"] == "expires 2026-09-30 — 2027-01-15"

    def test_no_active_exceptions(self):
        gate = {"status": "passed", "permanent_exclusions": [], "active_exceptions": []}
        result = mod._extract_exception_expiry(gate)
        assert result["is_permanent"] is False
        assert result["display_expiry"] == ""
        assert result["earliest_expiry"] is None

    def test_unparseable_date_ignored(self):
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"effectiveUntil": "not-a-date", "covers_components": ["comp-a"]},
            ],
        }
        result = mod._extract_exception_expiry(gate)
        assert result["display_expiry"] == ""

    def test_coverage_ratio_renders_in_status(self):
        """Status column shows plain coverage ratio, no URLs."""
        row = {
            "rule": "test.rule",
            "display_components": "comp-v1, comp-v2",
            "exception_expiry": {"display_expiry": "expires 2026-09-30"},
            "exception_details_by_component": [],
            "covered_count": 2,
            "total_components": 2,
            "coverage": "fully_covered",
            "open_mr_label": "",
            "open_jira_label": "",
            "status_label": "Exception granted, violation should disappear on next Conforma run",
            "next_steps": "Rerun validation",
        }
        summary = {"total_violations": 1, "fully_covered": 1, "partially_covered": 0, "not_covered": 0}
        md = mod._render_violations_markdown_table([row], summary)
        assert "Exception granted (2/2 components covered)" in md
        assert "[Exception granted]" not in md

    def test_partial_coverage_renders_in_status(self):
        """Partial coverage shows ratio with uncovered count, no URLs."""
        row = {
            "rule": "test.rule",
            "display_components": "comp-v1, comp-v2, comp-v3",
            "exception_expiry": {},
            "exception_details_by_component": [],
            "covered_count": 2,
            "total_components": 3,
            "coverage": "partially_covered",
            "open_mr_label": "",
            "open_jira_label": "",
            "status_label": "Partial coverage",
            "next_steps": "Fix uncovered",
        }
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 1, "not_covered": 0}
        md = mod._render_violations_markdown_table([row], summary)
        assert "Exception granted (2/3 components covered, 1 uncovered)" in md
        assert "[Exception granted]" not in md


class TestBuildComponentExceptionDetails:
    """Tests for _build_component_exception_details."""

    def test_per_component_exceptions(self, monkeypatch):
        """Multiple per-component exceptions produce one entry per component."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.cee.redhat.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"file": "config/policy/registry-rhoai-prod.yaml", "line": 75,
                 "effectiveUntil": "2026-06-30T00:00:00Z", "covers_components": ["comp-a"]},
                {"file": "config/policy/registry-rhoai-prod.yaml", "line": 101,
                 "effectiveUntil": "2026-10-10T00:00:00Z", "covers_components": ["comp-b"]},
            ],
        }
        result = mod._build_component_exception_details(
            gate, ["comp-a", "comp-b"], policy_files=["registry-rhoai-prod.yaml"]
        )
        assert len(result) == 2
        assert result[0]["component"] == "comp-a"
        assert result[0]["line"] == 75
        assert result[0]["effective_until"] == "2026-06-30"
        assert "#L75" in result[0]["url"]
        assert result[1]["component"] == "comp-b"
        assert result[1]["line"] == 101
        assert result[1]["effective_until"] == "2026-10-10"

    def test_unscoped_exception_covers_all(self, monkeypatch):
        """Unscoped exception (covers all) maps to every component."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.cee.redhat.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"file": "config/policy/registry-rhoai-prod.yaml", "line": 50,
                 "effectiveUntil": "2026-08-01T00:00:00Z",
                 "covers_components": ["comp-a", "comp-b", "comp-c"]},
            ],
        }
        result = mod._build_component_exception_details(
            gate, ["comp-a", "comp-b", "comp-c"], policy_files=["registry-rhoai-prod.yaml"]
        )
        assert len(result) == 3
        assert all(d["url"] is not None for d in result)
        assert all(d["line"] == 50 for d in result)

    def test_foreign_file_excluded_by_policy_files(self, monkeypatch):
        """Exceptions in files not in policy_files produce null fields."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.cee.redhat.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"file": "config/policy/registry-jetpack-prod.yaml", "line": 31,
                 "effectiveUntil": "2026-08-01T00:00:00Z", "covers_components": ["comp-a"]},
            ],
        }
        result = mod._build_component_exception_details(
            gate, ["comp-a"], policy_files=["registry-rhoai-prod.yaml"]
        )
        assert len(result) == 1
        assert result[0]["url"] is None
        assert result[0]["file"] is None

    def test_no_exceptions_returns_null_entries(self, monkeypatch):
        """No exceptions means all components get null fields."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.cee.redhat.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        gate = {"status": "passed", "permanent_exclusions": [], "active_exceptions": []}
        result = mod._build_component_exception_details(gate, ["comp-a", "comp-b"])
        assert len(result) == 2
        assert all(d["url"] is None for d in result)

    def test_permanent_exclusion(self, monkeypatch):
        """Permanent exclusion covers all components with no expiry."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.cee.redhat.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        gate = {
            "status": "permanent",
            "permanent_exclusions": [{"file": "config/policy/registry-rhoai-prod.yaml", "line": 10}],
            "active_exceptions": [],
        }
        result = mod._build_component_exception_details(
            gate, ["comp-a", "comp-b"], policy_files=["registry-rhoai-prod.yaml"]
        )
        assert len(result) == 2
        assert all(d["effective_until"] is None for d in result)
        assert all("#L10" in d["url"] for d in result)

    def test_no_gitlab_host_returns_null_urls(self, monkeypatch):
        """Without GITLAB_HOST, urls are None but file/line are still populated."""
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        gate = {
            "status": "blocked",
            "permanent_exclusions": [],
            "active_exceptions": [
                {"file": "config/policy/registry-rhoai-prod.yaml", "line": 42,
                 "effectiveUntil": "2026-09-30", "covers_components": ["comp-a"]},
            ],
        }
        result = mod._build_component_exception_details(gate, ["comp-a"])
        assert len(result) == 1
        assert result[0]["url"] is None


