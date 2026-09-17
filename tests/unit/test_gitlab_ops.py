"""Tests for scripts/gitlab_ops.py."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests
from gitlab.exceptions import GitlabAuthenticationError, GitlabError, GitlabGetError

import gitlab_ops


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _mock_project(
    *,
    project_id: int = 42,
    path: str = "group/repo",
    web_url: str = "https://gitlab.example.com/group/repo",
    default_branch: str = "main",
    http_url: str = "https://gitlab.example.com/group/repo.git",
) -> MagicMock:
    project = MagicMock()
    project.id = project_id
    project.path_with_namespace = path
    project.web_url = web_url
    project.default_branch = default_branch
    project.http_url_to_repo = http_url
    return project


def _mock_gl(project: MagicMock | None = None, user: str = "testuser") -> MagicMock:
    gl = MagicMock()
    gl.user = MagicMock(username=user)
    gl.projects.get.return_value = project or _mock_project()
    return gl


class TestDiscoverToken:
    def test_from_env_var(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "env-token")
        assert gitlab_ops.discover_token() == "env-token"

    def test_from_config_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("GITLAB_HOST", "gitlab.test.example.com")
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "hosts:\n  gitlab.test.example.com:\n    token: config-token\n",
            encoding="utf-8",
        )
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", config_path):
            assert gitlab_ops.discover_token() == "config-token"

    def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", tmp_path / "missing.yml"):
            assert gitlab_ops.discover_token() is None

    def test_from_oauth_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("GITLAB_HOST", "gitlab.test.example.com")
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "hosts:\n  gitlab.test.example.com:\n    oauth_token: oauth-token\n",
            encoding="utf-8",
        )
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", config_path):
            assert gitlab_ops.discover_token() == "oauth-token"

    def test_ignores_non_mapping_host_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("GITLAB_HOST", "gitlab.test.example.com")
        config_path = tmp_path / "config.yml"
        config_path.write_text("hosts:\n  gitlab.test.example.com: token\n", encoding="utf-8")
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", config_path):
            assert gitlab_ops.discover_token() is None

    def test_returns_none_for_invalid_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        config_path = tmp_path / "config.yml"
        config_path.write_text("hosts: [", encoding="utf-8")
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", config_path):
            assert gitlab_ops.discover_token() is None


class TestRetryGitlabOperation:
    def test_defaults_use_longer_timeout_and_backoff(self):
        assert gitlab_ops.DEFAULT_GITLAB_TIMEOUT_SECONDS == 30
        assert gitlab_ops.DEFAULT_GITLAB_RETRY_BACKOFF_SECONDS == 10.0

    def test_default_retry_limit_is_five_attempts(self):
        operation = MagicMock(side_effect=requests.exceptions.ReadTimeout("persistent"))

        with patch.object(gitlab_ops.time, "sleep") as sleep:
            with pytest.raises(requests.exceptions.ReadTimeout, match="persistent"):
                gitlab_ops.retry_gitlab_operation(operation)

        assert operation.call_count == 5
        assert sleep.call_count == 4

    def test_retries_transient_timeout_and_returns_result(self):
        operation = MagicMock(side_effect=[requests.exceptions.ReadTimeout("temporary"), "ok"])

        with patch.object(gitlab_ops.time, "sleep") as sleep:
            result = gitlab_ops.retry_gitlab_operation(operation, backoff_seconds=1)

        assert result == "ok"
        assert operation.call_count == 2
        sleep.assert_called_once_with(1)

    def test_retries_connection_error_with_exponential_backoff(self):
        operation = MagicMock(
            side_effect=[
                requests.exceptions.ConnectionError("temporary"),
                requests.exceptions.ConnectionError("temporary"),
                "ok",
            ]
        )

        with patch.object(gitlab_ops.time, "sleep") as sleep:
            result = gitlab_ops.retry_gitlab_operation(operation, backoff_seconds=2)

        assert result == "ok"
        assert sleep.call_args_list == [((2,),), ((4,),)]

    def test_reraises_after_max_attempts(self):
        error = requests.exceptions.ReadTimeout("persistent")
        operation = MagicMock(side_effect=error)

        with patch.object(gitlab_ops.time, "sleep") as sleep:
            with pytest.raises(requests.exceptions.ReadTimeout, match="persistent"):
                gitlab_ops.retry_gitlab_operation(operation, max_attempts=2, backoff_seconds=0)

        assert operation.call_count == 2
        sleep.assert_called_once_with(0)

    def test_does_not_retry_non_transient_errors(self):
        operation = MagicMock(side_effect=GitlabError("forbidden"))

        with patch.object(gitlab_ops.time, "sleep") as sleep:
            with pytest.raises(GitlabError, match="forbidden"):
                gitlab_ops.retry_gitlab_operation(operation)

        operation.assert_called_once_with()
        sleep.assert_not_called()

    def test_rejects_zero_attempts(self):
        with pytest.raises(ValueError, match="at least 1"):
            gitlab_ops.retry_gitlab_operation(lambda: None, max_attempts=0)


class TestVerifyAuth:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("GITLAB_HOST", "gitlab.test.example.com")
        gl = _mock_gl(user="alice")
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.verify_auth()

        assert result == {
            "ok": True,
            "user": "alice",
            "instance": "https://gitlab.test.example.com",
            "error": None,
        }

    def test_failure(self):
        with patch.object(
            gitlab_ops,
            "get_client",
            side_effect=GitlabAuthenticationError("invalid token"),
        ):
            result = gitlab_ops.verify_auth()

        assert result["ok"] is False
        assert result["user"] is None
        assert "invalid token" in result["error"]

    def test_unexpected_failure(self):
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("network down")):
            result = gitlab_ops.verify_auth("https://gitlab.example.com")

        assert result == {
            "ok": False,
            "user": None,
            "instance": "https://gitlab.example.com",
            "error": "network down",
        }


class TestGetClient:
    def test_requires_token(self, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        with patch.object(gitlab_ops, "discover_token", return_value=None):
            with pytest.raises(ValueError, match="GitLab token not found"):
                gitlab_ops.get_client("gitlab.example.com")

    def test_authenticates_with_explicit_token(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "true")
        client = MagicMock()
        with patch.object(gitlab_ops.gitlab, "Gitlab", return_value=client) as constructor:
            assert gitlab_ops.get_client("gitlab.example.com", token="token") is client

        constructor.assert_called_once_with(
            url="https://gitlab.example.com",
            private_token="token",
            ssl_verify=True,
            timeout=30,
        )
        client.auth.assert_called_once_with()

    def test_retries_without_certificate_verification(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "true")
        first_client = MagicMock()
        first_client.auth.side_effect = RuntimeError("CERTIFICATE_VERIFY_FAILED")
        second_client = MagicMock()
        with patch.object(gitlab_ops.gitlab, "Gitlab", side_effect=[first_client, second_client]) as constructor:
            result = gitlab_ops.get_client("gitlab.example.com", token="token")

        assert result is second_client
        assert constructor.call_count == 2
        second_client.auth.assert_called_once_with()

    def test_reraises_non_certificate_error(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "true")
        client = MagicMock()
        client.auth.side_effect = RuntimeError("unauthorized")
        with patch.object(gitlab_ops.gitlab, "Gitlab", return_value=client):
            with pytest.raises(RuntimeError, match="unauthorized"):
                gitlab_ops.get_client("gitlab.example.com", token="token")


class TestGetProject:
    def test_found(self):
        project = _mock_project()
        gl = _mock_gl(project=project)
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.get_project("group/repo")

        assert result == {
            "id": 42,
            "path": "group/repo",
            "url": "https://gitlab.example.com/group/repo",
        }

    def test_not_found(self):
        gl = MagicMock()
        gl.projects.get.side_effect = GitlabGetError("404")
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.get_project("group/missing")

        assert "error" in result
        assert "group/missing" in result["error"]

    def test_unexpected_error(self):
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("network")):
            assert gitlab_ops.get_project("group/repo") == {"error": "network"}


class TestCreateMr:
    def test_success(self):
        mr = MagicMock(web_url="https://gitlab.example.com/group/repo/-/merge_requests/7", iid=7)
        project = _mock_project()
        project.mergerequests.create.return_value = mr
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.create_mr(
                "group/repo",
                "feature",
                "main",
                "Add feature",
                description="Details",
            )

        assert result == {"mr_url": mr.web_url, "mr_iid": 7}
        project.mergerequests.create.assert_called_once_with(
            {
                "source_branch": "feature",
                "target_branch": "main",
                "title": "Add feature",
                "description": "Details",
            }
        )

    def test_error(self):
        project = _mock_project()
        project.mergerequests.create.side_effect = GitlabError("branch not found")
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.create_mr("group/repo", "feature", "main", "Add feature")

        assert "error" in result
        assert "branch not found" in result["error"]

    def test_unexpected_error(self):
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("network")):
            assert gitlab_ops.create_mr("group/repo", "feature", "main", "Title") == {"error": "network"}


class TestCheckIssuesEnabled:
    def test_enabled(self):
        project = _mock_project()
        project.issues_enabled = True
        gl = _mock_gl(project=project)
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.check_issues_enabled("group/repo")

        assert result == {"enabled": True}

    def test_disabled(self):
        project = _mock_project()
        project.issues_enabled = False
        gl = _mock_gl(project=project)
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.check_issues_enabled("group/repo")

        assert result == {"enabled": False}

    def test_project_not_found(self):
        gl = MagicMock()
        gl.projects.get.side_effect = GitlabGetError("404")
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.check_issues_enabled("group/missing")

        assert "error" in result

    def test_unexpected_error(self):
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("network")):
            assert gitlab_ops.check_issues_enabled("group/repo") == {"error": "network"}


class TestCreateIssue:
    def test_success(self):
        issue = MagicMock(
            web_url="https://gitlab.example.com/group/repo/-/issues/12",
            iid=12,
        )
        project = _mock_project()
        project.issues.create.return_value = issue
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.create_issue(
                "group/repo",
                "Bug report",
                "Description text",
                labels=["bug", "conforma"],
            )

        assert result == {"issue_url": issue.web_url, "issue_iid": 12}
        project.issues.create.assert_called_once_with(
            {
                "title": "Bug report",
                "description": "Description text",
                "labels": "bug,conforma",
            }
        )

    def test_success_no_labels(self):
        issue = MagicMock(
            web_url="https://gitlab.example.com/group/repo/-/issues/1",
            iid=1,
        )
        project = _mock_project()
        project.issues.create.return_value = issue
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.create_issue("group/repo", "Title", "Desc")

        assert result["issue_iid"] == 1
        call_data = project.issues.create.call_args[0][0]
        assert "labels" not in call_data

    def test_error(self):
        project = _mock_project()
        project.issues.create.side_effect = GitlabError("forbidden")
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.create_issue("group/repo", "Title", "Desc")

        assert "error" in result
        assert "forbidden" in result["error"]

    def test_project_not_found(self):
        gl = MagicMock()
        gl.projects.get.side_effect = GitlabGetError("404")
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.create_issue("group/missing", "Title", "Desc")

        assert "error" in result

    def test_gitlab_error(self):
        project = _mock_project()
        project.issues.create.side_effect = GitlabError("forbidden")
        with patch.object(gitlab_ops, "get_client", return_value=_mock_gl(project=project)):
            result = gitlab_ops.create_issue("group/repo", "Title", "Desc")
        assert result == {"error": "Failed to create issue: forbidden"}

    def test_unexpected_error(self):
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("network")):
            assert gitlab_ops.create_issue("group/repo", "Title", "Desc") == {"error": "network"}


class TestFindMr:
    def test_returns_matching_mrs(self):
        mr = MagicMock(
            iid=3,
            web_url="https://gitlab.example.com/group/repo/-/merge_requests/3",
            title="Fix bug",
            source_branch="fix",
            target_branch="main",
            state="opened",
        )
        project = _mock_project()
        project.mergerequests.list.return_value = [mr]
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.find_mr(
                "group/repo",
                source_branch="fix",
                target_branch="main",
                state="opened",
            )

        assert result == [
            {
                "mr_iid": 3,
                "mr_url": mr.web_url,
                "title": "Fix bug",
                "source_branch": "fix",
                "target_branch": "main",
                "state": "opened",
            }
        ]
        project.mergerequests.list.assert_called_once_with(
            state="opened",
            all=True,
            source_branch="fix",
            target_branch="main",
        )

    def test_returns_all_mrs_when_filters_are_absent(self):
        project = _mock_project()
        project.mergerequests.list.return_value = []
        with patch.object(gitlab_ops, "get_client", return_value=_mock_gl(project=project)):
            assert gitlab_ops.find_mr("group/repo", state="closed") == []
        project.mergerequests.list.assert_called_once_with(state="closed", all=True)

    def test_returns_error_on_failure(self):
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("network")):
            assert gitlab_ops.find_mr("group/repo") == [{"error": "network"}]


class TestUpdateMr:
    def test_rejects_empty_update(self):
        assert gitlab_ops.update_mr("group/repo", 1) == {
            "error": "At least one of title or description must be provided"
        }

    def test_updates_title_and_description(self):
        mr = MagicMock(web_url="https://gitlab.example/mr/1", iid=1)
        project = _mock_project()
        project.mergerequests.get.return_value = mr
        with patch.object(gitlab_ops, "get_client", return_value=_mock_gl(project=project)):
            result = gitlab_ops.update_mr("group/repo", 1, title="New title", description="New description")
        assert result == {"mr_url": mr.web_url, "mr_iid": 1}
        assert mr.title == "New title"
        assert mr.description == "New description"
        mr.save.assert_called_once_with()

    def test_updates_title_only(self):
        mr = MagicMock(web_url="url", iid=2)
        project = _mock_project()
        project.mergerequests.get.return_value = mr
        with patch.object(gitlab_ops, "get_client", return_value=_mock_gl(project=project)):
            result = gitlab_ops.update_mr("group/repo", 2, title="New title")
        assert result["mr_iid"] == 2
        assert mr.title == "New title"

    def test_updates_description_only(self):
        mr = MagicMock(web_url="url", iid=3)
        project = _mock_project()
        project.mergerequests.get.return_value = mr
        with patch.object(gitlab_ops, "get_client", return_value=_mock_gl(project=project)):
            result = gitlab_ops.update_mr("group/repo", 3, description="New description")
        assert result["mr_iid"] == 3
        assert mr.description == "New description"

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (GitlabGetError("404"), "Merge request not found: 4: 404"),
            (GitlabError("forbidden"), "Failed to update merge request: forbidden"),
            (RuntimeError("network"), "network"),
        ],
    )
    def test_update_errors(self, error, expected):
        project = _mock_project()
        project.mergerequests.get.side_effect = error
        with patch.object(gitlab_ops, "get_client", return_value=_mock_gl(project=project)):
            result = gitlab_ops.update_mr("group/repo", 4, title="Title")
        assert result == {"error": expected}


class TestMain:
    @pytest.mark.parametrize(
        "argv, function_name",
        [
            (["gitlab_ops.py", "verify-auth"], "verify_auth"),
            (["gitlab_ops.py", "get-project", "--project", "group/repo"], "get_project"),
            (
                ["gitlab_ops.py", "clone-repo", "--project", "group/repo", "--target-dir", "/tmp/repo"],
                "clone_repo",
            ),
            (
                ["gitlab_ops.py", "push-branch", "--repo-dir", "/tmp/repo", "--branch", "feature", "--commit-msg", "msg"],
                "push_branch",
            ),
            (
                ["gitlab_ops.py", "create-mr", "--project", "group/repo", "--source-branch", "feature", "--title", "Title"],
                "create_mr",
            ),
            (["gitlab_ops.py", "check-issues-enabled", "--project", "group/repo"], "check_issues_enabled"),
            (
                ["gitlab_ops.py", "create-issue", "--project", "group/repo", "--title", "Title"],
                "create_issue",
            ),
            (["gitlab_ops.py", "find-mr", "--project", "group/repo"], "find_mr"),
        ],
    )
    def test_dispatches_command(self, monkeypatch, capsys, argv, function_name):
        monkeypatch.setattr(sys, "argv", argv)
        with patch.object(gitlab_ops, function_name, return_value={"ok": True}) as function:
            gitlab_ops.main()
        function.assert_called_once()
        assert '"ok": true' in capsys.readouterr().out


class TestGitEnv:
    """Tests for git_env() — ensures GITLAB_SSL_VERIFY propagates to GIT_SSL_NO_VERIFY."""

    def test_ssl_verify_true_by_default(self, monkeypatch):
        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        env = gitlab_ops.git_env()
        assert "GIT_SSL_NO_VERIFY" not in env

    def test_ssl_verify_false_sets_git_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "false")
        env = gitlab_ops.git_env()
        assert env["GIT_SSL_NO_VERIFY"] == "1"

    def test_ssl_verify_zero_sets_git_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "0")
        env = gitlab_ops.git_env()
        assert env["GIT_SSL_NO_VERIFY"] == "1"

    def test_ssl_verify_off_sets_git_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "off")
        env = gitlab_ops.git_env()
        assert env["GIT_SSL_NO_VERIFY"] == "1"

    def test_ssl_verify_true_does_not_set_git_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "true")
        env = gitlab_ops.git_env()
        assert "GIT_SSL_NO_VERIFY" not in env

    def test_auth_header_when_token_available(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "test-token")
        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
        env = gitlab_ops.git_env()
        assert env["GIT_CONFIG_COUNT"] == "1"
        assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
        assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer test-token"

    def test_no_auth_header_when_no_token(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", tmp_path / "nonexistent.yml"):
            env = gitlab_ops.git_env()
        assert "GIT_CONFIG_COUNT" not in env

    def test_auth_appends_to_existing_git_config(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "test-token")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Test User")
        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        env = gitlab_ops.git_env()
        assert env["GIT_CONFIG_COUNT"] == "2"
        assert env["GIT_CONFIG_KEY_0"] == "user.name"
        assert env["GIT_CONFIG_KEY_1"] == "http.extraHeader"
        assert env["GIT_CONFIG_VALUE_1"] == "Authorization: Bearer test-token"


class TestRedactToken:
    """Tests for _redact_token() — scrubs tokens from error text."""

    def test_redacts_token(self):
        result = gitlab_ops._redact_token("error with token123 in msg", "token123")
        assert result == "error with REDACTED in msg"

    def test_empty_token_no_op(self):
        assert gitlab_ops._redact_token("some error message", "") == "some error message"

    def test_no_match_unchanged(self):
        assert gitlab_ops._redact_token("clean message", "absent") == "clean message"


class TestAuthenticatedCloneUrl:
    """Tests for authenticated_clone_url() — validates token and returns plain clone URL."""

    def test_returns_plain_url(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "my-token")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.example.com")
        url = gitlab_ops.authenticated_clone_url("group/repo")
        assert url == "https://gitlab.example.com/group/repo.git"
        assert "my-token" not in url

    def test_uses_glab_config_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("GITLAB_HOST", "gitlab.test.com")
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "hosts:\n  gitlab.test.com:\n    token: glab-token\n",
            encoding="utf-8",
        )
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", config_path):
            url = gitlab_ops.authenticated_clone_url("org/project")
        assert url == "https://gitlab.test.com/org/project.git"
        assert "glab-token" not in url

    def test_raises_when_no_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setenv("GITLAB_HOST", "gitlab.nowhere.com")
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", tmp_path / "missing.yml"):
            import pytest

            with pytest.raises(ValueError, match="No GitLab token found"):
                gitlab_ops.authenticated_clone_url("org/project")

    def test_custom_instance_url(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "custom-token")
        url = gitlab_ops.authenticated_clone_url("team/repo", instance_url="https://custom.gitlab.io")
        assert url == "https://custom.gitlab.io/team/repo.git"
        assert "custom-token" not in url


class TestRunGit:
    """Tests for run_git() — git subprocess wrapper with SSL env injection."""

    def test_passes_ssl_env_when_verify_disabled(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "false")
        with patch("subprocess.run", return_value=_completed()) as mock_run:
            gitlab_ops.run_git(["git", "status"])
        call_env = mock_run.call_args[1]["env"]
        assert call_env["GIT_SSL_NO_VERIFY"] == "1"

    def test_no_ssl_env_when_verify_enabled(self, monkeypatch):
        monkeypatch.setenv("GITLAB_SSL_VERIFY", "true")
        with patch("subprocess.run", return_value=_completed()) as mock_run:
            gitlab_ops.run_git(["git", "status"])
        call_env = mock_run.call_args[1]["env"]
        assert "GIT_SSL_NO_VERIFY" not in call_env

    def test_passes_cwd(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        with patch("subprocess.run", return_value=_completed()) as mock_run:
            gitlab_ops.run_git(["git", "fetch"], cwd=tmp_path)
        assert mock_run.call_args[1]["cwd"] == tmp_path

    def test_passes_timeout(self, monkeypatch):
        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        with patch("subprocess.run", return_value=_completed()) as mock_run:
            gitlab_ops.run_git(["git", "clone", "url"], timeout=300)
        assert mock_run.call_args[1]["timeout"] == 300

    def test_raises_on_failure_when_check_true(self, monkeypatch):
        import subprocess as sp

        monkeypatch.delenv("GITLAB_SSL_VERIFY", raising=False)
        with patch(
            "subprocess.run",
            side_effect=sp.CalledProcessError(1, ["git"], "", "fatal: error"),
        ):
            import pytest

            with pytest.raises(sp.CalledProcessError):
                gitlab_ops.run_git(["git", "fetch"], check=True)


class TestCloneRepo:
    def test_missing_token(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        with patch.object(gitlab_ops, "discover_token", return_value=None):
            assert gitlab_ops.clone_repo("group/repo", str(tmp_path / "repo")) == {
                "error": "GitLab token not found for clone"
            }

    def test_nonempty_target(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "token")
        target_dir = tmp_path / "repo"
        target_dir.mkdir()
        (target_dir / "existing").write_text("data", encoding="utf-8")
        with patch.object(gitlab_ops, "get_client"):
            result = gitlab_ops.clone_repo("group/repo", str(target_dir))
        assert result == {"error": f"Target directory is not empty: {target_dir}"}

    def test_success_no_token_in_url(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "clone-token")
        monkeypatch.delenv("GIT_CONFIG_COUNT", raising=False)
        target_dir = tmp_path / "repo"
        project = _mock_project(default_branch="develop")
        gl = _mock_gl(project=project)

        with (
            patch.object(gitlab_ops, "get_client", return_value=gl),
            patch.object(gitlab_ops.subprocess, "run", return_value=_completed()) as mock_run,
        ):
            result = gitlab_ops.clone_repo("group/repo", str(target_dir))

        assert result == {"path": str(target_dir.resolve()), "branch": "develop"}
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["git", "clone", "--branch"]
        assert cmd[3] == "develop"
        assert "clone-token" not in cmd[4]
        assert "oauth2:" not in cmd[4]
        call_env = mock_run.call_args[1]["env"]
        assert call_env["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer clone-token"

    def test_clone_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "clone-token")
        target_dir = tmp_path / "repo"
        gl = _mock_gl()

        with (
            patch.object(gitlab_ops, "get_client", return_value=gl),
            patch.object(
                gitlab_ops.subprocess,
                "run",
                return_value=_completed(returncode=1, stderr="fatal: repo not found"),
            ),
        ):
            result = gitlab_ops.clone_repo("group/repo", str(target_dir))

        assert "error" in result
        assert "git clone failed" in result["error"]

    def test_clone_error_redacts_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "secret-tok-123")
        target_dir = tmp_path / "repo"
        gl = _mock_gl()

        with (
            patch.object(gitlab_ops, "get_client", return_value=gl),
            patch.object(
                gitlab_ops.subprocess,
                "run",
                return_value=_completed(
                    returncode=1,
                    stderr="fatal: could not read secret-tok-123 from remote",
                ),
            ),
        ):
            result = gitlab_ops.clone_repo("group/repo", str(target_dir))

        assert "error" in result
        assert "secret-tok-123" not in result["error"]
        assert "REDACTED" in result["error"]

    def test_clone_uses_requested_branch(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "token")
        target_dir = tmp_path / "repo"
        with (
            patch.object(gitlab_ops, "get_client", return_value=_mock_gl()),
            patch.object(gitlab_ops.subprocess, "run", return_value=_completed()),
        ):
            result = gitlab_ops.clone_repo("group/repo", str(target_dir), branch="release")
        assert result["branch"] == "release"

    def test_project_lookup_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "secret")
        gl = MagicMock()
        gl.projects.get.side_effect = GitlabGetError("404")
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.clone_repo("group/repo", str(tmp_path / "repo"))
        assert "Project not found" in result["error"]

    def test_clone_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "token")
        with (
            patch.object(gitlab_ops, "get_client", return_value=_mock_gl()),
            patch.object(gitlab_ops.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 600)),
        ):
            assert gitlab_ops.clone_repo("group/repo", str(tmp_path / "repo")) == {"error": "git clone timed out"}

    def test_unexpected_clone_error_is_redacted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "secret")
        with patch.object(gitlab_ops, "get_client", side_effect=RuntimeError("secret failed")):
            result = gitlab_ops.clone_repo("group/repo", str(tmp_path / "repo"))
        assert result == {"error": "REDACTED failed"}


class TestPushBranch:
    def test_success(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        responses = [
            _completed(),  # checkout
            _completed(),  # add
            _completed(stdout="M file.txt\n"),  # status
            _completed(),  # commit
            _completed(),  # push
        ]
        with patch.object(gitlab_ops, "_run_git", side_effect=responses):
            result = gitlab_ops.push_branch(str(repo_dir), "feature", "Update files")

        assert result == {"branch": "feature", "pushed": True}

    def test_no_changes(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()

        responses = [
            _completed(),
            _completed(),
            _completed(stdout=""),
        ]
        with patch.object(gitlab_ops, "_run_git", side_effect=responses):
            result = gitlab_ops.push_branch(str(repo_dir), "feature", "Update files")

        assert result == {"error": "No changes to commit"}

    def test_missing_repo_dir(self, tmp_path):
        result = gitlab_ops.push_branch(str(tmp_path / "missing"), "feature", "msg")
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.parametrize(
        ("responses", "expected"),
        [
            ([_completed(returncode=1, stderr="checkout")], "git checkout failed: checkout"),
            ([_completed(), _completed(returncode=1, stderr="add")], "git add failed: add"),
            ([_completed(), _completed(), _completed(returncode=1, stderr="status")], "git status failed: status"),
            (
                [_completed(), _completed(), _completed(stdout="M file"), _completed(returncode=1, stderr="commit")],
                "git commit failed: commit",
            ),
            (
                [
                    _completed(),
                    _completed(),
                    _completed(stdout="M file"),
                    _completed(),
                    _completed(returncode=1, stderr="push"),
                ],
                "git push failed: push",
            ),
        ],
    )
    def test_git_step_failures(self, tmp_path, responses, expected):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        with patch.object(gitlab_ops, "_run_git", side_effect=responses):
            result = gitlab_ops.push_branch(str(repo_dir), "feature", "Update files")
        assert result == {"error": expected}

    def test_uses_explicit_files(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        responses = [_completed(), _completed(), _completed(stdout="M file"), _completed(), _completed()]
        with patch.object(gitlab_ops, "_run_git", side_effect=responses) as run_git:
            gitlab_ops.push_branch(str(repo_dir), "feature", "Update files", files=["file.txt"])
        assert run_git.call_args_list[1].args[1] == ["add", "file.txt"]

    def test_git_timeout(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        with patch.object(gitlab_ops, "_run_git", side_effect=subprocess.TimeoutExpired("git", 120)):
            assert gitlab_ops.push_branch(str(repo_dir), "feature", "msg") == {"error": "git operation timed out"}

    def test_unexpected_git_error(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        with patch.object(gitlab_ops, "_run_git", side_effect=RuntimeError("broken")):
            assert gitlab_ops.push_branch(str(repo_dir), "feature", "msg") == {"error": "broken"}


class TestRunGitInternal:
    def test_runs_git_with_repository_directory_and_environment(self, tmp_path):
        with patch.object(gitlab_ops.subprocess, "run", return_value=_completed()) as run:
            result = gitlab_ops._run_git(str(tmp_path), ["status"], timeout=7)

        assert result.returncode == 0
        run.assert_called_once()
        assert run.call_args.args[0] == ["git", "status"]
        assert run.call_args.kwargs["cwd"] == str(tmp_path)
        assert run.call_args.kwargs["timeout"] == 7
