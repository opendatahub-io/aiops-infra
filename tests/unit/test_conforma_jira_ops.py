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


class TestParseAcliTable:
    def test_parses_simple_table(self):
        table = (
            "┌──────┬────────────────┬──────────┬──────────┬──────────┬───────────────────────────────────┐\n"
            "│ Type │ Key            │ Assignee │ Priority │ Status   │ Summary                           │\n"
            "├──────┼────────────────┼──────────┼──────────┼──────────┼───────────────────────────────────┤\n"
            "│ Bug  │ RHOAIENG-66102 │          │ Blocker  │ New      │ [Exception] hermetic_task.hermetic│\n"
            "└──────┴────────────────┴──────────┴──────────┴──────────┴───────────────────────────────────┘\n"
        )
        tickets = mod._parse_acli_table(table)
        assert len(tickets) == 1
        assert tickets[0]["key"] == "RHOAIENG-66102"
        assert tickets[0]["type"] == "Bug"
        assert tickets[0]["status"] == "New"

    def test_empty_table(self):
        assert mod._parse_acli_table("") == []
