"""Tests for conforma-exception create_gitlab_mr.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import create_gitlab_mr as mod

TEST_CONFORMA_POLICY_DIR = "config/test-cluster.example.p1/product/EnterpriseContractPolicy"

RHOAI_CONFORMA_FILES = [
    "fbc-rhoai-prod.yaml",
    "fbc-rhoai-stage.yaml",
    "registry-rhoai-prod.yaml",
    "registry-rhoai-stage.yaml",
]

MULTI_PRODUCT_CONFORMA_FILES = [
    "fbc-rhoai-prod.yaml",
    "fbc-rhoai-stage.yaml",
    "registry-ai-containers-preview-prod.yaml",
    "registry-ai-containers-prod.yaml",
    "registry-rhoai-chart-prod.yaml",
    "registry-rhoai-prod.yaml",
    "registry-rhoai-stage.yaml",
]

RHOAI_SELF_SERVICE_FILES = [
    "fbc-rhoai-prod.yaml",
    "fbc-rhoai-stage.yaml",
    "registry-rhoai-prod.yaml",
    "registry-rhoai-stage.yaml",
]


@pytest.fixture(autouse=True)
def _patch_conforma_policy_dir(monkeypatch):
    monkeypatch.setattr(mod, "_CONFORMA_POLICY_DIR", TEST_CONFORMA_POLICY_DIR)
    monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", TEST_CONFORMA_POLICY_DIR)
    monkeypatch.setenv("KONFLUX_APPLICATION_SLUG", "rhoai")
    monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_FILES", ",".join(RHOAI_CONFORMA_FILES))
    monkeypatch.setenv("KONFLUX_SELF_SERVICE_FILES", ",".join(RHOAI_SELF_SERVICE_FILES))


SAMPLE_POLICY_CONTENT = """\
apiVersion: enterprisecontract.io/v1alpha1
kind: EnterpriseContractPolicy
spec:
  configuration:
    volatileCriteria:
          # https://issues.redhat.com/browse/RHOAIENG-100
          # impacted versions: rhoai-3.4
          - value: hermetic_task.hermetic
            componentNames:
              - odh-dashboard-v3-4
              - odh-model-v3-4
            effectiveUntil: "2026-12-01T00:00:00Z"
            reference: https://issues.redhat.com/browse/PSX-1
          # impacted versions: rhoai-3.3
          - value: rpm_signature.allowed:abc123
            effectiveUntil: "2025-06-01T00:00:00Z"
            reference: https://issues.redhat.com/browse/PSX-2
