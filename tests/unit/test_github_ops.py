"""Tests for scripts/github_ops.py."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import github_ops

_MOCK_GH_PATH = "/usr/bin/gh"


def _patch_which():
    """Mock shutil.which to return a fake gh path so _run_gh doesn't bail early."""
    return patch.object(github_ops.shutil, "which", return_value=_MOCK_GH_PATH)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _mock_response(status_code: int = 200, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


class TestVerifyAuth:
    def test_success(self):
        resp = _mock_response(200, json_data={"login": "octocat"})
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.verify_auth()

        assert result == {"ok": True, "user": "octocat", "error": None}

    def test_failure(self):
        resp = _mock_response(401)
        with patch.object(github_ops, "get_token", return_value="bad-token"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.verify_auth()

        assert result["ok"] is False
        assert result["user"] is None
        assert "401" in result["error"]

    def test_no_token(self):
        with patch.object(github_ops, "get_token", return_value=""):
            result = github_ops.verify_auth()

        assert result["ok"] is False
        assert "token" in result["error"].lower()


def _patch_no_env_token():
    """Clear GITHUB_TOKEN/GH_TOKEN so get_token() falls through to the gh CLI path."""
    return patch.dict("os.environ", {}, clear=True)


class TestGetToken:
    def test_success(self):
        with _patch_no_env_token(), _patch_which(), patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(stdout="ghp_token123\n"),
        ):
            assert github_ops.get_token() == "ghp_token123"

    def test_failure_returns_empty(self):
        with _patch_no_env_token(), _patch_which(), patch.object(
            github_ops.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr="not authenticated"),
        ):
            assert github_ops.get_token() == ""

    def test_env_var_takes_priority(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_from_env"}, clear=True):
            assert github_ops.get_token() == "ghp_from_env"

    def test_gh_token_env_var(self):
        with patch.dict("os.environ", {"GH_TOKEN": "ghp_alt"}, clear=True):
            assert github_ops.get_token() == "ghp_alt"


class TestCreatePr:
    def test_success(self):
        resp = _mock_response(201, json_data={
            "html_url": "https://github.com/org/repo/pull/42",
            "number": 42,
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", return_value=resp):
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
        resp = _mock_response(422, text="pull request create failed")
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", return_value=resp):
                result = github_ops.create_pr("org/repo", "Title", "Body", "branch")

        assert "error" in result
        assert "422" in result["error"]


class TestGetFile:
    def test_success(self):
        encoded = "aGVsbG8="  # "hello"
        response = _mock_response(200, json_data={
            "encoding": "base64",
            "content": encoded,
            "sha": "abc123",
        })

        with (
            patch.object(github_ops, "get_token", return_value="token"),
            patch.object(github_ops.requests, "get", return_value=response),
        ):
            result = github_ops.get_file("org/repo", "README.md", ref="main")

        assert result == {"content": "hello", "sha": "abc123"}

    def test_not_found(self):
        response = _mock_response(404, text="Not Found")

        with (
            patch.object(github_ops, "get_token", return_value="token"),
            patch.object(github_ops.requests, "get", return_value=response),
        ):
            result = github_ops.get_file("org/repo", "missing.txt")

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestGetRepo:
    def test_success(self):
        resp = _mock_response(200, json_data={
            "full_name": "org/repo",
            "default_branch": "main",
            "private": False,
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.get_repo("org/repo")

        assert result == {
            "full_name": "org/repo",
            "default_branch": "main",
            "private": False,
        }

    def test_error(self):
        resp = _mock_response(404, text="repository not found")
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.get_repo("org/missing")

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestCheckIssuesEnabled:
    def test_enabled(self):
        resp = _mock_response(200, json_data={"has_issues": True})
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.check_issues_enabled("org/repo")

        assert result == {"enabled": True}

    def test_disabled(self):
        resp = _mock_response(200, json_data={"has_issues": False})
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.check_issues_enabled("org/repo")

        assert result == {"enabled": False}

    def test_api_error(self):
        resp = _mock_response(404, text="Not Found")
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.check_issues_enabled("org/missing")

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestCreateIssue:
    def test_success(self):
        resp = _mock_response(201, json_data={
            "html_url": "https://github.com/org/repo/issues/99",
            "number": 99,
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", return_value=resp):
                result = github_ops.create_issue(
                    "org/repo",
                    "Bug: something broke",
                    "Details here",
                    labels=["bug", "conforma"],
                )

        assert result == {
            "issue_url": "https://github.com/org/repo/issues/99",
            "issue_number": 99,
        }

    def test_success_no_labels(self):
        resp = _mock_response(201, json_data={
            "html_url": "https://github.com/org/repo/issues/1",
            "number": 1,
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", return_value=resp):
                result = github_ops.create_issue("org/repo", "Title", "Body")

        assert result["issue_number"] == 1

    def test_labels_passed_to_api(self):
        resp = _mock_response(201, json_data={
            "html_url": "https://github.com/org/repo/issues/5",
            "number": 5,
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", return_value=resp) as mock_post:
                github_ops.create_issue("org/repo", "Title", "Body", labels=["bug", "conforma"])

        payload = mock_post.call_args[1]["json"]
        assert payload["labels"] == ["bug", "conforma"]

    def test_error(self):
        resp = _mock_response(403, text="issues are disabled")
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", return_value=resp):
                result = github_ops.create_issue("org/repo", "Title", "Body")

        assert "error" in result

    def test_timeout(self):
        import requests as _requests
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "post", side_effect=_requests.Timeout("timeout")):
                result = github_ops.create_issue("org/repo", "Title", "Body")

        assert "error" in result


class TestSearchIssues:
    def test_success_with_labels_and_keywords(self):
        resp = _mock_response(200, json_data={
            "total_count": 2,
            "items": [
                {
                    "html_url": "https://github.com/org/repo/issues/10",
                    "title": "[infra] query.py missing",
                    "state": "open",
                    "created_at": "2026-06-01T12:00:00Z",
                    "number": 10,
                },
                {
                    "html_url": "https://github.com/org/repo/issues/8",
                    "title": "[infra] query.py moved",
                    "state": "open",
                    "created_at": "2026-05-15T10:00:00Z",
                    "number": 8,
                },
            ],
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp) as mock_get:
                result = github_ops.search_issues(
                    "org/repo", labels=["infrastructure"], title_keywords="query.py",
                )

        assert result["total"] == 2
        assert len(result["issues"]) == 2
        assert result["issues"][0]["url"] == "https://github.com/org/repo/issues/10"
        assert result["issues"][0]["number"] == 10
        call_params = mock_get.call_args[1]["params"]
        assert "repo:org/repo" in call_params["q"]
        assert 'label:"infrastructure"' in call_params["q"]
        assert "query.py in:title" in call_params["q"]

    def test_no_results(self):
        resp = _mock_response(200, json_data={"total_count": 0, "items": []})
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.search_issues("org/repo")

        assert result["total"] == 0
        assert result["issues"] == []

    def test_no_token(self):
        with patch.object(github_ops, "get_token", return_value=""):
            result = github_ops.search_issues("org/repo")

        assert "error" in result
        assert "token" in result["error"].lower()

    def test_api_error(self):
        resp = _mock_response(422, text="Validation Failed")
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.search_issues("org/repo")

        assert "error" in result
        assert "422" in result["error"]

    def test_request_exception(self):
        import requests as _requests
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", side_effect=_requests.Timeout("timeout")):
                result = github_ops.search_issues("org/repo")

        assert "error" in result

    def test_max_results_respected(self):
        items = [
            {"html_url": f"https://github.com/org/repo/issues/{i}", "title": f"Issue {i}",
             "state": "open", "created_at": "2026-01-01", "number": i}
            for i in range(20)
        ]
        resp = _mock_response(200, json_data={"total_count": 20, "items": items})
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.search_issues("org/repo", max_results=5)

        assert len(result["issues"]) == 5
        assert result["total"] == 20

    def test_query_without_labels_or_keywords(self):
        resp = _mock_response(200, json_data={"total_count": 0, "items": []})
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp) as mock_get:
                github_ops.search_issues("org/repo", state="closed")

        call_params = mock_get.call_args[1]["params"]
        assert "repo:org/repo" in call_params["q"]
        assert "state:closed" in call_params["q"]
        assert "label:" not in call_params["q"]
        assert "in:title" not in call_params["q"]


class TestCheckWorkflowRun:
    def test_success(self):
        resp = _mock_response(200, json_data={
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/org/repo/actions/runs/99",
        })
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", return_value=resp):
                result = github_ops.check_workflow_run("org/repo", 99)

        assert result == {
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/org/repo/actions/runs/99",
        }

    def test_timeout(self):
        import requests as _requests
        with patch.object(github_ops, "get_token", return_value="ghp_test"):
            with patch.object(github_ops.requests, "get", side_effect=_requests.Timeout("timeout")):
                result = github_ops.check_workflow_run("org/repo", 99)

        assert "error" in result
