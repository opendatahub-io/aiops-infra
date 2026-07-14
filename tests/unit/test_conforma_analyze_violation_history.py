"""Tests for conforma-analyze violation_history.py."""

from __future__ import annotations

import csv
import io
from unittest.mock import patch


import violation_history


class TestCheckViolationInCsv:
    def _make_csv(self, rows):
        """Build a CSV string from a list of row dicts."""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["type", "component_name", "code", "message"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()

    def test_violation_present(self):
        content = self._make_csv(
            [
                {"type": "violation", "component_name": "comp-a", "code": "hermetic_task.hermetic", "message": "msg"},
            ]
        )
        result = violation_history._check_violation_in_csv(content, "hermetic_task.hermetic")
        assert result["present"] is True
        assert result["count"] == 1
        assert "comp-a" in result["components"]

    def test_violation_absent(self):
        content = self._make_csv(
            [
                {"type": "violation", "component_name": "comp-a", "code": "other.code", "message": "msg"},
            ]
        )
        result = violation_history._check_violation_in_csv(content, "hermetic_task.hermetic")
        assert result["present"] is False
        assert result["count"] == 0

    def test_filters_by_component(self):
        content = self._make_csv(
            [
                {"type": "violation", "component_name": "comp-a", "code": "hermetic_task.hermetic", "message": "msg"},
                {"type": "violation", "component_name": "comp-b", "code": "hermetic_task.hermetic", "message": "msg"},
            ]
        )
        result = violation_history._check_violation_in_csv(content, "hermetic_task.hermetic", component="comp-a")
        assert result["present"] is True
        assert result["count"] == 1
        assert result["components"] == ["comp-a"]

    def test_ignores_warnings(self):
        content = self._make_csv(
            [
                {"type": "warning", "component_name": "comp-a", "code": "hermetic_task.hermetic", "message": "msg"},
            ]
        )
        result = violation_history._check_violation_in_csv(content, "hermetic_task.hermetic")
        assert result["present"] is False

    def test_multiple_matches(self):
        content = self._make_csv(
            [
                {"type": "violation", "component_name": "comp-a", "code": "hermetic_task.hermetic", "message": "msg"},
                {"type": "violation", "component_name": "comp-b", "code": "hermetic_task.hermetic", "message": "msg"},
                {"type": "violation", "component_name": "comp-a", "code": "hermetic_task.hermetic", "message": "msg2"},
            ]
        )
        result = violation_history._check_violation_in_csv(content, "hermetic_task.hermetic")
        assert result["present"] is True
        assert result["count"] == 3
        assert len(result["components"]) == 2


class TestFormatText:
    def test_error_format(self):
        data = {"error": "No CSV found on branch rhoai-3.4"}
        text = violation_history.format_text(data)
        assert "ERROR" in text
        assert "No CSV found" in text

    def test_currently_present(self):
        data = {
            "release": "rhoai-3.4",
            "code": "hermetic_task.hermetic",
            "component_filter": None,
            "csv_path": "prod/future/build_type_latest/conforma-violations-report.csv",
            "total_commits_checked": 5,
            "history_range": {"oldest": "2026-05-01T00:00:00Z", "newest": "2026-06-01T00:00:00Z"},
            "currently_present": True,
            "current_status": {"count": 3, "components": ["comp-a", "comp-b"]},
            "last_seen": {"date": "2026-06-01T00:00:00Z", "sha": "abc123", "count": 3, "components": ["comp-a"]},
            "presence_summary": {"present_in": 5, "absent_in": 0, "total": 5},
        }
        text = violation_history.format_text(data)
        assert "CURRENTLY PRESENT" in text
        assert "rhoai-3.4" in text
        assert "hermetic_task.hermetic" in text

    def test_not_present_with_timeline(self):
        data = {
            "release": "rhoai-3.4",
            "code": "hermetic_task.hermetic",
            "component_filter": None,
            "csv_path": "prod/future/build_type_latest/conforma-violations-report.csv",
            "total_commits_checked": 3,
            "history_range": {"oldest": "2026-04-01T00:00:00Z", "newest": "2026-06-01T00:00:00Z"},
            "currently_present": False,
            "last_seen": {"date": "2026-05-01T00:00:00Z", "sha": "def456", "count": 2, "components": ["comp-a"]},
            "disappeared_on": {"date": "2026-05-15T00:00:00Z", "sha": "ghi789"},
            "first_seen_in_history": {"date": "2026-04-01T00:00:00Z", "sha": "jkl012"},
            "presence_summary": {"present_in": 2, "absent_in": 1, "total": 3},
            "timeline": [
                {"sha": "ghi789", "date": "2026-06-01T00:00:00Z", "present": False, "count": 0, "components": []},
                {
                    "sha": "def456",
                    "date": "2026-05-01T00:00:00Z",
                    "present": True,
                    "count": 2,
                    "components": ["comp-a"],
                },
                {
                    "sha": "jkl012",
                    "date": "2026-04-01T00:00:00Z",
                    "present": True,
                    "count": 1,
                    "components": ["comp-a"],
                },
            ],
        }
        text = violation_history.format_text(data)
        assert "NOT currently present" in text
        assert "Disappeared" in text
        assert "TIMELINE" in text


class TestTraceHistory:
    def setup_method(self):
        violation_history._github_token_cache = None

    def test_no_csv_path_found(self):
        with patch.object(violation_history, "_find_csv_path", return_value=None):
            result = violation_history.trace_history("rhoai-3.4", "hermetic_task.hermetic", environment="prod")
        assert "error" in result

    def test_no_commits_found(self):
        with (
            patch.object(violation_history, "_find_csv_path", return_value="prod/future/build_type_latest/report.csv"),
            patch.object(violation_history, "_fetch_commits", return_value=[]),
        ):
            result = violation_history.trace_history("rhoai-3.4", "hermetic_task.hermetic", environment="prod")
        assert "error" in result

    def test_basic_trace(self):
        csv_content = "type,component_name,code,message\nviolation,comp-a,hermetic_task.hermetic,not hermetic\n"
        commits = [
            {"sha": "aaa111bbb222", "date": "2026-06-01T00:00:00Z", "message": "Update report"},
            {"sha": "ccc333ddd444", "date": "2026-05-01T00:00:00Z", "message": "Update report"},
        ]
        with (
            patch.object(violation_history, "_find_csv_path", return_value="prod/future/build_type_latest/report.csv"),
            patch.object(violation_history, "_fetch_commits", return_value=commits),
            patch.object(violation_history, "_fetch_csv_content", return_value=csv_content),
        ):
            result = violation_history.trace_history("rhoai-3.4", "hermetic_task.hermetic", environment="prod")

        assert "error" not in result
        assert result["currently_present"] is True
        assert result["total_commits_checked"] == 2
        assert result["presence_summary"]["present_in"] == 2

    def test_until_found_stops_early(self):
        csv_present = "type,component_name,code,message\nviolation,comp-a,hermetic_task.hermetic,not hermetic\n"
        csv_absent = "type,component_name,code,message\n"

        commits = [
            {"sha": "aaa111bbb222", "date": "2026-06-01T00:00:00Z", "message": "Update"},
            {"sha": "ccc333ddd444", "date": "2026-05-01T00:00:00Z", "message": "Update"},
            {"sha": "eee555fff666", "date": "2026-04-01T00:00:00Z", "message": "Update"},
        ]

        call_count = 0

        def mock_fetch_csv(sha, csv_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return csv_absent
            return csv_present

        with (
            patch.object(violation_history, "_find_csv_path", return_value="report.csv"),
            patch.object(violation_history, "_fetch_commits", return_value=commits),
            patch.object(violation_history, "_fetch_csv_content", side_effect=mock_fetch_csv),
        ):
            result = violation_history.trace_history(
                "rhoai-3.4", "hermetic_task.hermetic", environment="prod", until_found=True
            )

        assert "error" not in result
        assert call_count == 2

    def test_with_csv_path_override(self):
        csv_content = "type,component_name,code,message\n"
        commits = [
            {"sha": "aaa111bbb222", "date": "2026-06-01T00:00:00Z", "message": "Update"},
        ]

        with (
            patch.object(violation_history, "_fetch_commits", return_value=commits),
            patch.object(violation_history, "_fetch_csv_content", return_value=csv_content),
        ):
            result = violation_history.trace_history(
                "rhoai-3.4",
                "hermetic_task.hermetic",
                environment="prod",
                csv_path_override="prod/future/build_type_latest/report.csv",
            )

        assert result["csv_path"] == "prod/future/build_type_latest/report.csv"

    def teardown_method(self):
        violation_history._github_token_cache = None


# ---------------------------------------------------------------------------
# Context.yaml parameter fallback
# ---------------------------------------------------------------------------


class TestContextIntegration:
    """Verify that main() reads --release, --code, --environment from context.yaml."""

    def _setup_run(
        self, tmp_path, monkeypatch, *, user_query=None, violation_code=None, environment=None, release=None
    ):
        import conforma_context_ops as ctx

        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "run1"
        initial = {}
        if user_query:
            initial["user_query"] = user_query
        if violation_code:
            initial["violation_code"] = violation_code
        if environment:
            initial["environment"] = environment
        if release:
            initial.setdefault("application", {})["release"] = release
        ctx.create(run_dir, initial)
        ctx.set_active(run_dir)
        return run_dir

    def test_reads_release_from_context(self, tmp_path, monkeypatch):
        self._setup_run(
            tmp_path, monkeypatch, release="rhoai-3.5", violation_code="hermetic_task.hermetic", environment="prod"
        )
        monkeypatch.setattr("sys.argv", ["violation_history.py", "--format", "json"])
        with patch.object(violation_history, "trace_history", return_value={"timeline": []}) as mock_trace:
            violation_history.main()
        assert mock_trace.call_args[1]["release"] == "rhoai-3.5"

    def test_reads_code_from_context(self, tmp_path, monkeypatch):
        self._setup_run(
            tmp_path, monkeypatch, release="rhoai-3.5", violation_code="hermetic_task.hermetic", environment="prod"
        )
        monkeypatch.setattr("sys.argv", ["violation_history.py", "--format", "json"])
        with patch.object(violation_history, "trace_history", return_value={"timeline": []}) as mock_trace:
            violation_history.main()
        assert mock_trace.call_args[1]["code"] == "hermetic_task.hermetic"

    def test_reads_environment_from_context(self, tmp_path, monkeypatch):
        self._setup_run(
            tmp_path, monkeypatch, release="rhoai-3.5", violation_code="hermetic_task.hermetic", environment="stage"
        )
        monkeypatch.setattr("sys.argv", ["violation_history.py", "--format", "json"])
        with patch.object(violation_history, "trace_history", return_value={"timeline": []}) as mock_trace:
            violation_history.main()
        assert mock_trace.call_args[1]["environment"] == "stage"

    def test_cli_overrides_context(self, tmp_path, monkeypatch):
        self._setup_run(
            tmp_path, monkeypatch, release="rhoai-3.5", violation_code="hermetic_task.hermetic", environment="prod"
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "violation_history.py",
                "--release",
                "rhoai-3.4",
                "--code",
                "trusted_task.trusted",
                "--environment",
                "stage",
                "--format",
                "json",
            ],
        )
        with patch.object(violation_history, "trace_history", return_value={"timeline": []}) as mock_trace:
            violation_history.main()
        assert mock_trace.call_args[1]["release"] == "rhoai-3.4"
        assert mock_trace.call_args[1]["code"] == "trusted_task.trusted"
        assert mock_trace.call_args[1]["environment"] == "stage"

    def test_fails_without_release_or_context(self, tmp_path, monkeypatch):
        import pytest

        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        monkeypatch.setattr(
            "sys.argv", ["violation_history.py", "--code", "hermetic_task.hermetic", "--environment", "prod"]
        )
        with pytest.raises(SystemExit) as exc_info:
            violation_history.main()
        assert exc_info.value.code != 0
