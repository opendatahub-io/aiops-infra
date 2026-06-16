"""Tests for site_config.py placeholder detection, ValidationResult, and require() guard."""

from __future__ import annotations

import os
import re
from unittest.mock import patch

import pytest

import site_config


@pytest.fixture(autouse=True)
def _reset_loaded():
    site_config._loaded = False
    yield
    site_config._loaded = False


class TestPlaceholderPatterns:
    """Each placeholder pattern must match known fakes and not match real values."""

    @pytest.mark.parametrize(
        "value",
        [
            "test.example.com",
            "example.com",
            "gitlab.example.com",
            "host.example.org",
            "something.example.net",
            "localhost",
            "localhost:8080",
            "my.cluster.p1",
            "my.host.internal",
            "changeme",
            "changeme-later",
            "TODO",
            "TODO-fill-this",
            "REPLACE_ME",
            "REPLACE.ME.NOW",
        ],
    )
    def test_placeholder_detected(self, value):
        matched = any(re.search(p, value) for p in site_config._PLACEHOLDER_PATTERNS)
        assert matched, f"Expected '{value}' to be detected as placeholder"

    @pytest.mark.parametrize(
        "value",
        [
            "gitlab.corp.redhat.com",
            "gitlab.cee.redhat.com",
            "stone-prod-p02.hjvn.p1",
            "my-cluster.abc.p1",  # has hyphen, not "my." prefix
            "real-gitlab.internal.company.io",
            "10.0.0.1",
            "tekton-results.apps.cluster.domain.com",
        ],
    )
    def test_real_values_not_flagged(self, value):
        matched = any(re.search(p, value) for p in site_config._PLACEHOLDER_PATTERNS)
        assert not matched, f"Expected '{value}' to NOT be flagged as placeholder"


class TestValidationResult:
    def test_all_good(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "real.corp.com", "KRD_CLUSTER_DOMAIN": "stone.abc.p1"}):
            result = site_config.validate()
        assert result.ok is True
        assert result.missing == []
        assert result.placeholders == []

    def test_missing_vars(self):
        clean = {k: v for k, v in os.environ.items() if k not in ("GITLAB_HOST", "KRD_CLUSTER_DOMAIN")}
        with patch.dict(os.environ, clean, clear=True):
            result = site_config.validate()
        assert result.ok is False
        assert "GITLAB_HOST" in result.missing
        assert "KRD_CLUSTER_DOMAIN" in result.missing
        assert result.placeholders == []

    def test_placeholder_vars(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "test.example.com", "KRD_CLUSTER_DOMAIN": "my.cluster.p1"}):
            result = site_config.validate()
        assert result.ok is False
        assert result.missing == []
        assert len(result.placeholders) == 2

    def test_mixed_missing_and_placeholder(self):
        clean = {k: v for k, v in os.environ.items() if k != "KRD_CLUSTER_DOMAIN"}
        clean["GITLAB_HOST"] = "test.example.com"
        with patch.dict(os.environ, clean, clear=True):
            result = site_config.validate()
        assert result.ok is False
        assert "KRD_CLUSTER_DOMAIN" in result.missing
        placeholder_vars = [p[0] for p in result.placeholders]
        assert "GITLAB_HOST" in placeholder_vars

    def test_placeholder_tuple_contains_pattern(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "test.example.com", "KRD_CLUSTER_DOMAIN": "real.abc.p1"}):
            result = site_config.validate()
        assert len(result.placeholders) == 1
        var_name, value, pattern = result.placeholders[0]
        assert var_name == "GITLAB_HOST"
        assert value == "test.example.com"
        assert re.search(pattern, value)


class TestRequire:
    def test_passes_with_valid_config(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "real.corp.com", "KRD_CLUSTER_DOMAIN": "stone.abc.p1"}):
            site_config.require("gitlab")

    def test_exits_when_gitlab_host_missing(self):
        clean = {k: v for k, v in os.environ.items() if k != "GITLAB_HOST"}
        with patch.dict(os.environ, clean, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                site_config.require("gitlab")
            assert exc_info.value.code == 1

    def test_exits_when_gitlab_host_is_placeholder(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "test.example.com", "KRD_CLUSTER_DOMAIN": "real.abc.p1"}):
            with pytest.raises(SystemExit) as exc_info:
                site_config.require("gitlab")
            assert exc_info.value.code == 1

    def test_exits_for_unknown_service(self):
        with pytest.raises(SystemExit) as exc_info:
            site_config.require("unknown_service")
        assert exc_info.value.code == 1

    def test_does_not_exit_when_non_gitlab_var_is_placeholder(self):
        """require('gitlab') only checks GITLAB_HOST, not KRD_CLUSTER_DOMAIN."""
        with patch.dict(os.environ, {"GITLAB_HOST": "real.corp.com", "KRD_CLUSTER_DOMAIN": "my.cluster.p1"}):
            site_config.require("gitlab")


class TestValidateCLIExitCodes:
    def test_exit_0_when_valid(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "real.corp.com", "KRD_CLUSTER_DOMAIN": "stone.abc.p1"}):
            result = site_config.validate()
        assert result.ok
        # CLI would return 0

    def test_exit_1_when_missing(self):
        clean = {k: v for k, v in os.environ.items() if k not in ("GITLAB_HOST", "KRD_CLUSTER_DOMAIN")}
        with patch.dict(os.environ, clean, clear=True):
            result = site_config.validate()
        assert not result.ok
        assert result.missing
        assert not result.placeholders
        # CLI would return 1

    def test_exit_2_when_placeholder(self):
        with patch.dict(os.environ, {"GITLAB_HOST": "example.com", "KRD_CLUSTER_DOMAIN": "real.abc.p1"}):
            result = site_config.validate()
        assert not result.ok
        assert result.placeholders
        # CLI would return 2
