"""Tests for scripts/release_dates.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import release_dates as mod


# ---------------------------------------------------------------------------
# get_eos_date
# ---------------------------------------------------------------------------


class TestGetEosDate:
    def test_known_release_returns_date(self):
        date = mod.get_eos_date("rhoai-3.4")
        assert date == "2026-08-12"

    def test_known_release_2_25(self):
        assert mod.get_eos_date("rhoai-2.25") == "2027-04-26"

    def test_known_release_3_3(self):
        assert mod.get_eos_date("rhoai-3.3") == "2026-10-05"

    def test_unknown_release_returns_none(self):
        assert mod.get_eos_date("rhoai-9.9") is None

    def test_empty_string_returns_none(self):
        assert mod.get_eos_date("") is None

    def test_remote_fallback_called_when_not_static(self):
        with patch.object(mod, "_get_eos_from_remote", return_value="2099-01-01") as mock_remote:
            result = mod.get_eos_date("rhoai-future-release")
        mock_remote.assert_called_once_with("rhoai-future-release")
        assert result == "2099-01-01"

    def test_remote_takes_precedence_over_static(self):
        with patch.object(mod, "_get_eos_from_remote", return_value="2099-12-31"):
            result = mod.get_eos_date("rhoai-3.4")
        assert result == "2099-12-31"

    def test_static_fallback_when_remote_returns_none(self):
        with patch.object(mod, "_get_eos_from_remote", return_value=None):
            result = mod.get_eos_date("rhoai-3.4")
        assert result == "2026-08-12"


# ---------------------------------------------------------------------------
# get_eos_date_with_source
# ---------------------------------------------------------------------------


class TestGetEosDateWithSource:
    def test_static_source_returns_link(self):
        with patch.object(mod, "_get_eos_from_remote", return_value=None):
            date, source = mod.get_eos_date_with_source("rhoai-3.4")
        assert date == "2026-08-12"
        assert "release_dates.yaml" in source
        assert source.startswith("[")

    def test_remote_source_returns_link(self):
        with patch.object(mod, "_get_eos_from_remote", return_value="2099-01-01"):
            date, source = mod.get_eos_date_with_source("rhoai-3.4")
        assert date == "2099-01-01"
        assert "rhai-release-data.yaml" in source
        assert source.startswith("[")

    def test_unknown_release_returns_none_and_empty_source(self):
        with patch.object(mod, "_get_eos_from_remote", return_value=None):
            date, source = mod.get_eos_date_with_source("rhoai-99.0")
        assert date is None
        assert source == ""


# ---------------------------------------------------------------------------
# get_upcoming_release_date_with_source
# ---------------------------------------------------------------------------


class TestGetUpcomingReleaseDateWithSource:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        mod._release_data_cache = None
        yield
        mod._release_data_cache = None

    def test_returns_date_and_link(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [{
                "version": "3.5",
                "products": {"rhoai": {
                    "milestones": [{"type": "ga", "date": "2026-08-20", "version": "3.5"}],
                }},
            }],
        }):
            date, source = mod.get_upcoming_release_date_with_source("rhoai-3.5")
        assert date == "2026-08-20"
        assert "rhai-release-data.yaml" in source
        assert source.startswith("[")

    def test_returns_none_and_empty_source_when_not_found(self):
        with patch.object(mod, "_fetch_release_data", return_value=None):
            date, source = mod.get_upcoming_release_date_with_source("rhoai-3.5")
        assert date is None
        assert source == ""


# ---------------------------------------------------------------------------
# _get_eos_from_remote
# ---------------------------------------------------------------------------


class TestGetEosFromRemote:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        mod._release_data_cache = None
        yield
        mod._release_data_cache = None

    def test_returns_date_when_field_exists(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [
                {"version": "3.5", "support": {"end_of_support": "2027-01-05"}, "products": {"rhoai": {}}},
            ],
        }):
            assert mod._get_eos_from_remote("rhoai-3.5") == "2027-01-05"

    def test_returns_none_when_field_missing(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [
                {"version": "3.5", "support": {"phase": "maintenance"}, "products": {"rhoai": {}}},
            ],
        }):
            assert mod._get_eos_from_remote("rhoai-3.5") is None

    def test_returns_none_when_fetch_fails(self):
        with patch.object(mod, "_fetch_release_data", return_value=None):
            assert mod._get_eos_from_remote("rhoai-3.5") is None

    def test_returns_none_when_version_not_found(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [
                {"version": "3.4", "support": {"end_of_support": "2026-08-12"}, "products": {"rhoai": {}}},
            ],
        }):
            assert mod._get_eos_from_remote("rhoai-3.5") is None

    def test_ea_release_maps_to_base_version(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [
                {"version": "3.5", "support": {"end_of_support": "2027-01-05"}, "products": {"rhoai": {}}},
            ],
        }):
            assert mod._get_eos_from_remote("rhoai-3.5-ea.2") == "2027-01-05"


# ---------------------------------------------------------------------------
# get_effective_until
# ---------------------------------------------------------------------------


class TestGetEffectiveUntil:
    def test_adds_7_day_buffer_to_eos(self):
        # rhoai-3.4 EOS = 2026-08-12, +7d = 2026-08-19
        result = mod.get_effective_until("rhoai-3.4")
        assert result == "2026-08-19T00:00:00Z"

    def test_returns_rfc3339_format(self):
        result = mod.get_effective_until("rhoai-3.4")
        assert result is not None
        assert result.endswith("T00:00:00Z")

    def test_unknown_release_returns_none(self):
        assert mod.get_effective_until("rhoai-99.0") is None

    def test_buffer_applied_correctly_to_2_25(self):
        # rhoai-2.25 EOS = 2027-04-26, +7d = 2027-05-03
        result = mod.get_effective_until("rhoai-2.25")
        assert result == "2027-05-03T00:00:00Z"

    def test_buffer_applied_correctly_to_3_3(self):
        # rhoai-3.3 EOS = 2026-10-05, +7d = 2026-10-12
        result = mod.get_effective_until("rhoai-3.3")
        assert result == "2026-10-12T00:00:00Z"


# ---------------------------------------------------------------------------
# resolve_effective_until_dates
# ---------------------------------------------------------------------------


class TestResolveEffectiveUntilDates:
    def test_known_version_returns_full_entry(self):
        result = mod.resolve_effective_until_dates(["rhoai-3.4"])
        assert "rhoai-3.4" in result
        entry = result["rhoai-3.4"]
        assert entry["effectiveUntil"] == "2026-08-19T00:00:00Z"
        assert entry["source"] == "release_dates_yaml"
        assert "buffer" in entry["note"]

    def test_unknown_version_returns_none_entry(self):
        result = mod.resolve_effective_until_dates(["rhoai-99.0"])
        entry = result["rhoai-99.0"]
        assert entry["effectiveUntil"] is None
        assert entry["source"] == "unknown"
        assert "must provide" in entry["note"]

    def test_mixed_known_and_unknown(self):
        result = mod.resolve_effective_until_dates(["rhoai-3.4", "rhoai-99.0"])
        assert result["rhoai-3.4"]["effectiveUntil"] is not None
        assert result["rhoai-99.0"]["effectiveUntil"] is None

    def test_empty_list(self):
        assert mod.resolve_effective_until_dates([]) == {}

    def test_multiple_known_versions(self):
        result = mod.resolve_effective_until_dates(["rhoai-3.4", "rhoai-3.3", "rhoai-2.25"])
        for ver in ["rhoai-3.4", "rhoai-3.3", "rhoai-2.25"]:
            assert result[ver]["effectiveUntil"] is not None


# ---------------------------------------------------------------------------
# validate_effective_until_date
# ---------------------------------------------------------------------------


class TestValidateEffectiveUntilDate:
    def test_correct_date_is_valid(self):
        result = mod.validate_effective_until_date("rhoai-3.4", "2026-08-19T00:00:00Z")
        assert result["valid"] is True
        assert result["provided"] == "2026-08-19"
        assert result["expected"] == "2026-08-19"

    def test_wrong_date_is_invalid(self):
        result = mod.validate_effective_until_date("rhoai-3.4", "2026-08-12T00:00:00Z")
        assert result["valid"] is False
        assert result["provided"] == "2026-08-12"
        assert result["expected"] == "2026-08-19"
        assert "Expected" in result["detail"]

    def test_unknown_version_is_valid_with_no_expected(self):
        result = mod.validate_effective_until_date("rhoai-99.0", "2099-01-01T00:00:00Z")
        assert result["valid"] is True
        assert result["expected"] is None
        assert "cannot validate" in result["detail"]

    def test_date_only_format_accepted(self):
        result = mod.validate_effective_until_date("rhoai-3.4", "2026-08-19")
        assert result["valid"] is True

    def test_empty_provided_date(self):
        result = mod.validate_effective_until_date("rhoai-3.4", "")
        assert result["valid"] is False
        assert result["provided"] == ""


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


class TestListAll:
    def test_returns_list_of_dicts(self):
        rows = mod.list_all()
        assert isinstance(rows, list)
        assert len(rows) > 0

    def test_each_row_has_required_fields(self):
        for row in mod.list_all():
            assert "release" in row
            assert "end_of_support" in row
            assert "effective_until" in row
            assert "source" in row

    def test_rhoai_3_4_present(self):
        releases = [r["release"] for r in mod.list_all()]
        assert "rhoai-3.4" in releases

    def test_effective_until_has_buffer(self):
        row = next(r for r in mod.list_all() if r["release"] == "rhoai-3.4")
        assert row["end_of_support"] == "2026-08-12"
        assert row["effective_until"] == "2026-08-19T00:00:00Z"


# ---------------------------------------------------------------------------
# format_version_label
# ---------------------------------------------------------------------------


class TestFormatVersionLabel:
    def test_ga_release(self):
        assert mod.format_version_label("rhoai-3.4") == "RHOAI 3.4"

    def test_ea_release(self):
        assert mod.format_version_label("rhoai-3.5-ea.2") == "RHOAI 3.5 EA2"

    def test_double_digit_minor(self):
        assert mod.format_version_label("rhoai-2.25") == "RHOAI 2.25"

    def test_ea1(self):
        assert mod.format_version_label("rhoai-3.5-ea.1") == "RHOAI 3.5 EA1"


class TestProductPagesUrl:
    def test_constant_is_set(self):
        assert mod.PRODUCT_PAGES_URL == "https://productpages.redhat.com/"


# ---------------------------------------------------------------------------
# resolve_release_context integration: end_of_support in output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _release_to_base_version
# ---------------------------------------------------------------------------


class TestReleaseToBaseVersion:
    def test_ga_release(self):
        assert mod._release_to_base_version("rhoai-3.5") == "3.5"

    def test_ea_release(self):
        assert mod._release_to_base_version("rhoai-3.5-ea.2") == "3.5"

    def test_ea1_release(self):
        assert mod._release_to_base_version("rhoai-3.5-ea.1") == "3.5"

    def test_double_digit_minor(self):
        assert mod._release_to_base_version("rhoai-2.25") == "2.25"

    def test_no_prefix(self):
        assert mod._release_to_base_version("3.5") == "3.5"


# ---------------------------------------------------------------------------
# get_upcoming_release_date
# ---------------------------------------------------------------------------

_SAMPLE_RELEASE_DATA_YAML = """\
supported:
  - version: "3.5"
    products:
      rhoai:
        upcoming_release:
          date: "2026-08-15"
  - version: "3.4"
    products:
      rhoai:
        upcoming_release:
          date: "2026-07-01"
