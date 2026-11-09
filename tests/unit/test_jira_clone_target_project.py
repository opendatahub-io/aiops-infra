"""New onboarding/offboarding tickets clone from RHOAIENG into RHAI by default."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_script(script_name: str):
    """Import a Jira helper without requiring a live Jira client package."""
    jira_module = types.ModuleType("jira")
    jira_module.__path__ = []
    jira_module.JIRA = type("JIRA", (), {})
    exceptions_module = types.ModuleType("jira.exceptions")
    exceptions_module.JIRAError = type("JIRAError", (Exception,), {})

    old_jira = sys.modules.get("jira")
    old_exceptions = sys.modules.get("jira.exceptions")
    sys.modules["jira"] = jira_module
    sys.modules["jira.exceptions"] = exceptions_module
    try:
        path = REPO_ROOT / "scripts" / script_name
        spec = importlib.util.spec_from_file_location(f"test_{script_name[:-3]}", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        if old_jira is None:
            sys.modules.pop("jira", None)
        else:
            sys.modules["jira"] = old_jira
        if old_exceptions is None:
            sys.modules.pop("jira.exceptions", None)
        else:
            sys.modules["jira.exceptions"] = old_exceptions


class FakeJira:
    def __init__(self):
        self.source = SimpleNamespace(
            key="RHOAIENG-1234",
            fields=SimpleNamespace(
                project=SimpleNamespace(key="RHOAIENG"),
                summary="Template summary",
                issuetype=SimpleNamespace(name="Task"),
                description="Template description",
            ),
        )
        self.created_fields = None
        self.created_issue = None
        self.links = []

    def issue(self, issue_key):
        if issue_key == "RHOAIENG-1234":
            return self.source
        if self.created_issue and issue_key == self.created_issue.key:
            return self.created_issue
        raise AssertionError(f"unexpected issue lookup: {issue_key}")

    def create_issue(self, fields):
        self.created_fields = fields
        self.created_issue = SimpleNamespace(key="RHAI-9000")
        return self.created_issue

    def create_issue_link(self, link_type, new_key, source_key):
        self.links.append((link_type, new_key, source_key))


@pytest.mark.parametrize(
    "script_name",
    ["update_jira_issue.py", "update_offboarding_jira.py"],
)
def test_clone_defaults_to_rhai_but_keeps_source_template(script_name: str):
    module = _load_script(script_name)
    jira = FakeJira()

    result = module.clone_issue(jira, "RHOAIENG-1234")

    assert result == "RHAI-9000"
    assert jira.created_fields["project"] == {"key": "RHAI"}
    assert jira.created_fields["summary"] == "Template summary"
    assert jira.created_fields["issuetype"] == {"name": "Task"}
    assert jira.links[0][2] == "RHOAIENG-1234"


@pytest.mark.parametrize(
    "script_name",
    ["update_jira_issue.py", "update_offboarding_jira.py"],
)
def test_clone_target_project_can_be_overridden(script_name: str):
    module = _load_script(script_name)
    jira = FakeJira()

    module.clone_issue(jira, "RHOAIENG-1234", "ALT")

    assert jira.created_fields["project"] == {"key": "ALT"}


@pytest.mark.parametrize(
    "script_name",
    ["update_jira_issue.py", "update_offboarding_jira.py"],
)
def test_clone_cli_defaults_to_rhai_project(script_name: str, monkeypatch, capsys):
    module = _load_script(script_name)
    jira = FakeJira()
    monkeypatch.setattr(module, "get_jira_client", lambda: jira)
    monkeypatch.delenv("JIRA_CREATE_PROJECT_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", [script_name, "new", "--clone-from", "RHOAIENG-1234"])

    module.main()

    assert jira.created_fields["project"] == {"key": "RHAI"}
    assert "https://redhat.atlassian.net/browse/RHAI-9000" in capsys.readouterr().out


@pytest.mark.parametrize(
    "script_name",
    ["update_jira_issue.py", "update_offboarding_jira.py"],
)
def test_clone_cli_uses_rhai_default_project(script_name: str, monkeypatch, capsys):
    module = _load_script(script_name)
    jira = FakeJira()
    monkeypatch.setattr(module, "get_jira_client", lambda: jira)
    monkeypatch.setattr(
        sys,
        "argv",
        [script_name, "new", "--clone-from", "RHOAIENG-1234"],
    )

    module.main()

    assert jira.created_fields["project"] == {"key": "RHAI"}
    assert "RHAI-9000" in capsys.readouterr().out
