"""Tests for conforma-exception verify_auth.py."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "conforma_exception_verify_auth",
    _REPO_ROOT / "skills/conforma-exception/scripts/verify_auth.py",
)
verify_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_auth)


class TestCheckAcliAvailable:
    def test_native_available(self):
        with patch.object(verify_auth, "_find_acli", return_value="/usr/bin/acli"), \
             patch.object(verify_auth, "resolve_method", return_value="native"):
            result = verify_auth.check_acli_available()

        assert result["passed"] is True
        assert result["check"] == "acli_available"
        assert "native" in result["detail"]

    def test_container_available(self):
        with patch.object(verify_auth, "_find_acli", return_value=None), \
             patch.object(verify_auth, "_install_acli_local", side_effect=RuntimeError("offline")), \
             patch.object(verify_auth, "resolve_method", return_value="docker"):
            result = verify_auth.check_acli_available()

        assert result["passed"] is True
        assert "docker" in result["detail"]

    def test_unavailable(self):
        with patch.object(verify_auth, "_find_acli", return_value=None), \
             patch.object(verify_auth, "_install_acli_local", side_effect=RuntimeError("offline")), \
             patch.object(verify_auth, "resolve_method", return_value="unavailable"):
            result = verify_auth.check_acli_available()

        assert result["passed"] is False
        assert "fix" in result


class TestCheckAcliAuth:
    def test_authenticated(self):
        mock_result = MagicMock(returncode=0, stdout="logged in", stderr="")
        with patch.object(verify_auth, "run_acli", return_value=mock_result):
            result = verify_auth.check_acli_auth()

        assert result["passed"] is True
        assert result["detail"] == "authenticated"

    def test_not_authenticated(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="not logged in")
        with patch.object(verify_auth, "run_acli", return_value=mock_result), \
             patch.object(verify_auth, "_acli_auth_fix", return_value="run acli login"):
            result = verify_auth.check_acli_auth()

        assert result["passed"] is False
        assert "not logged in" in result["detail"]
        assert result["fix"] == "run acli login"

    def test_timeout(self):
        with patch.object(verify_auth, "run_acli", side_effect=subprocess.TimeoutExpired("acli", 15)), \
             patch.object(verify_auth, "_acli_auth_fix", return_value="fix it"):
            result = verify_auth.check_acli_auth()

        assert result["passed"] is False
        assert "timed out" in result["detail"]

    def test_file_not_found(self):
        with patch.object(verify_auth, "run_acli", side_effect=FileNotFoundError("no acli")):
            result = verify_auth.check_acli_auth()

        assert result["passed"] is False
        assert "no acli" in result["detail"]


class TestCheckGlabAvailable:
    def test_native_available(self):
        with patch.object(verify_auth, "resolve_method", return_value="native"):
            result = verify_auth.check_glab_available()

        assert result["passed"] is True
        assert "native" in result["detail"]

    def test_container_available(self):
        with patch.object(verify_auth, "resolve_method", return_value="podman"):
            result = verify_auth.check_glab_available()

        assert result["passed"] is True
        assert "podman" in result["detail"]

    def test_unavailable(self):
        with patch.object(verify_auth, "resolve_method", return_value="unavailable"):
            result = verify_auth.check_glab_available()

        assert result["passed"] is False
        assert "fix" in result


class TestCheckGlabAuth:
    def test_authenticated(self):
        mock_result = MagicMock(returncode=0, stdout="logged in", stderr="")
        with patch.object(verify_auth, "run_glab", return_value=mock_result):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is True
        assert verify_auth.GITLAB_HOST in result["detail"]

    def test_not_logged_in(self):
        mock_result = MagicMock(returncode=1, stdout="not logged in", stderr="")
        with patch.object(verify_auth, "run_glab", return_value=mock_result), \
             patch.object(verify_auth, "_glab_auth_fix", return_value="glab login"):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is False
        assert "Not authenticated" in result["detail"]

    def test_timeout(self):
        with patch.object(verify_auth, "run_glab", side_effect=subprocess.TimeoutExpired("glab", 15)), \
             patch.object(verify_auth, "_glab_auth_fix", return_value="fix it"):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is False
        assert "timed out" in result["detail"]

    def test_file_not_found(self):
        with patch.object(verify_auth, "run_glab", side_effect=FileNotFoundError("no glab")):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is False
        assert "no glab" in result["detail"]


class TestRunChecks:
    def test_all_pass(self):
        with patch.object(verify_auth, "check_acli_available", return_value={"check": "acli_available", "passed": True}), \
             patch.object(verify_auth, "check_acli_auth", return_value={"check": "acli_auth", "passed": True}), \
             patch.object(verify_auth, "_setup_jira_rest_api"), \
             patch.object(verify_auth, "check_glab_available", return_value={"check": "glab_available", "passed": True}), \
             patch.object(verify_auth, "check_glab_auth", return_value={"check": "glab_auth", "passed": True}), \
             patch.object(verify_auth, "check_glab_push_access", return_value={"check": "glab_push_access", "passed": True}), \
             patch.object(verify_auth, "_check_jira_library_auth", return_value={"check": "jira_library_auth", "passed": True}), \
             patch.object(verify_auth, "_check_gitlab_library_auth", return_value={"check": "gitlab_library_auth", "passed": True}):
            result = verify_auth.run_checks()

        assert result["passed"] is True
        assert len(result["checks"]) == 7

    def test_stops_acli_auth_when_unavailable(self):
        with patch.object(verify_auth, "check_acli_available", return_value={"check": "acli_available", "passed": False}), \
             patch.object(verify_auth, "check_glab_available", return_value={"check": "glab_available", "passed": True}), \
             patch.object(verify_auth, "check_glab_auth", return_value={"check": "glab_auth", "passed": True}), \
             patch.object(verify_auth, "check_glab_push_access", return_value={"check": "glab_push_access", "passed": True}), \
             patch.object(verify_auth, "_check_jira_library_auth", return_value={"check": "jira_library_auth", "passed": True}), \
             patch.object(verify_auth, "_check_gitlab_library_auth", return_value={"check": "gitlab_library_auth", "passed": True}):
            result = verify_auth.run_checks()

        assert result["passed"] is False
        check_names = [c["check"] for c in result["checks"]]
        assert "acli_auth" not in check_names
        assert "glab_available" in check_names

    def test_stops_glab_auth_when_unavailable(self):
        with patch.object(verify_auth, "check_acli_available", return_value={"check": "acli_available", "passed": True}), \
             patch.object(verify_auth, "check_acli_auth", return_value={"check": "acli_auth", "passed": True}), \
             patch.object(verify_auth, "_setup_jira_rest_api"), \
             patch.object(verify_auth, "check_glab_available", return_value={"check": "glab_available", "passed": False}), \
             patch.object(verify_auth, "_check_jira_library_auth", return_value={"check": "jira_library_auth", "passed": True}), \
             patch.object(verify_auth, "_check_gitlab_library_auth", return_value={"check": "gitlab_library_auth", "passed": True}):
            result = verify_auth.run_checks()

        assert result["passed"] is False
        check_names = [c["check"] for c in result["checks"]]
        assert "glab_auth" not in check_names

    def test_skips_push_access_when_glab_auth_fails(self):
        with patch.object(verify_auth, "check_acli_available", return_value={"check": "acli_available", "passed": True}), \
             patch.object(verify_auth, "check_acli_auth", return_value={"check": "acli_auth", "passed": True}), \
             patch.object(verify_auth, "_setup_jira_rest_api"), \
             patch.object(verify_auth, "check_glab_available", return_value={"check": "glab_available", "passed": True}), \
             patch.object(verify_auth, "check_glab_auth", return_value={"check": "glab_auth", "passed": False}), \
             patch.object(verify_auth, "_check_jira_library_auth", return_value={"check": "jira_library_auth", "passed": True}), \
             patch.object(verify_auth, "_check_gitlab_library_auth", return_value={"check": "gitlab_library_auth", "passed": True}):
            result = verify_auth.run_checks()

        assert result["passed"] is False
        check_names = [c["check"] for c in result["checks"]]
        assert "glab_push_access" not in check_names