"""


class TestReleaseMilestoneType:
    def test_ga_release(self):
        assert mod._release_to_milestone_type("rhoai-3.5") == "ga"

    def test_ea1_release(self):
        assert mod._release_to_milestone_type("rhoai-3.5-ea.1") == "ea1"

    def test_ea2_release(self):
        assert mod._release_to_milestone_type("rhoai-3.5-ea.2") == "ea2"

    def test_bare_version(self):
        assert mod._release_to_milestone_type("3.5") == "ga"

    def test_bare_ea(self):
        assert mod._release_to_milestone_type("3.5-ea.1") == "ea1"


_RHOAI_MILESTONES_FIXTURE = {
    "supported": [{
        "version": "3.5",
        "products": {"rhoai": {
            "milestones": [
                {"type": "ea1", "date": "2026-06-15", "version": "3.5"},
                {"type": "ea2", "date": "2026-07-16", "version": "3.5"},
                {"type": "ga", "date": "2026-08-20", "version": "3.5"},
                {"type": "ga_code_freeze", "date": "2026-07-24", "version": "3.5"},
            ],
        }},
    }],
}

_RHOAI_36_MILESTONES_FIXTURE = {
    "supported": [{
        "version": "3.6",
        "products": {"rhoai": {
            "milestones": [
                {"type": "ea1", "date": "2026-09-01", "version": "3.6"},
                {"type": "ea2", "date": "2026-10-01", "version": "3.6"},
                {"type": "ga", "date": "2026-11-01", "version": "3.6"},
                {"type": "ea1_code_freeze", "date": "2026-08-15", "version": "3.6"},
                {"type": "ea2_code_freeze", "date": "2026-09-15", "version": "3.6"},
                {"type": "ga_code_freeze", "date": "2026-10-15", "version": "3.6"},
            ],
        }},
    }],
}

_RHOAI_OLD_MILESTONES_FIXTURE = {
    "supported": [{
        "version": "3.3",
        "products": {"rhoai": {
            "milestones": [
                {"type": "ga", "date": "2026-04-01", "version": "3.3"},
                {"type": "code_freeze", "date": "2026-03-15", "version": "3.3"},
            ],
        }},
    }],
}


class TestGetUpcomingReleaseDate:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        mod._release_data_cache = None
        yield
        mod._release_data_cache = None

    def test_ga_query_returns_ga_date(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            assert mod.get_upcoming_release_date("rhoai-3.5") == "2026-08-20"

    def test_ea2_query_returns_ea2_date(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            assert mod.get_upcoming_release_date("rhoai-3.5-ea.2") == "2026-07-16"

    def test_ea1_query_returns_ea1_date(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            assert mod.get_upcoming_release_date("rhoai-3.5-ea.1") == "2026-06-15"

    def test_returns_none_when_version_not_found(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            assert mod.get_upcoming_release_date("rhoai-9.9") is None

    def test_returns_none_when_fetch_fails(self):
        with patch.object(mod, "_fetch_release_data", return_value=None):
            assert mod.get_upcoming_release_date("rhoai-3.5") is None

    def test_returns_none_when_no_milestones(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [
                {"version": "3.5", "products": {"rhoai": {}}},
            ],
        }):
            assert mod.get_upcoming_release_date("rhoai-3.5") is None

    def test_returns_none_when_milestone_type_not_found(self):
        with patch.object(mod, "_fetch_release_data", return_value={
            "supported": [{
                "version": "3.5",
                "products": {"rhoai": {
                    "milestones": [{"type": "ea1", "date": "2026-06-15", "version": "3.5"}],
                }},
            }],
        }):
            assert mod.get_upcoming_release_date("rhoai-3.5") is None

    def test_returns_none_when_supported_list_empty(self):
        with patch.object(mod, "_fetch_release_data", return_value={"supported": []}):
            assert mod.get_upcoming_release_date("rhoai-3.5") is None

    def test_returns_none_when_data_has_no_supported_key(self):
        with patch.object(mod, "_fetch_release_data", return_value={"other": "stuff"}):
            assert mod.get_upcoming_release_date("rhoai-3.5") is None


class TestGetCodeFreezeDate:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        mod._release_data_cache = None
        yield
        mod._release_data_cache = None

    def test_ga_query_returns_ga_code_freeze(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            assert mod.get_code_freeze_date("rhoai-3.5") == "2026-07-24"

    def test_ea1_query_returns_ea1_code_freeze(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_36_MILESTONES_FIXTURE):
            assert mod.get_code_freeze_date("rhoai-3.6-ea.1") == "2026-08-15"

    def test_ea2_query_returns_ea2_code_freeze(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_36_MILESTONES_FIXTURE):
            assert mod.get_code_freeze_date("rhoai-3.6-ea.2") == "2026-09-15"

    def test_ga_fallback_to_generic_code_freeze(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_OLD_MILESTONES_FIXTURE):
            assert mod.get_code_freeze_date("rhoai-3.3") == "2026-03-15"

    def test_returns_none_when_fetch_fails(self):
        with patch.object(mod, "_fetch_release_data", return_value=None):
            assert mod.get_code_freeze_date("rhoai-3.5") is None

    def test_returns_none_when_version_not_found(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            assert mod.get_code_freeze_date("rhoai-9.9") is None

    def test_returns_none_when_milestone_absent(self):
        fixture = {
            "supported": [{
                "version": "3.5",
                "products": {"rhoai": {
                    "milestones": [{"type": "ga", "date": "2026-08-20", "version": "3.5"}],
                }},
            }],
        }
        with patch.object(mod, "_fetch_release_data", return_value=fixture):
            assert mod.get_code_freeze_date("rhoai-3.5") is None

    def test_ea_no_fallback_to_generic_code_freeze(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_OLD_MILESTONES_FIXTURE):
            assert mod.get_code_freeze_date("rhoai-3.3-ea.1") is None


class TestGetCodeFreezeDateWithSource:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        mod._release_data_cache = None
        yield
        mod._release_data_cache = None

    def test_returns_date_and_link(self):
        with patch.object(mod, "_fetch_release_data", return_value=_RHOAI_MILESTONES_FIXTURE):
            date, source = mod.get_code_freeze_date_with_source("rhoai-3.5")
        assert date == "2026-07-24"
        assert "rhai-release-data.yaml" in source
        assert source.startswith("[")

    def test_returns_none_and_empty_source_when_not_found(self):
        with patch.object(mod, "_fetch_release_data", return_value=None):
            date, source = mod.get_code_freeze_date_with_source("rhoai-3.5")
        assert date is None
        assert source == ""


class TestFetchReleaseData:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        mod._release_data_cache = None
        yield
        mod._release_data_cache = None

    def test_caches_result(self):
        mock_result = {"content": _SAMPLE_RELEASE_DATA_YAML, "sha": "abc"}
        with patch("github_ops.get_file", return_value=mock_result) as mock_get:
            first = mod._fetch_release_data()
            second = mod._fetch_release_data()
        mock_get.assert_called_once()
        assert first is second

    def test_github_error_returns_none(self):
        with patch("github_ops.get_file", return_value={"error": "auth failed"}):
            assert mod._fetch_release_data() is None

    def test_github_ops_not_importable_returns_none(self):
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "github_ops":
                raise ImportError("no module")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            assert mod._fetch_release_data() is None

    def test_malformed_yaml_returns_none(self):
        with patch("github_ops.get_file", return_value={"content": ":::bad yaml:::{{", "sha": "abc"}):
            result = mod._fetch_release_data()
            assert result is None or not isinstance(result, dict) or result == {}


# ---------------------------------------------------------------------------
# list_all includes upcoming_release_date
# ---------------------------------------------------------------------------


class TestListAllUpcomingReleaseDate:
    def test_each_row_has_upcoming_release_date_field(self):
        with patch.object(mod, "get_upcoming_release_date", return_value=None):
            for row in mod.list_all():
                assert "upcoming_release_date" in row


# ---------------------------------------------------------------------------
# resolve_release_context integration: end_of_support in output
# ---------------------------------------------------------------------------


class TestResolveReleaseContextEos:
    """Verify that resolve_release_context passes EOS date through."""

    def test_resolved_result_includes_end_of_support(self, monkeypatch):
        import resolve_release_context as ctx

        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster-01.abc.xyz")
        monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

        with patch.object(ctx, "list_version_dirs", return_value=["v3.4"]):
            result = ctx.resolve("rhoai-3.4")

        assert result["status"] == "resolved"
        assert result["end_of_support"] == "2026-08-12"

    def test_confirmation_display_contains_end_of_support(self, monkeypatch):
        import resolve_release_context as ctx

        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster-01.abc.xyz")
        monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

        with patch.object(ctx, "list_version_dirs", return_value=["v3.4"]):
            result = ctx.resolve("rhoai-3.4")

        assert "End of Support (RHOAI 3.4)" in result["confirmation_display"]
        assert "2026-08-12" in result["confirmation_display"]
        assert "based on [release_dates.yaml]" in result["confirmation_display"]
        assert "Product Pages" in result["confirmation_display"]

    def test_unknown_release_shows_unknown_in_display(self, monkeypatch):
        import resolve_release_context as ctx

        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "test-cluster-01.abc.xyz")
        monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

        with patch.object(ctx, "list_version_dirs", return_value=["v9.9"]):
            result = ctx.resolve("9.9")

        assert result["status"] == "resolved"
        assert result["end_of_support"] is None
        assert "Unknown" in result["confirmation_display"]
