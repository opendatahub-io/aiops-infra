"""Tests for conforma_policy_ops.py."""

from __future__ import annotations

import textwrap
from unittest.mock import patch

import pytest

import conforma_policy_ops as mod


class TestResolveRepoDir:
    def test_returns_none_when_policy_dir_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-stg-p01.hjvn.p1")
        assert mod._resolve_repo_dir(tmp_path) is None

    def test_returns_candidate_when_policy_dir_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-stg-p01.hjvn.p1")
        policy_dir = tmp_path / "config" / "stone-stg-p01.hjvn.p1" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        assert mod._resolve_repo_dir(tmp_path) == tmp_path

    def test_returns_repo_subdir_when_nested(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-stg-p01.hjvn.p1")
        policy_dir = tmp_path / "repo" / "config" / "stone-stg-p01.hjvn.p1" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        assert mod._resolve_repo_dir(tmp_path) == tmp_path / "repo"

    def test_returns_none_when_no_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_DIR", raising=False)
        assert mod._resolve_repo_dir(tmp_path) is None


class TestRefreshClone:
    @patch("conforma_policy_ops._refresh_workdir_clone")
    def test_calls_refresh_when_repo_dir_found(self, mock_refresh, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-stg-p01.hjvn.p1")
        (tmp_path / ".git").mkdir()
        policy_dir = tmp_path / "config" / "stone-stg-p01.hjvn.p1" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        result = mod.refresh_clone(tmp_path)
        assert result == tmp_path
        mock_refresh.assert_called_once_with(tmp_path)

    @patch("conforma_policy_ops._refresh_workdir_clone")
    def test_returns_none_when_no_policy_dir(self, mock_refresh, tmp_path, monkeypatch):
        monkeypatch.setenv("KONFLUX_CLUSTER_DOMAIN", "stone-stg-p01.hjvn.p1")
        (tmp_path / ".git").mkdir()
        result = mod.refresh_clone(tmp_path)
        assert result is None
        mock_refresh.assert_called_once_with(tmp_path)


class TestCheckPermanentExclusions:
    def test_finds_permanent_exclusion(self):
        content = (
            "exclude:\n"
            "  - some.other.rule\n"
            "  - hermetic_task.hermetic\n"
            "  - another.rule\n"
            "volatileCriteria:\n"
            "  - value: test\n"
        )
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 1
        assert results[0]["type"] == "permanent_global_exclusion"
        assert results[0]["line"] == 3

    def test_no_match_when_rule_not_in_exclude(self):
        content = "exclude:\n  - some.other.rule\n"
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 0

    def test_ignores_comments(self):
        content = "exclude:\n  # - hermetic_task.hermetic\n  - other.rule\n"
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 0

    def test_exits_section_on_non_list_item(self):
        content = "exclude:\n  - some.rule\nvolatileCriteria:\n  - hermetic_task.hermetic\n"
        results: list[dict] = []
        mod._check_permanent_exclusions(content, "hermetic_task.hermetic", "rhoai-prod.yaml", results)
        assert len(results) == 0


class TestSearchExistingExceptions:
    @pytest.fixture(autouse=True)
    def _gitlab_env(self, monkeypatch):
        monkeypatch.setenv("GITLAB_HOST", "gitlab.test-corp.fake")
        monkeypatch.setenv("GITLAB_TOKEN", "glpat-test-only")

    def test_returns_not_checked_when_no_dir(self, tmp_path):
        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path / "nonexistent")
        )
        assert result["checked"] is False

    def test_returns_not_checked_when_no_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_DIR", raising=False)
        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is False
        assert "KONFLUX_CLUSTER_DOMAIN" in result["reason"]

    def test_finds_permanent_exclusion_in_policy_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy_file = policy_dir / "registry-rhoai-prod.yaml"
        policy_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["permanent_count"] == 1

    def test_finds_volatile_exceptions_in_policy_file(self, tmp_path, monkeypatch):
        """Volatile (volatileCriteria) exceptions must be found, not just permanent ones.

        Regression guard: the import of _find_existing_exceptions from
        create_gitlab_mr must succeed, otherwise volatile exceptions are
        silently invisible and coverage reports are wrong.
        """
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        policy_file = policy_dir / "registry-rhoai-prod.yaml"
        policy_file.write_text(
            "volatileCriteria:\n"
            "          - value: rpm_signature.allowed:abc123\n"
            "            componentNames:\n"
            "              - odh-foo-v3-5-ea-1\n"
            '            effectiveUntil: "2099-01-01T00:00:00Z"\n'
            "            reference: https://issues.redhat.com/browse/TEST-1\n"
        )

        result = mod.search_existing_exceptions(
            "rpm_signature.allowed:abc123", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["count"] >= 1, (
            "Volatile exceptions not found — _find_existing_exceptions import "
            "from create_gitlab_mr is likely broken"
        )
        exc = result["existing_exceptions"][0]
        assert exc["componentNames"] == ["odh-foo-v3-5-ea-1"]
        assert "2099" in exc["effectiveUntil"]
        assert "block_start_line" in exc
        assert isinstance(exc["block_start_line"], int)
        assert exc["block_start_line"] >= 1

    def test_excludes_files_not_in_policy_files(self, tmp_path, monkeypatch):
        """Files not listed in policy_files must be skipped entirely.

        Regression guard for cross-product contamination: an unscoped exception
        in a desktop-extensions policy file must NOT appear in RHOAI results.
        """
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        rhoai_file = policy_dir / "registry-rhoai-prod.yaml"
        rhoai_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        other_file = policy_dir / "registry-red-hat-desktop-extensions-prod.yaml"
        other_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["permanent_count"] == 1
        assert result["permanent_exclusions"][0]["file"].endswith("registry-rhoai-prod.yaml")

    def test_no_results_when_policy_files_exclude_all(self, tmp_path, monkeypatch):
        """When policy_files doesn't match any existing file, nothing is found."""
        monkeypatch.delenv("KONFLUX_CLUSTER_DOMAIN", raising=False)
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "policy")
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()

        other_file = policy_dir / "registry-red-hat-desktop-extensions-prod.yaml"
        other_file.write_text("exclude:\n  - hermetic_task.hermetic\n")

        result = mod.search_existing_exceptions(
            "hermetic_task.hermetic", ["registry-rhoai-prod.yaml"], str(tmp_path)
        )
        assert result["checked"] is True
        assert result["permanent_count"] == 0
        assert result["count"] == 0


