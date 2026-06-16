"""Tests for scripts/verify_conforma_prerequisites.py — optional vs required checks."""

from __future__ import annotations

from unittest.mock import patch

import verify_conforma_prerequisites as prereqs


def _make_check(ok: bool, name: str, optional: bool = False) -> dict:
    return {
        "ok": ok,
        "name": name,
        "optional": optional,
        "error": None if ok else f"{name} failed",
        "fix": None if ok else f"fix {name}",
    }


class TestOptionalChecks:
    """Slack is optional — should not cause exit code 1."""

    def test_all_pass_returns_zero(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(True, "gitlab"),
            _make_check(True, "jira"),
            _make_check(True, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0

    def test_optional_fail_still_returns_zero(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(True, "gitlab"),
            _make_check(True, "jira"),
            _make_check(False, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0

    def test_required_fail_returns_one(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(False, "gitlab"),
            _make_check(True, "jira"),
            _make_check(False, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 1

    def test_json_mode_ignores_optional_failures(self, capsys):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
            _make_check(True, "gitlab"),
            _make_check(True, "jira"),
            _make_check(False, "slack", optional=True),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py", "--json"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0


class TestSlackCheckMarkedOptional:
    """Ensure the Slack check result always carries optional=True."""

    def test_slack_pass_is_optional(self):
        with patch("slack_ops.verify_auth", return_value={"ok": True, "team": "test", "team_url": "https://test.slack.com"}):
            result = prereqs._check_slack_auth()
        assert result["optional"] is True
        assert result["ok"] is True

    def test_slack_fail_is_optional(self):
        with patch("slack_ops.verify_auth", return_value={"ok": False, "error": "not installed"}):
            result = prereqs._check_slack_auth()
        assert result["optional"] is True
        assert result["ok"] is False
