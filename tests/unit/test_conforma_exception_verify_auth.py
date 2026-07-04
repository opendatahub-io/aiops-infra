"""Tests for conforma-exception verify_auth.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "conforma_exception_verify_auth",
    _REPO_ROOT / "skills/conforma-exception/scripts/verify_auth.py",
)
verify_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_auth)


class TestCheckAcliAvailable:
    def test_always_passes(self):
        result = verify_auth.check_acli_available()
        assert result["passed"] is True
        assert result["check"] == "acli_available"
        assert "jira_ops" in result["detail"]


class TestCheckAcliAuth:
    def test_authenticated(self):
        with patch.object(verify_auth.jira_ops, "verify_auth", return_value={"ok": True, "user": "testuser"}):
            result = verify_auth.check_acli_auth()

        assert result["passed"] is True
        assert "testuser" in result["detail"]

    def test_not_authenticated(self):
        with patch.object(verify_auth.jira_ops, "verify_auth", return_value={"ok": False, "error": "401 Unauthorized"}):
            result = verify_auth.check_acli_auth()

        assert result["passed"] is False
        assert "401" in result["detail"]
        assert "fix" in result


class TestCheckGlabAvailable:
    def test_always_passes(self):
        result = verify_auth.check_glab_available()
        assert result["passed"] is True
        assert "gitlab_ops" in result["detail"]


class TestCheckGlabAuth:
    def test_authenticated(self):
        mock_gl = MagicMock()
        with (
            patch.object(verify_auth.gitlab_ops, "discover_token", return_value="glpat-fake"),
            patch.object(verify_auth.gitlab_ops, "get_client", return_value=mock_gl),
        ):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is True
        mock_gl.auth.assert_called_once()

    def test_no_token(self):
        with patch.object(verify_auth.gitlab_ops, "discover_token", return_value=None):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is False
        assert "No GitLab token" in result["detail"]

    def test_auth_failure(self):
        mock_gl = MagicMock()
        mock_gl.auth.side_effect = Exception("SSL error")
        with (
            patch.object(verify_auth.gitlab_ops, "discover_token", return_value="glpat-fake"),
            patch.object(verify_auth.gitlab_ops, "get_client", return_value=mock_gl),
        ):
            result = verify_auth.check_glab_auth()

        assert result["passed"] is False
        assert "SSL error" in result["detail"]


class TestCheckGlabPushAccess:
    def test_developer_access(self):
        mock_project = MagicMock()
        mock_project.attributes = {"permissions": {"project_access": {"access_level": 30}, "group_access": None}}
        mock_gl = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        with patch.object(verify_auth.gitlab_ops, "get_client", return_value=mock_gl):
            result = verify_auth.check_glab_push_access()

        assert result["passed"] is True
        assert "30" in result["detail"]

    def test_low_access_warns(self):
        mock_project = MagicMock()
        mock_project.attributes = {"permissions": {"project_access": {"access_level": 20}, "group_access": None}}
        mock_gl = MagicMock()
        mock_gl.projects.get.return_value = mock_project
        with patch.object(verify_auth.gitlab_ops, "get_client", return_value=mock_gl):
            result = verify_auth.check_glab_push_access()

        assert result["passed"] is True
        assert "fork-based" in result["detail"]

    def test_project_not_found(self):
        mock_gl = MagicMock()
        mock_gl.projects.get.side_effect = Exception("404 Project Not Found")
        with patch.object(verify_auth.gitlab_ops, "get_client", return_value=mock_gl):
            result = verify_auth.check_glab_push_access()

        assert result["passed"] is False
        assert "404" in result["detail"]


class TestRunChecks:
    def test_all_pass(self):
        with (
            patch.object(verify_auth, "check_acli_available", return_value={"check": "acli_available", "passed": True}),
            patch.object(verify_auth, "check_acli_auth", return_value={"check": "acli_auth", "passed": True}),
            patch.object(verify_auth, "_setup_jira_rest_api"),
            patch.object(verify_auth, "check_glab_available", return_value={"check": "glab_available", "passed": True}),
            patch.object(verify_auth, "check_glab_auth", return_value={"check": "glab_auth", "passed": True}),
            patch.object(
                verify_auth, "check_glab_push_access", return_value={"check": "glab_push_access", "passed": True}
            ),
            patch.object(
                verify_auth, "_check_jira_library_auth", return_value={"check": "jira_library_auth", "passed": True}
            ),
            patch.object(
                verify_auth, "_check_gitlab_library_auth", return_value={"check": "gitlab_library_auth", "passed": True}
            ),
        ):
            result = verify_auth.run_checks()

        assert result["passed"] is True

    def test_glab_auth_failure_propagates(self):
        with (
            patch.object(verify_auth, "check_acli_available", return_value={"check": "acli_available", "passed": True}),
            patch.object(verify_auth, "check_acli_auth", return_value={"check": "acli_auth", "passed": True}),
            patch.object(verify_auth, "_setup_jira_rest_api"),
            patch.object(verify_auth, "check_glab_available", return_value={"check": "glab_available", "passed": True}),
            patch.object(verify_auth, "check_glab_auth", return_value={"check": "glab_auth", "passed": False}),
            patch.object(
                verify_auth, "_check_jira_library_auth", return_value={"check": "jira_library_auth", "passed": True}
            ),
            patch.object(
                verify_auth, "_check_gitlab_library_auth", return_value={"check": "gitlab_library_auth", "passed": True}
            ),
        ):
            result = verify_auth.run_checks()

        assert result["passed"] is False


class TestContextIntegration:
    """Tests for ~/.conforma/.env path references in fix messages."""

    def test_jira_fix_message_references_conforma_env(self):
        """Jira auth fix message points to ~/.conforma/.env."""
        with patch.object(verify_auth.jira_ops, "verify_auth", return_value={"ok": False, "error": "401"}):
            result = verify_auth.check_acli_auth()

        assert "~/.conforma/.env" in result["fix"]
        assert ".work/.env" not in result["fix"]

    def test_gitlab_fix_message_references_conforma_env(self):
        """GitLab auth fix message points to ~/.conforma/.env."""
        with patch.object(verify_auth.gitlab_ops, "discover_token", return_value=None):
            result = verify_auth.check_glab_auth()

        assert "~/.conforma/.env" in result["fix"]
        assert ".work/.env" not in result["fix"]