class TestSelfServiceRuleMatches:
    def test_exact_match(self):
        assert mod._self_service_rule_matches("schedule.weekday_restriction", "schedule.weekday_restriction") is True

    def test_subcode_match(self):
        assert mod._self_service_rule_matches(
            "test.no_failed_tests:fbc-target-index-pruning-check",
            "test.no_failed_tests",
        ) is True

    def test_reverse_subcode_match(self):
        assert mod._self_service_rule_matches(
            "test.no_failed_tests",
            "test.no_failed_tests:fbc-target-index-pruning-check",
        ) is True

    def test_no_match(self):
        assert mod._self_service_rule_matches("schedule.weekday_restriction", "hermetic_task.hermetic") is False

    def test_partial_name_no_match(self):
        assert mod._self_service_rule_matches("test.no_failed", "test.no_failed_tests") is False


class TestBuildDigestToComponentMap:
    def test_builds_map_from_csv(self, tmp_path):
        csv_content = textwrap.dedent("""\
            type,component_name,image,code
            violation,odh-dashboard-v3-5-ea-2,quay.io/rhoai/odh-dashboard-rhel9@sha256:abc123,test.rule
            violation,rhoai-fbc-fragment-v3-5,quay.io/rhoai/rhoai-fbc-fragment@sha256:def456,test.rule
        """)
        csv_file = tmp_path / "report.csv"
        csv_file.write_text(csv_content)

        result = mod._build_digest_to_component_map(str(csv_file))
        assert result["sha256:abc123"] == "odh-dashboard-v3-5-ea-2"
        assert result["sha256:def456"] == "rhoai-fbc-fragment-v3-5"

    def test_handles_image_without_digest(self, tmp_path):
        csv_content = textwrap.dedent("""\
            type,component_name,image,code
            violation,comp1,quay.io/repo/image:tag,test.rule
        """)
        csv_file = tmp_path / "report.csv"
        csv_file.write_text(csv_content)

        result = mod._build_digest_to_component_map(str(csv_file))
        assert len(result) == 0


