"""Tests for conforma_mr_ops.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import conforma_mr_ops as mod


class TestEnsureGitlabEnv:
    """Tests for _ensure_gitlab_env using gitlab_ops.discover_token."""

    @patch("conforma_mr_ops.gitlab_ops.discover_token", return_value="glpat-test-token")
    def test_sets_token_when_missing(self, mock_discover, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mod._ensure_gitlab_env()
        mock_discover.assert_called_once()
        assert mod.os.environ.get("GITLAB_TOKEN") == "glpat-test-token"
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    @patch("conforma_mr_ops.gitlab_ops.discover_token")
    def test_skips_when_token_already_set(self, mock_discover, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "existing-token")
        mod._ensure_gitlab_env()
        mock_discover.assert_not_called()
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)

    @patch("conforma_mr_ops.gitlab_ops.discover_token", return_value=None)
    def test_no_op_when_discover_returns_none(self, mock_discover, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        mod._ensure_gitlab_env()
        mock_discover.assert_called_once()
        assert mod.os.environ.get("GITLAB_TOKEN") is None


class TestImageUrlCoversComponent:
    def test_rhel9_image_covers_versioned_component(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-dashboard-rhel9",
            "odh-dashboard-v3-4",
        )

    def test_ubi9_image_covers_ea_component(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-vllm-cpu-ubi9",
            "odh-vllm-cpu-v3-5-ea-1",
        )

    def test_different_base_names_do_not_match(self):
        assert not mod.image_url_covers_component(
            "quay.io/rhoai/odh-dashboard-rhel9",
            "odh-modelmesh-v3-4",
        )

    def test_same_base_different_versions(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-mlmd-grpc-server-rhel9",
            "odh-mlmd-grpc-server-v2-25",
        )


class TestExtractImageBase:
    def test_strips_rhel_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-dashboard-rhel9") == "odh-dashboard"

    def test_strips_ubi_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-vllm-cpu-ubi9") == "odh-vllm-cpu"

    def test_no_suffix(self):
        assert mod._extract_image_base("quay.io/rhoai/odh-dashboard") == "odh-dashboard"


class TestExtractComponentBase:
    def test_strips_version(self):
        assert mod._extract_component_base("odh-dashboard-v3-4") == "odh-dashboard"

    def test_strips_ea_version(self):
        assert mod._extract_component_base("odh-vllm-cpu-v3-5-ea-1") == "odh-vllm-cpu"

    def test_no_version(self):
        assert mod._extract_component_base("odh-dashboard") == "odh-dashboard"


class TestAnalyzeMrComponentCoverage:
    def setup_method(self):
        mod._mr_cache._diffs.clear()

    def test_fully_covered_from_prefetched_diff(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - odh-dashboard-v3-4\n"
            "+              - odh-model-v3-4\n"
        )
        mod._mr_cache.store(
            42,
            [
                {
                    "new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml",
                    "diff": diff,
                }
            ],
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=42,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["source"] == "diff"
        assert result["suggestion"] == "fully_covered"
        assert result["covered"] == ["odh-dashboard-v3-4", "odh-model-v3-4"]
        assert result["missing"] == []

    def test_extend_mr_when_partial_overlap_from_diff(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - odh-dashboard-v3-4\n"
        )
        mod._mr_cache.store(
            7,
            [
                {
                    "new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml",
                    "diff": diff,
                }
            ],
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=7,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["suggestion"] == "extend_mr"
        assert result["covered"] == ["odh-dashboard-v3-4"]
        assert result["missing"] == ["odh-model-v3-4"]

    def test_falls_back_to_description_when_diff_empty(self):
        description = (
            "## Exception: `trusted_task.trusted` for `rhoai-3.4`\n\n"
            "### Components\n"
            "- `odh-modelmesh-v3-4`\n"
            "- `odh-dashboard-v3-4`\n"
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=99,
            rule="trusted_task.trusted",
            requested_components=["odh-dashboard-v3-4"],
            mr_description=description,
        )

        assert result["source"] == "description"
        assert result["suggestion"] == "fully_covered"
        assert "odh-dashboard-v3-4" in result["covered"]

    def test_no_overlap_when_diff_and_description_missing(self):
        result = mod.analyze_mr_component_coverage(
            mr_iid=1,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4"],
        )
        assert result["suggestion"] == "no_overlap"
        assert result["source"] == "none"
        assert result["missing"] == ["odh-dashboard-v3-4"]

    @patch("cli_runner.run_glab")
    def test_fetches_diff_on_demand_when_not_cached(self, mock_run_glab):
        mock_run_glab.return_value = MagicMock(
            returncode=0,
            stdout=(
                '{"changes": [{"new_path": "exceptions/registry-rhoai-prod.yaml", '
                '"diff": "+- value: schedule.weekday_restriction\\n'
                '+  componentNames:\\n+    - odh-operator-v3-4\\n"}]}'
            ),
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=55,
            rule="schedule.weekday_restriction",
            requested_components=["odh-operator-v3-4"],
        )

        mock_run_glab.assert_called_once()
        assert result["source"] == "diff"
        assert result["suggestion"] == "fully_covered"
        assert mod._mr_cache.has(55)


class TestParseComponentsFromDiff:
    def test_quoted_rule_value(self):
        diff = '+          - value: "hermetic_task.hermetic"\n+            componentNames:\n+              - comp-a\n'
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == ["comp-a"]

    def test_multiple_components(self):
        diff = (
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - comp-a\n"
            "+              - comp-b\n"
        )
        result = mod._parse_components_from_diff(diff, "hermetic_task.hermetic")
        assert result == ["comp-a", "comp-b"]


class TestParseComponentsFromDescription:
    def test_single_version_format(self):
        desc = "### Components\n- `odh-dashboard-v3-4`\n- `odh-modelmesh-v3-4`\n"
        result = mod._parse_components_from_description(desc)
        assert "odh-dashboard-v3-4" in result
        assert "odh-modelmesh-v3-4" in result

    def test_multi_version_format(self):
        desc = "### `rhoai-3.4`\n**Components**:\n- `odh-dashboard-v3-4`\n"
        result = mod._parse_components_from_description(desc)
        assert "odh-dashboard-v3-4" in result
