"""Tests for classify_error, from_error, and search_existing in submit_feedback.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SKILL_SCRIPTS = str(Path(__file__).resolve().parent.parent.parent / "skills" / "conforma-feedback" / "scripts")
if _SKILL_SCRIPTS not in sys.path:
    sys.path.insert(0, _SKILL_SCRIPTS)

import submit_feedback


_GITHUB_REMOTE = {
    "platform": "github",
    "host": "github.com",
    "repo_path": "opendatahub-io/aiops-infra",
    "url": "https://github.com/opendatahub-io/aiops-infra",
}


class TestClassifyError:
    def test_known_pattern_component_maturity(self):
        result = submit_feedback.classify_error(
            exception_type="FileNotFoundError",
            error_message="query.py not found at .work/component-maturity/scripts/query.py",
            script_path="scripts/component_catalog_ops.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "component-maturity-query-missing"
        assert result["affected_skill"] == "conforma-analyze"
        assert result["severity"] == "major"
        assert "query.py" in result["title_hint"]

    def test_known_pattern_policy_dir(self):
        result = submit_feedback.classify_error(
            exception_type="FileNotFoundError",
            error_message="Policy dir not found: /tmp/policies/enterprise-contract",
            script_path="scripts/conforma_policy_ops.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "policy-dir-missing"
        assert result["severity"] == "critical"

    def test_known_pattern_github_api(self):
        result = submit_feedback.classify_error(
            exception_type="KeyError",
            error_message="Failed to parse repo response: 'default_branch'",
            script_path="scripts/github_ops.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "github-api-contract-change"

    def test_known_pattern_cli_output(self):
        result = submit_feedback.classify_error(
            exception_type="JSONDecodeError",
            error_message="Invalid JSON output: Expecting value: line 1 column 1",
            script_path="scripts/cli_runner.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "cli-output-format-change"

    def test_known_pattern_target_file_not_found(self):
        result = submit_feedback.classify_error(
            exception_type="FileNotFoundError",
            error_message="Target file not found: data/policy/release/rhoai-3.5/policy.yaml",
            script_path="skills/conforma-exception/scripts/create_gitlab_mr.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "target-file-not-found-in-policy-repo"

    def test_unknown_error_returns_not_classified(self):
        result = submit_feedback.classify_error(
            exception_type="ValueError",
            error_message="some random error",
            script_path="scripts/some_script.py",
        )
        assert result == {"classified": False}

    def test_partial_keyword_match_does_not_classify(self):
        result = submit_feedback.classify_error(
            exception_type="FileNotFoundError",
            error_message="query.py",  # missing script_path match
            script_path="scripts/unrelated_script.py",
        )
        assert result["classified"] is False

    def test_wrong_exception_type_does_not_classify(self):
        result = submit_feedback.classify_error(
            exception_type="ValueError",
            error_message="query.py not found at somewhere",
            script_path="scripts/component_catalog_ops.py",
        )
        assert result["classified"] is False

    def test_case_insensitive_message_keywords(self):
        result = submit_feedback.classify_error(
            exception_type="FileNotFoundError",
            error_message="QUERY.PY NOT FOUND at /some/path",
            script_path="scripts/component_catalog_ops.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "component-maturity-query-missing"

    def test_first_match_wins(self):
        result = submit_feedback.classify_error(
            exception_type="FileNotFoundError",
            error_message="query.py not found in Policy dir not found",
            script_path="scripts/component_catalog_ops.py",
        )
        assert result["classified"] is True
        assert result["pattern_id"] == "component-maturity-query-missing"

    def test_missing_patterns_file_returns_not_classified(self):
        with patch.object(submit_feedback, "_load_known_patterns", return_value=[]):
            result = submit_feedback.classify_error(
                exception_type="FileNotFoundError",
                error_message="query.py not found",
                script_path="scripts/component_catalog_ops.py",
            )
        assert result["classified"] is False


class TestFromError:
    def test_basic_issue_generation(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="infrastructure",
                error_message="RuntimeError: query.py not found",
            )

        assert "error" not in result
        assert "[infra]" in result["title"]
        assert "conforma-analyze" in result["title"]
        assert "conforma-analyze" in result["body"]
        assert "query.py not found" in result["body"]
        assert "infrastructure" in result["labels"]
        assert "bug" in result["labels"]
        assert "conforma" in result["labels"]
        assert result["platform"] == "github"

    def test_with_root_cause_includes_disclaimer(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="infrastructure",
                error_message="query.py not found",
                root_cause="The component-maturity repo reorganized",
            )

        assert "AI-generated, may need verification" in result["body"]
        assert "component-maturity repo reorganized" in result["body"]

    def test_without_root_cause_omits_section(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="infrastructure",
                error_message="query.py not found",
            )

        assert "Root Cause Analysis" not in result["body"]

    def test_title_hint_used_in_title(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="infrastructure",
                error_message="query.py not found",
                title_hint="component-maturity query.py missing",
            )

        assert "component-maturity query.py missing" in result["title"]

    def test_title_falls_back_to_error_type(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="upstream_change",
                error_message="something broke",
            )

        assert "upstream_change" in result["title"]

    def test_reproduction_command_in_body(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="infrastructure",
                error_message="failed",
                reproduction_command="python3 scripts/parse_violations.py --release rhoai-3.5",
            )

        assert "python3 scripts/parse_violations.py --release rhoai-3.5" in result["body"]

    def test_traceback_in_body(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="conforma-analyze",
                workflow_step="4. Parse violations",
                script_path="scripts/component_catalog_ops.py",
                error_type="infrastructure",
                error_message="failed",
                traceback="Traceback (most recent call last):\n  File ...\nRuntimeError",
            )

        assert "Traceback (most recent call last)" in result["body"]

    def test_detect_error_propagates(self):
        with patch.object(submit_feedback, "detect", return_value={"error": "not a git repo"}):
            result = submit_feedback.from_error(
                skill_name="test",
                workflow_step="1",
                script_path="test.py",
                error_type="infrastructure",
                error_message="test",
            )

        assert "error" in result

    def test_environment_info_present(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.from_error(
                skill_name="test",
                workflow_step="1",
                script_path="test.py",
                error_type="infrastructure",
                error_message="test",
            )

        assert result["python_version"]
        assert result["os_info"]
        assert "Python" in result["body"]


class TestSearchExisting:
    def test_github_dispatch(self):
        mock_result = {
            "issues": [
                {"url": "https://github.com/org/repo/issues/1", "title": "Bug", "state": "open",
                 "created_at": "2026-01-01", "number": 1},
            ],
            "total": 1,
        }
        with patch.object(submit_feedback.github_ops, "search_issues", return_value=mock_result) as mock:
            result = submit_feedback.search_existing(
                "org/repo", "github", labels=["infrastructure"], title_keywords="query.py",
            )

        mock.assert_called_once_with("org/repo", labels=["infrastructure"], title_keywords="query.py")
        assert result["total"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["url"] == "https://github.com/org/repo/issues/1"

    def test_github_no_matches(self):
        with patch.object(
            submit_feedback.github_ops, "search_issues",
            return_value={"issues": [], "total": 0},
        ):
            result = submit_feedback.search_existing("org/repo", "github")

        assert result["matches"] == []
        assert result["total"] == 0

    def test_github_error_propagates(self):
        with patch.object(
            submit_feedback.github_ops, "search_issues",
            return_value={"error": "API error"},
        ):
            result = submit_feedback.search_existing("org/repo", "github")

        assert "error" in result

    def test_gitlab_returns_empty(self):
        result = submit_feedback.search_existing("group/project", "gitlab")
        assert result["matches"] == []
        assert result["total"] == 0


class TestParseArgsNewSubcommands:
    def test_classify_error(self):
        args = submit_feedback.parse_args([
            "classify-error",
            "--exception-type", "FileNotFoundError",
            "--error-message", "query.py not found",
            "--script-path", "scripts/component_catalog_ops.py",
        ])
        assert args.command == "classify-error"
        assert args.exception_type == "FileNotFoundError"
        assert args.error_message == "query.py not found"
        assert args.script_path == "scripts/component_catalog_ops.py"

    def test_from_error_required_fields(self):
        args = submit_feedback.parse_args([
            "from-error",
            "--skill-name", "conforma-analyze",
            "--workflow-step", "4. Parse violations",
            "--script-path", "scripts/parse_violations.py",
            "--error-type", "infrastructure",
            "--error-message", "query.py not found",
        ])
        assert args.command == "from-error"
        assert args.skill_name == "conforma-analyze"
        assert args.workflow_step == "4. Parse violations"
        assert args.severity == "major"
        assert args.root_cause is None
        assert args.title_hint is None
        assert args.traceback == "N/A"
        assert args.reproduction_command == "N/A"

    def test_from_error_all_fields(self):
        args = submit_feedback.parse_args([
            "from-error",
            "--skill-name", "conforma-analyze",
            "--workflow-step", "4. Parse violations",
            "--script-path", "scripts/parse_violations.py",
            "--error-type", "infrastructure",
            "--error-message", "query.py not found",
            "--traceback", "Traceback ...",
            "--reproduction-command", "python3 scripts/parse.py",
            "--severity", "critical",
            "--root-cause", "repo reorganized",
            "--title-hint", "query.py missing",
        ])
        assert args.severity == "critical"
        assert args.root_cause == "repo reorganized"
        assert args.title_hint == "query.py missing"
        assert args.traceback == "Traceback ..."
        assert args.reproduction_command == "python3 scripts/parse.py"

    def test_from_error_invalid_severity_rejected(self):
        with pytest.raises(SystemExit):
            submit_feedback.parse_args([
                "from-error",
                "--skill-name", "test",
                "--workflow-step", "1",
                "--script-path", "test.py",
                "--error-type", "infrastructure",
                "--error-message", "test",
                "--severity", "blocker",
            ])

    def test_search_existing(self):
        args = submit_feedback.parse_args([
            "search-existing",
            "--repo-path", "org/repo",
            "--platform", "github",
            "--label", "infrastructure",
            "--label", "bug",
            "--title-keywords", "query.py missing",
        ])
        assert args.command == "search-existing"
        assert args.repo_path == "org/repo"
        assert args.platform == "github"
        assert args.labels == ["infrastructure", "bug"]
        assert args.title_keywords == "query.py missing"

    def test_search_existing_defaults(self):
        args = submit_feedback.parse_args([
            "search-existing",
            "--repo-path", "org/repo",
            "--platform", "github",
        ])
        assert args.labels is None
        assert args.title_keywords is None