class TestSearchSelfServiceExceptions:
    def test_finds_rule_in_flat_yaml(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "registry-rhoai-stage.yaml").write_text(textwrap.dedent("""\
            ---
            - value: schedule.weekday_restriction
              imageRef: sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
        """))

        result = mod.search_self_service_exceptions(
            "schedule.weekday_restriction",
            ["registry-rhoai-stage.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert len(result["matching_entries"]) == 1
        assert result["matching_entries"][0]["value"] == "schedule.weekday_restriction"
        assert "exceptions/registry-rhoai-stage.yaml" in result["source_files"]

    def test_matches_subcode_rule(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "fbc-rhoai-stage.yaml").write_text(textwrap.dedent("""\
            ---
            - value: test.no_failed_tests:fbc-target-index-pruning-check
              imageRef: sha256:abc123
        """))

        result = mod.search_self_service_exceptions(
            "test.no_failed_tests",
            ["fbc-rhoai-stage.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert len(result["matching_entries"]) >= 1

    def test_returns_empty_when_rule_not_present(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "registry-rhoai-stage.yaml").write_text(textwrap.dedent("""\
            ---
            - value: schedule.weekday_restriction
              imageRef: sha256:fff
        """))

        result = mod.search_self_service_exceptions(
            "hermetic_task.hermetic",
            ["registry-rhoai-stage.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert len(result["matching_entries"]) == 0
        assert len(result["covered_components"]) == 0

    def test_handles_missing_exception_file(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()

        result = mod.search_self_service_exceptions(
            "test.rule",
            ["nonexistent-file.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert len(result["matching_entries"]) == 0

    def test_handles_missing_exceptions_dir(self, tmp_path):
        result = mod.search_self_service_exceptions(
            "test.rule",
            ["some-file.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is False

    def test_cross_references_imageref_with_csv(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "fbc-rhoai-prod.yaml").write_text(textwrap.dedent("""\
            ---
            - value: test.no_failed_tests:fbc-target-index-pruning-check
              imageRef: sha256:abc123
            - value: test.no_failed_tests:fbc-target-index-pruning-check
              imageRef: sha256:def456
        """))

        csv_content = textwrap.dedent("""\
            type,component_name,image,code
            violation,rhoai-fbc-fragment-v3-5,quay.io/rhoai/fbc@sha256:abc123,test.no_failed_tests
            violation,other-component-v3-5,quay.io/rhoai/other@sha256:ghi789,test.no_failed_tests
        """)
        csv_file = tmp_path / "report.csv"
        csv_file.write_text(csv_content)

        result = mod.search_self_service_exceptions(
            "test.no_failed_tests",
            ["fbc-rhoai-prod.yaml"],
            clone_dir=str(tmp_path),
            csv_path=str(csv_file),
        )
        assert result["checked"] is True
        assert "rhoai-fbc-fragment-v3-5" in result["covered_components"]
        assert "other-component-v3-5" not in result["covered_components"]

    def test_respects_component_names_scoping(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "registry-rhoai-stage.yaml").write_text(textwrap.dedent("""\
            ---
            - value: hermetic_task.hermetic
              componentNames:
                - odh-dashboard-v3-5-ea-2
                - odh-notebook-v3-5-ea-2
              effectiveUntil: "2099-01-01T00:00:00Z"
        """))

        result = mod.search_self_service_exceptions(
            "hermetic_task.hermetic",
            ["registry-rhoai-stage.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert "odh-dashboard-v3-5-ea-2" in result["covered_components"]
        assert "odh-notebook-v3-5-ea-2" in result["covered_components"]

    def test_excludes_expired_entries(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "registry-rhoai-stage.yaml").write_text(textwrap.dedent("""\
            ---
            - value: hermetic_task.hermetic
              effectiveUntil: "2020-01-01T00:00:00Z"
        """))

        result = mod.search_self_service_exceptions(
            "hermetic_task.hermetic",
            ["registry-rhoai-stage.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert len(result["matching_entries"]) == 0

    def test_unscoped_entry_marks_has_unscoped(self, tmp_path):
        exc_dir = tmp_path / "exceptions"
        exc_dir.mkdir()
        (exc_dir / "registry-rhoai-stage.yaml").write_text(textwrap.dedent("""\
            ---
            - value: schedule.weekday_restriction
        """))

        result = mod.search_self_service_exceptions(
            "schedule.weekday_restriction",
            ["registry-rhoai-stage.yaml"],
            clone_dir=str(tmp_path),
        )
        assert result["checked"] is True
        assert result["has_unscoped"] is True
