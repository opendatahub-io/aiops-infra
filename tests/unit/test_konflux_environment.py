"""Tests for scripts/konflux_environment.py — environment loader."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

import konflux_environment


@pytest.fixture(autouse=True)
def _reset_loaded():
    """Reset the module-level _loaded flag between tests."""
    konflux_environment._loaded = False
    yield
    konflux_environment._loaded = False


class TestLoad:
    def test_idempotent(self):
        """Second call returns empty dict."""
        with patch.object(konflux_environment, "_load_dotenv"):
            with patch.object(konflux_environment, "_resolve_jira_email"):
                with patch.object(konflux_environment, "_derive_from_cluster_domain"):
                    konflux_environment.load()
                    result = konflux_environment.load()
        assert result == {}

    def test_calls_load_dotenv(self):
        with patch.object(konflux_environment, "_load_dotenv") as mock_dotenv:
            with patch.object(konflux_environment, "_resolve_jira_email"):
                with patch.object(konflux_environment, "_derive_from_cluster_domain"):
                    konflux_environment.load()
        mock_dotenv.assert_called_once()

    def test_calls_derive_from_cluster_domain(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster.abc.p1")
        with patch.object(konflux_environment, "_load_dotenv"):
            with patch.object(konflux_environment, "_resolve_jira_email"):
                with patch.object(konflux_environment, "_derive_from_cluster_domain") as mock_derive:
                    konflux_environment.load()
        mock_derive.assert_called_once()


class TestValidate:
    def test_passes_when_required_vars_set(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "real-gitlab.corp.com", "KONFLUX_CLUSTER_DOMAIN": "stone-prod.abc.p1"}):
            result = konflux_environment.validate()
        assert result.ok
        assert result.missing == []
        assert result.placeholders == []

    def test_fails_when_required_vars_missing(self):
        clean = {k: v for k, v in os.environ.items() if k not in ("GITLAB_HOST", "KONFLUX_CLUSTER_DOMAIN")}
        with patch.dict(os.environ, clean, clear=True):
            result = konflux_environment.validate()
        assert not result.ok
        assert "GITLAB_HOST" in result.missing

    def test_detects_placeholder_values(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "test.example.com", "KONFLUX_CLUSTER_DOMAIN": "my.cluster.p1"}):
            result = konflux_environment.validate()
        assert not result.ok
        assert len(result.placeholders) == 2
        placeholder_vars = [p[0] for p in result.placeholders]
        assert "GITLAB_HOST" in placeholder_vars
        assert "KONFLUX_CLUSTER_DOMAIN" in placeholder_vars


class TestDeriveFromClusterDomain:
    def test_derives_tekton_domain(self, monkeypatch):
        for var in ("KONFLUX_CLUSTER_ID", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_API_DOMAIN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster.example.p1")

        populated: dict[str, str] = {}
        konflux_environment._derive_from_cluster_domain(populated)
        assert populated["TEKTON_RESULTS_API_DOMAIN"] == (
            "tekton-results-tekton-results.apps.test-cluster.example.p1.openshiftapps.com"
        )

    def test_derives_cluster_id(self, monkeypatch):
        for var in ("KONFLUX_CLUSTER_ID", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_API_DOMAIN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster.example.p1")

        populated: dict[str, str] = {}
        konflux_environment._derive_from_cluster_domain(populated)
        assert populated["KONFLUX_CLUSTER_ID"] == "test-cluster"

    def test_derives_internal_api(self, monkeypatch):
        for var in ("KONFLUX_CLUSTER_ID", "KONFLUX_INTERNAL_API", "TEKTON_RESULTS_API_DOMAIN"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster.example.p1")

        populated: dict[str, str] = {}
        konflux_environment._derive_from_cluster_domain(populated)
        assert populated["KONFLUX_INTERNAL_API"] == "https://api.test-cluster.example.p1.openshiftapps.com:6443"

    def test_explicit_overrides_derived(self, monkeypatch):
        for var in ("KONFLUX_CLUSTER_ID", "KONFLUX_INTERNAL_API"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster.example.p1")
        monkeypatch.setenv("TEKTON_RESULTS_API_DOMAIN", "custom-tekton.example.com")

        populated: dict[str, str] = {}
        konflux_environment._derive_from_cluster_domain(populated)
        assert "TEKTON_RESULTS_API_DOMAIN" not in populated
        assert os.environ["TEKTON_RESULTS_API_DOMAIN"] == "custom-tekton.example.com"
