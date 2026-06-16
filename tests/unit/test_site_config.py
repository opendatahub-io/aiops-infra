"""Tests for scripts/site_config.py — site configuration loader."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import yaml

import site_config


@pytest.fixture(autouse=True)
def _reset_loaded():
    """Reset the module-level _loaded flag between tests."""
    site_config._loaded = False
    yield
    site_config._loaded = False


@pytest.fixture
def config_file(tmp_path):
    """Create a temporary site config YAML file."""
    config = {
        "gitlab": {"host": "gitlab.test.example.com", "project": "test/project"},
        "konflux": {
            "external_api": "https://api.ext.example.com:6443",
            "internal_api": "https://api.int.example.com:6443",
            "namespace": "test-tenant",
            "cluster_domain": "test-cluster.example.p1",
            "cluster_id": "test-cluster",
        },
        "tekton": {"results_domain": "tekton.test.example.com"},
    }
    path = tmp_path / "site-config.yaml"
    path.write_text(yaml.dump(config))
    return path


class TestResolveYamlPath:
    def test_simple_path(self):
        data = {"gitlab": {"host": "example.com"}}
        assert site_config._resolve_yaml_path(data, "gitlab.host") == "example.com"

    def test_nested_path(self):
        data = {"konflux": {"cluster_domain": "test.p1"}}
        assert site_config._resolve_yaml_path(data, "konflux.cluster_domain") == "test.p1"

    def test_missing_key(self):
        assert site_config._resolve_yaml_path({}, "gitlab.host") is None

    def test_empty_value(self):
        data = {"gitlab": {"host": ""}}
        assert site_config._resolve_yaml_path(data, "gitlab.host") is None


class TestFindConfig:
    def test_finds_explicit_path(self, config_file):
        with patch.dict(os.environ, {"AIOPS_SITE_CONFIG": str(config_file)}):
            site_config.CONFIG_SEARCH_PATHS[0] = config_file
            try:
                found = site_config.find_config()
                assert found == config_file
            finally:
                site_config.CONFIG_SEARCH_PATHS[0] = None

    def test_returns_none_when_no_config(self, tmp_path, monkeypatch):
        orig = site_config.CONFIG_SEARCH_PATHS[:]
        site_config.CONFIG_SEARCH_PATHS[:] = [tmp_path / "nonexistent.yaml"]
        monkeypatch.setattr(site_config, "REMOTE_CACHE_FILE", tmp_path / "no-cache.yaml")
        monkeypatch.setattr(site_config, "_fetch_remote_config", lambda: None)
        try:
            assert site_config.find_config() is None
        finally:
            site_config.CONFIG_SEARCH_PATHS[:] = orig


class TestLoad:
    def test_populates_env_vars(self, config_file):
        env_vars = [
            "GITLAB_HOST",
            "GITLAB_PROJECT",
            "KONFLUX_EXTERNAL_API",
            "KONFLUX_INTERNAL_API",
            "KONFLUX_NAMESPACE",
            "KRD_CLUSTER_DOMAIN",
            "KRD_CLUSTER_ID",
            "TEKTON_RESULTS_DOMAIN",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars}
        with patch.dict(os.environ, clean_env, clear=True):
            populated = site_config.load(config_path=config_file)

        assert "GITLAB_HOST" in populated
        assert populated["GITLAB_HOST"] == "gitlab.test.example.com"
        assert populated["KRD_CLUSTER_DOMAIN"] == "test-cluster.example.p1"

    def test_env_vars_take_precedence(self, config_file):
        with patch.dict(os.environ, {"GITLAB_HOST": "already-set.example.com"}):
            populated = site_config.load(config_path=config_file)
            assert "GITLAB_HOST" not in populated
            assert os.environ["GITLAB_HOST"] == "already-set.example.com"

    def test_handles_missing_config(self, tmp_path):
        populated = site_config.load(config_path=tmp_path / "nonexistent.yaml")
        assert populated == {}

    def test_handles_malformed_yaml(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(": : : not valid yaml [[[")
        populated = site_config.load(config_path=bad_file)
        assert populated == {}


class TestValidate:
    def test_passes_when_required_vars_set(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "real-gitlab.corp.com", "KRD_CLUSTER_DOMAIN": "stone-prod.abc.p1"}):
            result = site_config.validate()
        assert result.ok
        assert result.missing == []
        assert result.placeholders == []

    def test_fails_when_required_vars_missing(self):
        clean = {k: v for k, v in os.environ.items() if k not in ("GITLAB_HOST", "KRD_CLUSTER_DOMAIN")}
        with patch.dict(os.environ, clean, clear=True):
            result = site_config.validate()
        assert not result.ok
        assert "GITLAB_HOST" in result.missing

    def test_detects_placeholder_values(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "test.example.com", "KRD_CLUSTER_DOMAIN": "my.cluster.p1"}):
            result = site_config.validate()
        assert not result.ok
        assert len(result.placeholders) == 2
        placeholder_vars = [p[0] for p in result.placeholders]
        assert "GITLAB_HOST" in placeholder_vars
        assert "KRD_CLUSTER_DOMAIN" in placeholder_vars


class TestDeriveFromClusterDomain:
    @pytest.fixture
    def minimal_config(self, tmp_path):
        """Config with only domain set — no internal_api, so derivation kicks in."""
        config = {
            "gitlab": {"host": "gitlab.test.example.com"},
            "konflux": {"cluster_domain": "test-cluster.example.p1", "namespace": "test-ns"},
        }
        path = tmp_path / "minimal-config.yaml"
        path.write_text(yaml.dump(config))
        return path

    def test_derives_tekton_domain(self, minimal_config):
        env_vars = [
            "GITLAB_HOST",
            "KRD_CLUSTER_DOMAIN",
            "KRD_CLUSTER_ID",
            "KONFLUX_INTERNAL_API",
            "TEKTON_RESULTS_DOMAIN",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars}
        with patch.dict(os.environ, clean_env, clear=True):
            populated = site_config.load(config_path=minimal_config)
            assert populated["TEKTON_RESULTS_DOMAIN"] == (
                "tekton-results-tekton-results.apps.test-cluster.example.p1.openshiftapps.com"
            )

    def test_derives_cluster_id(self, minimal_config):
        env_vars = [
            "GITLAB_HOST",
            "KRD_CLUSTER_DOMAIN",
            "KRD_CLUSTER_ID",
            "KONFLUX_INTERNAL_API",
            "TEKTON_RESULTS_DOMAIN",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars}
        with patch.dict(os.environ, clean_env, clear=True):
            populated = site_config.load(config_path=minimal_config)
            assert populated["KRD_CLUSTER_ID"] == "test-cluster"

    def test_derives_internal_api(self, minimal_config):
        env_vars = [
            "GITLAB_HOST",
            "KRD_CLUSTER_DOMAIN",
            "KRD_CLUSTER_ID",
            "KONFLUX_INTERNAL_API",
            "TEKTON_RESULTS_DOMAIN",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars}
        with patch.dict(os.environ, clean_env, clear=True):
            populated = site_config.load(config_path=minimal_config)
            assert populated["KONFLUX_INTERNAL_API"] == ("https://api.test-cluster.example.p1.openshiftapps.com:6443")

    def test_explicit_overrides_derived(self, minimal_config):
        env_vars = [
            "GITLAB_HOST",
            "KRD_CLUSTER_DOMAIN",
            "KRD_CLUSTER_ID",
            "KONFLUX_INTERNAL_API",
        ]
        clean_env = {k: v for k, v in os.environ.items() if k not in env_vars}
        clean_env["TEKTON_RESULTS_DOMAIN"] = "custom-tekton.example.com"
        with patch.dict(os.environ, clean_env, clear=True):
            populated = site_config.load(config_path=minimal_config)
            assert "TEKTON_RESULTS_DOMAIN" not in populated
            assert os.environ["TEKTON_RESULTS_DOMAIN"] == "custom-tekton.example.com"


class TestGetStatus:
    def test_returns_structured_status(self, config_file):
        with patch.dict(os.environ, {"GITLAB_HOST": "test.example.com"}):
            status = site_config.get_status()
        assert "entries" in status
        assert any(e["env_var"] == "GITLAB_HOST" for e in status["entries"])


class TestIsCacheFresh:
    def test_fresh_cache(self, tmp_path):
        cache = tmp_path / "test.yaml"
        cache.write_text("test: true")
        assert site_config._is_cache_fresh(cache) is True

    def test_missing_cache(self, tmp_path):
        assert site_config._is_cache_fresh(tmp_path / "missing.yaml") is False

    def test_stale_cache(self, tmp_path):
        cache = tmp_path / "test.yaml"
        cache.write_text("test: true")
        import time as _time

        stale_mtime = _time.time() - (site_config.CACHE_TTL_HOURS + 1) * 3600
        os.utime(cache, (stale_mtime, stale_mtime))
        assert site_config._is_cache_fresh(cache) is False


class TestFetchRemoteConfig:
    def test_success(self, monkeypatch):
        import base64

        content = "gitlab:\n  host: remote.example.com\n"
        encoded = base64.b64encode(content.encode()).decode()
        mock_result = MagicMock(returncode=0, stdout=encoded + "\n", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            result = site_config._fetch_remote_config()
        assert result is not None
        assert "remote.example.com" in result

    def test_failure(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="error")
        with patch("subprocess.run", return_value=mock_result):
            result = site_config._fetch_remote_config()
        assert result is None

    def test_timeout(self):
        import subprocess as sp

        with patch("subprocess.run", side_effect=sp.TimeoutExpired("gh", 30)):
            result = site_config._fetch_remote_config()
        assert result is None

    def test_custom_url(self, monkeypatch):
        monkeypatch.setenv("CONFORMA_SKILL_SITE_CONFIG_URL", "repos/custom/repo/contents/config.yaml")
        mock_result = MagicMock(returncode=1, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            site_config._fetch_remote_config()
        call_args = mock_run.call_args[0][0]
        assert "repos/custom/repo/contents/config.yaml" in call_args


class TestFindConfigWithRemoteCache:
    def test_local_takes_precedence(self, config_file, tmp_path):
        cache = tmp_path / ".remote-cache" / "site-config.yaml"
        cache.parent.mkdir(parents=True)
        cache.write_text("gitlab:\n  host: remote-cached.example.com\n")
        with patch.object(site_config, "CONFIG_SEARCH_PATHS", [config_file]):
            found = site_config.find_config()
        assert found == config_file

    def test_uses_fresh_cache(self, tmp_path):
        cache_dir = tmp_path / ".remote-cache"
        cache_dir.mkdir()
        cache = cache_dir / "site-config.yaml"
        cache.write_text("gitlab:\n  host: cached.example.com\n")
        with (
            patch.object(site_config, "CONFIG_SEARCH_PATHS", [tmp_path / "no-local.yaml"]),
            patch.object(site_config, "REMOTE_CACHE_FILE", cache),
        ):
            found = site_config.find_config()
        assert found == cache


class TestWriteLocal:
    def test_creates_new_file(self, tmp_path, monkeypatch):
        with patch.object(site_config, "write_local") as _:
            pass
        result = site_config.write_local(["gitlab.host=test.example.com", "konflux.cluster_domain=my.cluster.p1"])
        written = result["written"]
        assert written["gitlab.host"] == "test.example.com"
        assert written["konflux.cluster_domain"] == "my.cluster.p1"

    def test_ignores_invalid_pairs(self):
        result = site_config.write_local(["not-a-pair", "valid.key=value"])
        assert len(result["written"]) == 1


class TestSetYamlPath:
    def test_creates_nested_structure(self):
        data: dict = {}
        site_config._set_yaml_path(data, "gitlab.host", "test.com")
        assert data["gitlab"]["host"] == "test.com"

    def test_overwrites_existing(self):
        data = {"gitlab": {"host": "old.com"}}
        site_config._set_yaml_path(data, "gitlab.host", "new.com")
        assert data["gitlab"]["host"] == "new.com"
