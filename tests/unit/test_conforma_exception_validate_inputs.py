"""Tests for conforma-exception validate_inputs.py."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import validate_inputs
from validate_inputs import RhoaiVersion


class TestParseRhoaiVersion:
    def test_rhoai_prefix(self):
        v = validate_inputs.parse_rhoai_version("rhoai-3.5")
        assert v == RhoaiVersion(3, 5, "", 0)
        assert str(v) == "rhoai-3.5"

    def test_ea_qualifier(self):
        v = validate_inputs.parse_rhoai_version("rhoai-3.5-ea.1")
        assert v == RhoaiVersion(3, 5, "ea", 1)
        assert str(v) == "rhoai-3.5-ea.1"
        assert v.to_component_suffix() == "v3-5-ea-1"

    def test_without_prefix(self):
        v = validate_inputs.parse_rhoai_version("3.4")
        assert v == RhoaiVersion(3, 4, "", 0)

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid RHOAI version format"):
            validate_inputs.parse_rhoai_version("not-a-version")


class TestVersionGteThreshold:
    def test_below_threshold(self):
        assert validate_inputs.version_gte_threshold(RhoaiVersion(3, 4, "", 0)) is False

    def test_at_threshold(self):
        assert validate_inputs.version_gte_threshold(RhoaiVersion(3, 5, "ea", 1)) is True

    def test_above_threshold(self):
        assert validate_inputs.version_gte_threshold(RhoaiVersion(3, 5, "ea", 2)) is True
        assert validate_inputs.version_gte_threshold(RhoaiVersion(3, 6, "", 0)) is True

    def test_35_without_qualifier_meets_threshold(self):
        # Empty qualifier is treated as "z" (GA), which is >= ea.1 at same major.minor
        assert validate_inputs.version_gte_threshold(RhoaiVersion(3, 5, "", 0)) is True


class TestCheckImageNameVsComponentName:
    def test_rhel_suffix_without_version(self):
        err = validate_inputs.check_image_name_vs_component_name("odh-mlflow-rhel9")
        assert err is not None
        assert "container image name" in err

    def test_ubi_suffix_without_version(self):
        err = validate_inputs.check_image_name_vs_component_name("odh-dashboard-ubi9")
        assert err is not None
        assert "container image name" in err

    def test_valid_konflux_component(self):
        assert validate_inputs.check_image_name_vs_component_name("odh-mlflow-v3-3") is None

    def test_rhel_with_version_suffix(self):
        assert validate_inputs.check_image_name_vs_component_name("odh-mlflow-v3-3-rhel9") is None


class TestReconcileComponentVersion:
    def test_matching_version(self):
        version = RhoaiVersion(3, 5, "ea", 1)
        assert validate_inputs.reconcile_component_version("odh-mlflow-v3-5-ea-1", version) is None

    def test_mismatched_version(self):
        version = RhoaiVersion(3, 5, "", 0)
        err = validate_inputs.reconcile_component_version("odh-mlflow-v3-4", version)
        assert err is not None
        assert "v3-4" in err
        assert "v3-5" in err

    def test_no_version_in_component(self):
        version = RhoaiVersion(3, 3, "", 0)
        assert validate_inputs.reconcile_component_version("odh-mlflow", version) is None


class TestComputeEffectiveUntil:
    @patch("validate_inputs.datetime")
    def test_future_date_rfc3339(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_dt.strptime = datetime.strptime
        result = validate_inputs.compute_effective_until("2026-06-01")
        assert result == "2026-06-01T00:00:00Z"

    @patch("validate_inputs.datetime")
    def test_eos_buffer_adds_seven_days(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
        mock_dt.strptime = datetime.strptime
        result = validate_inputs.compute_effective_until("2026-06-01", eos_buffer=True)
        assert result == "2026-06-08T00:00:00Z"

    @patch("validate_inputs.datetime")
    def test_past_date_rejected(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 6, 1, tzinfo=timezone.utc)
        mock_dt.strptime = datetime.strptime
        with pytest.raises(ValueError, match="must be a future date"):
            validate_inputs.compute_effective_until("2026-01-01")

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            validate_inputs.compute_effective_until("06-01-2026")


class TestDetectFbc:
    def test_fbc_component_detected(self):
        assert validate_inputs.detect_fbc(["odh-operator-fbc-v3-4"]) is True

    def test_no_fbc(self):
        assert validate_inputs.detect_fbc(["odh-mlflow-v3-3", "odh-dashboard-v3-4"]) is False


class TestDetermineWorkflow:
    def test_hermetic_build_rule(self):
        category_id, workflow = validate_inputs.determine_workflow("hermetic_task.hermetic")
        assert category_id == "hermetic_build"
        assert len(workflow) > 0

    def test_self_service_weekday_rule(self):
        category_id, workflow = validate_inputs.determine_workflow("schedule.weekday_restriction")
        assert category_id == "weekday_restriction"
        assert validate_inputs.workflow_is_self_service(workflow) is True

    def test_unknown_rule_returns_empty(self):
        category_id, workflow = validate_inputs.determine_workflow("totally.unknown.rule.xyz")
        assert category_id == "other"
        assert len(workflow) > 0


class TestWorkflowHelpers:
    @pytest.fixture
    def psx_workflow(self):
        _, workflow = validate_inputs.determine_workflow("hermetic_task.hermetic")
        return workflow

    @pytest.fixture
    def self_service_workflow(self):
        _, workflow = validate_inputs.determine_workflow("schedule.weekday_restriction")
        return workflow

    def test_workflow_has_step(self, psx_workflow):
        assert validate_inputs.workflow_has_step(psx_workflow, "psx_exception_jira") is True
        assert validate_inputs.workflow_has_step(psx_workflow, "nonexistent_step") is False

    def test_workflow_is_self_service(self, psx_workflow, self_service_workflow):
        assert validate_inputs.workflow_is_self_service(psx_workflow) is False
        assert validate_inputs.workflow_is_self_service(self_service_workflow) is True
