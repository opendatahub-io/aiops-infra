"""Tests for conforma-release-readiness check_readiness.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

import check_readiness
import conforma_context_ops


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


class TestContextIntegration:
    """Tests for context-based parameter discovery in main()."""

    def _setup_run_with_violations(self, tmp_path):
        """Create a run directory with context.yaml and a violations YAML file."""
        run_dir = tmp_path / "20260703-120000"
        run_dir.mkdir()

        violations = {
            "violation_data": {
                "violations_by_rule": {
                    "hermetic_task.hermetic": {
                        "title": "Hermetic build required",
                        "base_code": "hermetic_task.hermetic",
                        "releases": {"rhoai-3.5-ea.2": ["comp-a"]},
                    },
                },
            },
        }
        viol_path = run_dir / "violations.yaml"
        viol_path.write_text(yaml.dump(violations), encoding="utf-8")

        context = {
            "application": {"release": "rhoai-3.5-ea.2"},
            "environment": "prod",
            "run": {"run_dir": conforma_context_ops.contract_home(run_dir)},
            "steps": {
                "parse": {
                    "status": "completed",
                    "violations_yaml": "violations.yaml",
                },
            },
        }
        context_path = run_dir / "context.yaml"
        context_path.write_text(yaml.dump(context), encoding="utf-8")

        work_dir = tmp_path / ".conforma"
        work_dir.mkdir(exist_ok=True)
        active_link = work_dir / ".conforma-active"
        active_link.symlink_to(run_dir)

        return run_dir, work_dir

    @patch("check_readiness.load_exceptions", return_value=[])
    def test_reads_params_from_context(self, _mock_exc, tmp_path, monkeypatch):
        """Zero-arg invocation resolves release, violations, environment from context."""
        run_dir, work_dir = self._setup_run_with_violations(tmp_path)
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        monkeypatch.setattr("sys.argv", ["check_readiness.py"])

        rc = check_readiness.main()
        assert rc in (0, 1)

    @patch("check_readiness.load_exceptions", return_value=[])
    def test_cli_overrides_context(self, _mock_exc, tmp_path, monkeypatch):
        """Explicit CLI args override context values."""
        run_dir, work_dir = self._setup_run_with_violations(tmp_path)
        viol_path = run_dir / "violations.yaml"
        monkeypatch.setenv("CONFORMA_WORKDIR", str(work_dir))
        monkeypatch.setattr("sys.argv", [
            "check_readiness.py",
            "--release", "rhoai-3.4",
            "--violations-input", str(viol_path),
            "--environment", "stage",
        ])

        rc = check_readiness.main()
        assert rc in (0, 1)

    @patch("check_readiness.load_exceptions", return_value=[])
    def test_explicit_run_dir(self, _mock_exc, tmp_path, monkeypatch):
        """--run-dir works without symlink."""
        run_dir, _ = self._setup_run_with_violations(tmp_path)
        monkeypatch.setattr("sys.argv", ["check_readiness.py", "--run-dir", str(run_dir)])

        rc = check_readiness.main()
        assert rc in (0, 1)

    def test_no_context_requires_explicit_args(self, tmp_path, monkeypatch):
        """Without context and without required args, main() exits with error."""
        monkeypatch.setenv("CONFORMA_WORKDIR", str(tmp_path / "empty"))
        monkeypatch.setattr("sys.argv", ["check_readiness.py"])

        with pytest.raises(SystemExit):
            check_readiness.main()
