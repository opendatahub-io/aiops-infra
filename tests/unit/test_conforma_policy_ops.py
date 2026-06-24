"""Tests for conforma_policy_ops.py."""

from __future__ import annotations

from unittest.mock import patch

import conforma_policy_ops as mod


class TestResolveRepoDir:
    def test_returns_none_when_policy_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        assert mod._resolve_repo_dir(tmp_path) is None

    def test_returns_candidate_when_policy_dir_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        policy_dir = tmp_path / "config" / "stone-prod-p02.hjvn.p1" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        assert mod._resolve_repo_dir(tmp_path) == tmp_path

    def test_returns_repo_subdir_when_nested(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        policy_dir = tmp_path / "repo" / "config" / "stone-prod-p02.hjvn.p1" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        assert mod._resolve_repo_dir(tmp_path) == tmp_path / "repo"

    def test_returns_none_when_no_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_DIR", raising=False)
        assert mod._resolve_repo_dir(tmp_path) is None


class TestRefreshClone:
    @patch("conforma_policy_ops._refresh_workdir_clone")
    def test_calls_refresh_when_repo_dir_found(self, mock_refresh, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        policy_dir = tmp_path / "config" / "stone-prod-p02.hjvn.p1" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        result = mod.refresh_clone(tmp_path)
        assert result == tmp_path
        mock_refresh.assert_called_once_with(tmp_path)

    @patch("conforma_policy_ops._refresh_workdir_clone")
    def test_returns_none_when_no_policy_dir(self, mock_refresh, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        result = mod.refresh_clone(tmp_path)
        assert result is None
        mock_refresh.assert_not_called()


class TestCheckPermanentExclusions:
    def test_finds_permanent_exclusion(self):
        content = (
            "exclude:\n"
            "  - some.other.rule\n"
            "  - hermetic_task.hermetic\n"
            "  - another.rule\n"
            "volatileCriteria:\n"
            "  - value: test\n"
        )
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 1
        assert results[0]["type"] == "permanent_global_exclusion"
        assert results[0]["line"] == 3

    def test_no_match_when_rule_not_in_exclude(self):
        content = "exclude:\n  - some.other.rule\n"
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 0

    def test_ignores_comments(self):
        content = "exclude:\n  # - hermetic_task.hermetic\n  - other.rule\n"
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 0

    def test_exits_section_on_non_list_item(self):
        content = "exclude:\n  - some.rule\nvolatileCriteria:\n  - hermetic_task.hermetic\n"
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 0


class TestSearchExistingExceptions:
    def test_returns_not_checked_when_no_dir(self, tmp_path):
        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path / "nonexistent")
        )
        assert result["checked"] is False

    def test_returns_not_checked_when_no_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_DIR", raising=False)
        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is False
        assert "KONFLUX_CLUSTER_DOMAIN" in result["reason"]

    def test_finds_permanent_exclusion_in_policy_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy_file = policy_dir / "registry-rhoai-prod.yaml"
        policy_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["permanent_count"] == 1

    def test_finds_volatile_exceptions_in_policy_file(self, tmp_path, monkeypatch):
        """Volatile (volatileCriteria) exceptions must be found, not just permanent ones.

        Regression guard: the import of _find_existing_exceptions from
        create_gitlab_mr must succeed, otherwise volatile exceptions are
        silently invisible and coverage reports are wrong.
        """
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy_file = policy_dir / "registry-rhoai-prod.yaml"
        policy_file.write_text(
            "volatileCriteria:\n"
            "          - value: rpm_signature.allowed:abc123\n"
            "            componentNames:\n"
            "              - odh-foo-v3-5-ea-1\n"
            '            effectiveUntil: "2099-01-01T00:00:00Z"\n'
            "            reference: https://issues.redhat.com/browse/TEST-1\n"
        )

        result = mod.search_existing_exceptions(
            "rpm_signature.allowed:abc123", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["count"] >= 1, (
            "Volatile exceptions not found — _find_existing_exceptions import "
            "from create_gitlab_mr is likely broken"
        )
        exc = result["existing_exceptions"][0]
        assert exc["componentNames"] == ["odh-foo-v3-5-ea-1"]
        assert "2099" in exc["effectiveUntil"]
        assert "block_start_line" in exc
        assert isinstance(exc["block_start_line"], int)
        assert exc["block_start_line"] >= 1

    def test_excludes_files_not_in_policy_files(self, tmp_path, monkeypatch):
        """Files not listed in policy_files must be skipped entirely.

        Regression guard for cross-product contamination: an unscoped exception
        in a desktop-extensions policy file must NOT appear in RHOAI results.
        """
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        rhoai_file = policy_dir / "registry-rhoai-prod.yaml"
        rhoai_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        other_file = policy_dir / "registry-red-hat-desktop-extensions-prod.yaml"
        other_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["permanent_count"] == 1
        assert result["permanent_exclusions"][0]["file"].endswith("registry-rhoai-prod.yaml")

    def test_no_results_when_policy_files_exclude_all(self, tmp_path, monkeypatch):
        """When policy_files doesn't match any existing file, nothing is found."""
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        other_file = policy_dir / "registry-red-hat-desktop-extensions-prod.yaml"
        other_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["permanent_count"] == 0
        assert result["count"] == 0
