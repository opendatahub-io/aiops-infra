"""Tests for site_config.py connectivity check and confirmed state."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import site_config


@pytest.fixture(autouse=True)
def _reset_loaded():
    site_config._loaded = False
    yield
    site_config._loaded = False


@pytest.fixture
def connectivity_dir(tmp_path, monkeypatch):
    """Redirect connectivity state to a temp directory."""
    monkeypatch.setattr(site_config, "CONNECTIVITY_STATE_DIR", tmp_path)
    monkeypatch.setattr(site_config, "CONNECTIVITY_STATE_FILE", tmp_path / ".connectivity.json")
    return tmp_path


class TestCheckConnectivity:
    def test_dns_failure(self, connectivity_dir):
        with patch.dict(os.environ, {"GITLAB_HOST": "nonexistent.internal.corp"}):
            with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name resolution failed")):
                result = site_config.check_connectivity()
        assert result.gitlab_dns is False
        assert result.gitlab_https is False
        assert "dns" in result.error_details

    def test_https_failure(self, connectivity_dir):
        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com"}):
            with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 443))]):
                with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
                    result = site_config.check_connectivity()
        assert result.gitlab_dns is True
        assert result.gitlab_https is False
        assert "https" in result.error_details

    def test_auth_no_token(self, connectivity_dir):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        env = {"GITLAB_HOST": "gitlab.corp.com", "GITLAB_PROJECT": "test/project"}
        env_clean = {k: v for k, v in os.environ.items() if k != "GITLAB_TOKEN"}
        env_clean.update(env)

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 443))]):
                with patch("urllib.request.urlopen", return_value=mock_resp):
                    with patch.dict("sys.modules", {"gitlab_ops": MagicMock(discover_token=MagicMock(return_value=None))}):
                        result = site_config.check_connectivity()
        assert result.gitlab_dns is True
        assert result.gitlab_https is True
        assert result.gitlab_auth is None
        assert "auth" in result.error_details

    def test_auth_token_rejected(self, connectivity_dir):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_gitlab_ops = MagicMock()
        mock_gitlab_ops.discover_token = MagicMock(return_value="bad-token")

        mock_gitlab_mod = MagicMock()
        mock_gl_instance = MagicMock()
        mock_gl_instance.auth.side_effect = Exception("401 Unauthorized")
        mock_gitlab_mod.Gitlab.return_value = mock_gl_instance

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com", "GITLAB_PROJECT": "test/project"}):
            with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 443))]):
                with patch("urllib.request.urlopen", return_value=mock_resp):
                    with patch.dict("sys.modules", {"gitlab_ops": mock_gitlab_ops, "gitlab": mock_gitlab_mod}):
                        result = site_config.check_connectivity()
        assert result.gitlab_dns is True
        assert result.gitlab_https is True
        assert result.gitlab_auth is False
        assert "auth" in result.error_details

    def test_project_not_accessible(self, connectivity_dir):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_gitlab_ops = MagicMock()
        mock_gitlab_ops.discover_token = MagicMock(return_value="good-token")

        mock_gl_instance = MagicMock()
        mock_gl_instance.auth.return_value = None
        mock_gl_instance.projects.get.side_effect = Exception("404 Project Not Found")

        mock_gitlab_mod = MagicMock()
        mock_gitlab_mod.Gitlab.return_value = mock_gl_instance

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com", "GITLAB_PROJECT": "test/project"}):
            with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 443))]):
                with patch("urllib.request.urlopen", return_value=mock_resp):
                    with patch.dict("sys.modules", {"gitlab_ops": mock_gitlab_ops, "gitlab": mock_gitlab_mod}):
                        result = site_config.check_connectivity()
        assert result.gitlab_dns is True
        assert result.gitlab_https is True
        assert result.gitlab_auth is True
        assert result.gitlab_project is False
        assert "project" in result.error_details

    def test_all_pass_writes_state(self, connectivity_dir):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        mock_gitlab_ops = MagicMock()
        mock_gitlab_ops.discover_token = MagicMock(return_value="good-token")

        mock_gl_instance = MagicMock()
        mock_gl_instance.auth.return_value = None
        mock_gl_instance.projects.get.return_value = MagicMock()

        mock_gitlab_mod = MagicMock()
        mock_gitlab_mod.Gitlab.return_value = mock_gl_instance

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com", "GITLAB_PROJECT": "test/project"}):
            with patch("socket.getaddrinfo", return_value=[(None, None, None, None, ("1.2.3.4", 443))]):
                with patch("urllib.request.urlopen", return_value=mock_resp):
                    with patch.dict("sys.modules", {"gitlab_ops": mock_gitlab_ops, "gitlab": mock_gitlab_mod}):
                        result = site_config.check_connectivity()

        assert result.gitlab_dns is True
        assert result.gitlab_https is True
        assert result.gitlab_auth is True
        assert result.gitlab_project is True
        assert result.error_details == {}

        state_file = connectivity_dir / ".connectivity.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["gitlab_host"] == "gitlab.corp.com"
        assert state["project"] == "test/project"
        assert "checked_at" in state

    def test_host_not_set(self, connectivity_dir):
        clean = {k: v for k, v in os.environ.items() if k != "GITLAB_HOST"}
        with patch.dict(os.environ, clean, clear=True):
            result = site_config.check_connectivity()
        assert result.gitlab_dns is False
        assert "dns" in result.error_details


class TestConnectivityConfirmed:
    def test_fresh_state_returns_true(self, connectivity_dir):
        state = {
            "gitlab_host": "gitlab.corp.com",
            "project": "test/project",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "ttl_hours": 24,
        }
        state_file = connectivity_dir / ".connectivity.json"
        state_file.write_text(json.dumps(state))

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com"}):
            assert site_config.connectivity_confirmed() is True

    def test_stale_state_returns_false(self, connectivity_dir):
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        state = {
            "gitlab_host": "gitlab.corp.com",
            "project": "test/project",
            "checked_at": old_time.isoformat(),
            "ttl_hours": 24,
        }
        state_file = connectivity_dir / ".connectivity.json"
        state_file.write_text(json.dumps(state))

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com"}):
            assert site_config.connectivity_confirmed() is False

    def test_mismatched_host_returns_false(self, connectivity_dir):
        state = {
            "gitlab_host": "old-gitlab.corp.com",
            "project": "test/project",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "ttl_hours": 24,
        }
        state_file = connectivity_dir / ".connectivity.json"
        state_file.write_text(json.dumps(state))

        with patch.dict(os.environ, {"GITLAB_HOST": "new-gitlab.corp.com"}):
            assert site_config.connectivity_confirmed() is False

    def test_missing_file_returns_false(self, connectivity_dir):
        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com"}):
            assert site_config.connectivity_confirmed() is False

    def test_malformed_json_returns_false(self, connectivity_dir):
        state_file = connectivity_dir / ".connectivity.json"
        state_file.write_text("not valid json {{{")

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com"}):
            assert site_config.connectivity_confirmed() is False

    def test_missing_checked_at_returns_false(self, connectivity_dir):
        state = {"gitlab_host": "gitlab.corp.com", "project": "test/project"}
        state_file = connectivity_dir / ".connectivity.json"
        state_file.write_text(json.dumps(state))

        with patch.dict(os.environ, {"GITLAB_HOST": "gitlab.corp.com"}):
            assert site_config.connectivity_confirmed() is False


class TestCheckConnectivityCLIExitCodes:
    """Verify the mapping from ConnectivityResult to CLI exit codes."""

    def test_exit_3_for_dns_failure(self):
        result = site_config.ConnectivityResult(gitlab_dns=False, error_details={"dns": "fail"})
        assert not result.gitlab_dns

    def test_exit_4_for_https_failure(self):
        result = site_config.ConnectivityResult(gitlab_dns=True, gitlab_https=False, error_details={"https": "fail"})
        assert result.gitlab_dns and not result.gitlab_https

    def test_exit_5_for_auth_failure(self):
        result = site_config.ConnectivityResult(
            gitlab_dns=True, gitlab_https=True, gitlab_auth=False, error_details={"auth": "fail"}
        )
        assert result.gitlab_dns and result.gitlab_https and result.gitlab_auth is False

    def test_exit_6_for_project_failure(self):
        result = site_config.ConnectivityResult(
            gitlab_dns=True, gitlab_https=True, gitlab_auth=True, gitlab_project=False,
            error_details={"project": "fail"},
        )
        assert result.gitlab_project is False
