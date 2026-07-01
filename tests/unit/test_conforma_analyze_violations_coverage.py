"""Tests for conforma-analyze violations_coverage.py."""

from __future__ import annotations

import json

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
            "next_steps_short": "Fix in code — see guide below",
        }
        row.update(overrides)
        return row

    def test_table_has_five_columns(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        header_line = [l for l in md.splitlines() if l.startswith("| #")][0]
        assert header_line.count("|") == 6  # 5 columns = 6 pipe chars

    def test_column_headers(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "| Violation |" in md
        assert "| Count |" in md
        assert "| Status |" in md
        assert "| Next Steps |" in md
        assert "Components" not in md
        assert "Open Merge Requests" not in md
        assert "Open Jira" not in md
        assert "Slack" not in md

    def test_next_steps_short_used_in_table(self):
        results = [self._make_row(
            next_steps="Fix in code or request exception — see resolution guide",
            next_steps_short="Fix in code — see guide below",
        )]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "see guide below" in md
        assert "see resolution guide" not in md

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

    def test_status_column_present(self):
        results = [self._make_row(status_label="No coverage")]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "| Status |" in md
        assert "No coverage" in md

    def test_report_header_with_metadata(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        meta = {"release": "rhoai-3.5-ea.1", "source_path": "prod/future/build_type_latest/report.csv"}
        md = mod._render_violations_markdown_table(results, summary, report_meta=meta)
        assert "`rhoai-3.5-ea.1`" in md
        assert "prod/future/build_type_latest/report.csv" in md

    def test_report_header_without_metadata(self):
        results = [self._make_row()]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "`unknown`" in md


class TestDetermineStatusAndNextSteps:
    """Tests for _determine_status_and_next_steps."""

    def test_fully_covered(self):
        status, next_steps, short = mod._determine_status_and_next_steps("fully_covered", [], [], 0)
        assert status == "Exception granted, violation should disappear on next Conforma run"
        assert "conforma-reporter" in next_steps
        assert "conforma-violations-scan" in next_steps
        assert "no longer reported" in next_steps
        assert next_steps == short

    def test_not_covered_no_mr_no_jira(self):
        status, next_steps, short = mod._determine_status_and_next_steps("not_covered", [], [], 3)
        assert status == "No exception coverage"
        assert "Fix in code or request exception" in next_steps
        assert "see guide below" in short.lower()

    def test_not_covered_with_jira(self):
        tickets = [{"key": "RHOAIENG-1", "status": "Open"}]
        status, next_steps, short = mod._determine_status_and_next_steps("not_covered", [], tickets, 3)
        assert "Jira" in status
        assert "Fix in code or request exception" in next_steps
        assert "see guide below" in short.lower()

    def test_not_covered_with_exception_mr(self):
        mrs = [{"suggestion": "fully_covered", "mr_type": "exception", "iid": 1}]
        status, next_steps, short = mod._determine_status_and_next_steps("not_covered", mrs, [], 3)
        assert "Exception Merge Request pending" in status
        assert "ProdSec" in next_steps
        assert short == "Get Merge Request merged"

    def test_not_covered_with_remedy_mr(self):
        mrs = [{"suggestion": "no_overlap", "mr_type": "remedy", "iid": 2}]
        status, next_steps, short = mod._determine_status_and_next_steps("not_covered", mrs, [], 3)
        assert "Remedy Merge Request pending" in status
        assert "rebuild" in next_steps.lower()
        assert short == "Merge fix and rebuild"

    def test_not_covered_with_both_mr_types(self):
        mrs = [
            {"suggestion": "fully_covered", "mr_type": "exception", "iid": 1},
            {"suggestion": "no_overlap", "mr_type": "remedy", "iid": 2},
        ]
        status, next_steps, short = mod._determine_status_and_next_steps("not_covered", mrs, [], 3)
        assert "Exception + remedy" in status
        assert "ProdSec" in next_steps
        assert short == "Get Merge Requests merged"

    def test_partially_covered_with_exception_mr(self):
        mrs = [{"suggestion": "extend_mr", "mr_type": "exception", "iid": 1}]
        status, next_steps, short = mod._determine_status_and_next_steps("partially_covered", mrs, [], 5)
        assert "Partially covered" in status
        assert "exception Merge Request" in status
        assert "5 component(s) without coverage" in next_steps
        assert "5 without coverage" in short

    def test_partially_covered_no_mr(self):
        status, next_steps, short = mod._determine_status_and_next_steps("partially_covered", [], [], 2)
        assert "2 without coverage" in status
        assert "Fix in code or request exception" in next_steps
        assert "see guide below" in short.lower()

    def test_fully_covered_does_not_mention_resolution_guide(self):
        _, next_steps, _ = mod._determine_status_and_next_steps("fully_covered", [], [], 0)
        assert "resolution guide" not in next_steps.lower()

    def test_not_covered_mentions_resolution_guide(self):
        _, next_steps, _ = mod._determine_status_and_next_steps("not_covered", [], [], 1)
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
                    "source_path": "prod/future/build_type_latest/conforma-violations-report.csv",
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
            "next_steps_short": "Fix in code",
        }]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        meta = {"release": "rhoai-3.5-ea.1", "source_path": "prod/future/build_type_latest/report.csv"}
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
            "next_steps_short": "Rerun validation to verify",
        }
        summary = {"total_violations": 1, "fully_covered": 1, "partially_covered": 0, "not_covered": 0}
        md = mod._render_violations_markdown_table([row], summary)
        assert "Exception granted (2/2 components covered)" in md

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
            "next_steps": "Fix in code or request exception — see resolution guide",
            "next_steps_short": "Fix remaining — see guide below",
        }
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 1, "not_covered": 0}
        md = mod._render_violations_markdown_table([row], summary)
        assert "Exception granted (2/3 components covered, 1 without coverage)" in md


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


