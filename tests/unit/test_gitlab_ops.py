"""Tests for scripts/gitlab_ops.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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
        url = gitlab_ops.authenticated_clone_url(
            "team/repo", instance_url="https://custom.gitlab.io"
        )
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
