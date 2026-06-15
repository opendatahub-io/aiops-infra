"""Tests for skills/conforma-feedback/scripts/submit_feedback.py."""

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

_GITLAB_REMOTE = {
    "platform": "gitlab",
    "host": "gitlab.cee.redhat.com",
    "repo_path": "team/project",
    "url": "https://gitlab.cee.redhat.com/team/project",
}


class TestDetect:
    def test_delegates_to_git_ops(self):
        with patch.object(submit_feedback.git_ops, "detect_remote", return_value=_GITHUB_REMOTE) as mock:
            result = submit_feedback.detect(cwd="/some/path", remote="upstream")

        mock.assert_called_once_with(cwd="/some/path", remote="upstream")
        assert result == _GITHUB_REMOTE

    def test_error_passthrough(self):
        with patch.object(
            submit_feedback.git_ops, "detect_remote", return_value={"error": "not a git repo"},
        ):
            result = submit_feedback.detect()

        assert "error" in result


class TestCheckIssues:
    def test_github_dispatch(self):
        with patch.object(
            submit_feedback.github_ops, "check_issues_enabled", return_value={"enabled": True},
        ) as mock:
            result = submit_feedback.check_issues("org/repo", "github")

        mock.assert_called_once_with("org/repo")
        assert result == {"enabled": True}

    def test_gitlab_dispatch(self):
        with patch.object(
            submit_feedback.gitlab_ops, "check_issues_enabled", return_value={"enabled": True},
        ) as mock:
            result = submit_feedback.check_issues("group/repo", "gitlab", host="gitlab.example.com")

        mock.assert_called_once_with("group/repo", instance_url="gitlab.example.com")
        assert result == {"enabled": True}

    def test_unsupported_platform(self):
        result = submit_feedback.check_issues("repo", "bitbucket")
        assert "error" in result
        assert "Unsupported" in result["error"]


class TestGatherContext:
    def test_bug_report(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.gather_context(
                skill_name="conforma-exception",
                issue_type="bug",
                summary="MR creation fails",
                expected="MR should be created",
                actual="Script crashes with KeyError",
                error_output="KeyError: 'branch'",
                severity="major",
                additional_context="Using RHOAI 3.5",
            )

        assert "error" not in result
        assert result["title"] == "[conforma-feedback] bug: MR creation fails"
        assert "conforma-exception" in result["body"]
        assert "KeyError" in result["body"]
        assert "conforma" in result["labels"]
        assert "conforma-skill" in result["labels"]
        assert "bug" in result["labels"]
        assert "enhancement" not in result["labels"]
        assert result["platform"] == "github"
        assert result["repo_path"] == "opendatahub-io/aiops-infra"

    def test_enhancement_request(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.gather_context(
                skill_name="conforma-analyze",
                issue_type="enhancement",
                summary="Add CSV export",
                expected="CSV export option",
                actual="No export available",
            )

        assert "enhancement" in result["labels"]
        assert "bug" not in result["labels"]
        assert "conforma" in result["labels"]

    def test_defaults_for_optional_fields(self):
        with patch.object(submit_feedback, "detect", return_value=_GITHUB_REMOTE):
            result = submit_feedback.gather_context(
                skill_name="conforma-docs",
                issue_type="bug",
                summary="Missing docs",
                expected="Docs exist",
                actual="404 page",
            )

        assert "N/A" in result["body"]
        assert result["python_version"]
        assert result["os_info"]

    def test_detect_error_propagates(self):
        with patch.object(submit_feedback, "detect", return_value={"error": "not a git repo"}):
            result = submit_feedback.gather_context(
                skill_name="test",
                issue_type="bug",
                summary="test",
                expected="test",
                actual="test",
            )

        assert "error" in result

    def test_gitlab_platform(self):
        with patch.object(submit_feedback, "detect", return_value=_GITLAB_REMOTE):
            result = submit_feedback.gather_context(
                skill_name="test",
                issue_type="bug",
                summary="test",
                expected="test",
                actual="test",
            )

        assert result["platform"] == "gitlab"
        assert result["host"] == "gitlab.cee.redhat.com"


class TestSubmit:
    def test_github_dispatch(self):
        with patch.object(
            submit_feedback.github_ops,
            "create_issue",
            return_value={"issue_url": "https://github.com/org/repo/issues/1", "issue_number": 1},
        ) as mock:
            result = submit_feedback.submit(
                "org/repo", "github", "Title", "Body", labels=["bug"],
            )

        mock.assert_called_once_with("org/repo", "Title", "Body", labels=["bug"])
        assert result["issue_url"] == "https://github.com/org/repo/issues/1"

    def test_gitlab_dispatch(self):
        with patch.object(
            submit_feedback.gitlab_ops,
            "create_issue",
            return_value={"issue_url": "https://gitlab.example.com/g/r/-/issues/5", "issue_iid": 5},
        ) as mock:
            result = submit_feedback.submit(
                "g/r", "gitlab", "Title", "Body", labels=["bug"], host="gitlab.example.com",
            )

        mock.assert_called_once_with(
            "g/r", "Title", "Body", labels=["bug"], instance_url="gitlab.example.com",
        )
        assert result["issue_iid"] == 5

    def test_unsupported_platform(self):
        result = submit_feedback.submit("repo", "bitbucket", "Title", "Body")
        assert "error" in result


class TestParseArgs:
    def test_detect_defaults(self):
        args = submit_feedback.parse_args(["detect"])
        assert args.command == "detect"
        assert args.remote == "origin"
        assert args.cwd is None

    def test_check_issues(self):
        args = submit_feedback.parse_args([
            "check-issues", "--repo-path", "org/repo", "--platform", "github",
        ])
        assert args.command == "check-issues"
        assert args.repo_path == "org/repo"
        assert args.platform == "github"

    def test_gather_context_required_fields(self):
        args = submit_feedback.parse_args([
            "gather-context",
            "--skill-name", "conforma-exception",
            "--type", "bug",
            "--summary", "It broke",
            "--expected", "It works",
            "--actual", "It crashed",
        ])
        assert args.skill_name == "conforma-exception"
        assert args.issue_type == "bug"
        assert args.severity == "major"

    def test_gather_context_all_fields(self):
        args = submit_feedback.parse_args([
            "gather-context",
            "--skill-name", "test",
            "--type", "enhancement",
            "--summary", "Add feature",
            "--expected", "Feature exists",
            "--actual", "No feature",
            "--error-output", "none",
            "--severity", "minor",
            "--additional-context", "Extra info",
        ])
        assert args.issue_type == "enhancement"
        assert args.severity == "minor"
        assert args.additional_context == "Extra info"

    def test_submit_with_labels(self):
        args = submit_feedback.parse_args([
            "submit",
            "--repo-path", "org/repo",
            "--platform", "github",
            "--title", "Bug",
            "--body", "Details",
            "--label", "bug",
            "--label", "conforma",
        ])
        assert args.labels == ["bug", "conforma"]

    def test_invalid_type_rejected(self):
        with pytest.raises(SystemExit):
            submit_feedback.parse_args([
                "gather-context",
                "--skill-name", "test",
                "--type", "invalid",
                "--summary", "s",
                "--expected", "e",
                "--actual", "a",
            ])

    def test_invalid_severity_rejected(self):
        with pytest.raises(SystemExit):
            submit_feedback.parse_args([
                "gather-context",
                "--skill-name", "test",
                "--type", "bug",
                "--summary", "s",
                "--expected", "e",
                "--actual", "a",
                "--severity", "blocker",
            ])
