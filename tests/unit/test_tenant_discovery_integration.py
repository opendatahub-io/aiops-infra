"""Integration tests: tenant_discovery with site_config.load()."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

import site_config
import tenant_discovery


@pytest.fixture(autouse=True)
def _reset_loaded():
    site_config._loaded = False
    yield
    site_config._loaded = False


@pytest.fixture
def connectivity_dir(tmp_path, monkeypatch):
    """Set up fresh connectivity state file."""
    monkeypatch.setattr(site_config, "CONNECTIVITY_STATE_DIR", tmp_path)
    monkeypatch.setattr(site_config, "CONNECTIVITY_STATE_FILE", tmp_path / ".connectivity.json")
    return tmp_path


@pytest.fixture
def discovery_cache_dir(tmp_path, monkeypatch):
    cache_dir = tmp_path / "discovery-cache"
    cache_dir.mkdir()
    monkeypatch.setattr(tenant_discovery, "DISCOVERY_CACHE_DIR", cache_dir)
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


def _make_config(tmp_path, tenant=None, preferred_cluster=None, cluster_domain=None, host="gitlab.corp.com"):
    config = {"gitlab": {"host": host, "project": "releng/konflux-release-data"}}
    if cluster_domain:
        config["konflux"] = {"cluster_domain": cluster_domain}
    if tenant:
        config["tenant"] = tenant
    if preferred_cluster:
        config["preferred_cluster"] = preferred_cluster
    path = tmp_path / "site-config.yaml"
    path.write_text(yaml.dump(config))
    return path


def _mock_discover(tenant, preferred_cluster=None, refresh=False):
    return tenant_discovery.TenantContext(
        tenant=tenant,
        cluster=tenant_discovery.DiscoveredCluster(cluster_id="stone-prod-p02", cluster_domain="stone-prod-p02.hjvn.p1"),
        all_clusters=[
            tenant_discovery.DiscoveredCluster(cluster_id="stone-prod-p02", cluster_domain="stone-prod-p02.hjvn.p1")
        ],
        ec_policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
        ec_policy_files=["registry-rhoai-prod.yaml"],
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
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID", "KRD_EC_POLICY_DIR",
                                  "KRD_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover):
                populated = site_config.load(config_path=config_path)

        assert populated["KRD_CLUSTER_DOMAIN"] == "stone-prod-p02.hjvn.p1"

    def test_sets_ec_policy_dir(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID", "KRD_EC_POLICY_DIR",
                                  "KRD_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover):
                populated = site_config.load(config_path=config_path)

        assert populated.get("KRD_EC_POLICY_DIR") == "config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy"

    def test_sets_rpa_subpath(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID", "KRD_EC_POLICY_DIR",
                                  "KRD_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover):
                populated = site_config.load(config_path=config_path)

        assert populated.get("KRD_RPA_SUBPATH") == "config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission"

    def test_does_not_overwrite_existing_vars(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}
        env_clean["KRD_CLUSTER_DOMAIN"] = "existing-domain.abc.p1"

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover) as mock_disc:
                populated = site_config.load(config_path=config_path)
            mock_disc.assert_not_called()
            assert os.environ["KRD_CLUSTER_DOMAIN"] == "existing-domain.abc.p1"

    def test_triggers_derive_from_cluster_domain(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID", "KRD_EC_POLICY_DIR",
                                  "KRD_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover):
                populated = site_config.load(config_path=config_path)

        assert populated.get("KRD_CLUSTER_ID") == "stone-prod-p02"
        assert "KONFLUX_INTERNAL_API" in populated
        assert "TEKTON_RESULTS_DOMAIN" in populated


class TestLoadTriggersDiscovery:
    def test_calls_discover_when_tenant_set_and_no_cluster_domain(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID", "KRD_EC_POLICY_DIR",
                                  "KRD_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover) as mock_disc:
                site_config.load(config_path=config_path)

        mock_disc.assert_called_once_with("rhoai-tenant", preferred_cluster=None)

    def test_does_not_call_discover_when_cluster_domain_set(self, tmp_path, connectivity_dir, discovery_cache_dir):
        _write_connectivity_state(connectivity_dir)
        config_path = _make_config(tmp_path, tenant="rhoai-tenant", cluster_domain="already-set.abc.p1")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID",
                                  "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover) as mock_disc:
                site_config.load(config_path=config_path)

        mock_disc.assert_not_called()

    def test_does_not_call_discover_when_connectivity_not_confirmed(
        self, tmp_path, connectivity_dir, discovery_cache_dir, capsys
    ):
        config_path = _make_config(tmp_path, tenant="rhoai-tenant")
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("KRD_CLUSTER_DOMAIN", "KRD_CLUSTER_ID", "KRD_EC_POLICY_DIR",
                                  "KRD_RPA_SUBPATH", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_DOMAIN",
                                  "GITLAB_HOST", "GITLAB_PROJECT", "TENANT", "PREFERRED_CLUSTER")}

        with patch.dict(os.environ, env_clean, clear=True):
            with patch("tenant_discovery.discover", side_effect=_mock_discover) as mock_disc:
                site_config.load(config_path=config_path)

        mock_disc.assert_not_called()
        captured = capsys.readouterr()
        assert "connectivity not confirmed" in captured.err.lower()
