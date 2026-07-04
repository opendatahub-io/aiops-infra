"""Tests for manage_exceptions.py -- fuzzy matching and exception search."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import conforma_context_ops
import manage_exceptions as mod


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_strips_hyphens(self):
        assert mod._normalize_name("nemo-guardrails") == "nemoguardrails"

    def test_strips_underscores(self):
        assert mod._normalize_name("nemo_guardrails") == "nemoguardrails"

    def test_mixed_separators(self):
        assert mod._normalize_name("odh-nemo_guard-rails") == "odhnemoguardrails"

    def test_already_clean(self):
        assert mod._normalize_name("mlflow") == "mlflow"

    def test_uppercased(self):
        assert mod._normalize_name("ODH-Dashboard") == "odhdashboard"


# ---------------------------------------------------------------------------
# _strip_version_suffix
# ---------------------------------------------------------------------------


class TestStripVersionSuffix:
    def test_simple_version(self):
        assert mod._strip_version_suffix("odh-dashboard-v3-4") == "odh-dashboard"

    def test_ea_version(self):
        assert mod._strip_version_suffix("odh-vllm-v3-5-ea-1") == "odh-vllm"

    def test_no_version(self):
        assert mod._strip_version_suffix("odh-dashboard") == "odh-dashboard"

    def test_bare_name(self):
        assert mod._strip_version_suffix("mlflow") == "mlflow"


# ---------------------------------------------------------------------------
# _extract_image_base
# ---------------------------------------------------------------------------


class TestExtractImageBase:
    def test_strips_rhel_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-dashboard-rhel9") == "odh-dashboard"

    def test_strips_ubi_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-vllm-ubi8") == "odh-vllm"

    def test_no_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-mlflow") == "odh-mlflow"

    def test_bare_name(self):
        assert mod._extract_image_base("odh-dashboard-rhel9") == "odh-dashboard"


# ---------------------------------------------------------------------------
# _fuzzy_component_match
# ---------------------------------------------------------------------------


class TestFuzzyComponentMatch:
    def test_exact_match(self):
        assert mod._fuzzy_component_match("odh-mlflow", "odh-mlflow")

    def test_hyphen_vs_underscore(self):
        assert mod._fuzzy_component_match("nemo-guardrails", "odh-nemo_guardrails-v3-5-ea-1")

    def test_no_separator(self):
        assert mod._fuzzy_component_match("nemoguardrails", "odh-nemo-guardrails-v3-4")

    def test_with_version_suffix(self):
        assert mod._fuzzy_component_match("mlflow", "odh-mlflow-v3-3")

    def test_with_odh_prefix(self):
        assert mod._fuzzy_component_match("mlflow", "odh-mlflow-v3-3")

    def test_with_rhoai_prefix(self):
        assert mod._fuzzy_component_match("dashboard", "rhoai-dashboard-v3-4")

    def test_non_match(self):
        assert not mod._fuzzy_component_match("vllm", "odh-mlflow-v3-3")

    def test_partial_substring(self):
        assert mod._fuzzy_component_match("mlmd", "odh-mlmd-grpc-server-v2-25")

    def test_search_term_with_version(self):
        assert mod._fuzzy_component_match("odh-mlflow-v3-3", "odh-mlflow-v3-3")


# ---------------------------------------------------------------------------
# _fuzzy_image_match
# ---------------------------------------------------------------------------


class TestFuzzyImageMatch:
    def test_matches_image_url(self):
        assert mod._fuzzy_image_match("mlflow", "quay.io/rhoai/odh-mlflow-rhel9")

    def test_no_match(self):
        assert not mod._fuzzy_image_match("vllm", "quay.io/rhoai/odh-mlflow-rhel9")

    def test_underscore_in_search(self):
        assert mod._fuzzy_image_match("nemo_guardrails", "quay.io/rhoai/odh-nemo-guardrails-rhel9")


# ---------------------------------------------------------------------------
# scan_permanent_exclusions
# ---------------------------------------------------------------------------


_POLICY_YAML = """\
apiVersion: appstudio.redhat.com/v1alpha1
kind: EnterpriseContractPolicy
spec:
  sources:
    - name: rhoai-registry-prod
      policy:
        - oci::quay.io/conforma/release-policy:konflux
      config:
        include:
          - '@redhat'
        exclude:
          # https://issues.redhat.com/browse/KONFLUX-7113
          - cve.cve_blockers
          # CUDA notebooks, https://issues.redhat.com/browse/RHOAIENG-33412
          - rpm_signature.allowed:9cd0a493d42d0685
      volatileConfig:
        exclude:
          - value: hermetic_task.hermetic
            componentNames:
              - odh-mlflow-v3-3
            effectiveUntil: "2026-10-10T00:00:00Z"
            reference: https://issues.redhat.com/browse/PSX-1089
