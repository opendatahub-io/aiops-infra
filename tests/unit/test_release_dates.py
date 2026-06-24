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

    def test_dynamic_fallback_called_when_not_static(self):
        with patch.object(mod, "_fetch_dynamic", return_value="2099-01-01") as mock_dyn:
            result = mod.get_eos_date("rhoai-future-release")
        mock_dyn.assert_called_once_with("rhoai-future-release")
        assert result == "2099-01-01"

    def test_static_takes_precedence_over_dynamic(self):
        with patch.object(mod, "_fetch_dynamic", return_value="1999-01-01") as mock_dyn:
            result = mod.get_eos_date("rhoai-3.4")
        mock_dyn.assert_not_called()
        assert result == "2026-08-12"


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
# resolve_release_context integration: end_of_support in output
# ---------------------------------------------------------------------------


class TestResolveReleaseContextEos:
    """Verify that resolve_release_context passes EOS date through."""

    def test_resolved_result_includes_end_of_support(self, monkeypatch):
        import resolve_release_context as ctx

        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
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

        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

        with patch.object(ctx, "list_version_dirs", return_value=["v3.4"]):
            result = ctx.resolve("rhoai-3.4")

        assert "End of Support" in result["confirmation_display"]
        assert "2026-08-12" in result["confirmation_display"]

    def test_unknown_release_shows_unknown_in_display(self, monkeypatch):
        import resolve_release_context as ctx

        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-prod-p02.hjvn.p1")
        monkeypatch.setenv("KONFLUX_TENANT", "rhoai-tenant")
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "config/x/product/EnterpriseContractPolicy")
        monkeypatch.setenv("GITLAB_HOST", "gitlab.corp.internal")
        monkeypatch.setenv("GITLAB_TOKEN", "fake")

        with patch.object(ctx, "list_version_dirs", return_value=["v9.9"]):
            result = ctx.resolve("9.9")

        assert result["status"] == "resolved"
        assert result["end_of_support"] is None
        assert "Unknown" in result["confirmation_display"]
