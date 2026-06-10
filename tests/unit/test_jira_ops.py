"""Tests for scripts/jira_ops.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


class TestGetIssue:
    def test_success(self):
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

    def test_error(self):
        client = _mock_client()
        client.issue.side_effect = JIRAError("Issue not found")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.get_issue("ABC-999")

        assert result["key"] == "ABC-999"
        assert result["summary"] is None
        assert "error" in result


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

    def test_no_fields(self):
        result = jira_ops.update_issue("ABC-2")
        assert result == {"key": "ABC-2", "updated": [], "error": "No fields to update"}


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

    def test_error(self):
        client = _mock_client()
        client.search_issues.side_effect = JIRAError("Bad JQL")
        with patch.object(jira_ops, "get_client", return_value=client):
            result = jira_ops.search_issues("invalid jql")

        assert result["total"] == 0
        assert result["issues"] == []
        assert "error" in result

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
        client.create_issue_link.assert_called_once_with(
            type={"name": "Blocks"},
            inwardIssue="ABC-1",
            outwardIssue="ABC-2",
        )


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
        }
        client.transition_issue.assert_called_once_with(issue, "21")

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
