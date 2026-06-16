"""Tests for scripts/tenant_discovery.py — tenant-based auto-discovery."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import tenant_discovery


@pytest.fixture
def mock_project():
    """Create a mock GitLab project with configurable repository_tree responses."""
    project = MagicMock()
    project.commits.list.return_value = [MagicMock(id="abc123def456")]
    return project


def _tree_entry(name: str, entry_type: str = "tree") -> dict:
    return {"name": name, "type": entry_type, "path": name}


def _setup_single_cluster_tenant(mock_project, tenant="rhoai-tenant", cluster_id="stone-prod-p02",
                                  domain="stone-prod-p02.hjvn.p1"):
    """Set up mock responses for a single cluster with one tenant."""

    def tree_side_effect(path="", per_page=100, page=1, ref="main"):
        if path == "tenants-config/cluster" and page == 1:
            return [_tree_entry(cluster_id)]
        if path == f"tenants-config/cluster/{cluster_id}/tenants" and page == 1:
            return [_tree_entry(tenant)]
        if path == "config" and page == 1:
            return [_tree_entry(domain)]
        if path == f"config/{domain}/product/EnterpriseContractPolicy" and page == 1:
            return [
                _tree_entry("registry-rhoai-prod.yaml", "blob"),
                _tree_entry("fbc-rhoai-prod.yaml", "blob"),
            ]
        if path == f"config/{domain}/product/ReleasePlanAdmission" and page == 1:
            return [_tree_entry("rhoai")]
        if path == "exceptions" and page == 1:
            return [
                _tree_entry("registry-rhoai-prod.yaml", "blob"),
                _tree_entry("fbc-rhoai-prod.yaml", "blob"),
            ]
        return []

    mock_project.repository_tree.side_effect = tree_side_effect


def _setup_multi_cluster_tenant(mock_project, tenant="rhoai-tenant"):
    """Set up mock responses for tenant on multiple clusters."""

    def tree_side_effect(path="", per_page=100, page=1, ref="main"):
        if path == "tenants-config/cluster" and page == 1:
            return [_tree_entry("stone-prod-p02"), _tree_entry("stone-stg-p01")]
        if path == "tenants-config/cluster/stone-prod-p02/tenants" and page == 1:
            return [_tree_entry(tenant)]
        if path == "tenants-config/cluster/stone-stg-p01/tenants" and page == 1:
            return [_tree_entry(tenant)]
        if path == "config" and page == 1:
            return [_tree_entry("stone-prod-p02.hjvn.p1"), _tree_entry("stone-stg-p01.abc.p1")]
        if "EnterpriseContractPolicy" in path and page == 1:
            return [_tree_entry("registry-rhoai-prod.yaml", "blob")]
        if "ReleasePlanAdmission" in path and page == 1:
            return [_tree_entry("rhoai")]
        if path == "exceptions" and page == 1:
            return [_tree_entry("registry-rhoai-prod.yaml", "blob")]
        return []

    mock_project.repository_tree.side_effect = tree_side_effect


@pytest.fixture
def connectivity_confirmed_true(monkeypatch):
    monkeypatch.setattr(tenant_discovery, "_import_site_config_connectivity", lambda: True)


def _import_site_config_connectivity():
    """Helper that tests can override."""
    import site_config
    return site_config.connectivity_confirmed()


# Patch the discover function to use our helper
@pytest.fixture(autouse=True)
def _patch_connectivity_check(monkeypatch):
    """By default, patch connectivity as confirmed for all tests."""
    monkeypatch.setattr(
        "site_config.connectivity_confirmed",
        lambda: True,
    )


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tenant_discovery, "DISCOVERY_CACHE_DIR", tmp_path)
    return tmp_path


class TestDiscoverSingleCluster:
    def test_basic_discovery(self, mock_project, cache_dir):
        _setup_single_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("rhoai-tenant")

        assert ctx.tenant == "rhoai-tenant"
        assert ctx.cluster.cluster_id == "stone-prod-p02"
        assert ctx.cluster.cluster_domain == "stone-prod-p02.hjvn.p1"
        assert ctx.ec_policy_dir == "config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy"
        assert "registry-rhoai-prod.yaml" in ctx.ec_policy_files
        assert "fbc-rhoai-prod.yaml" in ctx.ec_policy_files
        assert "rhoai" in ctx.rpa_subdirs
        assert ctx.self_service_dir == "exceptions"
        assert "registry-rhoai-prod.yaml" in ctx.self_service_files
        assert ctx.source_commit == "abc123def456"

    def test_writes_cache(self, mock_project, cache_dir):
        _setup_single_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            tenant_discovery.discover("rhoai-tenant")

        cache_file = cache_dir / "rhoai-tenant.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["tenant"] == "rhoai-tenant"
        assert data["cluster"]["cluster_id"] == "stone-prod-p02"


class TestDiscoverMultipleClusters:
    def test_preferred_cluster_selects_correctly(self, mock_project, cache_dir):
        _setup_multi_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("rhoai-tenant", preferred_cluster="stone-stg-p01")

        assert ctx.cluster.cluster_id == "stone-stg-p01"
        assert ctx.cluster.cluster_domain == "stone-stg-p01.abc.p1"
        assert len(ctx.all_clusters) == 2

    def test_no_preferred_cluster_errors(self, mock_project, cache_dir):
        _setup_multi_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            with pytest.raises(tenant_discovery.DiscoveryError) as exc_info:
                tenant_discovery.discover("rhoai-tenant")
        assert exc_info.value.exit_code == 10
        assert "multiple clusters" in str(exc_info.value).lower()

    def test_wrong_preferred_cluster_errors(self, mock_project, cache_dir):
        _setup_multi_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            with pytest.raises(tenant_discovery.DiscoveryError) as exc_info:
                tenant_discovery.discover("rhoai-tenant", preferred_cluster="nonexistent-cluster")
        assert exc_info.value.exit_code == 10
        assert "nonexistent-cluster" in str(exc_info.value)


class TestDiscoverTenantNotFound:
    def test_exit_8_when_not_found(self, mock_project, cache_dir):
        def tree_side_effect(path="", per_page=100, page=1, ref="main"):
            if path == "tenants-config/cluster" and page == 1:
                return [_tree_entry("stone-prod-p02")]
            if path == "tenants-config/cluster/stone-prod-p02/tenants" and page == 1:
                return [_tree_entry("other-tenant")]
            return []

        mock_project.repository_tree.side_effect = tree_side_effect
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            with pytest.raises(tenant_discovery.DiscoveryError) as exc_info:
                tenant_discovery.discover("rhoai-tenant")
        assert exc_info.value.exit_code == 8


class TestDiscoverGitLabError:
    def test_exit_9_on_api_error(self, cache_dir):
        with patch.object(
            tenant_discovery, "_get_gitlab_project", side_effect=tenant_discovery.DiscoveryError("API fail", 9)
        ):
            with pytest.raises(tenant_discovery.DiscoveryError) as exc_info:
                tenant_discovery.discover("rhoai-tenant")
        assert exc_info.value.exit_code == 9


class TestDiscoverConnectivityNotConfirmed:
    def test_exit_7_when_not_confirmed(self, cache_dir, monkeypatch):
        monkeypatch.setattr("site_config.connectivity_confirmed", lambda: False)
        with pytest.raises(tenant_discovery.DiscoveryError) as exc_info:
            tenant_discovery.discover("rhoai-tenant")
        assert exc_info.value.exit_code == 7


class TestPagination:
    def test_handles_more_than_100_items(self, mock_project, cache_dir):
        page1_clusters = [_tree_entry(f"cluster-{i:03d}") for i in range(100)]
        page2_clusters = [_tree_entry("target-cluster")]

        call_count = {"tenants": 0}

        def tree_side_effect(path="", per_page=100, page=1, ref="main"):
            if path == "tenants-config/cluster":
                if page == 1:
                    return page1_clusters
                if page == 2:
                    return page2_clusters
                return []
            if "tenants-config/cluster/" in path and "/tenants" in path:
                call_count["tenants"] += 1
                cluster_id = path.split("/")[2]
                if cluster_id == "target-cluster":
                    return [_tree_entry("rhoai-tenant")]
                return [_tree_entry("other-tenant")]
            if path == "config" and page == 1:
                return [_tree_entry("target-cluster.abc.p1")]
            if "EnterpriseContractPolicy" in path:
                return [_tree_entry("registry-rhoai-prod.yaml", "blob")]
            if "ReleasePlanAdmission" in path:
                return [_tree_entry("rhoai")]
            if path == "exceptions":
                return []
            return []

        mock_project.repository_tree.side_effect = tree_side_effect
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("rhoai-tenant")

        assert ctx.cluster.cluster_id == "target-cluster"
        assert call_count["tenants"] == 101


class TestClusterDomainMatching:
    def test_multi_dot_domain(self, mock_project, cache_dir):
        """cluster_domain.split('.')[0] correctly extracts cluster_id from multi-dot domains."""

        def tree_side_effect(path="", per_page=100, page=1, ref="main"):
            if path == "tenants-config/cluster" and page == 1:
                return [_tree_entry("stone-prod-p02")]
            if path == "tenants-config/cluster/stone-prod-p02/tenants" and page == 1:
                return [_tree_entry("rhoai-tenant")]
            if path == "config" and page == 1:
                return [_tree_entry("stone-prod-p02.hjvn.p1.extra.segment")]
            if "EnterpriseContractPolicy" in path:
                return [_tree_entry("test.yaml", "blob")]
            if "ReleasePlanAdmission" in path:
                return []
            if path == "exceptions":
                return []
            return []

        mock_project.repository_tree.side_effect = tree_side_effect
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("rhoai-tenant")

        assert ctx.cluster.cluster_domain == "stone-prod-p02.hjvn.p1.extra.segment"
        assert ctx.cluster.cluster_id == "stone-prod-p02"

    def test_single_segment_domain_no_match(self, mock_project, cache_dir):
        """If config/ has a directory that is just the cluster_id (no dots), it still matches."""

        def tree_side_effect(path="", per_page=100, page=1, ref="main"):
            if path == "tenants-config/cluster" and page == 1:
                return [_tree_entry("simple")]
            if path == "tenants-config/cluster/simple/tenants" and page == 1:
                return [_tree_entry("rhoai-tenant")]
            if path == "config" and page == 1:
                return [_tree_entry("simple")]
            if "EnterpriseContractPolicy" in path:
                return [_tree_entry("policy.yaml", "blob")]
            if "ReleasePlanAdmission" in path:
                return []
            if path == "exceptions":
                return []
            return []

        mock_project.repository_tree.side_effect = tree_side_effect
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("rhoai-tenant")

        assert ctx.cluster.cluster_id == "simple"
        assert ctx.cluster.cluster_domain == "simple"


class TestRawFileStorage:
    def test_filenames_stored_without_transformation(self, mock_project, cache_dir):
        """Verifies that Tree API filenames are stored exactly as returned."""

        def tree_side_effect(path="", per_page=100, page=1, ref="main"):
            if path == "tenants-config/cluster" and page == 1:
                return [_tree_entry("cluster-01")]
            if path == "tenants-config/cluster/cluster-01/tenants" and page == 1:
                return [_tree_entry("my-tenant")]
            if path == "config" and page == 1:
                return [_tree_entry("cluster-01.domain.p1")]
            if "EnterpriseContractPolicy" in path and page == 1:
                return [
                    _tree_entry("weird-name_v2.yaml", "blob"),
                    _tree_entry("another-file.yaml", "blob"),
                    _tree_entry("not-yaml.txt", "blob"),
                ]
            if "ReleasePlanAdmission" in path and page == 1:
                return [_tree_entry("product-a"), _tree_entry("product-b")]
            if path == "exceptions" and page == 1:
                return [_tree_entry("some-exception.yaml", "blob")]
            return []

        mock_project.repository_tree.side_effect = tree_side_effect
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("my-tenant")

        assert ctx.ec_policy_files == ["another-file.yaml", "weird-name_v2.yaml"]
        assert "not-yaml.txt" not in ctx.ec_policy_files
        assert ctx.rpa_subdirs == ["product-a", "product-b"]
        assert ctx.self_service_files == ["some-exception.yaml"]


class TestCache:
    def test_uses_cache_when_fresh(self, mock_project, cache_dir):
        _setup_single_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx1 = tenant_discovery.discover("rhoai-tenant")

        mock_project.repository_tree.reset_mock()
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx2 = tenant_discovery.discover("rhoai-tenant")

        mock_project.repository_tree.assert_not_called()
        assert ctx2.cluster.cluster_id == ctx1.cluster.cluster_id

    def test_refresh_ignores_cache(self, mock_project, cache_dir):
        _setup_single_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            tenant_discovery.discover("rhoai-tenant")

        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            _setup_single_cluster_tenant(mock_project)
            tenant_discovery.discover("rhoai-tenant", refresh=True)

        assert mock_project.repository_tree.called

    def test_expired_cache_triggers_fresh_discovery(self, mock_project, cache_dir):
        _setup_single_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            tenant_discovery.discover("rhoai-tenant")

        cache_file = cache_dir / "rhoai-tenant.json"
        data = json.loads(cache_file.read_text())
        old_time = (datetime.now(timezone.utc) - timedelta(hours=73)).isoformat()
        data["discovered_at"] = old_time
        cache_file.write_text(json.dumps(data))

        mock_project.repository_tree.reset_mock()
        _setup_single_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            tenant_discovery.discover("rhoai-tenant")

        assert mock_project.repository_tree.called

    def test_preferred_cluster_change_invalidates_cache(self, mock_project, cache_dir):
        _setup_multi_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            tenant_discovery.discover("rhoai-tenant", preferred_cluster="stone-prod-p02")

        mock_project.repository_tree.reset_mock()
        _setup_multi_cluster_tenant(mock_project)
        with patch.object(tenant_discovery, "_get_gitlab_project", return_value=mock_project):
            ctx = tenant_discovery.discover("rhoai-tenant", preferred_cluster="stone-stg-p01")

        assert mock_project.repository_tree.called
        assert ctx.cluster.cluster_id == "stone-stg-p01"
