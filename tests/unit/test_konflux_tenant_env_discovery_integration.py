"""Integration tests: konflux_tenant_env_discovery with konflux_environment.load()."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import konflux_environment
import konflux_tenant_env_discovery


@pytest.fixture(autouse=True)
def _reset_loaded():
    konflux_environment._loaded = False
    yield
    konflux_environment._loaded = False


@pytest.fixture
def connectivity_dir(tmp_path, monkeypatch):
    """Set up fresh connectivity state file."""
    monkeypatch.setattr(konflux_environment, "CONNECTIVITY_STATE_DIR", tmp_path)
    monkeypatch.setattr(konflux_environment, "CONNECTIVITY_STATE_FILE", tmp_path / ".connectivity.json")
    return tmp_path


@pytest.fixture
def discovery_cache_dir(tmp_path, monkeypatch):
    cache_dir = tmp_path / "discovery-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(konflux_tenant_env_discovery, "DISCOVERY_CACHE_DIR", cache_dir)
    return cache_dir


def _write_connectivity_state(conn_dir, host="gitlab.corp.com"):
    state = {
        "gitlab_host": host,
        "project": "releng/konflux-release-data",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "ttl_hours": 24,
    }
    state_file = conn_dir / ".connectivity.json"
    state_file.write_text(json.dumps(state))


_DISCOVERY_VARS = (
    "KONFLUX_CLUSTER_DOMAIN", "KONFLUX_CLUSTER_ID", "KONFLUX_CONFORMA_POLICY_DIR",
    "KONFLUX_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_API_DOMAIN",
    "GITLAB_HOST", "GITLAB_PROJECT", "KONFLUX_TENANT", "PREFERRED_KONFLUX_CLUSTER",
)


def _clean_env():
    return {k: v for k, v in os.environ.items() if k not in _DISCOVERY_VARS}


def _mock_discover(tenant, preferred_cluster=None, refresh=False):
    return konflux_tenant_env_discovery.TenantContext(
        tenant=tenant,
        cluster=konflux_tenant_env_discovery.DiscoveredCluster(cluster_id="stone-prod-p02", cluster_domain="stone-prod-p02.hjvn.p1"),
        all_clusters=[
            konflux_tenant_env_discovery.DiscoveredCluster(cluster_id="stone-prod-p02", cluster_domain="stone-prod-p02.hjvn.p1")
        ],
        conforma_policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
        conforma_policy_files=["registry-rhoai-prod.yaml"],
        rpa_dir="config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission",
        rpa_subdirs=["rhoai"],
        self_service_dir="exceptions",
        self_service_files=["registry-rhoai-prod.yaml"],
        discovered_at=datetime.now(timezone.utc).isoformat(),
        source_commit="abc123",
        preferred_cluster=preferred_cluster,
    )


class TestPopulateFromDiscovery:
    def test_sets_cluster_domain(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover):
                populated = konflux_environment.load()

        assert populated["KONFLUX_CLUSTER_DOMAIN"] == "stone-prod-p02.hjvn.p1"

    def test_sets_conforma_policy_dir(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover):
                populated = konflux_environment.load()

        assert populated.get("KONFLUX_CONFORMA_POLICY_DIR") == "config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy"

    def test_sets_rpa_subpath(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover):
                populated = konflux_environment.load()

        assert populated.get("KONFLUX_RPA_SUBPATH") == "config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission"

    def test_does_not_overwrite_existing_vars(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"
        env["KONFLUX_CLUSTER_DOMAIN"] = "existing-domain.abc.p1"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover) as mock_disc:
                konflux_environment.load()
            mock_disc.assert_not_called()
            assert os.environ["KONFLUX_CLUSTER_DOMAIN"] == "existing-domain.abc.p1"

    def test_triggers_derive_from_cluster_domain(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover):
                populated = konflux_environment.load()

        assert populated.get("KONFLUX_CLUSTER_ID") == "stone-prod-p02"
        assert "KONFLUX_INTERNAL_API" in populated
        assert "TEKTON_RESULTS_API_DOMAIN" in populated


class TestLoadTriggersDiscovery:
    @pytest.fixture(autouse=True)
    def _no_dotenv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(konflux_environment, "DOTENV_PATH", tmp_path / "nonexistent.env")

    def test_calls_discover_when_tenant_set_and_no_cluster_domain(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover) as mock_disc:
                konflux_environment.load()

        mock_disc.assert_called_once_with("rhoai-tenant", preferred_cluster=None)

    def test_does_not_call_discover_when_cluster_domain_set(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"
        env["KONFLUX_CLUSTER_DOMAIN"] = "already-set.abc.p1"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover) as mock_disc:
                konflux_environment.load()

        mock_disc.assert_not_called()

    def test_does_not_call_discover_when_connectivity_not_confirmed(
        self, tmp_path, connectivity_dir, discovery_cache_dir, capsys
    ):
        env = _clean_env()
        env["KONFLUX_TENANT"] = "rhoai-tenant"
        env["GITLAB_HOST"] = "gitlab.corp.com"

        with patch.dict(os.environ, env, clear=True):
            with patch("konflux_tenant_env_discovery.discover", side_effect=_mock_discover) as mock_disc:
                konflux_environment.load()

        mock_disc.assert_not_called()
        captured = capsys.readouterr()
        assert "connectivity not confirmed" in captured.err.lower()
