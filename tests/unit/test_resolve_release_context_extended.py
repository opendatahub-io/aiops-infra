"""Extended tests for resolve_release_context.py — covers list_version_dirs,
list_all, and main() branches missed by the base test file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import conforma_context_ops
import gitlab_ops
import konflux_environment
import resolve_release_context as mod


class TestListVersionDirs:
    """Tests for list_version_dirs — GitLab tree pagination."""

    def _make_client(self, pages):
        client = MagicMock()
        project = MagicMock()
        client.projects.get.return_value = project
        project.repository_tree.side_effect = pages
        return client

    def test_single_page(self):
        items = [
            {"name": "v3.4", "type": "tree"},
            {"name": "v3.5", "type": "tree"},
            {"name": "other", "type": "tree"},
            {"name": "v3.6", "type": "blob"},
        ]
        client = self._make_client([items])
        with patch.object(mod.gitlab_ops, "get_client", return_value=client):
            result = mod.list_version_dirs("cluster1", "test-tenant")
        assert result == ["v3.4", "v3.5"]

    def test_multiple_pages(self):
        page1 = [{"name": f"v{i}", "type": "tree"} for i in range(100)]
        page2 = [{"name": "v3.5", "type": "tree"}, {"name": "v3.6", "type": "tree"}]
        client = self._make_client([page1, page2])
        with patch.object(mod.gitlab_ops, "get_client", return_value=client):
            result = mod.list_version_dirs("cluster1", "test-tenant")
        assert len(result) == 102
        assert "v3.5" in result

    def test_empty_result(self):
        client = self._make_client([[]])
        with patch.object(mod.gitlab_ops, "get_client", return_value=client):
            result = mod.list_version_dirs("cluster1", "test-tenant")
        assert result == []

    def test_uses_gitlab_project_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_PROJECT", "custom/project")
        client = self._make_client([[]])
        with patch.object(mod.gitlab_ops, "get_client", return_value=client):
            mod.list_version_dirs("c1", "t1")
        client.projects.get.assert_called_once_with("custom/project")


class TestListAll:
    """Tests for list_all — listing all available versions."""

    def test_missing_cluster_domain(self, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_TENANT", "test-tenant")
        with patch.object(mod.konflux_environment, "load"):
            result = mod.list_all()
        assert result["status"] == "error"
        assert "KONFLUX_CLUSTER_DOMAIN" in result["confirmation_display"]

    def test_missing_tenant(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.example.com")
        monkeypatch.delenv("KONFLUX_TENANT", raising=False)
        monkeypatch.delenv("KONFLUX_NAMESPACE", raising=False)
        with patch.object(mod.konflux_environment, "load"):
            result = mod.list_all()
        assert result["status"] == "error"
        assert "KONFLUX_TENANT" in result["confirmation_display"]

    def test_gitlab_query_error(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.example.com")
        monkeypatch.setenv("KONFLUX_TENANT", "test-tenant")
        with patch.object(mod.konflux_environment, "load"), \
             patch.object(mod, "list_version_dirs", side_effect=Exception("connection refused")):
            result = mod.list_all()
        assert result["status"] == "error"
        assert "GitLab tree query failed" in result["confirmation_display"]

    def test_success_returns_versions(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.example.com")
        monkeypatch.setenv("KONFLUX_TENANT", "test-tenant")
        versions = ["v3.4", "v3.5", "v3.5-ea.1"]
        with patch.object(mod.konflux_environment, "load"), \
             patch.object(mod, "list_version_dirs", return_value=versions):
            result = mod.list_all()
        assert result["status"] == "list"
        assert result["available_versions"] == versions
        assert len(result["versions"]) == 3
        assert result["versions"][0]["version_dir"] == "v3.4"
        assert result["versions"][0]["release"] == "rhoai-3.4"
        assert result["versions"][0]["konflux_app"] == "rhoai-v3-4"
        assert "| v3.4 | rhoai-3.4 | rhoai-v3-4 |" in result["confirmation_display"]

    def test_empty_versions_list(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test.example.com")
        monkeypatch.setenv("KONFLUX_TENANT", "test-tenant")
        with patch.object(mod.konflux_environment, "load"), \
             patch.object(mod, "list_version_dirs", return_value=[]):
            result = mod.list_all()
        assert result["status"] == "list"
        assert result["available_versions"] == []


class TestMainListFlag:
    """Tests for main() with --list flag."""

    def test_list_flag_calls_list_all(self, monkeypatch, capsys):
        mock_result = {"status": "list", "available_versions": ["v3.4"],
                       "versions": [{"version_dir": "v3.4", "release": "rhoai-3.4", "konflux_app": "rhoai-v3-4"}],
                       "confirmation_display": "| v3.4 | rhoai-3.4 | rhoai-v3-4 |"}
        monkeypatch.setattr(sys, "argv", ["resolve_release_context.py", "--list"])
        with patch.object(mod, "list_all", return_value=mock_result) as mock_la:
            rc = mod.main()
        assert rc == 0
        mock_la.assert_called_once()
        captured = capsys.readouterr()
        assert "v3.4" in captured.out

    def test_list_flag_error_returns_1(self, monkeypatch, capsys):
        mock_result = {"status": "error", "confirmation_display": "Missing env"}
        monkeypatch.setattr(sys, "argv", ["resolve_release_context.py", "--list"])
        with patch.object(mod, "list_all", return_value=mock_result):
            rc = mod.main()
        assert rc == 1


def _resolved(v="v3.4"):
    return {
        "status": "resolved",
        "version_dir": v,
        "release": "rhoai-" + v.lstrip("v"),
        "konflux_app": "rhoai-" + v.lstrip("v").replace(".", "-"),
        "cluster_domain": "test.example.com",
        "cluster_id": "test",
        "tenant": "test-tenant",
        "environment": "prod",
        "conforma_policy_dir": "",
        "policy_files": [],
        "self_service_files": [],
        "end_of_support": None,
        "upcoming_release_date": None,
        "code_freeze_date": None,
        "links": {},
        "confirmation_display": "",
    }


class TestMainMergeMode:
    """Tests for main() merge-mode (Step 0 context.yaml already exists)."""

    def test_merge_mode_enriches_existing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260101-000000"
        conforma_context_ops.create(run_dir, {"aiops_infra_root": "/repo"})
        conforma_context_ops.set_active(run_dir)

        monkeypatch.setattr(sys, "argv", ["resolve_release_context.py", "--query", "3.4"])
        with patch.object(mod, "resolve", return_value=_resolved()):
            rc = mod.main()
        assert rc == 0
        ctx_data = conforma_context_ops.load(run_dir)
        assert "aiops_infra_root" in ctx_data
        assert ctx_data["application"]["release"] == "rhoai-3.4"
        captured = capsys.readouterr()
        assert "Enriched existing run directory" in captured.err

    def test_merge_mode_not_triggered_with_application(self, tmp_path, monkeypatch, capsys):
        """Context has application key already → no merge, new run dir created."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260101-000000"
        conforma_context_ops.create(run_dir, {"application": {"release": "rhoai-3.4"}})
        conforma_context_ops.set_active(run_dir)

        monkeypatch.setattr(sys, "argv", ["resolve_release_context.py", "--query", "3.5"])
        with patch.object(mod, "resolve", return_value=_resolved("v3.5")):
            rc = mod.main()
        assert rc == 0
        captured = capsys.readouterr()
        assert "Enriched" not in captured.err

    def test_query_falls_back_to_context_user_query(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path))
        run_dir = tmp_path / "20260101-000000"
        conforma_context_ops.create(run_dir, {"user_query": "rhoai-3.4", "aiops_infra_root": "/repo"})
        conforma_context_ops.set_active(run_dir)

        monkeypatch.setattr(sys, "argv", ["resolve_release_context.py"])
        with patch.object(mod, "resolve", return_value=_resolved()) as mock_resolve:
            rc = mod.main()
        assert rc == 0
        assert mock_resolve.call_args[0][0] == "rhoai-3.4"

    def test_query_missing_no_context_errors(self, tmp_path, monkeypatch):
        """No --query and no context → parser.error (SystemExit)."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        monkeypatch.setattr(sys, "argv", ["resolve_release_context.py"])
        with pytest.raises(SystemExit):
            mod.main()