class TestEcCoverageForRule:
    """Tests for _ec_coverage_for_rule."""

    def test_all_covered_by_ec(self):
        ec_viols = {"comp-a": set(), "comp-b": set()}
        ec_succ = {"comp-a": {"rule.x"}, "comp-b": {"rule.x"}}
        covered, uncovered, coverage, label, divergences = mod._ec_coverage_for_rule(
            "rule.x", ["comp-a", "comp-b"], ec_viols, ec_succ,
        )
        assert covered == ["comp-a", "comp-b"]
        assert uncovered == []
        assert coverage == "fully_covered"
        assert "Conforma engine" in label
        assert divergences == []

    def test_none_covered_by_ec(self):
        ec_viols = {"comp-a": {"rule.x"}, "comp-b": {"rule.x"}}
        ec_succ = {"comp-a": set(), "comp-b": set()}
        covered, uncovered, coverage, label, divergences = mod._ec_coverage_for_rule(
            "rule.x", ["comp-a", "comp-b"], ec_viols, ec_succ,
        )
        assert covered == []
        assert uncovered == ["comp-a", "comp-b"]
        assert coverage == "not_covered"
        assert divergences == []

    def test_partial_coverage(self):
        ec_viols = {"comp-a": set(), "comp-b": {"rule.x"}}
        ec_succ = {"comp-a": {"rule.x"}, "comp-b": set()}
        covered, uncovered, coverage, label, divergences = mod._ec_coverage_for_rule(
            "rule.x", ["comp-a", "comp-b"], ec_viols, ec_succ,
        )
        assert covered == ["comp-a"]
        assert uncovered == ["comp-b"]
        assert coverage == "partially_covered"
        assert "1 of 2" in label
        assert divergences == []

    def test_component_missing_from_ec_treated_as_uncovered(self):
        ec_viols = {"comp-a": set()}
        ec_succ = {"comp-a": {"rule.x"}}
        covered, uncovered, coverage, label, divergences = mod._ec_coverage_for_rule(
            "rule.x", ["comp-a", "comp-b"], ec_viols, ec_succ,
        )
        assert "comp-a" in covered
        assert "comp-b" in uncovered

    def test_divergence_when_not_in_violations_or_successes(self):
        ec_viols = {"comp-a": set(), "comp-b": set()}
        ec_succ = {"comp-a": {"rule.x"}, "comp-b": set()}
        covered, uncovered, coverage, label, divergences = mod._ec_coverage_for_rule(
            "rule.x", ["comp-a", "comp-b"], ec_viols, ec_succ,
        )
        assert "comp-a" in covered
        assert "comp-b" in uncovered
        assert len(divergences) == 1
        assert divergences[0]["component"] == "comp-b"
        assert divergences[0]["violation_code"] == "rule.x"
        assert "source CSV report" in divergences[0]["reason"]
        assert "policy may have changed" in divergences[0]["reason"]

    def test_no_successes_falls_back_to_two_way(self):
        ec_viols = {"comp-a": set(), "comp-b": {"rule.x"}}
        covered, uncovered, coverage, label, divergences = mod._ec_coverage_for_rule(
            "rule.x", ["comp-a", "comp-b"], ec_viols,
        )
        assert "comp-a" in covered
        assert "comp-b" in uncovered
        assert divergences == []


