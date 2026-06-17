"""Tests for scripts/verify_conforma_prerequisites.py — optional vs required checks."""

from __future__ import annotations

from unittest.mock import patch

import verify_conforma_prerequisites as prereqs


def _make_check(ok: bool, name: str, optional: bool = False, error: str | None = None, fix: str | None = None, detail: str | None = None) -> dict:
    result = {
        "ok": ok,
        "name": name,
        "optional": optional,
        "error": error if error else (None if ok else f"{name} failed"),
        "fix": fix if fix else (None if ok else f"fix {name}"),
    }
    if detail:
        result["detail"] = detail
    return result


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


class TestFormatMarkdown:
    """Tests for the --format markdown output mode."""

    def test_all_pass_produces_table(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github", detail="user@example.com"),
            _make_check(True, "slack", optional=True, detail="team-x"),
        ]
        output = prereqs._format_markdown(results)
        assert "\u2705 Conforma Prerequisites \u2014 All Passed" in output
        assert "| python_deps | \u2705 Pass |" in output
        assert "| github | \u2705 Pass \u2014 user@example.com |" in output
        assert "| slack *(optional)* | \u2705 Pass \u2014 team-x |" in output
        assert "\u274c" not in output

    def test_failure_produces_sections(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "github", fix="Add to .work/.env:\n  GITHUB_TOKEN=ghp_xxx"),
        ]
        output = prereqs._format_markdown(results)
        assert "### \u2705 python_deps" in output
        assert "### \u274c github" in output
        assert "github failed" in output

    def test_failure_fix_has_code_block(self):
        results = [
            _make_check(False, "infra", fix="Add to .work/.env:\n  GITLAB_HOST=my-host\n  TENANT=my-tenant"),
        ]
        output = prereqs._format_markdown(results)
        assert "```bash" in output
        assert "GITLAB_HOST=my-host" in output
        assert "TENANT=my-tenant" in output
        assert "```" in output

    def test_optional_warn_section(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "slack", optional=True, error="not configured", fix="Run: bash scripts/install.sh"),
        ]
        output = prereqs._format_markdown(results)
        assert "### \u26a0\ufe0f slack *(optional)*" in output
        assert "not configured" in output

    def test_footer_shows_counts(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "github"),
            _make_check(False, "slack", optional=True),
        ]
        output = prereqs._format_markdown(results)
        assert "1 passed" in output
        assert "1 failed" in output
        assert "1 warned (optional)" in output
        assert "Fix required checks before proceeding" in output

    def test_no_failures_footer_says_ready(self):
        results = [
            _make_check(True, "python_deps"),
            _make_check(False, "slack", optional=True),
        ]
        output = prereqs._format_markdown(results)
        assert "Ready to proceed" in output

    def test_main_markdown_format(self, capsys):
        results = [
            _make_check(True, "python_deps"),
            _make_check(True, "github"),
        ]
        with (
            patch.object(prereqs, "run_all_checks", return_value=results),
            patch("sys.argv", ["verify_conforma_prerequisites.py", "--format", "markdown"]),
        ):
            exit_code = prereqs.main()
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Conforma Prerequisites" in captured.out
        assert "All Passed" in captured.out


class TestIsCodeLine:
    """Tests for the _is_code_line heuristic."""

    def test_key_value_assignment(self):
        assert prereqs._is_code_line("GITLAB_HOST=my-host") is True
        assert prereqs._is_code_line("GITHUB_TOKEN=ghp_xxx") is True

    def test_shell_commands(self):
        assert prereqs._is_code_line("echo 'hello'") is True
        assert prereqs._is_code_line("python3 scripts/foo.py") is True
        assert prereqs._is_code_line("bash scripts/install.sh") is True
        assert prereqs._is_code_line("cp .work/.env.example .work/.env") is True
        assert prereqs._is_code_line("uv sync") is True

    def test_prose_is_not_code(self):
        assert prereqs._is_code_line("Then re-run this check") is False
        assert prereqs._is_code_line("Ensure VPN is connected") is False
        assert prereqs._is_code_line("(scope: api, read_repository)") is False


class TestFormatFixMarkdown:
    """Tests for fix text splitting into prose and code blocks."""

    def test_mixed_prose_and_code(self):
        fix = "Add to .work/.env:\n  GITLAB_HOST=my-host\n  TENANT=my-tenant\nThen re-run."
        output = prereqs._format_fix_markdown(fix)
        assert "```bash" in output
        assert "GITLAB_HOST=my-host" in output
        assert "TENANT=my-tenant" in output
        assert "Then re-run." in output
        parts = output.split("```")
        assert len(parts) == 3  # before, inside, after

    def test_pure_prose(self):
        fix = "Fix the infrastructure check above first"
        output = prereqs._format_fix_markdown(fix)
        assert "```" not in output
        assert "Fix the infrastructure check above first" in output

    def test_pure_code(self):
        fix = "GITHUB_TOKEN=ghp_xxx"
        output = prereqs._format_fix_markdown(fix)
        assert "```bash" in output
        assert "GITHUB_TOKEN=ghp_xxx" in output
