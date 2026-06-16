"""Tests for scripts/git_ops.py."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import git_ops


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestParseUrl:
    def test_https_url(self):
        result = git_ops.parse_url("https://github.com/opendatahub-io/aiops-infra")
        assert result == {
            "host": "github.com",
            "repo_path": "opendatahub-io/aiops-infra",
            "scheme": "https",
        }

    def test_https_url_with_git_suffix(self):
        result = git_ops.parse_url("https://github.com/opendatahub-io/aiops-infra.git")
        assert result == {
            "host": "github.com",
            "repo_path": "opendatahub-io/aiops-infra",
            "scheme": "https",
        }

    def test_ssh_url(self):
        result = git_ops.parse_url("git@github.com:opendatahub-io/aiops-infra.git")
        assert result == {
            "host": "github.com",
            "repo_path": "opendatahub-io/aiops-infra",
            "scheme": "ssh",
        }

    def test_ssh_url_without_git_suffix(self):
        result = git_ops.parse_url("git@github.com:opendatahub-io/aiops-infra")
        assert result == {
            "host": "github.com",
            "repo_path": "opendatahub-io/aiops-infra",
            "scheme": "ssh",
        }

    def test_gitlab_https_url(self):
        result = git_ops.parse_url("https://gitlab.cee.redhat.com/group/project.git")
        assert result == {
            "host": "gitlab.cee.redhat.com",
            "repo_path": "group/project",
            "scheme": "https",
        }

    def test_gitlab_ssh_nested_path(self):
        result = git_ops.parse_url("git@gitlab.example.com:group/subgroup/project.git")
        assert result == {
            "host": "gitlab.example.com",
            "repo_path": "group/subgroup/project",
            "scheme": "ssh",
        }

    def test_empty_url(self):
        result = git_ops.parse_url("")
        assert "error" in result

    def test_malformed_url(self):
        result = git_ops.parse_url("not-a-url")
        assert "error" in result


class TestClassifyPlatform:
    def test_github_com(self):
        assert git_ops._classify_platform("github.com") == "github"

    def test_gitlab_host_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_HOST", "gitlab.internal.example.com")
        assert git_ops._classify_platform("gitlab.internal.example.com") == "gitlab"

    def test_gl_host_env(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.setenv("GL_HOST", "gl.corp.io")
        assert git_ops._classify_platform("gl.corp.io") == "gitlab"

    def test_host_containing_gitlab(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.delenv("GL_HOST", raising=False)
        assert git_ops._classify_platform("gitlab.cee.redhat.com") == "gitlab"

    def test_unknown_host(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.delenv("GL_HOST", raising=False)
        assert git_ops._classify_platform("bitbucket.org") == "unknown"


class TestDetectRemote:
    def test_github_remote(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.delenv("GL_HOST", raising=False)
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(stdout="https://github.com/opendatahub-io/aiops-infra.git\n"),
        ):
            result = git_ops.detect_remote()

        assert result == {
            "platform": "github",
            "host": "github.com",
            "repo_path": "opendatahub-io/aiops-infra",
            "url": "https://github.com/opendatahub-io/aiops-infra",
        }

    def test_gitlab_remote_via_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.io")
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(stdout="git@gitlab.corp.io:team/project.git\n"),
        ):
            result = git_ops.detect_remote()

        assert result["platform"] == "gitlab"
        assert result["host"] == "gitlab.corp.io"
        assert result["repo_path"] == "team/project"

    def test_gitlab_remote_via_hostname(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.delenv("GL_HOST", raising=False)
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(stdout="https://gitlab.cee.redhat.com/group/repo\n"),
        ):
            result = git_ops.detect_remote()

        assert result["platform"] == "gitlab"

    def test_unknown_host(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.delenv("GL_HOST", raising=False)
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(stdout="https://bitbucket.org/team/repo.git\n"),
        ):
            result = git_ops.detect_remote()

        assert result["platform"] == "unknown"

    def test_missing_remote(self):
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(returncode=128, stderr="fatal: No such remote 'upstream'"),
        ):
            result = git_ops.detect_remote(remote="upstream")

        assert "error" in result
        assert "upstream" in result["error"]

    def test_not_a_git_dir(self):
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(returncode=128, stderr="fatal: not a git repository"),
        ):
            result = git_ops.detect_remote(cwd="/tmp/not-a-repo")

        assert "error" in result

    def test_git_not_found(self):
        with patch.object(
            git_ops.subprocess,
            "run",
            side_effect=FileNotFoundError(),
        ):
            result = git_ops.detect_remote()

        assert result == {"error": "git not found on PATH"}

    def test_timeout(self):
        with patch.object(
            git_ops.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("git", 15),
        ):
            result = git_ops.detect_remote()

        assert result == {"error": "git command timed out"}

    def test_custom_cwd_and_remote(self, monkeypatch):
        monkeypatch.delenv("GITLAB_HOST", raising=False)
        monkeypatch.delenv("GL_HOST", raising=False)
        with patch.object(
            git_ops.subprocess,
            "run",
            return_value=_completed(stdout="https://github.com/org/repo\n"),
        ) as mock_run:
            git_ops.detect_remote(cwd="/some/path", remote="upstream")

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["git", "remote", "get-url", "upstream"]
        assert call_args[1]["cwd"] == "/some/path"
