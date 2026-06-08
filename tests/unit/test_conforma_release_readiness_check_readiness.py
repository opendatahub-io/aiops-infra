"""Tests for conforma-release-readiness check_readiness.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_readiness",
    _REPO_ROOT / "skills/conforma-release-readiness/scripts/check_readiness.py",
)
check_readiness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_readiness)


@pytest.fixture
def violations_data():
    return {
        "violations_by_rule": {
            "hermetic_task.hermetic": {
                "title": "Hermetic build required",
                "base_code": "hermetic_task.hermetic",
                "releases": {
                    "rhoai-3.4": ["comp-a", "comp-b"],
                    "rhoai-3.5": [],
                },
            },
            "trusted_task.trusted": {
                "title": "Task must be trusted",
                "base_code": "trusted_task.trusted",
                "releases": {
                    "rhoai-3.4": ["comp-c"],
                    "rhoai-3.5": ["comp-d"],
                },
            },
        },
    }


class TestCheckReadiness:
    def test_all_covered_is_ship(self, violations_data):
        exceptions = [
            {
                "rule": "hermetic_task.hermetic",
                "is_expired": False,
                "is_unscoped": True,
                "component_names": [],
                "expires_in_days": 30,
            },
            {
                "rule": "trusted_task.trusted",
                "is_expired": False,
                "is_unscoped": False,
                "component_names": ["comp-c"],
                "expires_in_days": 60,
            },
        ]
        result = check_readiness.check_readiness("rhoai-3.4", violations_data, exceptions)
        assert result["verdict"] == "SHIP"
        assert result["blocking_count"] == 0
        assert result["covered_count"] == 2

    def test_uncovered_is_no_ship(self, violations_data):
        result = check_readiness.check_readiness("rhoai-3.4", violations_data, [])
        assert result["verdict"] == "NO-SHIP"
        assert result["blocking_count"] == 2

    def test_partial_coverage(self, violations_data):
        exceptions = [
            {
                "rule": "hermetic_task.hermetic",
                "is_expired": False,
                "is_unscoped": True,
                "component_names": [],
                "expires_in_days": 30,
            },
        ]
        result = check_readiness.check_readiness("rhoai-3.4", violations_data, exceptions)
        assert result["verdict"] == "NO-SHIP"
        assert result["blocking_count"] == 1
        assert result["covered_count"] == 1

    def test_no_violations_is_no_data(self, violations_data):
        result = check_readiness.check_readiness("rhoai-9.9", violations_data, [])
        assert result["verdict"] == "NO-DATA"

    def test_expiring_soon_flagged(self, violations_data):
        exceptions = [
            {
                "rule": "hermetic_task.hermetic",
                "is_expired": False,
                "is_unscoped": True,
                "component_names": [],
                "expires_in_days": 7,
                "effective_until": "2026-06-13T00:00:00Z",
            },
        ]
        result = check_readiness.check_readiness("rhoai-3.4", violations_data, exceptions, soon_days=14)
        assert len(result["expiring_soon"]) == 1
        assert result["expiring_soon"][0]["expires_in_days"] == 7

    def test_expired_exceptions_not_used(self, violations_data):
        exceptions = [
            {
                "rule": "hermetic_task.hermetic",
                "is_expired": True,
                "is_unscoped": True,
                "component_names": [],
            },
        ]
        result = check_readiness.check_readiness("rhoai-3.4", violations_data, exceptions)
        assert result["verdict"] == "NO-SHIP"
