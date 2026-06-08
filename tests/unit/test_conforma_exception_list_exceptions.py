"""Tests for conforma-exception list_exceptions.py formatting helpers."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Load list_exceptions without pulling in manage_exceptions' heavy deps.
# Temporarily inject a mock only during module loading, then restore.
_orig_manage = sys.modules.get("manage_exceptions")
_had_manage = "manage_exceptions" in sys.modules
if _orig_manage is None:
    sys.modules["manage_exceptions"] = MagicMock()

_spec = importlib.util.spec_from_file_location(
    "list_exceptions_under_test",
    _REPO_ROOT / "skills/conforma-exception/scripts/list_exceptions.py",
)
list_exceptions = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(list_exceptions)

# Restore sys.modules to avoid poisoning other tests
if not _had_manage:
    del sys.modules["manage_exceptions"]
elif _orig_manage is not None:
    sys.modules["manage_exceptions"] = _orig_manage


class TestFormatRule:
    def test_short_rule_unchanged(self):
        assert list_exceptions._format_rule("hermetic_task.hermetic") == "hermetic_task.hermetic"

    def test_long_rule_truncated_to_base(self):
        long_rule = "rpm_signature.allowed:" + "x" * 100
        assert list_exceptions._format_rule(long_rule) == "rpm_signature.allowed"

    def test_strips_quotes(self):
        assert list_exceptions._format_rule('"hermetic_task.hermetic"') == "hermetic_task.hermetic"


class TestFormatComponent:
    def test_single_component_name(self):
        exc = {"has_component_names": True, "component_names": ["odh-mlflow-v3-4"]}
        assert list_exceptions._format_component(exc) == "odh-mlflow-v3-4"

    def test_two_component_names(self):
        exc = {
            "has_component_names": True,
            "component_names": ["odh-mlflow-v3-4", "odh-dashboard-v3-4"],
        }
        assert list_exceptions._format_component(exc) == "odh-mlflow-v3-4, odh-dashboard-v3-4"

    def test_many_component_names_truncated(self):
        exc = {
            "has_component_names": True,
            "component_names": ["a-v3-4", "b-v3-4", "c-v3-4", "d-v3-4"],
        }
        assert list_exceptions._format_component(exc) == "a-v3-4, b-v3-4 +2 more"

    def test_image_url_strips_rhel_suffix(self):
        exc = {
            "has_component_names": False,
            "rule": "hermetic_task.hermetic",
            "image_url": "quay.io/rhoai/odh-mlflow-rhel9",
        }
        assert list_exceptions._format_component(exc) == "odh-mlflow"

    def test_image_url_with_package_from_rule(self):
        rule = 'sbom.package_sources:pkg:generic/my-package?version=1.0'
        exc = {
            "has_component_names": False,
            "rule": rule,
            "image_url": "quay.io/rhoai/autorag-rhel9",
        }
        assert list_exceptions._format_component(exc) == "autorag: my-package"

    def test_unscoped_all(self):
        exc = {"has_component_names": False, "rule": "hermetic_task.hermetic"}
        assert list_exceptions._format_component(exc) == "(all)"


class TestExtractRhoaiVersion:
    def test_from_component_names(self):
        exc = {
            "has_component_names": True,
            "component_names": ["odh-mlflow-v3-4", "odh-dashboard-v3-5"],
        }
        assert list_exceptions._extract_rhoai_version(exc) == "3.4, 3.5"

    def test_ea_suffix(self):
        exc = {
            "has_component_names": True,
            "component_names": ["odh-operator-fbc-v3-5-ea-1"],
        }
        assert list_exceptions._extract_rhoai_version(exc) == "3.5"

    def test_components_without_version_suffix(self):
        exc = {"has_component_names": True, "component_names": ["odh-mlflow"]}
        assert list_exceptions._extract_rhoai_version(exc) == "—"

    def test_image_url_only_returns_all(self):
        exc = {
            "has_component_names": False,
            "image_url": "quay.io/rhoai/odh-operator-bundle",
        }
        assert list_exceptions._extract_rhoai_version(exc) == "all"


class TestFormatReference:
    def test_none_returns_em_dash(self):
        assert list_exceptions._format_reference(None) == "—"

    def test_jira_issues_redhat(self):
        url = "https://issues.redhat.com/browse/RHOAIENG-12345"
        assert list_exceptions._format_reference(url) == "[RHOAIENG-12345]({url})".format(url=url)

    def test_jira_atlassian(self):
        url = "https://redhat.atlassian.net/browse/PSX-999"
        assert list_exceptions._format_reference(url) == "[PSX-999]({url})".format(url=url)

    def test_github_issue(self):
        url = "https://github.com/org/repo/issues/42"
        assert list_exceptions._format_reference(url) == "[org/repo#42]({url})".format(url=url)

    def test_long_url_becomes_link(self):
        url = "https://example.com/" + "a" * 80
        assert list_exceptions._format_reference(url) == f"[link]({url})"


class TestFormatDate:
    def test_none_returns_em_dash(self):
        assert list_exceptions._format_date(None) == "—"

    def test_rfc3339_extracts_date(self):
        assert list_exceptions._format_date("2026-06-01T00:00:00Z") == "2026-06-01"

    def test_quoted_date(self):
        assert list_exceptions._format_date('"2026-12-15T00:00:00Z"') == "2026-12-15"


class TestRenderTable:
    def test_renders_header_and_rows(self):
        exceptions = [
            {
                "rule": "hermetic_task.hermetic",
                "has_component_names": True,
                "component_names": ["odh-mlflow-v3-4"],
                "effective_until": "2026-06-01T00:00:00Z",
                "reference": "https://issues.redhat.com/browse/RHOAIENG-1",
            },
            {
                "rule": "trusted_task.trusted",
                "has_component_names": False,
                "image_url": "quay.io/rhoai/odh-dashboard-rhel9",
                "effective_until": "2026-12-01T00:00:00Z",
                "reference": None,
            },
        ]
        table = list_exceptions._render_table(exceptions)
        lines = table.splitlines()
        assert lines[0].startswith("| Rule | Component / Image |")
        assert lines[1].startswith("|------|")
        assert len(lines) == 4
        assert "`hermetic_task.hermetic`" in lines[2]
        assert "odh-mlflow-v3-4" in lines[2]
        assert "3.4" in lines[2]
        assert "2026-06-01" in lines[2]
        assert "[RHOAIENG-1]" in lines[2]
        assert "odh-dashboard" in lines[3]
        assert "all" in lines[3]
        assert "—" in lines[3]
