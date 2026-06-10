"""Tests for conforma-exception preflight_check.py."""

from __future__ import annotations

import preflight_check as mod


class TestEvaluateDecision:
    def test_proceed_create_new_when_not_checked(self):
        result = mod.evaluate_decision(
            existing_exceptions={"checked": False, "reason": "No local clone"},
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "create_new"

    def test_abort_on_permanent_global_exclusion_in_target_env(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [
                    {
                        "file": "config/.../registry-rhoai-prod.yaml",
                        "line": 10,
                        "type": "permanent_global_exclusion",
                    }
                ],
                "existing_exceptions": [],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is False
        assert result["action"] == "abort"
        assert "permanently excluded" in result["reason"]

    def test_abort_on_permanent_scoped_exception(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": True,
                        "componentNames": ["odh-dashboard-v3-4", "odh-model-v3-4"],
                        "effectiveUntil": None,
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is False
        assert result["action"] == "abort"

    def test_extend_when_matching_component_names_and_effective_until(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": True,
                        "componentNames": ["odh-dashboard-v3-4"],
                        "effectiveUntil": "2026-12-01T00:00:00Z",
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "extend"

    def test_append_new_style_when_old_style_exists(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": False,
                        "componentNames": [],
                        "effectiveUntil": "2026-12-01T00:00:00Z",
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "append_new_style"

    def test_create_new_when_different_component_names(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": True,
                        "componentNames": ["odh-other-v3-4"],
                        "effectiveUntil": "2026-12-01T00:00:00Z",
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "create_new"

    def test_stage_permanent_exclusion_does_not_block_prod(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [
                    {
                        "file": "config/.../registry-rhoai-stage.yaml",
                        "line": 5,
                    }
                ],
                "existing_exceptions": [],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "create_new"
