"""Tests for scripts/jira_ops.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from jira.exceptions import JIRAError

import jira_ops


def _mock_client() -> MagicMock:
    client = MagicMock()
    client._options = {"server": "https://redhat.atlassian.net"}
    return client


class TestVerifyAuth:
    def test_success(self):
        client = _mock_client()
        client.myself.return_value = {"displayName": "Jane Doe"}
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.verify_auth()

        assert result == {"ok": True, "user": "Jane Doe", "error": None}

    def test_failure(self):
        with patch.object(jira_ops, "get_client", side_effect=ValueError("missing credentials")):
            result = jira_ops.verify_auth()

        assert result["ok"] is False
        assert result["user"] is None
        assert "missing credentials" in result["error"]


class TestGetClient:
    def test_requires_email_and_token(self, monkeypatch):
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

        with pytest.raises(ValueError, match="JIRA_EMAIL"):
            jira_ops.get_client()

        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        with pytest.raises(ValueError, match="JIRA_API_TOKEN"):
            jira_ops.get_client()

    def test_constructs_authenticated_client(self, monkeypatch):
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "token")

        with patch.object(jira_ops, "JIRA") as jira_class:
            result = jira_ops.get_client(url="https://jira.example")

        assert result is jira_class.return_value
        jira_class.assert_called_once_with(
            server="https://jira.example",
            basic_auth=("user@example.com", "token"),
        )


class TestGetIssue:
    def test_success_base_fields(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "ABC-1"
        issue.fields.summary = "Test summary"
        issue.fields.status.name = "Open"
        issue.fields.issuetype.name = "Task"
        issue.fields.assignee = MagicMock(displayName="Bob")
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue("ABC-1")

        assert result == {
            "key": "ABC-1",
            "summary": "Test summary",
            "status": "Open",
            "issue_type": "Task",
            "assignee": "Bob",
        }
        assert "description" not in result

    def test_success_extra_fields(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "ABC-1"
        issue.fields.summary = "Test summary"
        issue.fields.status.name = "Open"
        issue.fields.issuetype.name = "Bug"
        issue.fields.assignee = None
        issue.fields.description = "Full description text"
        issue.fields.labels = ["conforma-violation", "rhoai-3.4"]
        issue.fields.created = "2026-06-03T11:07:36.157+0000"
        issue.fields.creator = MagicMock(displayName="Alice")
        issue.fields.reporter = MagicMock(displayName="Bob")
        comp = MagicMock()
        comp.name = "AI Hub"
        issue.fields.components = [comp]
        fv = MagicMock()
        fv.name = "RHOAI 3.4"
        issue.fields.fixVersions = [fv]
        priority = MagicMock()
        priority.name = "Critical"
        issue.fields.priority = priority
        resolution = MagicMock()
        resolution.name = "Duplicate"
        issue.fields.resolution = resolution
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue(
                "ABC-1",
                fields=[
                    "description",
                    "labels",
                    "created",
                    "creator",
                    "reporter",
                    "components",
                    "fix_versions",
                    "priority",
                    "resolution",
                    "url",
                ],
            )

        assert result["key"] == "ABC-1"
        assert result["description"] == "Full description text"
        assert result["labels"] == ["conforma-violation", "rhoai-3.4"]
        assert result["created"] == "2026-06-03T11:07:36.157+0000"
        assert result["creator"] == "Alice"
        assert result["reporter"] == "Bob"
        assert result["components"] == ["AI Hub"]
        assert result["fix_versions"] == ["RHOAI 3.4"]
        assert result["priority"] == "Critical"
        assert result["resolution"] == "Duplicate"
        assert result["url"] == "https://redhat.atlassian.net/browse/ABC-1"

    def test_extra_fields_with_nulls(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "ABC-2"
        issue.fields.summary = "Minimal"
        issue.fields.status.name = "New"
        issue.fields.issuetype.name = "Task"
        issue.fields.assignee = None
        issue.fields.description = None
        issue.fields.creator = None
        issue.fields.reporter = None
        issue.fields.components = []
        issue.fields.fixVersions = []
        issue.fields.priority = None
        issue.fields.resolution = None
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue(
                "ABC-2",
                fields=["description", "creator", "reporter", "components", "fix_versions", "priority", "resolution"],
            )

        assert result["description"] is None
        assert result["creator"] is None
        assert result["reporter"] is None
        assert result["components"] == []
        assert result["fix_versions"] == []
        assert result["priority"] is None
        assert result["resolution"] is None

    def test_error(self):
        client = _mock_client()
        client.issue.side_effect = JIRAError("Issue not found")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue("ABC-999")

        assert result["key"] == "ABC-999"
        assert "error" in result

    def test_non_jira_exception(self):
        client = _mock_client()
        client.issue.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue("ABC-999")
        assert result == {"key": "ABC-999", "error": "boom"}


class TestGetJiraClientAlias:
    def test_alias_is_get_client(self):
        assert jira_ops.get_jira_client is jira_ops.get_client


class TestAddComment:
    def test_success(self):
        client = _mock_client()
        comment = MagicMock(id="12345")
        client.add_comment.return_value = comment

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.add_comment("ABC-1", "Closing as duplicate.")

        assert result == {"key": "ABC-1", "comment_id": "12345", "ok": True}
        client.add_comment.assert_called_once_with("ABC-1", "Closing as duplicate.")

    def test_error(self):
        client = _mock_client()
        client.add_comment.side_effect = JIRAError("Permission denied")

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.add_comment("ABC-1", "test")

        assert result["ok"] is False
        assert "Permission denied" in result["error"]


class TestCreateIssue:
    def test_success(self):
        client = _mock_client()
        created = MagicMock(key="XYZ-10")
        client.create_issue.return_value = created

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.create_issue("XYZ", "New task", "Description")

        assert result == {
            "key": "XYZ-10",
            "url": "https://redhat.atlassian.net/browse/XYZ-10",
        }
        client.create_issue.assert_called_once_with(
            fields={
                "project": {"key": "XYZ"},
                "summary": "New task",
                "description": "Description",
                "issuetype": {"name": "Task"},
            }
        )


class TestUpdateIssue:
    def test_success(self):
        client = _mock_client()
        issue = MagicMock()
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.update_issue("ABC-2", summary="Updated", labels=["onboarding"])

        assert result == {"key": "ABC-2", "updated": ["summary", "labels"]}
        issue.update.assert_called_once_with(fields={"summary": "Updated", "labels": ["onboarding"]})

    def test_updates_description(self):
        client = _mock_client()
        issue = MagicMock()
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.update_issue("ABC-2", description="Updated description")

        assert result == {"key": "ABC-2", "updated": ["description"]}
        issue.update.assert_called_once_with(fields={"description": "Updated description"})

    def test_no_fields(self):
        result = jira_ops.update_issue("ABC-2")
        assert result == {"key": "ABC-2", "updated": [], "error": "No fields to update"}

    def test_components_and_priority(self):
        client = _mock_client()
        issue = MagicMock()
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.update_issue("ABC-2", components=["AI-Guardrails"], priority="Blocker")

        assert result == {"key": "ABC-2", "updated": ["components", "priority"]}
        issue.update.assert_called_once_with(
            fields={
                "components": [{"name": "AI-Guardrails"}],
                "priority": {"name": "Blocker"},
            }
        )

    def test_extra_fields(self):
        client = _mock_client()
        issue = MagicMock()
        client.issue.return_value = issue

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.update_issue(
                "ABC-2",
                extra_fields={"customfield_10855": [{"name": "rhoai-3.6"}], "zfield": 1},
            )

        assert result == {"key": "ABC-2", "updated": ["customfield_10855", "zfield"]}
        issue.update.assert_called_once_with(fields={"customfield_10855": [{"name": "rhoai-3.6"}], "zfield": 1})


class TestAddWatchers:
    def test_success(self):
        client = _mock_client()
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.add_watchers("ABC-3", ["user-1", "user-2"])

        assert result == {"added": ["user-1", "user-2"], "failed": []}
        assert client.add_watcher.call_count == 2

    def test_some_fail(self):
        client = _mock_client()

        def add_watcher_side_effect(issue_key, account_id):
            if account_id == "bad-user":
                raise JIRAError("User not found")

        client.add_watcher.side_effect = add_watcher_side_effect

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.add_watchers("ABC-3", ["good-user", "bad-user"])

        assert result == {"added": ["good-user"], "failed": ["bad-user"]}


class TestSearchIssues:
    def test_success(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "PSX-100"
        issue.fields.summary = "RPM signing key exception"
        issue.fields.status = MagicMock(__str__=lambda self: "New")
        issue.fields.issuetype = MagicMock(__str__=lambda self: "PSRD Exception")
        issue.fields.assignee = None

        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([issue])
        result_set.total = 1
        client.search_issues.return_value = result_set

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("project = PSX")

        assert result["total"] == 1
        assert len(result["issues"]) == 1
        assert result["issues"][0]["key"] == "PSX-100"
        assert result["issues"][0]["summary"] == "RPM signing key exception"
        assert result["issues"][0]["assignee"] == "Unassigned"
        assert result["issues"][0]["url"] == "https://redhat.atlassian.net/browse/PSX-100"


class TestIssueHistory:
    def test_history_is_normalized(self):
        client = _mock_client()
        issue = MagicMock()
        history = MagicMock(id="1", created="2026-01-01", author=MagicMock(displayName="A"))
        history.items = [MagicMock(field="Target Version", fromString="3.5", toString="3.6")]
        issue.changelog.histories = [history]
        client.issue.return_value = issue
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue_history("A-1")
        assert result["ok"] is True
        assert result["history"][0]["items"][0]["to"] == "3.6"

    def test_unavailable_target_field_is_explicit(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "A-1"
        issue.fields.summary = "Test"
        issue.fields.status = MagicMock(__str__=lambda self: "Open")
        issue.fields.issuetype = MagicMock(__str__=lambda self: "Task")
        issue.fields.assignee = None
        del issue.fields.customfield_10855
        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([issue])
        result_set.total = 1
        client.search_issues.return_value = result_set
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("project = A", fields=["key", "target_versions"])
        assert "customfield_10855 unavailable" in result["issues"][0]["field_errors"]

    def test_search_issues_paginated_fetches_all_pages(self, monkeypatch):
        pages = [
            {"issues": [{"key": "A-1"}], "total": 2, "start_at": 0, "max_results": 1},
            {"issues": [{"key": "A-2"}], "total": 2, "start_at": 1, "max_results": 1},
        ]
        monkeypatch.setattr(jira_ops, "search_issues", lambda *args, **kwargs: pages.pop(0))
        result = jira_ops.search_issues_paginated("project = A", max_results=1)
        assert [issue["key"] for issue in result["issues"]] == ["A-1", "A-2"]
        assert result["complete"] is True
        assert len(result["pages"]) == 2

    def test_custom_fields(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "ABC-5"
        issue.fields.summary = "Test"
        issue.fields.status = MagicMock(__str__=lambda self: "Open")

        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([issue])
        result_set.total = 1
        client.search_issues.return_value = result_set

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("project = ABC", fields=["key", "summary", "status"])

        assert "type" not in result["issues"][0]
        assert "assignee" not in result["issues"][0]
        assert result["issues"][0]["status"] == "Open"

    def test_priority_components_target_versions(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "RHOAIENG-1"
        issue.fields.summary = "Conforma violation"
        issue.fields.status = MagicMock(__str__=lambda self: "Open")
        issue.fields.issuetype = MagicMock(__str__=lambda self: "Task")
        issue.fields.assignee = None
        issue.fields.priority = MagicMock(__str__=lambda self: "Blocker")
        comp_a = MagicMock()
        comp_a.name = "AI-Guardrails"
        comp_b = MagicMock()
        comp_b.name = "Model-Registry"
        issue.fields.components = [comp_a, comp_b]
        version_1 = MagicMock()
        version_1.name = "rhoai-3.6-ea.2"
        issue.fields.customfield_10855 = [version_1]

        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([issue])
        result_set.total = 1
        client.search_issues.return_value = result_set

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues(
                "project = RHOAIENG",
                fields=["key", "summary", "status", "priority", "components", "target_versions"],
            )

        entry = result["issues"][0]
        assert entry["priority"] == "Blocker"
        assert entry["components"] == ["AI-Guardrails", "Model-Registry"]
        assert entry["target_versions"] == ["rhoai-3.6-ea.2"]

    def test_new_fields_absent_when_not_requested(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "RHOAIENG-2"
        issue.fields.summary = "x"
        issue.fields.status = MagicMock(__str__=lambda self: "Open")
        issue.fields.issuetype = MagicMock(__str__=lambda self: "Task")
        issue.fields.assignee = None

        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([issue])
        result_set.total = 1
        client.search_issues.return_value = result_set

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("project = RHOAIENG", fields=["key", "summary"])

        entry = result["issues"][0]
        assert "priority" not in entry
        assert "components" not in entry
        assert "target_versions" not in entry

    def test_description_is_returned_when_requested(self):
        client = _mock_client()
        issue = MagicMock()
        issue.key = "RHOAIENG-3"
        issue.fields.summary = "Shared exception"
        issue.fields.status = MagicMock(__str__=lambda self: "Review")
        issue.fields.description = "hermetic_task.hermetic for odh-openvino-model-server"

        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([issue])
        result_set.total = 1
        client.search_issues.return_value = result_set

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("key = RHOAIENG-3", fields=["key", "description"])

        assert result["issues"][0]["description"] == issue.fields.description

    def test_error_raises_jira_search_error(self):
        import pytest

        client = _mock_client()
        client.search_issues.side_effect = JIRAError("Bad JQL")
        with patch.object(jira_ops, "get_client", return_value=client):
            with pytest.raises(jira_ops.JiraSearchError) as exc_info:
                jira_ops.search_issues("invalid jql")

        assert exc_info.value.jql == "invalid jql"
        assert "Bad JQL" in exc_info.value.message
        # A failure must not be reported as a silent empty result.
        assert not hasattr(exc_info.value, "issues")

    def test_error_status_propagates(self):
        import pytest

        client = _mock_client()
        client.search_issues.side_effect = JIRAError(status_code=400, text="unknown field")
        with patch.object(jira_ops, "get_client", return_value=client):
            with pytest.raises(jira_ops.JiraSearchError) as exc_info:
                jira_ops.search_issues("project = NOPE", fields=["key", "badfield"])

        assert exc_info.value.status == 400
        assert "unknown field" in exc_info.value.message

    def test_unexpected_error_also_raises(self):
        import pytest

        client = _mock_client()
        client.search_issues.side_effect = ValueError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            with pytest.raises(jira_ops.JiraSearchError):
                jira_ops.search_issues("project = X")

    def test_empty_results(self):
        client = _mock_client()
        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter([])
        result_set.total = 0
        client.search_issues.return_value = result_set

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("project = EMPTY")

        assert result["total"] == 0
        assert result["issues"] == []
        assert "error" not in result


class TestSearchUser:
    def test_found(self):
        client = _mock_client()
        user = MagicMock(accountId="acc-123", displayName="Alice Smith")
        client.search_users.return_value = [user]

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_user("Alice Smith")

        assert result == {
            "account_id": "acc-123",
            "display_name": "Alice Smith",
            "found": True,
        }

    def test_not_found(self):
        client = _mock_client()
        client.search_users.return_value = []

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_user("Nobody Here")

        assert result == {
            "account_id": None,
            "display_name": "Nobody Here",
            "found": False,
        }


class TestLinkIssues:
    def test_success(self):
        client = _mock_client()
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.link_issues("ABC-1", "ABC-2", link_type="Blocks")

        assert result == {
            "from_key": "ABC-1",
            "to_key": "ABC-2",
            "link_type": "Blocks",
            "ok": True,
        }
        client.create_issue_link.assert_called_once_with("Blocks", "ABC-1", "ABC-2")


class TestTransitionIssue:
    def test_success(self):
        client = _mock_client()
        issue = MagicMock()
        issue.fields.status.name = "Open"
        client.issue.return_value = issue
        client.transitions.return_value = [
            {"id": "21", "name": "Start Progress", "to": {"name": "In Progress"}},
        ]

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.transition_issue("ABC-4", "In Progress")

        assert result == {
            "key": "ABC-4",
            "ok": True,
            "from_status": "Open",
            "to_status": "In Progress",
            "resolution": None,
        }
        client.transition_issue.assert_called_once_with(issue, "21", fields=None)

    def test_success_with_resolution(self):
        client = _mock_client()
        issue = MagicMock()
        issue.fields.status.name = "New"
        client.issue.return_value = issue
        client.transitions.return_value = [
            {"id": "61", "name": "Closed", "to": {"name": "Closed"}},
        ]

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.transition_issue("ABC-5", "Closed", resolution="Duplicate")

        assert result == {
            "key": "ABC-5",
            "ok": True,
            "from_status": "New",
            "to_status": "Closed",
            "resolution": "Duplicate",
        }
        client.transition_issue.assert_called_once_with(issue, "61", fields={"resolution": {"name": "Duplicate"}})

    def test_transition_not_found(self):
        client = _mock_client()
        issue = MagicMock()
        issue.fields.status.name = "Open"
        client.issue.return_value = issue
        client.transitions.return_value = [
            {"id": "21", "name": "Close", "to": {"name": "Closed"}},
        ]

        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.transition_issue("ABC-4", "Done")

        assert result["ok"] is False
        assert result["current_status"] == "Open"
        assert "not found" in result["error"]
        assert result["available_transitions"] == ["Close"]


class TestGetComments:
    def test_success(self):
        client = _mock_client()
        issue = MagicMock()
        c1 = MagicMock(id="1", author=MagicMock(displayName="Alice"), body="hello", created="2026-01-01T00:00:00Z")
        c2 = MagicMock(id="2", author=None, body=None, created="2026-01-02T00:00:00Z")
        issue.fields.comment.comments = [c1, c2]
        client.issue.return_value = issue
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_comments("ABC-1")
        assert result == {
            "ok": True,
            "comments": [
                {"id": "1", "author": "Alice", "body": "hello", "created": "2026-01-01T00:00:00Z"},
                {"id": "2", "author": "", "body": "", "created": "2026-01-02T00:00:00Z"},
            ],
        }
        client.issue.assert_called_once_with("ABC-1", fields="comment")

    def test_no_comments(self):
        client = _mock_client()
        issue = MagicMock()
        issue.fields.comment.comments = []
        client.issue.return_value = issue
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_comments("ABC-1")
        assert result == {"ok": True, "comments": []}

    def test_jira_error(self):
        client = _mock_client()
        client.issue.side_effect = JIRAError("not found")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_comments("ABC-1")
        assert result["ok"] is False
        assert result["comments"] == []
        assert "not found" in result["error"]

    def test_non_jira_exception(self):
        client = _mock_client()
        client.issue.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_comments("ABC-1")
        assert result["ok"] is False
        assert result["error"] == "boom"


class TestAddCommentGeneric:
    def test_non_jira_exception(self):
        client = _mock_client()
        client.add_comment.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.add_comment("ABC-1", "x")
        assert result == {"key": "ABC-1", "ok": False, "error": "boom"}


class TestCreateIssueOptions:
    def test_all_options(self):
        client = _mock_client()
        created = MagicMock(key="XYZ-20")
        client.create_issue.return_value = created
        with patch.object(jira_ops, "get_client", return_value=client):
            jira_ops.create_issue(
                "XYZ",
                "s",
                None,
                issue_type="Bug",
                components=["C1"],
                labels=["l1"],
                priority="Blocker",
                extra_fields={"customfield_10855": [{"name": "v"}]},
            )
        kwargs = client.create_issue.call_args.kwargs
        fields = kwargs["fields"]
        assert "description" not in fields
        assert fields["issuetype"] == {"name": "Bug"}
        assert fields["components"] == [{"name": "C1"}]
        assert fields["labels"] == ["l1"]
        assert fields["priority"] == {"name": "Blocker"}
        assert fields["customfield_10855"] == [{"name": "v"}]

    def test_error(self):
        client = _mock_client()
        client.create_issue.side_effect = JIRAError("nope")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.create_issue("XYZ", "s", "d")
        assert result["key"] is None
        assert result["url"] is None
        assert "nope" in result["error"]


class TestUpdateIssueErrors:
    def test_jira_error(self):
        client = _mock_client()
        client.issue.side_effect = JIRAError("locked")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.update_issue("ABC-2", summary="s")
        assert result["key"] == "ABC-2"
        assert result["updated"] == []
        assert "locked" in result["error"]

    def test_non_jira_exception(self):
        client = _mock_client()
        client.issue.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.update_issue("ABC-2", summary="s")
        assert result == {"key": "ABC-2", "updated": [], "error": "boom"}


class TestAddWatchersErrors:
    def test_client_error_remaining(self):
        with patch.object(jira_ops, "get_client", side_effect=RuntimeError("down")):
            result = jira_ops.add_watchers("ABC-1", ["a1", "a2"])
        assert result == {"added": [], "failed": ["a1", "a2"], "error": "down"}


class TestSearchIssuesOptionalFields:
    def _result_set(self, issues):
        result_set = MagicMock()
        result_set.__iter__ = lambda self: iter(issues)
        result_set.total = len(issues)
        return result_set

    def _issue_mock(self):
        issue = MagicMock()
        issue.key = "ABC-1"
        issue.fields.summary = "s"
        issue.fields.status = "Open"
        issue.fields.issuetype = "Task"
        issue.fields.assignee = None
        issue.fields.created = "2026-01-01T00:00:00Z"
        issue.fields.labels = ["l1"]
        issue.fields.fixVersions = None
        issue.fields.priority = None
        issue.fields.components = None
        issue.fields.customfield_10855 = None
        return issue

    def test_all_optional_fields(self):
        client = _mock_client()
        client.search_issues.return_value = self._result_set([self._issue_mock()])
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues(
                "jql",
                fields=[
                    "key",
                    "summary",
                    "status",
                    "issuetype",
                    "assignee",
                    "created",
                    "labels",
                    "fixVersions",
                    "priority",
                    "components",
                    "target_versions",
                ],
            )
        entry = result["issues"][0]
        assert entry["assignee"] == "Unassigned"
        assert entry["created"] == "2026-01-01T00:00:00Z"
        assert entry["labels"] == ["l1"]
        assert entry["fix_versions"] == []
        assert entry["priority"] is None
        assert entry["components"] == []
        assert entry["target_versions"] == []

    def test_optional_fields_with_values(self):
        client = _mock_client()
        issue = self._issue_mock()
        issue.fields.assignee = "Bob"
        fix_v1 = MagicMock()
        fix_v1.name = "v1"
        issue.fields.fixVersions = [fix_v1]
        issue.fields.priority = "High"
        comp_c1 = MagicMock()
        comp_c1.name = "C1"
        issue.fields.components = [comp_c1]
        target_v1 = MagicMock()
        target_v1.name = "tv1"
        issue.fields.customfield_10855 = [target_v1]
        client.search_issues.return_value = self._result_set([issue])
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues(
                "jql",
                fields=["key", "assignee", "fixVersions", "priority", "components", "target_versions"],
            )
        entry = result["issues"][0]
        assert entry["assignee"] == "Bob"
        assert entry["fix_versions"] == ["v1"]
        assert entry["priority"] == "High"
        assert entry["components"] == ["C1"]
        assert entry["target_versions"] == ["tv1"]


class TestSearchUserErrors:
    def test_error(self):
        client = _mock_client()
        client.search_users.side_effect = RuntimeError("down")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_user("Nobody")
        assert result["found"] is False
        assert result["error"] == "down"


class TestLinkIssuesErrors:
    def test_jira_error(self):
        client = _mock_client()
        client.create_issue_link.side_effect = JIRAError("link denied")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.link_issues("A-1", "B-2", link_type="Blocks")
        assert result["from_key"] == "A-1"
        assert result["to_key"] == "B-2"
        assert result["link_type"] == "Blocks"
        assert result["ok"] is False
        assert "link denied" in result["error"]

    def test_generic_error(self):
        client = _mock_client()
        client.create_issue_link.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.link_issues("A-1", "B-2")
        assert result["ok"] is False
        assert result["error"] == "boom"


class TestDeleteIssueLink:
    def test_success(self):
        client = _mock_client()
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.delete_issue_link("42")
        assert result == {"ok": True, "link_id": "42"}
        client._session.delete.assert_called_once_with("https://redhat.atlassian.net/rest/api/2/issueLink/42")

    def test_jira_error(self):
        client = _mock_client()
        client._session.delete.side_effect = JIRAError("gone")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.delete_issue_link("42")
        assert result["ok"] is False
        assert result["link_id"] == "42"
        assert "gone" in result["error"]

    def test_generic_error(self):
        client = _mock_client()
        client._session.delete.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.delete_issue_link("42")
        assert result["ok"] is False
        assert result["error"] == "boom"


class TestTransitionIssueErrors:
    def test_jira_error(self):
        client = _mock_client()
        client.issue.side_effect = JIRAError("locked")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.transition_issue("ABC-4", "Done")
        assert result["key"] == "ABC-4"
        assert result["ok"] is False
        assert "locked" in result["error"]

    def test_generic_error(self):
        client = _mock_client()
        client.transitions.side_effect = RuntimeError("boom")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.transition_issue("ABC-4", "Done")
        assert result == {"key": "ABC-4", "ok": False, "error": "boom"}


class TestMainCLI:
    def _set_argv(self, monkeypatch, *argv):
        monkeypatch.setattr("sys.argv", ["jira_ops.py", *argv])

    def test_verify_auth(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "verify-auth")
        monkeypatch.setattr(jira_ops, "verify_auth", lambda **k: {"ok": True, "user": "u", "error": None})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out) == {"ok": True, "user": "u", "error": None}

    def test_get_issue(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "get-issue", "--key", "ABC-1", "--fields", "labels,priority")
        monkeypatch.setattr(jira_ops, "get_issue", lambda key, fields=None: {"key": key, "fields": fields})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out)["fields"] == ["labels", "priority"]

    def test_add_comment(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "add-comment", "--key", "ABC-1", "--body", "hi")
        monkeypatch.setattr(jira_ops, "add_comment", lambda key, body: {"ok": True})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out) == {"ok": True}

    def test_create_issue(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "create-issue", "--project", "P", "--summary", "s", "--description", "d")
        monkeypatch.setattr(jira_ops, "create_issue", lambda *a, **k: {"key": "P-1", "url": "u"})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out)["key"] == "P-1"

    def test_update_issue(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "update-issue", "--key", "P-1", "--summary", "s2", "--labels", "a", "b")
        monkeypatch.setattr(jira_ops, "update_issue", lambda key, **k: {"key": key, "updated": ["summary", "labels"]})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out)["updated"] == ["summary", "labels"]

    def test_search(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "search", "--jql", "j", "--fields", "labels")
        monkeypatch.setattr(jira_ops, "search_issues", lambda jql, **k: {"issues": [], "total": 0})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out) == {"issues": [], "total": 0}

    def test_search_error_exits_1(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "search", "--jql", "bad")
        monkeypatch.setattr(
            jira_ops,
            "search_issues",
            lambda jql, **k: (_ for _ in ()).throw(jira_ops.JiraSearchError("bad jql", "bad", 400)),
        )
        with pytest.raises(SystemExit) as exc_info:
            jira_ops.main()
        assert exc_info.value.code == 1
        assert json.loads(capsys.readouterr().err)["jql"] == "bad"

    def test_search_user(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "search-user", "--name", "Alice")
        monkeypatch.setattr(jira_ops, "search_user", lambda name: {"found": True})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out) == {"found": True}

    def test_link_issues(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "link-issues", "--from", "A-1", "--to", "B-2", "--link-type", "Blocks")
        monkeypatch.setattr(jira_ops, "link_issues", lambda a, b, link_type=None: {"ok": True})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out) == {"ok": True}

    def test_transition(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "transition", "--key", "A-1", "--transition", "Done", "--resolution", "Done")
        monkeypatch.setattr(jira_ops, "transition_issue", lambda key, name, resolution=None: {"ok": True})
        jira_ops.main()
        assert json.loads(capsys.readouterr().out) == {"ok": True}

    def test_no_command_prints_help_and_exits_1(self, monkeypatch, capsys):
        self._set_argv(monkeypatch)
        with pytest.raises(SystemExit) as exc_info:
            jira_ops.main()
        assert exc_info.value.code == 1
        assert "usage" in capsys.readouterr().out.lower()