"""


class TestDetectComponentType:
    def test_fbc_in_component_name(self):
        assert mod.detect_component_type(["odh-fbc-v3-4"]) == "fbc"

    def test_fbc_case_insensitive(self):
        assert mod.detect_component_type(["my-FBC-component-v3-4"]) == "fbc"

    def test_registry_when_no_fbc(self):
        assert mod.detect_component_type(["odh-dashboard-v3-4", "odh-model-v3-4"]) == "registry"

    def test_empty_list_defaults_registry(self):
        assert mod.detect_component_type([]) == "registry"


class TestGetTargetFile:
    def test_registry_prod_policy_path(self):
        path = mod.get_target_file("registry", "prod", is_self_service=False)
        assert path.endswith("registry-rhoai-prod.yaml")
        assert "EnterpriseContractPolicy" in path

    def test_fbc_stage_policy_path(self):
        path = mod.get_target_file("fbc", "stage", is_self_service=False)
        assert path.endswith("fbc-rhoai-stage.yaml")

    def test_self_service_registry_prod(self):
        path = mod.get_target_file("registry", "prod", is_self_service=True)
        assert path == "exceptions/registry-rhoai-prod.yaml"

    def test_self_service_fbc_stage(self):
        path = mod.get_target_file("fbc", "stage", is_self_service=True)
        assert path == "exceptions/fbc-rhoai-stage.yaml"

    def test_unknown_type_falls_back_to_glob(self, monkeypatch):
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_FILES", raising=False)
        policy = mod.get_target_file("unknown", "unknown", is_self_service=False)
        assert "unknown-*-unknown.yaml" in policy


class TestApplicationSlugFiltering:
    """Application slug must disambiguate when multiple apps share the EC dir."""

    def test_app_slug_selects_rhoai(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_FILES", ",".join(MULTI_PRODUCT_CONFORMA_FILES))
        monkeypatch.setenv("KONFLUX_APPLICATION_SLUG", "rhoai")
        path = mod.get_target_file("registry", "prod", is_self_service=False)
        assert path.endswith("registry-rhoai-prod.yaml")

    def test_app_slug_selects_ai_containers_preview(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_FILES", ",".join(MULTI_PRODUCT_CONFORMA_FILES))
        monkeypatch.setenv("KONFLUX_APPLICATION_SLUG", "ai-containers-preview")
        path = mod.get_target_file("registry", "prod", is_self_service=False)
        assert path.endswith("registry-ai-containers-preview-prod.yaml")

    def test_ambiguous_raises_without_app_slug(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_FILES", ",".join(MULTI_PRODUCT_CONFORMA_FILES))
        monkeypatch.delenv("KONFLUX_APPLICATION_SLUG", raising=False)
        with pytest.raises(mod.AmbiguousPolicyFileError) as exc_info:
            mod.get_target_file("registry", "prod", is_self_service=False)
        assert "registry-ai-containers-preview-prod.yaml" in exc_info.value.candidates
        assert "registry-rhoai-prod.yaml" in exc_info.value.candidates

    def test_single_match_works_without_app_slug(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_FILES", ",".join(RHOAI_CONFORMA_FILES))
        monkeypatch.delenv("KONFLUX_APPLICATION_SLUG", raising=False)
        path = mod.get_target_file("registry", "prod", is_self_service=False)
        assert path.endswith("registry-rhoai-prod.yaml")

    def test_fbc_unambiguous_with_app_slug(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_FILES", ",".join(MULTI_PRODUCT_CONFORMA_FILES))
        monkeypatch.setenv("KONFLUX_APPLICATION_SLUG", "rhoai")
        path = mod.get_target_file("fbc", "prod", is_self_service=False)
        assert path.endswith("fbc-rhoai-prod.yaml")


class TestGenerateExceptionYaml:
    def test_self_service_with_components(self):
        block = mod.generate_exception_yaml(
            rule="hermetic_task.hermetic",
            components=["odh-dashboard-v3-4"],
            effective_until="2026-12-01T00:00:00Z",
            reference_url="https://issues.redhat.com/browse/PSX-1",
            rhoaieng_url=None,
            rhoai_version="rhoai-3.4",
            is_self_service=True,
        )
        assert block == (
            "- value: hermetic_task.hermetic\n"
            "  componentNames:\n"
            "    - odh-dashboard-v3-4\n"
            '  effectiveUntil: "2026-12-01T00:00:00Z"\n'
        )

    def test_self_service_weekday_restriction(self):
        block = mod.generate_exception_yaml(
            rule="schedule.weekday_restriction",
            components=[],
            effective_until="",
            reference_url="",
            rhoaieng_url=None,
            rhoai_version="rhoai-3.4",
            is_self_service=True,
            is_weekday_restriction=True,
            image_ref="sha256:abc123",
        )
        assert block == "- value: schedule.weekday_restriction\n  imageRef: sha256:abc123\n"

    def test_policy_file_block_with_comments(self):
        block = mod.generate_exception_yaml(
            rule="hermetic_task.hermetic",
            components=["odh-dashboard-v3-4"],
            effective_until="2026-12-01T00:00:00Z",
            reference_url="https://issues.redhat.com/browse/PSX-1",
            rhoaieng_url="https://issues.redhat.com/browse/RHOAIENG-1",
            rhoai_version="rhoai-3.4",
            is_self_service=False,
            reference_title="PSX ticket",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/abc",
        )
        assert "          # https://issues.redhat.com/browse/RHOAIENG-1" in block
        assert "          # impacted versions: rhoai-3.4" in block
        assert "          # spreadsheet: https://docs.google.com/spreadsheets/d/abc" in block
        assert "          - value: hermetic_task.hermetic" in block
        assert "          reference: https://issues.redhat.com/browse/PSX-1  # PSX ticket" in block


class TestFindExistingExceptions:
    def test_finds_component_scoped_block(self):
        blocks = mod._find_existing_exceptions(SAMPLE_POLICY_CONTENT, "hermetic_task.hermetic")
        assert len(blocks) == 1
        block = blocks[0]
        assert block["has_component_names"] is True
        assert block["component_names"] == ["odh-dashboard-v3-4", "odh-model-v3-4"]
        assert block["effective_until_value"] == "2026-12-01T00:00:00Z"

    def test_finds_old_style_unscoped_block(self):
        blocks = mod._find_existing_exceptions(SAMPLE_POLICY_CONTENT, "rpm_signature.allowed:abc123")
        assert len(blocks) == 1
        block = blocks[0]
        assert block["has_component_names"] is False
        assert block["component_names"] == []
        assert block["effective_until_value"] == "2025-06-01T00:00:00Z"

    def test_returns_empty_for_unknown_rule(self):
        assert mod._find_existing_exceptions(SAMPLE_POLICY_CONTENT, "unknown.rule") == []


class TestApplyExceptionToPolicyFile:
    def test_appends_when_no_existing_exception(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text("header:\n  volatileCriteria:\n", encoding="utf-8")
        yaml_block = mod.generate_exception_yaml(
            rule="trusted_task.trusted",
            components=["odh-model-v3-4"],
            effective_until="2027-01-01T00:00:00Z",
            reference_url="https://issues.redhat.com/browse/PSX-9",
            rhoaieng_url=None,
            rhoai_version="rhoai-3.4",
            is_self_service=False,
        )

        result = mod.apply_exception_to_policy_file(
            file_path=policy_file,
            yaml_block=yaml_block,
            is_self_service=False,
            rule="trusted_task.trusted",
            components=["odh-model-v3-4"],
            effective_until="2027-01-01T00:00:00Z",
        )

        assert result["action"] == "appended"
        content = policy_file.read_text(encoding="utf-8")
        assert "trusted_task.trusted" in content
        assert "odh-model-v3-4" in content

    def test_extends_matching_component_names(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(SAMPLE_POLICY_CONTENT, encoding="utf-8")
        yaml_block = mod.generate_exception_yaml(
            rule="hermetic_task.hermetic",
            components=["odh-dashboard-v3-4", "odh-model-v3-4"],
            effective_until="2027-06-01T00:00:00Z",
            reference_url="https://issues.redhat.com/browse/PSX-1",
            rhoaieng_url="https://issues.redhat.com/browse/RHOAIENG-100",
            rhoai_version="rhoai-3.4",
            is_self_service=False,
        )

        result = mod.apply_exception_to_policy_file(
            file_path=policy_file,
            yaml_block=yaml_block,
            is_self_service=False,
            rule="hermetic_task.hermetic",
            components=["odh-dashboard-v3-4", "odh-model-v3-4"],
            effective_until="2027-06-01T00:00:00Z",
        )

        assert result["action"] == "extended"
        content = policy_file.read_text(encoding="utf-8")
        assert 'effectiveUntil: "2027-06-01T00:00:00Z"' in content
        assert 'effectiveUntil: "2026-12-01T00:00:00Z"' not in content

    def test_appends_new_style_when_old_style_exists(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(SAMPLE_POLICY_CONTENT, encoding="utf-8")
        yaml_block = mod.generate_exception_yaml(
            rule="rpm_signature.allowed:abc123",
            components=["odh-operator-v3-3"],
            effective_until="2027-01-01T00:00:00Z",
            reference_url="https://issues.redhat.com/browse/PSX-3",
            rhoaieng_url=None,
            rhoai_version="rhoai-3.3",
            is_self_service=False,
        )

        result = mod.apply_exception_to_policy_file(
            file_path=policy_file,
            yaml_block=yaml_block,
            is_self_service=False,
            rule="rpm_signature.allowed:abc123",
            components=["odh-operator-v3-3"],
            effective_until="2027-01-01T00:00:00Z",
        )

        assert result["action"] == "appended_new_style"
        content = policy_file.read_text(encoding="utf-8")
        assert content.count("rpm_signature.allowed:abc123") == 2
        assert "odh-operator-v3-3" in content

    def test_self_service_append(self, tmp_path):
        policy_file = tmp_path / "exceptions.yaml"
        policy_file.write_text("---\n", encoding="utf-8")
        yaml_block = mod.generate_exception_yaml(
            rule="hermetic_task.hermetic",
            components=["odh-dashboard-v3-4"],
            effective_until="2026-12-01T00:00:00Z",
            reference_url="",
            rhoaieng_url=None,
            rhoai_version="rhoai-3.4",
            is_self_service=True,
        )

        result = mod.apply_exception_to_policy_file(
            file_path=policy_file,
            yaml_block=yaml_block,
            is_self_service=True,
            rule="hermetic_task.hermetic",
            components=["odh-dashboard-v3-4"],
            effective_until="2026-12-01T00:00:00Z",
        )

        assert result["action"] == "appended"
        content = policy_file.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "- value: hermetic_task.hermetic" in content


class TestRemoveExceptionFromPolicyFile:
    def test_removes_scoped_exception_with_comments(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(SAMPLE_POLICY_CONTENT, encoding="utf-8")

        result = mod.remove_exception_from_policy_file(
            file_path=policy_file,
            rule="hermetic_task.hermetic",
            effective_until="2026-12-01T00:00:00Z",
            components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["action"] == "removed"
        assert result["lines_removed"] > 0
        content = policy_file.read_text(encoding="utf-8")
        assert "hermetic_task.hermetic" not in content
        assert "RHOAIENG-100" not in content
        assert "rpm_signature.allowed:abc123" in content

    def test_removes_unscoped_exception(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(SAMPLE_POLICY_CONTENT, encoding="utf-8")

        result = mod.remove_exception_from_policy_file(
            file_path=policy_file,
            rule="rpm_signature.allowed:abc123",
            effective_until="2025-06-01T00:00:00Z",
            components=None,
        )

        assert result["action"] == "removed"
        content = policy_file.read_text(encoding="utf-8")
        assert "rpm_signature.allowed:abc123" not in content
        assert "hermetic_task.hermetic" in content

    def test_not_found_when_no_match(self, tmp_path):
        policy_file = tmp_path / "policy.yaml"
        policy_file.write_text(SAMPLE_POLICY_CONTENT, encoding="utf-8")

        result = mod.remove_exception_from_policy_file(
            file_path=policy_file,
            rule="hermetic_task.hermetic",
            effective_until="2099-01-01T00:00:00Z",
            components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["action"] == "not_found"
        assert "No matching exception block found" in result["detail"]


class TestMrTitleEnvPrefix:
    """Tests for [prod]/[stage] prefix in MR titles."""

    def test_prod_prefix(self):
        title = mod._build_mr_title("hermetic_task.hermetic", "rhoai-3.3", environment="prod")
        assert title.startswith("[prod] [RHOAI]")

    def test_stage_prefix(self):
        title = mod._build_mr_title("hermetic_task.hermetic", "rhoai-3.3", environment="stage")
        assert title.startswith("[stage] [RHOAI]")

    def test_vendor_tag_with_env_prefix(self):
        title = mod._build_mr_title("rpm_signature.allowed:abc", "rhoai-3.4", vendor_tag="AMD", environment="prod")
        assert title.startswith("[AMD] [prod]")

    def test_consolidated_prod_prefix(self):
        specs = [{"version": "rhoai-3.3"}, {"version": "rhoai-3.4"}]
        title = mod._build_mr_title_consolidated("hermetic_task.hermetic", specs, environment="prod")
        assert title.startswith("[prod] [RHOAI]")

    def test_consolidated_stage_prefix(self):
        specs = [{"version": "rhoai-3.3"}]
        title = mod._build_mr_title_consolidated("hermetic_task.hermetic", specs, environment="stage")
        assert title.startswith("[stage] [RHOAI]")


class TestSyncMrDescription:
    """_sync_mr_description must update title + description on the open MR."""

    @patch("create_gitlab_mr.gitlab_ops")
    def test_updates_existing_mr(self, mock_ops):
        mock_ops.find_mr.return_value = [
            {"mr_iid": 42, "mr_url": "https://gitlab.example.com/mr/42"}
        ]
        mock_ops.update_mr.return_value = {
            "mr_url": "https://gitlab.example.com/mr/42"
        }

        result = mod._sync_mr_description(
            "my-branch", "New Title", "New body text"
        )

        mock_ops.find_mr.assert_called_once_with(
            mod.GITLAB_PROJECT, source_branch="my-branch", state="opened"
        )
        mock_ops.update_mr.assert_called_once_with(
            mod.GITLAB_PROJECT, 42, title="New Title", description="New body text"
        )
        assert result == {"mr_url": "https://gitlab.example.com/mr/42"}

    @patch("create_gitlab_mr.gitlab_ops")
    def test_returns_none_when_no_mr_found(self, mock_ops):
        mock_ops.find_mr.return_value = []

        result = mod._sync_mr_description(
            "nonexistent-branch", "Title", "Body"
        )

        assert result is None
        mock_ops.update_mr.assert_not_called()

    @patch("create_gitlab_mr.gitlab_ops")
    def test_returns_none_when_find_mr_errors(self, mock_ops):
        mock_ops.find_mr.return_value = [{"error": "API failure"}]

        result = mod._sync_mr_description(
            "my-branch", "Title", "Body"
        )

        assert result is None
        mock_ops.update_mr.assert_not_called()


class TestMrBodyContent:
    """MR body builders must include all version/component details."""

    def test_consolidated_body_lists_all_versions(self):
        specs = [
            {"version": "rhoai-3.3", "components": ["comp-v3-3"], "effective_until": "2026-10-01T00:00:00Z"},
            {"version": "rhoai-3.4", "components": ["comp-v3-4"], "effective_until": "2026-08-01T00:00:00Z"},
            {"version": "rhoai-3.5-ea.1", "components": ["comp-v3-5-ea-1"], "effective_until": "2026-10-05T00:00:00Z"},
        ]
        body = mod._build_mr_body_consolidated(
            rule="rpm_signature.allowed:abc",
            version_specs=specs,
            target_file="config/test/registry-rhoai-prod.yaml",
        )
        assert "`rhoai-3.3`" in body
        assert "`rhoai-3.4`" in body
        assert "`rhoai-3.5-ea.1`" in body
        assert "`comp-v3-3`" in body
        assert "`comp-v3-4`" in body
        assert "`comp-v3-5-ea-1`" in body
        assert "2026-10-05T00:00:00Z" in body

    def test_single_body_includes_components(self):
        body = mod._build_mr_body(
            rule="hermetic_task.hermetic",
            components=["dash-v3-4", "model-v3-4"],
            rhoai_version="rhoai-3.4",
            effective_until="2026-12-01T00:00:00Z",
            target_file="config/test/registry-rhoai-prod.yaml",
        )
        assert "`dash-v3-4`" in body
        assert "`model-v3-4`" in body
        assert "`rhoai-3.4`" in body


class TestValidateRepoRelativePath:
    """_validate_repo_relative_path rejects traversal and absolute paths."""

    def test_normal_relative_path_passes(self):
        result = mod._validate_repo_relative_path("config/cluster/product/registry-rhoai-prod.yaml")
        assert result == "config/cluster/product/registry-rhoai-prod.yaml"

    def test_normalizes_redundant_separators(self):
        result = mod._validate_repo_relative_path("config//cluster///file.yaml")
        assert result == "config/cluster/file.yaml"

    def test_normalizes_safe_dotdot(self):
        result = mod._validate_repo_relative_path("config/a/../b/file.yaml")
        assert result == "config/b/file.yaml"

    def test_rejects_absolute_path(self):
        with pytest.raises(ValueError, match="not repo-relative"):
            mod._validate_repo_relative_path("/etc/passwd")

    def test_rejects_dotdot_escaping_root(self):
        with pytest.raises(ValueError, match="not repo-relative"):
            mod._validate_repo_relative_path("../../etc/passwd")

    def test_rejects_deep_traversal(self):
        with pytest.raises(ValueError, match="not repo-relative"):
            mod._validate_repo_relative_path("config/../../etc/passwd")

    def test_rejects_bare_dotdot(self):
        with pytest.raises(ValueError, match="not repo-relative"):
            mod._validate_repo_relative_path("..")

    def test_exceptions_dir_passes(self):
        result = mod._validate_repo_relative_path("exceptions/registry-rhoai-prod.yaml")
        assert result == "exceptions/registry-rhoai-prod.yaml"

    def test_dot_path_passes(self):
        result = mod._validate_repo_relative_path("./config/file.yaml")
        assert result == "config/file.yaml"


class TestGetTargetFilePathValidation:
    """get_target_file validates the resolved path."""

    def test_rejects_traversal_in_policy_dir(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "/etc/evil")
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_FILES", raising=False)
        with pytest.raises(ValueError, match="not repo-relative"):
            mod.get_target_file("registry", "prod", is_self_service=False)

    def test_rejects_dotdot_in_policy_dir(self, monkeypatch):
        monkeypatch.setenv("KONFLUX_CONFORMA_POLICY_DIR", "../../etc")
        monkeypatch.delenv("KONFLUX_CONFORMA_POLICY_FILES", raising=False)
        with pytest.raises(ValueError, match="not repo-relative"):
            mod.get_target_file("registry", "prod", is_self_service=False)
