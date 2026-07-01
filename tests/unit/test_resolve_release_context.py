"""Tests for scripts/resolve_release_context.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import resolve_release_context as mod


# ---------------------------------------------------------------------------
# extract_environment tests (pure logic, no mocks)
# ---------------------------------------------------------------------------


class TestExtractEnvironment:
    def test_stage_prefix(self):
        cleaned, env = mod.extract_environment("stage rhoai-3.5-ea2")
        assert env == "stage"
        assert "stage" not in cleaned.lower()

    def test_stage_suffix(self):
        cleaned, env = mod.extract_environment("rhoai-3.5-ea2 stage")
        assert env == "stage"
        assert "stage" not in cleaned.lower()

    def test_prod_prefix(self):
        cleaned, env = mod.extract_environment("prod rhoai-3.5-ea2")
        assert env == "prod"
        assert "prod" not in cleaned.lower()

    def test_prod_suffix(self):
        cleaned, env = mod.extract_environment("rhoai-3.5-ea2 prod")
        assert env == "prod"

    def test_no_environment_defaults_to_prod(self):
        cleaned, env = mod.extract_environment("rhoai-3.5-ea2")
        assert env == "prod"
        assert cleaned == "rhoai-3.5-ea2"

    def test_case_insensitive(self):
        _, env = mod.extract_environment("STAGE rhoai-3.5")
        assert env == "stage"

    def test_stage_mid_query(self):
        cleaned, env = mod.extract_environment("conforma stage rhoai-3.5-ea2")
        assert env == "stage"

    def test_version_parsing_still_works_with_stage(self):
        assert mod.parse_query("stage rhoai-3.5-ea2") == "v3.5-ea.2"

    def test_version_parsing_still_works_with_prod(self):
        assert mod.parse_query("prod 3.4") == "v3.4"


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

    def test_ea_no_separator_before_number(self):
        assert mod.parse_query("3.5-ea2") == "v3.5-ea.2"

    def test_rhoai_ea_no_separator_before_number(self):
        assert mod.parse_query("rhoai-3.5-ea2") == "v3.5-ea.2"

    def test_ea_no_separators_at_all(self):
        assert mod.parse_query("3.5ea1") == "v3.5-ea.1"

    def test_dash_separated_major_minor_with_ea(self):
        assert mod.parse_query("rhoai-3-5.ea2") == "v3.5-ea.2"

    def test_dash_separated_major_minor_with_ea_dash(self):
        assert mod.parse_query("3-5-ea2") == "v3.5-ea.2"

    def test_dash_separated_major_minor_with_ea_dot(self):
        assert mod.parse_query("3-5-ea.2") == "v3.5-ea.2"

    def test_dash_separated_major_minor_ga(self):
        assert mod.parse_query("rhoai-3-4") == "v3.4"

    def test_dash_separated_double_digit_minor(self):
        assert mod.parse_query("rhoai-2-25") == "v2.25"

    def test_rhoai_dot_separator_with_ea(self):
        assert mod.parse_query("rhoai.3-5 ea2") == "v3.5-ea.2"

    def test_rhoai_dot_separator_ga(self):
        assert mod.parse_query("rhoai.3-4") == "v3.4"


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

    def test_resolved_stage_environment(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.5-ea.2"]):
            result = mod.resolve("stage rhoai-3.5-ea2")

        assert result["status"] == "resolved"
        assert result["release"] == "rhoai-3.5-ea.2"
        assert result["environment"] == "stage"
        assert "| **Environment** | stage |" in result["confirmation_display"]

    def test_resolved_stage_suffix(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("rhoai-3.4 stage")

        assert result["environment"] == "stage"

    def test_resolved_defaults_to_prod(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("rhoai-3.4")

        assert result["environment"] == "prod"
        assert "| **Environment** | prod |" in result["confirmation_display"]

    def test_environment_override_stage(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.5-ea.2"]):
            result = mod.resolve("rhoai-3.5-ea2", environment_override="stage")

        assert result["status"] == "resolved"
        assert result["environment"] == "stage"
        assert "| **Environment** | stage |" in result["confirmation_display"]

    def test_environment_override_beats_query_keyword(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("prod rhoai-3.4", environment_override="stage")

        assert result["environment"] == "stage"

    def test_environment_override_prod(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("stage rhoai-3.4", environment_override="prod")

        assert result["environment"] == "prod"

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

    def test_policy_files_filtered_by_environment(self):
        all_files = [
            "fbc-rhoai-prod.yaml",
            "fbc-rhoai-stage.yaml",
            "registry-rhoai-chart-prod.yaml",
            "registry-rhoai-chart-stage.yaml",
            "registry-rhoai-prod.yaml",
            "registry-rhoai-stage.yaml",
        ]
        links = mod._build_links(
            cluster_domain="stone-prod-p02.hjvn.p1",
            policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
            gitlab_host="gitlab.cee.redhat.com",
            gitlab_project="releng/konflux-release-data",
            policy_files=all_files,
            app_slug="rhoai",
            environment="prod",
        )
        names = [f["name"] for f in links["policy_files"]]
        assert names == [
            "fbc-rhoai-prod.yaml",
            "registry-rhoai-chart-prod.yaml",
            "registry-rhoai-prod.yaml",
        ]

    def test_policy_files_filtered_by_stage_environment(self):
        all_files = [
            "fbc-rhoai-prod.yaml",
            "fbc-rhoai-stage.yaml",
            "registry-rhoai-prod.yaml",
            "registry-rhoai-stage.yaml",
        ]
        links = mod._build_links(
            cluster_domain="stone-prod-p02.hjvn.p1",
            policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
            gitlab_host="gitlab.cee.redhat.com",
            gitlab_project="releng/konflux-release-data",
            policy_files=all_files,
            app_slug="rhoai",
            environment="stage",
        )
        names = [f["name"] for f in links["policy_files"]]
        assert names == ["fbc-rhoai-stage.yaml", "registry-rhoai-stage.yaml"]

    def test_policy_files_unfiltered_without_environment(self):
        all_files = [
            "fbc-rhoai-prod.yaml",
            "fbc-rhoai-stage.yaml",
            "registry-rhoai-prod.yaml",
            "registry-rhoai-stage.yaml",
        ]
        links = mod._build_links(
            cluster_domain="stone-prod-p02.hjvn.p1",
            policy_dir="config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy",
            gitlab_host="gitlab.cee.redhat.com",
            gitlab_project="releng/konflux-release-data",
            policy_files=all_files,
            app_slug="rhoai",
        )
        names = [f["name"] for f in links["policy_files"]]
        assert len(names) == 4


# ---------------------------------------------------------------------------
# create_rundir tests
# ---------------------------------------------------------------------------


class TestCreateRundir:
    def test_creates_timestamped_directory(self, tmp_path):
        rundir = mod.create_rundir(str(tmp_path))
        assert tmp_path in __import__("pathlib").Path(rundir).parents
        assert __import__("pathlib").Path(rundir).is_dir()

    def test_directory_name_is_timestamp_format(self, tmp_path):
        rundir = mod.create_rundir(str(tmp_path))
        dirname = __import__("pathlib").Path(rundir).name
        import re
        assert re.match(r"^\d{8}-\d{6}$", dirname)

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "a" / "b"
        rundir = mod.create_rundir(str(nested))
        assert __import__("pathlib").Path(rundir).is_dir()


# ---------------------------------------------------------------------------
# --output-dir integration tests
# ---------------------------------------------------------------------------


class TestOutputDir:
    def test_resolved_creates_rundir_and_saves_context(self, mock_env, tmp_path):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("3.4")

        assert result["status"] == "resolved"

        rundir = mod.create_rundir(str(tmp_path))
        result["rundir"] = rundir
        context_path = __import__("pathlib").Path(rundir) / "resolve-context.json"
        context_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

        saved = json.loads(context_path.read_text(encoding="utf-8"))
        assert saved["status"] == "resolved"
        assert saved["release"] == "rhoai-3.4"
        assert saved["rundir"] == rundir

    def test_rundir_key_in_output(self, mock_env, tmp_path):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("3.4")

        rundir = mod.create_rundir(str(tmp_path))
        result["rundir"] = rundir

        assert "rundir" in result
        assert str(tmp_path) in result["rundir"]

    def test_not_resolved_skips_rundir(self, mock_env):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            result = mod.resolve("9.9")

        assert result["status"] == "not_found"
        assert "rundir" not in result

    def test_main_with_output_dir(self, mock_env, tmp_path, capsys):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            with patch("sys.argv", ["prog", "--query", "3.4", "--output-dir", str(tmp_path)]):
                exit_code = mod.main()

        assert exit_code == 0
        stdout = capsys.readouterr().out
        output = json.loads(stdout)
        assert output["status"] == "resolved"
        assert "rundir" in output

        rundir = __import__("pathlib").Path(output["rundir"])
        assert rundir.is_dir()
        context_file = rundir / "resolve-context.json"
        assert context_file.exists()
        saved = json.loads(context_file.read_text(encoding="utf-8"))
        assert saved["release"] == "rhoai-3.4"

    def test_main_with_environment_flag(self, mock_env, tmp_path, capsys):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            with patch("sys.argv", ["prog", "--query", "3.4", "--environment", "stage", "--output-dir", str(tmp_path)]):
                exit_code = mod.main()

        assert exit_code == 0
        stdout = capsys.readouterr().out
        output = json.loads(stdout)
        assert output["environment"] == "stage"

    def test_main_without_output_dir(self, mock_env, capsys):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            with patch("sys.argv", ["prog", "--query", "3.4"]):
                exit_code = mod.main()

        assert exit_code == 0
        stdout = capsys.readouterr().out
        output = json.loads(stdout)
        assert "rundir" not in output

    def test_reuses_existing_rundir(self, mock_env, tmp_path, capsys):
        rundir = tmp_path / "20260629-143854"
        rundir.mkdir()
        (rundir / "resolve-context.json").write_text("{}")

        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            with patch("sys.argv", ["prog", "--query", "3.4", "--output-dir", str(rundir)]):
                exit_code = mod.main()

        assert exit_code == 0
        stdout = capsys.readouterr().out
        output = json.loads(stdout)
        assert output["rundir"] == str(rundir)
        assert not list(p for p in rundir.iterdir() if p.is_dir())

    def test_main_error_status_skips_output_dir(self, mock_env, tmp_path, capsys):
        with patch.object(mod, "list_version_dirs", return_value=["v3.4"]):
            with patch("sys.argv", ["prog", "--query", "9.9", "--output-dir", str(tmp_path)]):
                exit_code = mod.main()

        assert exit_code == 1
        assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# upcoming_release_date in resolve output
# ---------------------------------------------------------------------------


class TestUpcomingReleaseDate:
    @pytest.fixture(autouse=True)
    def mock_env(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

    @pytest.fixture(autouse=True)
    def _clear_release_data_cache(self):
        mod.release_dates._release_data_cache = None
        yield
        mod.release_dates._release_data_cache = None

    def test_resolved_result_includes_upcoming_release_date(self):
        with patch.object(mod, "list_version_dirs", return_value=["v3.5"]), \
             patch.object(mod.release_dates, "_fetch_release_data", return_value={
                 "supported": [{"version": "3.5", "products": {"rhoai": {"upcoming_release": {"date": "2026-08-15"}}}}],
             }):
            result = mod.resolve("3.5")

        assert result["status"] == "resolved"
        assert result["upcoming_release_date"] == "2026-08-15"

    def test_confirmation_display_contains_upcoming_release_date(self):
        with patch.object(mod, "list_version_dirs", return_value=["v3.5"]), \
             patch.object(mod.release_dates, "_fetch_release_data", return_value={
                 "supported": [{"version": "3.5", "products": {"rhoai": {"upcoming_release": {"date": "2026-08-15"}}}}],
             }):
            result = mod.resolve("3.5")

        assert "Upcoming release date (RHOAI 3.5)" in result["confirmation_display"]
        assert "2026-08-15" in result["confirmation_display"]
        assert "Product Pages" in result["confirmation_display"]

    def test_upcoming_release_date_none_omits_row(self):
        with patch.object(mod, "list_version_dirs", return_value=["v3.5"]), \
             patch.object(mod.release_dates, "_fetch_release_data", return_value=None):
            result = mod.resolve("3.5")

        assert result["upcoming_release_date"] is None
        assert "Upcoming release date" not in result["confirmation_display"]
