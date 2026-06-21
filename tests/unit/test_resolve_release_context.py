"""Tests for scripts/resolve_release_context.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import resolve_release_context as mod


# ---------------------------------------------------------------------------
# parse_query tests (pure logic, no mocks)
# ---------------------------------------------------------------------------


class TestParseQuery:
    def test_simple_version(self):
        assert mod.parse_query("3.4") == "v3.4"

    def test_rhoai_prefix_with_dash(self):
        assert mod.parse_query("rhoai-3.4") == "v3.4"

    def test_rhoai_prefix_with_space(self):
        assert mod.parse_query("rhoai 3.4") == "v3.4"

    def test_ea_dot_format(self):
        assert mod.parse_query("3.5-ea.1") == "v3.5-ea.1"

    def test_ea_hyphen_format(self):
        assert mod.parse_query("3.5-ea-1") == "v3.5-ea.1"

    def test_ea_space_format(self):
        assert mod.parse_query("3.5 ea 1") == "v3.5-ea.1"

    def test_rhoai_ea_full(self):
        assert mod.parse_query("rhoai-3.5-ea.1") == "v3.5-ea.1"

    def test_rhoai_ea_space_separated(self):
        assert mod.parse_query("rhoai 3.5 ea 1") == "v3.5-ea.1"

    def test_v_prefix_stripped(self):
        assert mod.parse_query("v3.4") == "v3.4"

    def test_rhoai_v_prefix(self):
        assert mod.parse_query("rhoai-v3.4") == "v3.4"

    def test_empty_string(self):
        assert mod.parse_query("") is None

    def test_garbage_input(self):
        assert mod.parse_query("hello world") is None

    def test_single_number(self):
        assert mod.parse_query("3") is None

    def test_whitespace_handling(self):
        assert mod.parse_query("  3.4  ") == "v3.4"

    def test_uppercase(self):
        assert mod.parse_query("RHOAI-3.5-EA.1") == "v3.5-ea.1"

    def test_ea_dot_separated_all(self):
        assert mod.parse_query("3.5.ea.1") == "v3.5-ea.1"


# ---------------------------------------------------------------------------
# version derivation tests (pure logic)
# ---------------------------------------------------------------------------


class TestVersionDerivation:
    def test_version_to_release_ga(self):
        assert mod.version_to_release("v3.4") == "rhoai-3.4"

    def test_version_to_release_ea(self):
        assert mod.version_to_release("v3.5-ea.1") == "rhoai-3.5-ea.1"

    def test_version_to_konflux_app_ga(self):
        assert mod.version_to_konflux_app("v3.4") == "rhoai-v3-4"

    def test_version_to_konflux_app_ea(self):
        assert mod.version_to_konflux_app("v3.5-ea.1") == "rhoai-v3-5-ea-1"

    def test_version_to_konflux_app_double_digit(self):
        assert mod.version_to_konflux_app("v2.25") == "rhoai-v2-25"


# ---------------------------------------------------------------------------
# match_versions tests (pure logic)
# ---------------------------------------------------------------------------


class TestMatchVersions:
    AVAILABLE = ["v3.4", "v3.5", "v3.5-ea.1", "v3.5-ea.2"]

    def test_exact_match(self):
        assert mod.match_versions("v3.5-ea.1", self.AVAILABLE) == ["v3.5-ea.1"]

    def test_exact_match_ga(self):
        assert mod.match_versions("v3.4", self.AVAILABLE) == ["v3.4"]

    def test_exact_match_wins_over_prefix(self):
        # v3.5 exists exactly, so exact match returns only that
        result = mod.match_versions("v3.5", self.AVAILABLE)
        assert result == ["v3.5"]

    def test_prefix_match_when_no_exact(self):
        # v3.6 doesn't exist, but v3.6-ea.1 would be a prefix match
        available = ["v3.4", "v3.6-ea.1", "v3.6-ea.2"]
        result = mod.match_versions("v3.6", available)
        assert "v3.6-ea.1" in result
        assert "v3.6-ea.2" in result

    def test_no_match(self):
        assert mod.match_versions("v9.9", self.AVAILABLE) == []

    def test_exact_takes_priority_over_prefix(self):
        result = mod.match_versions("v3.5", self.AVAILABLE)
        assert "v3.5" in result


# ---------------------------------------------------------------------------
# resolve() integration tests (mock GitLab)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
    monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
    monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy")
    monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
    monkeypatch.setenv("GITLAB_TOKEN", "fake-token")


FAKE_TREE = [
    {"name": "v3.4", "type": "tree"},
    {"name": "v3.5", "type": "tree"},
    {"name": "v3.5-ea.1", "type": "tree"},
    {"name": "automation", "type": "tree"},
    {"name": "resources.yaml", "type": "blob"},
]


class TestResolve:
    def test_resolved_single_match(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4", "v3.5", "v3.5-ea.1"]):
            result = mod.resolve("rhoai-3.5-ea.1")

        assert result["status"] == "resolved"
        assert result["release"] == "rhoai-3.5-ea.1"
        assert result["konflux_app"] == "rhoai-v3-5-ea-1"
        assert result["version_dir"] == "v3.5-ea.1"
        assert result["cluster_domain"] == "stone-prod-p02.hjvn.p1"
        assert result["cluster_id"] == "stone-prod-p02"
        assert result["tenant"] == "rhoai-tenant"
        assert result["environment"] == "prod"
        assert "Context Confirmation" in result["confirmation_display"]

    def test_ambiguous_multiple_matches(self, mock_env):
        # v3.6 doesn't exist exactly, but v3.6-ea.1 and v3.6-ea.2 prefix-match
        with patch.object(mod, "list_version_dirs", return_value=["v3.4", "v3.6-ea.1", "v3.6-ea.2"]):
            result = mod.resolve("3.6")

        assert result["status"] == "ambiguous"
        assert len(result["candidates"]) == 2
        assert "Multiple Matches" in result["confirmation_display"]

    def test_not_found(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4", "v3.5", "v3.5-ea.1"]):
            result = mod.resolve("9.9")

        assert result["status"] == "not_found"
        assert "Version Not Found" in result["confirmation_display"]
        assert "v3.4" in result["available_versions"]

    def test_missing_cluster_domain(self, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_TENANT", raising=False)
        monkeypatch.delenv("KONFLUX_NAMESPACE", raising=False)
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")

        with patch.object(mod.konflux_environment, "load"):
            result = mod.resolve("3.4")

        assert result["status"] == "error"
        assert "KONFLUX_CLUSTER_DOMAIN" in result["confirmation_display"]

    def test_tenant_fallback_to_namespace(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        monkeypatch.delenv("KONFLUX_TENANT", raising=False)
        monkeypatch.setenv("KONFLUX_NAMESPACE", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]) as mock_list:
            result = mod.resolve("3.4")

        assert result["status"] == "resolved"
        mock_list.assert_called_once_with("stone-prod-p02", "rhoai-tenant")

    def test_parse_failure(self, mock_env):
        with patch.object(mod.konflux_environment, "load"):
            result = mod.resolve("not a version")

        assert result["status"] == "error"
        assert "Could not parse" in result["confirmation_display"]

    def test_gitlab_error(self, mock_env):
        with patch.object(mod, "list_version_dirs", side_effect=Exception("connection refused")):
            result = mod.resolve("3.4")

        assert result["status"] == "error"
        assert "connection refused" in result["confirmation_display"]


# ---------------------------------------------------------------------------
# confirmation_display formatting tests
# ---------------------------------------------------------------------------


class TestConfirmationDisplay:
    def test_resolved_contains_all_fields(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.5-ea.1"]):
            result = mod.resolve("3.5-ea.1")

        display = result["confirmation_display"]
        assert "rhoai-3.5-ea.1" in display
        assert "rhoai-v3-5-ea-1" in display
        assert "stone-prod-p02.hjvn.p1" in display
        assert "rhoai-tenant" in display
        assert "EnterpriseContractPolicy" in display
        assert "prod" in display

    def test_ambiguous_lists_all_candidates(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4", "v3.6-ea.1", "v3.6-ea.2"]):
            result = mod.resolve("3.6")

        display = result["confirmation_display"]
        assert "| 1 |" in display
        assert "| 2 |" in display
        assert "rhoai-3.6-ea.1" in display
        assert "rhoai-3.6-ea.2" in display

    def test_not_found_lists_available(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4", "v3.5"]):
            result = mod.resolve("9.9")

        display = result["confirmation_display"]
        assert "v3.4" in display
        assert "v3.5" in display
        assert "rhoai-tenant" in display
        assert "stone-prod-p02" in display


class TestBuildLinks:
    def test_cluster_console_includes_openshiftapps_domain(self):
        links = mod._build_links(
            cluster_domain="stone-prod-p02.hjvn.p1",
            policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
            gitlab_host="gitlab.cee.redhat.com",
            gitlab_project="releng/konflux-release-data",
            policy_files=[],
            app_slug="rhoai",
        )
        assert links["cluster_console"] == "https://konflux-ui.apps.stone-prod-p02.hjvn.p1.openshiftapps.com/"

    def test_cluster_console_uses_ns_path_with_tenant_and_app(self):
        links = mod._build_links(
            cluster_domain="stone-prod-p02.hjvn.p1",
            policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
            gitlab_host="gitlab.cee.redhat.com",
            gitlab_project="releng/konflux-release-data",
            policy_files=[],
            app_slug="rhoai",
            tenant="rhoai-tenant",
            konflux_app="rhoai-v3-5-ea-2",
        )
        assert links["cluster_console"] == (
            "https://konflux-ui.apps.stone-prod-p02.hjvn.p1.openshiftapps.com"
            "/ns/rhoai-tenant/applications/rhoai-v3-5-ea-2"
        )

    def test_cluster_console_not_set_without_domain(self):
        links = mod._build_links(
            cluster_domain="",
            policy_dir="config/test",
            gitlab_host="gitlab.example.com",
            gitlab_project="test/project",
            policy_files=[],
            app_slug="rhoai",
        )
        assert "cluster_console" not in links
