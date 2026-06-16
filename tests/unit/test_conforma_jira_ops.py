"""Tests for conforma_jira_ops.py."""

from __future__ import annotations

import conforma_jira_ops as mod


class TestExtractRuleFromSummary:
    def test_rpm_signature_with_hex(self):
        assert (
            mod._extract_rule_from_summary("[Exception Approval] rpm_signature.allowed:9386b48a1a693c5c")
            == "rpm_signature.allowed:9386b48a1a693c5c"
        )

    def test_signed_with_key(self):
        assert (
            mod._extract_rule_from_summary("RPM signed with 9386b48a1a693c5c key")
            == "rpm_signature.allowed:9386b48a1a693c5c"
        )

    def test_signing_key_pattern(self):
        assert (
            mod._extract_rule_from_summary("signing key 1234567890abcdef found")
            == "rpm_signature.allowed:1234567890abcdef"
        )

    def test_hermetic_task(self):
        assert mod._extract_rule_from_summary("hermetic_task.hermetic violation") == "hermetic_task.hermetic"

    def test_schedule_rule(self):
        assert mod._extract_rule_from_summary("schedule.weekday_restriction") == "schedule.weekday_restriction"

    def test_test_rule(self):
        assert mod._extract_rule_from_summary("test.some_test:param") == "test.some_test:param"

    def test_no_match(self):
        assert mod._extract_rule_from_summary("unrelated ticket summary") is None


class TestExtractTicketKey:
    def test_extracts_rhoaieng(self):
        assert mod._extract_ticket_key("https://redhat.atlassian.net/browse/RHOAIENG-12345") == "RHOAIENG-12345"

    def test_extracts_psx(self):
        assert mod._extract_ticket_key("https://redhat.atlassian.net/browse/PSX-678") == "PSX-678"

    def test_no_match(self):
        assert mod._extract_ticket_key("https://example.com/no-ticket") is None


class TestBuildReleaseVersionPatterns:
    def test_full_version(self):
        patterns = mod._build_release_version_patterns(["rhoai-3.5-ea.1"])
        assert "rhoai-3.5-ea.1" in patterns
        assert "3.5-ea.1" in patterns
        assert "v3-5-ea-1" in patterns
        assert "v3.5" in patterns

    def test_simple_version(self):
        patterns = mod._build_release_version_patterns(["rhoai-3.4"])
        assert "rhoai-3.4" in patterns
        assert "3.4" in patterns
        assert "v3-4" in patterns


class TestTicketMatchesRelease:
    def test_matches_full_branch_name(self):
        assert mod._ticket_matches_release(
            {"summary": "Exception for rhoai-3.4"},
            ["rhoai-3.4", "3.4", "v3-4"],
        )

    def test_no_match(self):
        assert not mod._ticket_matches_release(
            {"summary": "Exception for rhoai-2.25"},
            ["rhoai-3.4", "3.4", "v3-4"],
        )


class TestClassifyTicketVersionRelevance:
    def test_targets_current_exact_match(self):
        ticket = {"fix_versions": ["RHOAI 3.5-ea.1"]}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "targets_current"

    def test_targets_current_partial_match(self):
        ticket = {"fix_versions": ["3.5-ea.1"]}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "targets_current"

    def test_targets_future(self):
        ticket = {"fix_versions": ["RHOAI 3.6"]}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "targets_future"

    def test_no_target_version(self):
        ticket = {"fix_versions": []}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "no_target_version"

    def test_no_fix_versions_key(self):
        ticket = {}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "no_target_version"

    def test_multiple_versions_one_matches(self):
        ticket = {"fix_versions": ["RHOAI 3.6", "RHOAI 3.5-ea.1"]}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "targets_current"

    def test_targets_current_short_version(self):
        ticket = {"fix_versions": ["v3.5"]}
        assert mod.classify_ticket_version_relevance(ticket, "rhoai-3.5-ea.1") == "targets_current"


class TestPrefetchOpenJiraTickets:
    def test_matches_tickets_to_rules(self, monkeypatch):
        fake_issues = [
            {"key": "RHOAIENG-66102", "url": "https://redhat.atlassian.net/browse/RHOAIENG-66102",
             "summary": "[Exception] hermetic_task.hermetic for rhoai-3.4", "status": "New", "type": "Bug"},
            {"key": "PSX-1097", "url": "https://redhat.atlassian.net/browse/PSX-1097",
             "summary": "[AMD] rpm_signature.allowed:9386b48a1a693c5c rhoai-3.4", "status": "In Progress", "type": "Task"},
        ]
        monkeypatch.setattr("jira_ops.search_issues", lambda jql, **kw: {"issues": fake_issues, "total": 2})
        result = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic", "rpm_signature.allowed:9386b48a1a693c5c"],
            releases=["rhoai-3.4"],
        )
        assert len(result["hermetic_task.hermetic"]) == 1
        assert result["hermetic_task.hermetic"][0]["key"] == "RHOAIENG-66102"
        assert len(result["rpm_signature.allowed:9386b48a1a693c5c"]) == 1
        assert result["rpm_signature.allowed:9386b48a1a693c5c"][0]["key"] == "PSX-1097"

    def test_returns_empty_on_no_results(self, monkeypatch):
        monkeypatch.setattr("jira_ops.search_issues", lambda jql, **kw: {"issues": [], "total": 0})
        result = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])
        assert result["hermetic_task.hermetic"] == []

    def test_label_fallback_search(self, monkeypatch):
        call_count = {"n": 0}

        def fake_search(jql, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"issues": [], "total": 0}
            return {"issues": [
                {"key": "RHOAIENG-99", "url": "https://redhat.atlassian.net/browse/RHOAIENG-99",
                 "summary": "found via label", "status": "Open", "type": "Bug"},
            ], "total": 1}

        monkeypatch.setattr("jira_ops.search_issues", fake_search)
        result = mod.prefetch_open_jira_tickets(["some.rule"])
        assert len(result["some.rule"]) == 1
        assert result["some.rule"][0]["key"] == "RHOAIENG-99"
