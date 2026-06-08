"""Tests for scripts/gitlab_ops.py."""
from __future__ import annotations

import subprocess
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
        config_path = tmp_path / "config.yml"
        config_path.write_text(
            "hosts:\n"
            "  gitlab.cee.redhat.com:\n"
            "    token: config-token\n",
            encoding="utf-8",
        )
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", config_path):
            assert gitlab_ops.discover_token() == "config-token"

    def test_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        with patch.object(gitlab_ops, "GLAB_CONFIG_PATH", tmp_path / "missing.yml"):
            assert gitlab_ops.discover_token() is None


class TestVerifyAuth:
    def test_success(self):
        gl = _mock_gl(user="alice")
        with patch.object(gitlab_ops, "get_client", return_value=gl):
            result = gitlab_ops.verify_auth()

        assert result == {
            "ok": True,
            "user": "alice",
            "instance": "https://gitlab.cee.redhat.com",
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


class TestCloneRepo:
    def test_success(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "clone-token")
        target_dir = tmp_path / "repo"
        project = _mock_project(default_branch="develop")
        gl = _mock_gl(project=project)

        with patch.object(gitlab_ops, "get_client", return_value=gl), \
             patch.object(gitlab_ops.subprocess, "run", return_value=_completed()) as mock_run:
            result = gitlab_ops.clone_repo("group/repo", str(target_dir))

        assert result == {"path": str(target_dir.resolve()), "branch": "develop"}
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0:3] == ["git", "clone", "--branch"]
        assert cmd[3] == "develop"
        assert "oauth2:clone-token@" in cmd[4]

    def test_clone_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "clone-token")
        target_dir = tmp_path / "repo"
        gl = _mock_gl()

        with patch.object(gitlab_ops, "get_client", return_value=gl), \
             patch.object(
                 gitlab_ops.subprocess,
                 "run",
                 return_value=_completed(returncode=1, stderr="fatal: repo not found"),
             ):
            result = gitlab_ops.clone_repo("group/repo", str(target_dir))

        assert "error" in result
        assert "git clone failed" in result["error"]


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
