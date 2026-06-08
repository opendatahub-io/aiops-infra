"""Tests for scripts/github_ops.py."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import github_ops


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestVerifyAuth:
    def test_success(self):
        responses = [
            _completed(stdout="Logged in to github.com\n"),
            _completed(stdout="octocat\n"),
        ]
        with patch.object(github_ops.subprocess, "run", side_effect=responses):
            result = github_ops.verify_auth()

        assert result == {"ok": True, "user": "octocat", "error": None}

    def test_failure(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr="not logged in"),
        ):
            result = github_ops.verify_auth()

        assert result["ok"] is False
        assert result["user"] is None
        assert "not logged in" in result["error"]


class TestGetToken:
    def test_success(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(stdout="ghp_token123\n"),
        ):
            assert github_ops.get_token() == "ghp_token123"

    def test_failure_returns_empty(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr="not authenticated"),
        ):
            assert github_ops.get_token() == ""


class TestCreatePr:
    def test_success(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(stdout="https://github.com/org/repo/pull/42\n"),
        ):
            result = github_ops.create_pr(
                "org/repo",
                "Add feature",
                "Body text",
                "feature-branch",
                base_branch="main",
            )

        assert result == {
            "pr_url": "https://github.com/org/repo/pull/42",
            "pr_number": 42,
        }

    def test_error(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr="pull request create failed"),
        ):
            result = github_ops.create_pr("org/repo", "Title", "Body", "branch")

        assert "error" in result
        assert "pull request create failed" in result["error"]


class TestGetFile:
    def test_success(self):
        encoded = "aGVsbG8="  # "hello"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "encoding": "base64",
            "content": encoded,
            "sha": "abc123",
        }

        with patch.object(github_ops, "get_token", return_value="token"), \
             patch.object(github_ops.requests, "get", return_value=response):
            result = github_ops.get_file("org/repo", "README.md", ref="main")

        assert result == {"content": "hello", "sha": "abc123"}

    def test_not_found(self):
        response = MagicMock(status_code=404)

        with patch.object(github_ops, "get_token", return_value="token"), \
             patch.object(github_ops.requests, "get", return_value=response):
            result = github_ops.get_file("org/repo", "missing.txt")

        assert "error" in result
        assert "File not found" in result["error"]


class TestGetRepo:
    def test_success(self):
        payload = {
            "full_name": "org/repo",
            "default_branch": "main",
            "private": False,
        }
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(stdout=json.dumps(payload)),
        ):
            result = github_ops.get_repo("org/repo")

        assert result == {
            "full_name": "org/repo",
            "default_branch": "main",
            "private": False,
        }

    def test_error(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr="repository not found"),
        ):
            result = github_ops.get_repo("org/missing")

        assert "error" in result
        assert "repository not found" in result["error"]


class TestCheckWorkflowRun:
    def test_success(self):
        payload = {
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/org/repo/actions/runs/99",
        }
        with patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(stdout=json.dumps(payload)),
        ):
            result = github_ops.check_workflow_run("org/repo", 99)

        assert result == {
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/org/repo/actions/runs/99",
        }

    def test_timeout(self):
        with patch.object(
            github_ops.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("gh", 30),
        ):
            result = github_ops.check_workflow_run("org/repo", 99)

        assert result == {"error": "gh api timed out"}