class TestOutputFlag:
    """Verify --output writes JSON to file instead of stdout."""

    def test_output_writes_valid_json_to_file(self, tmp_path, monkeypatch):
        import json

        output_file = tmp_path / "result.json"
        monkeypatch.setattr(
            mod, "check_violations_coverage",
            lambda **_kw: {"summary": {"total": 0}, "violations": []},
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "violations_coverage.py",
                "--violations-yaml", "dummy.yaml",
                "--csv", "dummy.csv",
                "--environment", "prod",
                "--clone-dir", str(tmp_path),
                "--policy-files", "a.yaml",
                "--output", str(output_file),
            ],
        )
        mod.main()
        data = json.loads(output_file.read_text())
        assert "summary" in data

    def test_no_output_flag_prints_to_stdout(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            mod, "check_violations_coverage",
            lambda **_kw: {"summary": {"total": 0}},
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "violations_coverage.py",
                "--violations-yaml", "dummy.yaml",
                "--csv", "dummy.csv",
                "--environment", "prod",
                "--clone-dir", str(tmp_path),
                "--policy-files", "a.yaml",
            ],
        )
        mod.main()
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert "summary" in data

    def test_resolve_context_json_extracts_policy_files(self, tmp_path, monkeypatch):
        captured_kwargs = {}

        def mock_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {"summary": {"total": 0}, "violations": []}

        monkeypatch.setattr(mod, "check_violations_coverage", mock_check)

        resolve_ctx = {
            "links": {
                "policy_files": [
                    {"name": "rhoai-v3-5-ea-2-prod.yaml", "url": "https://example.com/a.yaml"},
                    {"name": "rhoai-v3-5-ea-2-prod-hermetic.yaml", "url": "https://example.com/b.yaml"},
                ],
            }
        }
        rc_file = tmp_path / "resolve-context.json"
        rc_file.write_text(json.dumps(resolve_ctx))

        monkeypatch.setattr(
            "sys.argv",
            [
                "violations_coverage.py",
                "--violations-yaml", "dummy.yaml",
                "--csv", "dummy.csv",
                "--environment", "prod",
                "--clone-dir", str(tmp_path),
                "--resolve-context-json", str(rc_file),
            ],
        )
        mod.main()
        assert captured_kwargs["policy_files"] == [
            "rhoai-v3-5-ea-2-prod.yaml",
            "rhoai-v3-5-ea-2-prod-hermetic.yaml",
        ]

    def test_policy_files_cli_overrides_resolve_context(self, tmp_path, monkeypatch):
        captured_kwargs = {}

        def mock_check(**kwargs):
            captured_kwargs.update(kwargs)
            return {"summary": {"total": 0}, "violations": []}

        monkeypatch.setattr(mod, "check_violations_coverage", mock_check)

        resolve_ctx = {
            "links": {
                "policy_files": [
                    {"name": "from-resolve.yaml", "url": "https://example.com/resolve.yaml"},
                ],
            }
        }
        rc_file = tmp_path / "resolve-context.json"
        rc_file.write_text(json.dumps(resolve_ctx))

        monkeypatch.setattr(
            "sys.argv",
            [
                "violations_coverage.py",
                "--violations-yaml", "dummy.yaml",
                "--csv", "dummy.csv",
                "--environment", "prod",
                "--clone-dir", str(tmp_path),
                "--policy-files", "explicit.yaml",
                "--resolve-context-json", str(rc_file),
            ],
        )
        mod.main()
        assert captured_kwargs["policy_files"] == ["explicit.yaml"]

    def test_fails_without_policy_files_or_resolve_context(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            mod, "check_violations_coverage",
            lambda **_kw: {"summary": {"total": 0}},
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "violations_coverage.py",
                "--violations-yaml", "dummy.yaml",
                "--csv", "dummy.csv",
                "--environment", "prod",
                "--clone-dir", str(tmp_path),
            ],
        )
        rc = mod.main()
        assert rc == 1


