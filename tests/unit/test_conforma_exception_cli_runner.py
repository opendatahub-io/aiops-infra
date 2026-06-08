"""Tests for conforma-exception cli_runner.py."""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import cli_runner


class TestSaveToken:
    def test_saves_token_with_mode_0600(self, tmp_path, monkeypatch):
        token_file = tmp_path / "jira_api_token"
        monkeypatch.setitem(cli_runner._TOKEN_FILES, "JIRA_API_TOKEN", token_file)

        result = cli_runner.save_token("JIRA_API_TOKEN", "my-secret-token")

        assert result == token_file
        assert token_file.read_text(encoding="utf-8") == "my-secret-token\n"
        assert stat.S_IMODE(token_file.stat().st_mode) == 0o600

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        token_file = tmp_path / "nested" / "glab" / "token"
        monkeypatch.setitem(cli_runner._TOKEN_FILES, "GITLAB_TOKEN", token_file)

        cli_runner.save_token("GITLAB_TOKEN", "glab-token")

        assert token_file.is_file()


class TestResolveMethod:
    def test_acli_native_when_found(self):
        with patch.object(cli_runner, "_find_acli", return_value="/usr/bin/acli"):
            assert cli_runner.resolve_method("acli") == "native"

    def test_glab_native_on_path(self):
        with patch.object(cli_runner, "_find_acli", return_value=None), \
             patch.object(cli_runner.shutil, "which", return_value="/usr/bin/glab"):
            assert cli_runner.resolve_method("glab") == "native"

    def test_docker_fallback(self):
        with patch.object(cli_runner, "_find_acli", return_value=None), \
             patch.object(cli_runner.shutil, "which", side_effect=lambda b: "/usr/bin/docker" if b == "docker" else None), \
             patch.object(cli_runner, "_container_runtime", return_value="docker"):
            assert cli_runner.resolve_method("acli") == "docker"

    def test_podman_fallback(self):
        with patch.object(cli_runner, "_find_acli", return_value=None), \
             patch.object(cli_runner.shutil, "which", return_value=None), \
             patch.object(cli_runner, "_container_runtime", return_value="podman"):
            assert cli_runner.resolve_method("glab") == "podman"

    def test_unavailable(self):
        with patch.object(cli_runner, "_find_acli", return_value=None), \
             patch.object(cli_runner.shutil, "which", return_value=None), \
             patch.object(cli_runner, "_container_runtime", return_value=None):
            assert cli_runner.resolve_method("acli") == "unavailable"


class TestRunAcli:
    def test_runs_native_binary(self):
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.object(cli_runner, "_find_acli", return_value="/usr/bin/acli"), \
             patch.object(cli_runner.subprocess, "run", return_value=mock_result) as mock_run:
            result = cli_runner.run_acli(["jira", "auth", "status"])

        assert result is mock_result
        mock_run.assert_called_once_with(
            ["/usr/bin/acli", "jira", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=None,
        )

    def test_container_fallback_when_native_missing(self):
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.object(cli_runner, "_find_acli", return_value=None), \
             patch.object(cli_runner, "_install_acli_local", side_effect=RuntimeError("no network")), \
             patch.object(cli_runner, "_container_runtime", return_value="docker"), \
             patch.object(cli_runner, "_build_container_cmd", return_value=["docker", "run", "acli"]) as mock_build, \
             patch.object(cli_runner.subprocess, "run", return_value=mock_result) as mock_run:
            result = cli_runner.run_acli(["jira", "workitem", "view", "ABC-1"])

        assert result is mock_result
        mock_build.assert_called_once()
        mock_run.assert_called_once_with(
            ["docker", "run", "acli"],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_raises_when_unavailable(self):
        with patch.object(cli_runner, "_find_acli", return_value=None), \
             patch.object(cli_runner, "_install_acli_local", side_effect=RuntimeError("fail")), \
             patch.object(cli_runner, "_container_runtime", return_value=None):
            with pytest.raises(FileNotFoundError, match="acli"):
                cli_runner.run_acli(["jira", "auth", "status"])


class TestRunGlab:
    def test_runs_native_glab(self):
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.object(cli_runner.shutil, "which", return_value="/usr/bin/glab"), \
             patch.object(cli_runner.subprocess, "run", return_value=mock_result) as mock_run:
            result = cli_runner.run_glab(["auth", "status"])

        assert result is mock_result
        mock_run.assert_called_once_with(
            ["glab", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=None,
        )

    def test_container_fallback(self):
        mock_result = MagicMock(returncode=0, stdout="ok", stderr="")
        with patch.object(cli_runner.shutil, "which", return_value=None), \
             patch.object(cli_runner, "_container_runtime", return_value="podman"), \
             patch.object(cli_runner, "_build_container_cmd", return_value=["podman", "run", "glab"]) as mock_build, \
             patch.object(cli_runner.subprocess, "run", return_value=mock_result):
            result = cli_runner.run_glab(["api", "projects"])

        mock_build.assert_called_once()
        assert result is mock_result

    def test_raises_when_unavailable(self):
        with patch.object(cli_runner.shutil, "which", return_value=None), \
             patch.object(cli_runner, "_container_runtime", return_value=None):
            with pytest.raises(FileNotFoundError, match="glab"):
                cli_runner.run_glab(["auth", "status"])


class TestResolveEnv:
    def test_returns_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "from-env")
        with patch.object(cli_runner, "_migrate_old_config_dir"):
            assert cli_runner._resolve_env("GITLAB_TOKEN") == "from-env"

    def test_falls_back_to_token_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        token_file = tmp_path / "jira_api_token"
        token_file.write_text("file-token\n", encoding="utf-8")
        monkeypatch.setitem(cli_runner._TOKEN_FILES, "JIRA_API_TOKEN", token_file)

        with patch.object(cli_runner, "_migrate_old_config_dir"):
            assert cli_runner._resolve_env("JIRA_API_TOKEN") == "file-token"

    def test_jira_email_from_acli_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        missing_token = tmp_path / "no_jira_email"
        monkeypatch.setitem(cli_runner._TOKEN_FILES, "JIRA_EMAIL", missing_token)
        with patch.object(cli_runner, "_migrate_old_config_dir"), \
             patch.object(cli_runner, "_get_email_from_acli_config", return_value="user@redhat.com"):
            assert cli_runner._resolve_env("JIRA_EMAIL") == "user@redhat.com"

    def test_jira_email_fallback_to_getuser(self, tmp_path, monkeypatch):
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        missing_token = tmp_path / "no_jira_email"
        monkeypatch.setitem(cli_runner._TOKEN_FILES, "JIRA_EMAIL", missing_token)
        with patch.object(cli_runner, "_migrate_old_config_dir"), \
             patch.object(cli_runner, "_get_email_from_acli_config", return_value=None), \
             patch("getpass.getuser", return_value="jdoe"):
            assert cli_runner._resolve_env("JIRA_EMAIL") == "jdoe@redhat.com"

    def test_returns_none_for_unknown_var(self, monkeypatch):
        monkeypatch.delenv("UNKNOWN_VAR", raising=False)
        with patch.object(cli_runner, "_migrate_old_config_dir"):
            assert cli_runner._resolve_env("UNKNOWN_VAR") is None
