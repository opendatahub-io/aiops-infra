"""Tests for conforma-exception create_exception.py."""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import MagicMock, patch

import create_exception as ce


MOCK_TEMPLATES = {
    "categories": {
        "hermetic_build": {
            "display_name": "Non-hermetic build",
            "common": True,
            "matches_rules": ["hermetic_task.hermetic"],
            "workflow": [
                {"step": "rhoaieng_approval_jira", "track": "exception_approval"},
                {"step": "psx_exception_jira", "track": "exception_approval", "project": "PSX"},
                {"step": "exception_merge_request", "track": "exception_approval"},
            ],
            "find_examples": {"jira_search": "https://example.com/jira"},
            "example_tickets": [{"jira": "https://redhat.atlassian.net/browse/PSX-1102"}],
        },
        "sbom_package_sources": {
            "display_name": "External package source in SBOM",
            "common": True,
            "matches_rules": ["sbom_spdx.allowed_package_sources:*"],
            "workflow": [
                {"step": "rhoaieng_approval_jira", "track": "exception_approval"},
            ],
        },
        "rare_category": {
            "display_name": "Rare exception",
            "common": False,
            "workflow": [],
        },
        "other": {
            "display_name": "Other",
            "is_catch_all": True,
            "workflow": [
                {"step": "psx_exception_jira", "track": "exception_approval", "project": "PSX"},
            ],
        },
    }
}

MOCK_CATALOG = {"rules": [{"code": "hermetic_task.hermetic"}, {"code": "sbom_spdx.allowed_package_sources"}]}


class TestListExceptionTypes:
    def test_returns_common_categories_only_by_default(self):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", return_value=mock_file), patch(
            "yaml.safe_load",
            side_effect=[MOCK_TEMPLATES, MOCK_CATALOG],
        ):
            result = ce.list_exception_types(show_all=False)

        assert "common" in result
        assert result["common_count"] == 2
        assert result["non_common_count"] == 1
        assert result["total_catalog_rules"] == 2
        assert result["conforma_rules_url"] == "https://conforma.dev/docs/policy/release_policy.html"
        assert "non_common" not in result
        assert "catch_all" not in result

        common_ids = {entry["id"] for entry in result["common"]}
        assert common_ids == {"hermetic_build", "sbom_package_sources"}
        assert all("workflow_summary" in entry for entry in result["common"])
        assert all("links" in entry for entry in result["common"])

    def test_show_all_includes_non_common_and_catch_all(self):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", return_value=mock_file), patch(
            "yaml.safe_load",
            side_effect=[MOCK_TEMPLATES, MOCK_CATALOG],
        ):
            result = ce.list_exception_types(show_all=True)

        assert "non_common" in result
        assert "catch_all" in result
        assert result["catch_all"]["id"] == "other"
        assert result["catch_all"]["is_catch_all"] is True
        assert "interactive" in result["catch_all"]["display_name"]
        non_common_ids = {entry["id"] for entry in result["non_common"]}
        assert non_common_ids == {"rare_category"}

    def test_handles_missing_catalog_file(self):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)

        with patch("builtins.open", return_value=mock_file), patch(
            "yaml.safe_load", return_value=MOCK_TEMPLATES
        ), patch("pathlib.Path.is_file", return_value=False):
            result = ce.list_exception_types()

        assert result["total_catalog_rules"] == 0


class TestRunScript:
    def test_parses_json_stdout(self):
        script_output = {"valid": True, "workflow_steps": []}
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps(script_output)
        completed.stderr = ""

        with patch("create_exception.subprocess.run", return_value=completed) as mock_run:
            result = ce.run_script("validate_inputs.py", ["--dry-run"])

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == sys.executable
        assert str(ce.SCRIPTS_DIR / "validate_inputs.py") in call_args[1]
        assert "--dry-run" in call_args
        assert result == script_output

    def test_nonzero_returncode_adds_script_error(self):
        completed = MagicMock()
        completed.returncode = 1
        completed.stdout = json.dumps({"valid": False})
        completed.stderr = "validation failed"

        with patch("create_exception.subprocess.run", return_value=completed):
            result = ce.run_script("validate_inputs.py", [])

        assert result["_script_error"] == "validation failed"
        assert result["_returncode"] == 1

    def test_invalid_json_falls_back_to_raw_output(self):
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = "not json"
        completed.stderr = "some stderr"

        with patch("create_exception.subprocess.run", return_value=completed):
            result = ce.run_script("some_script.py", ["--flag"])

        assert result["raw_stdout"] == "not json"
        assert result["raw_stderr"] == "some stderr"
