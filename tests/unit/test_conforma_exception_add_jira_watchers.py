"""Tests for conforma-exception add_jira_watchers.py."""

from __future__ import annotations

from unittest.mock import patch

import add_jira_watchers


WATCHER_ACCOUNT = {
    "accountId": "abc123",
    "displayName": "Jane Doe",
    "emailAddress": "jane@redhat.com",
}


class TestResolveWatchers:
    def test_resolves_display_names(self):
        with patch.object(
            add_jira_watchers,
            "_search_user",
            side_effect=[
                {"accountId": "abc123", "displayName": "Jane Doe", "emailAddress": "jane@redhat.com"},
                {"accountId": "def456", "displayName": "John Smith", "emailAddress": "john@redhat.com"},
            ],
        ):
            result = add_jira_watchers.resolve_watchers(["Jane Doe", "John Smith"])

        assert len(result["resolved"]) == 2
        assert result["not_found"] == []
        assert result["resolved"][0]["accountId"] == "abc123"

    def test_reports_not_found_names(self):
        with patch.object(
            add_jira_watchers,
            "_search_user",
            side_effect=[
                {"accountId": "abc123", "displayName": "Jane Doe", "emailAddress": "jane@redhat.com"},
                None,
            ],
        ):
            result = add_jira_watchers.resolve_watchers(["Jane Doe", "Unknown Person"])

        assert len(result["resolved"]) == 1
        assert result["not_found"] == ["Unknown Person"]


class TestAddWatchersToTicket:
    def test_standard_api_adds_watcher(self):
        with (
            patch.object(add_jira_watchers, "_get_standard_watchers", return_value=set()),
            patch.object(add_jira_watchers, "_jira_post", return_value={"ok": True, "status": 204, "error": ""}),
        ):
            result = add_jira_watchers.add_watchers_to_ticket(
                "RHOAIENG-12345",
                [WATCHER_ACCOUNT],
            )

        assert result["method"] == "standard_api"
        assert result["status"] == "updated"
        assert result["added"] == ["Jane Doe"]

    def test_standard_api_skips_existing_watcher(self):
        with patch.object(add_jira_watchers, "_get_standard_watchers", return_value={"abc123"}):
            result = add_jira_watchers.add_watchers_to_ticket(
                "RHOAIENG-12345",
                [WATCHER_ACCOUNT],
            )

        assert result["status"] == "no_change"
        assert result["already_present"] == ["Jane Doe"]
        assert result["added"] == []

    def test_custom_field_path_for_psx(self):
        issue = {
            "fields": {
                "customfield_10705": [],
                "reporter": {"displayName": "Reporter"},
                "assignee": {"displayName": "Assignee"},
            }
        }
        with (
            patch.object(add_jira_watchers, "_jira_get", return_value=issue),
            patch.object(add_jira_watchers, "_jira_put", return_value={"ok": True, "status": 204, "error": ""}),
        ):
            result = add_jira_watchers.add_watchers_to_ticket(
                "PSX-1040",
                [WATCHER_ACCOUNT],
            )

        assert result["method"] == "custom_field"
        assert result["status"] == "updated"
        assert result["added"] == ["Jane Doe"]

    def test_dry_run_standard_api(self):
        with (
            patch.object(add_jira_watchers, "_get_standard_watchers", return_value=set()),
            patch.object(add_jira_watchers, "_jira_post") as mock_post,
        ):
            result = add_jira_watchers.add_watchers_to_ticket(
                "RHOAIENG-99999",
                [WATCHER_ACCOUNT],
                dry_run=True,
            )

        assert result["status"] == "dry_run"
        assert result["would_add"] == ["Jane Doe"]
        mock_post.assert_not_called()


class TestAddWatchersToTickets:
    def test_batch_adds_to_multiple_tickets(self):
        ticket_result = {
            "ticket_key": "RHOAIENG-1",
            "method": "standard_api",
            "status": "updated",
            "added": ["Jane Doe"],
            "already_present": [],
            "errors": [],
        }
        with (
            patch.object(
                add_jira_watchers,
                "resolve_watchers",
                return_value={"resolved": [WATCHER_ACCOUNT], "not_found": []},
            ),
            patch.object(add_jira_watchers, "add_watchers_to_ticket", return_value=ticket_result) as mock_add,
        ):
            result = add_jira_watchers.add_watchers_to_tickets(
                ["RHOAIENG-1", "RHOAIENG-2"],
                ["Jane Doe"],
            )

        assert result["status"] == "completed"
        assert result["summary"]["total"] == 2
        assert result["summary"]["updated"] == 2
        assert mock_add.call_count == 2

    def test_error_when_user_not_found(self):
        with patch.object(
            add_jira_watchers,
            "resolve_watchers",
            return_value={"resolved": [], "not_found": ["Nobody Here"]},
        ):
            result = add_jira_watchers.add_watchers_to_tickets(
                ["RHOAIENG-1"],
                ["Nobody Here"],
            )

        assert result["status"] == "error"
        assert "Nobody Here" in result["error"]
        assert result["tickets"] == []

    def test_error_when_no_names_provided(self):
        result = add_jira_watchers.add_watchers_to_tickets(
            ["RHOAIENG-1"],
            None,
            auto_discover=False,
        )

        assert result["status"] == "error"
        assert "No watcher names" in result["error"]

    def test_auto_discover_merges_team_members(self):
        with (
            patch.object(
                add_jira_watchers,
                "discover_team",
                return_value={
                    "members": [{"displayName": "Team Member", "accountId": "team1"}],
                    "caller": {"displayName": "Me"},
                    "groups_checked": [],
                    "errors": [],
                },
            ),
            patch.object(
                add_jira_watchers,
                "resolve_watchers",
                return_value={
                    "resolved": [
                        WATCHER_ACCOUNT,
                        {"accountId": "team1", "displayName": "Team Member", "emailAddress": ""},
                    ],
                    "not_found": [],
                },
            ),
            patch.object(
                add_jira_watchers,
                "add_watchers_to_ticket",
                return_value={"status": "updated", "added": ["Jane Doe", "Team Member"]},
            ),
        ):
            result = add_jira_watchers.add_watchers_to_tickets(
                ["RHOAIENG-1"],
                ["Jane Doe"],
                auto_discover=True,
            )

        assert result["status"] == "completed"
        assert result["team_discovery"]["members_discovered"] == 1
        assert "Team Member" in result["watchers_added"]
