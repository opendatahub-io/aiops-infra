"""Tests for conforma-analyze verify_auth.py."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Disambiguate: both conforma-analyze and conforma-exception have verify_auth.py.
# Import the conforma-analyze one explicitly by file path.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_VERIFY_AUTH_PATH = _REPO_ROOT / "skills" / "conforma-analyze" / "scripts" / "verify_auth.py"
_spec = importlib.util.spec_from_file_location("conforma_analyze_verify_auth", _VERIFY_AUTH_PATH)
verify_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_auth)


class TestCheckGhAvailable:
    def test_gh_found(self):
        mock_result = MagicMock(returncode=0, stdout="gh version 2.50.0\n")
        with patch.object(verify_auth.subprocess, "run", return_value=mock_result):
            result = verify_auth.check_gh_available()
        assert result["passed"] is True
        assert "2.50.0" in result["detail"]

    def test_gh_not_found(self):
        with patch.object(verify_auth.subprocess, "run", side_effect=FileNotFoundError):
            result = verify_auth.check_gh_available()
        assert result["passed"] is False
        assert "fix" in result

    def test_gh_returns_error(self):
        mock_result = MagicMock(returncode=1, stderr="something went wrong")
        with patch.object(verify_auth.subprocess, "run", return_value=mock_result):
            result = verify_auth.check_gh_available()
        assert result["passed"] is False


class TestCheckGhAuth:
    def test_authenticated(self):
        mock_result = MagicMock(returncode=0)
        with patch.object(verify_auth.subprocess, "run", return_value=mock_result):
            result = verify_auth.check_gh_auth()
        assert result["passed"] is True

    def test_not_authenticated(self):
        mock_result = MagicMock(returncode=1, stderr="not logged in", stdout="")
        with patch.object(verify_auth.subprocess, "run", return_value=mock_result):
            result = verify_auth.check_gh_auth()
        assert result["passed"] is False
        assert "fix" in result

    def test_timeout(self):
        with patch.object(verify_auth.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 15)):
            result = verify_auth.check_gh_auth()
        assert result["passed"] is False
        assert "timed out" in result["detail"]


class TestCheckRepoAccess:
    def test_access_granted(self):
        mock_result = MagicMock(
            returncode=0,
            stdout="red-hat-data-services/conforma-reporter\n",
        )
        with patch.object(verify_auth.subprocess, "run", return_value=mock_result):
            result = verify_auth.check_repo_access()
        assert result["passed"] is True

    def test_access_denied(self):
        mock_result = MagicMock(returncode=1, stderr="Not Found", stdout="")
        with patch.object(verify_auth.subprocess, "run", return_value=mock_result):
            result = verify_auth.check_repo_access()
        assert result["passed"] is False

    def test_timeout(self):
        with patch.object(verify_auth.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 15)):
            result = verify_auth.check_repo_access()
        assert result["passed"] is False


class TestRunChecks:
    def test_all_pass(self):
        with patch.object(verify_auth, "check_gh_available", return_value={"check": "gh_available", "passed": True, "detail": "ok"}), \
             patch.object(verify_auth, "check_gh_auth", return_value={"check": "gh_auth", "passed": True, "detail": "ok"}), \
             patch.object(verify_auth, "check_repo_access", return_value={"check": "repo_access", "passed": True, "detail": "ok"}):
            result = verify_auth.run_checks()
        assert result["passed"] is True
        assert len(result["checks"]) == 3

    def test_stops_on_gh_not_available(self):
        with patch.object(verify_auth, "check_gh_available", return_value={"check": "gh_available", "passed": False, "detail": "not found"}):
            result = verify_auth.run_checks()
        assert result["passed"] is False
        assert len(result["checks"]) == 1

    def test_stops_on_auth_failure(self):
        with patch.object(verify_auth, "check_gh_available", return_value={"check": "gh_available", "passed": True, "detail": "ok"}), \
             patch.object(verify_auth, "check_gh_auth", return_value={"check": "gh_auth", "passed": False, "detail": "not logged in"}):
            result = verify_auth.run_checks()
        assert result["passed"] is False
        assert len(result["checks"]) == 2