"""


class TestScanPermanentExclusions:
    def test_finds_permanent_exclusions(self, tmp_path):
        policy_dir = tmp_path / "config" / "stone" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "registry-rhoai-prod.yaml").write_text(_POLICY_YAML)

        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            results = mod.scan_permanent_exclusions(tmp_path, "prod")

        assert len(results) == 2
        assert results[0]["rule"] == "cve.cve_blockers"
        assert results[0]["type"] == "permanent"
        assert results[0]["scope"] == "permanent"
        assert results[0]["reference"] == "https://issues.redhat.com/browse/KONFLUX-7113"
        assert results[1]["rule"] == "rpm_signature.allowed:9cd0a493d42d0685"
        assert results[1]["reference"] == "https://issues.redhat.com/browse/RHOAIENG-33412"

    def test_skips_volatile_section(self, tmp_path):
        policy_dir = tmp_path / "config" / "stone" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "registry-rhoai-prod.yaml").write_text(_POLICY_YAML)

        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            results = mod.scan_permanent_exclusions(tmp_path, "prod")

        rules = [r["rule"] for r in results]
        assert "hermetic_task.hermetic" not in rules

    def test_empty_when_no_policy_files(self, tmp_path):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            results = mod.scan_permanent_exclusions(tmp_path, "prod")
        assert results == []

    def test_filters_by_environment(self, tmp_path):
        policy_dir = tmp_path / "config" / "stone" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "registry-rhoai-stage.yaml").write_text(_POLICY_YAML)

        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            results = mod.scan_permanent_exclusions(tmp_path, "prod")
        assert results == []


# ---------------------------------------------------------------------------
# scan_self_service_exceptions
# ---------------------------------------------------------------------------


class TestScanSelfServiceExceptions:
    def test_parses_flat_yaml_list(self, tmp_path):
        exceptions_dir = tmp_path / "exceptions"
        exceptions_dir.mkdir()
        data = [
            {
                "value": "hermetic_task.hermetic",
                "componentNames": ["odh-mlflow-v3-3"],
                "effectiveUntil": "2026-10-10T00:00:00Z",
                "reference": "https://issues.redhat.com/browse/PSX-1089",
            },
        ]
        (exceptions_dir / "registry-rhoai-prod.yaml").write_text(yaml.dump(data))

        results = mod.scan_self_service_exceptions(tmp_path, "prod")
        assert len(results) == 1
        assert results[0]["rule"] == "hermetic_task.hermetic"
        assert results[0]["scope"] == "component"
        assert results[0]["component_names"] == ["odh-mlflow-v3-3"]
        assert results[0]["type"] == "self-service"

    def test_handles_imageRef(self, tmp_path):
        exceptions_dir = tmp_path / "exceptions"
        exceptions_dir.mkdir()
        data = [{"value": "schedule.weekday_restriction", "imageRef": "sha256:abcdef1234567890"}]
        (exceptions_dir / "fbc-rhoai-prod.yaml").write_text(yaml.dump(data))

        results = mod.scan_self_service_exceptions(tmp_path, "prod")
        assert len(results) == 1
        assert results[0]["scope"] == "unscoped"

    def test_handles_imageUrl(self, tmp_path):
        exceptions_dir = tmp_path / "exceptions"
        exceptions_dir.mkdir()
        data = [
            {
                "value": "hermetic_task.hermetic",
                "imageUrl": "quay.io/rhoai/odh-mlflow-rhel9",
                "effectiveUntil": "2026-10-10T00:00:00Z",
            }
        ]
        (exceptions_dir / "registry-rhoai-prod.yaml").write_text(yaml.dump(data))

        results = mod.scan_self_service_exceptions(tmp_path, "prod")
        assert len(results) == 1
        assert results[0]["scope"] == "image"
        assert results[0]["image_url"] == "quay.io/rhoai/odh-mlflow-rhel9"

    def test_filters_by_environment(self, tmp_path):
        exceptions_dir = tmp_path / "exceptions"
        exceptions_dir.mkdir()
        data = [{"value": "some.rule", "effectiveUntil": "2026-12-01T00:00:00Z"}]
        (exceptions_dir / "registry-rhoai-stage.yaml").write_text(yaml.dump(data))

        results = mod.scan_self_service_exceptions(tmp_path, "prod")
        assert results == []

    def test_skips_missing_dir(self, tmp_path):
        results = mod.scan_self_service_exceptions(tmp_path, "prod")
        assert results == []

    def test_skips_invalid_yaml(self, tmp_path):
        exceptions_dir = tmp_path / "exceptions"
        exceptions_dir.mkdir()
        (exceptions_dir / "registry-rhoai-prod.yaml").write_text("{{invalid yaml")

        results = mod.scan_self_service_exceptions(tmp_path, "prod")
        assert results == []


# ---------------------------------------------------------------------------
# search_exceptions_for_components
# ---------------------------------------------------------------------------


class TestSearchExceptionsForComponents:
    @pytest.fixture()
    def repo_tree(self, tmp_path):
        """Create a minimal repo tree with policy + self-service exception files."""
        policy_dir = tmp_path / "config" / "stone" / "product" / "EnterpriseContractPolicy"
        policy_dir.mkdir(parents=True)
        (policy_dir / "registry-rhoai-prod.yaml").write_text(_POLICY_YAML)

        exceptions_dir = tmp_path / "exceptions"
        exceptions_dir.mkdir()
        ss_data = [
            {
                "value": "test.some_rule",
                "componentNames": ["odh-nemo-guardrails-v3-5"],
                "effectiveUntil": "2026-12-01T00:00:00Z",
                "reference": "https://issues.redhat.com/browse/TEST-1",
            },
        ]
        (exceptions_dir / "registry-rhoai-prod.yaml").write_text(yaml.dump(ss_data))
        return tmp_path

    def test_finds_volatile_by_component(self, repo_tree):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            result = mod.search_exceptions_for_components(
                ["mlflow"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )

        component_matches = [m for m in result["matches"] if m["scope"] == "component"]
        assert any("mlflow" in m.get("matched_search_terms", []) for m in component_matches)

    def test_finds_permanent_always(self, repo_tree):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            result = mod.search_exceptions_for_components(
                ["mlflow"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )

        permanent_matches = [m for m in result["matches"] if m["type"] == "permanent"]
        assert len(permanent_matches) == 2

    def test_finds_self_service_by_component(self, repo_tree):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            result = mod.search_exceptions_for_components(
                ["nemo-guardrails"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )

        ss_matches = [m for m in result["matches"] if m["type"] == "self-service"]
        assert any("nemo-guardrails" in m.get("matched_search_terms", []) for m in ss_matches)

    def test_fuzzy_matches_underscore_hyphen(self, repo_tree):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            result = mod.search_exceptions_for_components(
                ["nemo_guardrails"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )

        ss_matches = [m for m in result["matches"] if m["type"] == "self-service" and m["scope"] == "component"]
        assert len(ss_matches) == 1

    def test_no_match_returns_only_unscoped_and_permanent(self, repo_tree):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            result = mod.search_exceptions_for_components(
                ["nonexistent-component"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )

        for m in result["matches"]:
            assert m["scope"] in ("unscoped", "permanent")

    def test_summary_counts(self, repo_tree):
        with patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"):
            result = mod.search_exceptions_for_components(
                ["mlflow"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )

        summary = result["summary"]
        assert summary["total_matches"] == summary["volatile"] + summary["permanent"] + summary["self_service"]

    def test_refresh_calls_git(self, repo_tree):
        with (
            patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"),
            patch.object(mod, "_refresh_clone") as mock_refresh,
        ):
            mod.search_exceptions_for_components(
                ["mlflow"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=True,
            )
        mock_refresh.assert_called_once_with(repo_tree)

    def test_no_refresh_skips_git(self, repo_tree):
        with (
            patch.object(mod, "_get_conforma_policy_dir", return_value="config/stone/product/EnterpriseContractPolicy"),
            patch.object(mod, "_refresh_clone") as mock_refresh,
        ):
            mod.search_exceptions_for_components(
                ["mlflow"],
                environment="prod",
                clone_dir=repo_tree,
                refresh=False,
            )
        mock_refresh.assert_not_called()


class TestContextIntegration:
    """Tests for context-based parameter discovery in main()."""

    def _setup_run(self, tmp_path):
        """Create a run directory with context.yaml."""
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()

        context = {
            "application": {"release": "rhoai-3.5-ea.2"},
            "environment": "prod",
            "run": {"run_dir": conforma_context_ops.contract_home(run_dir)},
            "steps": {},
        }
        context_path = run_dir / "context.yaml"
        context_path.write_text(yaml.dump(context), encoding="utf-8")

        work_dir = tmp_path / ".conforma"
        work_dir.mkdir(exist_ok=True)
        active_link = work_dir / ".conforma-active"
        active_link.symlink_to(run_dir)

        return run_dir, work_dir

    def test_resolves_environment_from_context(self, tmp_path, monkeypatch):
        """Context-based environment discovery works with --find-expired."""
        run_dir, work_dir = self._setup_run(tmp_path)
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        monkeypatch.setattr("sys.argv", ["manage_exceptions.py", "--find-expired"])

        with patch.object(mod, "_clone_repo", side_effect=Exception("should not clone")):
            with patch.object(mod, "cmd_find_expired", return_value=0) as mock_cmd:
                rc = mod.main()

        assert rc == 0
        called_args = mock_cmd.call_args[0][0]
        assert called_args.environment == "prod"

    def test_no_context_requires_environment(self, tmp_path, monkeypatch):
        """Without context and without --environment, main() exits with error."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        monkeypatch.setattr("sys.argv", ["manage_exceptions.py", "--find-expired"])

        with pytest.raises(SystemExit):
            mod.main()