class TestFindAllPolicyFilePaths:
    """Tests for _find_all_policy_file_paths."""

    def test_returns_all_env_matching_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.cluster")
        policy_dir = tmp_path / "config" / "test.cluster" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "fbc-rhoai-stage.yaml").write_text("a")
        (policy_dir / "registry-rhoai-stage.yaml").write_text("b")
        (policy_dir / "registry-rhoai-chart-stage.yaml").write_text("c")

        result = mod._find_all_policy_file_paths(
            str(tmp_path),
            ["fbc-rhoai-stage.yaml", "registry-rhoai-stage.yaml", "registry-rhoai-chart-stage.yaml"],
            "stage",
        )
        assert len(result) == 3
        names = {p.name for p in result}
        assert names == {"fbc-rhoai-stage.yaml", "registry-rhoai-stage.yaml", "registry-rhoai-chart-stage.yaml"}

    def test_filters_by_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.cluster")
        policy_dir = tmp_path / "config" / "test.cluster" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "fbc-rhoai-stage.yaml").write_text("a")
        (policy_dir / "fbc-rhoai-prod.yaml").write_text("b")
        (policy_dir / "registry-rhoai-stage.yaml").write_text("c")

        result = mod._find_all_policy_file_paths(
            str(tmp_path),
            ["fbc-rhoai-stage.yaml", "fbc-rhoai-prod.yaml", "registry-rhoai-stage.yaml"],
            "stage",
        )
        names = {p.name for p in result}
        assert "fbc-rhoai-prod.yaml" not in names
        assert "fbc-rhoai-stage.yaml" in names
        assert "registry-rhoai-stage.yaml" in names

    def test_falls_back_when_no_env_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.cluster")
        policy_dir = tmp_path / "config" / "test.cluster" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "custom-policy.yaml").write_text("a")

        result = mod._find_all_policy_file_paths(
            str(tmp_path),
            ["custom-policy.yaml"],
            "stage",
        )
        assert len(result) == 1
        assert result[0].name == "custom-policy.yaml"

    def test_returns_empty_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.cluster")
        policy_dir = tmp_path / "config" / "test.cluster" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)

        result = mod._find_all_policy_file_paths(
            str(tmp_path),
            ["nonexistent.yaml"],
            "stage",
        )
        assert result == []

    def test_returns_empty_when_no_ec_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_DIR", raising=False)

        result = mod._find_all_policy_file_paths(str(tmp_path), ["a.yaml"], "stage")
        assert result == []


class TestComponentPolicyMapping:
    """Tests for _map_component_to_policy and _group_components_by_policy."""

    @pytest.fixture
    def policy_paths(self, tmp_path):
        fbc = tmp_path / "fbc-rhoai-stage.yaml"
        reg = tmp_path / "registry-rhoai-stage.yaml"
        chart = tmp_path / "registry-rhoai-chart-stage.yaml"
        fbc.write_text("a")
        reg.write_text("b")
        chart.write_text("c")
        return [fbc, reg, chart]

    @pytest.fixture
    def mapping_rules(self):
        return mod._load_component_policy_mapping()

    def test_fbc_maps_to_fbc_policy(self, policy_paths, mapping_rules):
        result = mod._map_component_to_policy(
            "rhoai-fbc-fragment-v3-5-ea-2", policy_paths, mapping_rules,
        )
        assert result is not None
        assert result.name == "fbc-rhoai-stage.yaml"

    def test_chart_maps_to_chart_policy(self, policy_paths, mapping_rules):
        result = mod._map_component_to_policy(
            "odh-chart-v3-5-ea-2", policy_paths, mapping_rules,
        )
        assert result is not None
        assert result.name == "registry-rhoai-chart-stage.yaml"

    def test_regular_maps_to_registry_policy(self, policy_paths, mapping_rules):
        result = mod._map_component_to_policy(
            "odh-dashboard-v3-5-ea-2", policy_paths, mapping_rules,
        )
        assert result is not None
        assert result.name == "registry-rhoai-stage.yaml"

    def test_regular_does_not_match_chart_policy(self, policy_paths, mapping_rules):
        result = mod._map_component_to_policy(
            "odh-training-cuda121-torch24-py311-v3-5-ea-2", policy_paths, mapping_rules,
        )
        assert result is not None
        assert "chart" not in result.name

    def test_group_components_by_policy(self, policy_paths, mapping_rules):
        components = [
            "rhoai-fbc-fragment-v3-5-ea-2",
            "odh-dashboard-v3-5-ea-2",
            "odh-chart-v3-5-ea-2",
            "odh-model-registry-v3-5-ea-2",
        ]
        groups = mod._group_components_by_policy(components, policy_paths, mapping_rules)
        fbc_path = policy_paths[0]
        reg_path = policy_paths[1]
        chart_path = policy_paths[2]
        assert "rhoai-fbc-fragment-v3-5-ea-2" in groups[fbc_path]
        assert "odh-dashboard-v3-5-ea-2" in groups[reg_path]
        assert "odh-model-registry-v3-5-ea-2" in groups[reg_path]
        assert "odh-chart-v3-5-ea-2" in groups[chart_path]

    def test_returns_none_when_no_matching_policy(self, mapping_rules):
        result = mod._map_component_to_policy(
            "odh-dashboard-v3-5-ea-2", [], mapping_rules,
        )
        assert result is None


