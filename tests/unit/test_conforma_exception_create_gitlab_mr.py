"""Tests for conforma-exception create_gitlab_mr.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import create_gitlab_mr as mod

TEST_EC_POLICY_DIR = "config/test-cluster.example.p1/product/EnterpriseContractPolicy"


@pytest.fixture(autouse=True)
def _patch_ec_policy_dir():
    with patch.object(mod, "_EC_POLICY_DIR", TEST_EC_POLICY_DIR):
        with patch.object(
            mod,
            "POLICY_PATHS",
            {
                ("registry", "prod"): f"{TEST_EC_POLICY_DIR}/registry-rhoai-prod.yaml",
                ("registry", "stage"): f"{TEST_EC_POLICY_DIR}/registry-rhoai-stage.yaml",
                ("fbc", "prod"): f"{TEST_EC_POLICY_DIR}/fbc-rhoai-prod.yaml",
                ("fbc", "stage"): f"{TEST_EC_POLICY_DIR}/fbc-rhoai-stage.yaml",
            },
        ):
            yield


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

    def test_unknown_key_falls_back(self):
        policy = mod.get_target_file("unknown", "unknown", is_self_service=False)
        assert policy.endswith("registry-rhoai-prod.yaml")
        self_service = mod.get_target_file("unknown", "unknown", is_self_service=True)
        assert self_service == "exceptions/fbc-rhoai-prod.yaml"


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
