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


class TestStripVersionSuffix:
    def test_strips_ea_suffix(self):
        assert mod._strip_version_suffix("odh-ogx-core-v3-5-ea-1") == "odh-ogx-core"

    def test_strips_simple_suffix(self):
        assert mod._strip_version_suffix("odh-spark-operator-v3-5") == "odh-spark-operator"

    def test_no_suffix_unchanged(self):
        assert mod._strip_version_suffix("odh-ogx-core") == "odh-ogx-core"

    def test_strips_v2_25(self):
        assert mod._strip_version_suffix("rhoai-fbc-fragment-v2-25") == "rhoai-fbc-fragment"


class TestInferRuleFromText:
    def test_confirmed_exact_rule_in_text(self):
        text = "This ticket is about hermetic_task.hermetic violation in the component"
        assert mod._infer_rule_from_text(text, "hermetic_task.hermetic") == "confirmed"

    def test_confirmed_hermetic_keyword(self):
        text = "We need to make this build hermetic for conforma compliance"
        assert mod._infer_rule_from_text(text, "hermetic_task.hermetic") == "confirmed"

    def test_confirmed_rpm_signature_keyword(self):
        text = "The RPM signature check failed, signing key not in allowed list"
        assert mod._infer_rule_from_text(text, "rpm_signature.allowed:9386b48a1a693c5c") == "confirmed"

    def test_confirmed_suffix_in_text(self):
        text = "conforma exception for 9386b48a1a693c5c"
        assert mod._infer_rule_from_text(text, "rpm_signature.allowed:9386b48a1a693c5c") == "confirmed"

    def test_confirmed_test_failure_keyword(self):
        text = "The test failure for deprecated-image-check needs to be resolved"
        assert mod._infer_rule_from_text(text, "test.no_failed_tests:deprecated-image-check") == "confirmed"

    def test_confirmed_test_task_suffix(self):
        text = "Investigating deprecated-image-check conforma issue"
        assert mod._infer_rule_from_text(text, "test.no_failed_tests:deprecated-image-check") == "confirmed"

    def test_unconfirmed_no_relevant_keywords(self):
        text = "General conforma discussion about this component"
        assert mod._infer_rule_from_text(text, "hermetic_task.hermetic") == "unconfirmed"

    def test_unconfirmed_empty_text(self):
        assert mod._infer_rule_from_text("", "hermetic_task.hermetic") == "unconfirmed"

    def test_unconfirmed_none_text(self):
        assert mod._infer_rule_from_text(None, "hermetic_task.hermetic") == "unconfirmed"


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

    def test_pass4_finds_ticket_by_component_name(self, monkeypatch):
        """Pass 4 finds a ticket via component name when passes 1-3 return nothing."""
        call_count = {"n": 0}

        def fake_search(jql, **kw):
            call_count["n"] += 1
            # Passes 1-3 return empty
            if "conforma" not in jql:
                return {"issues": [], "total": 0}
            # Pass 4: component-based search finds a ticket
            return {"issues": [
                {"key": "RHOAIENG-70000", "url": "https://redhat.atlassian.net/browse/RHOAIENG-70000",
                 "summary": "Fix hermetic builds for odh-ogx-core",
                 "description": "Make the build hermetic for conforma compliance",
                 "status": "In Progress", "type": "Task", "fix_versions": []},
            ], "total": 1}

        monkeypatch.setattr("jira_ops.search_issues", fake_search)
        result = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )
        assert len(result["hermetic_task.hermetic"]) == 1
        ticket = result["hermetic_task.hermetic"][0]
        assert ticket["key"] == "RHOAIENG-70000"
        assert ticket["match_source"] == "component_inference"
        assert ticket["inference_confidence"] == "confirmed"

    def test_pass4_expands_aliases(self, monkeypatch):
        """Pass 4 searches for aliased component names too."""
        captured_jqls = []

        def fake_search(jql, **kw):
            captured_jqls.append(jql)
            if "conforma" in jql and "odh-llama-cpp-server" in jql:
                return {"issues": [
                    {"key": "RHOAIENG-70001", "url": "https://redhat.atlassian.net/browse/RHOAIENG-70001",
                     "summary": "Conforma fix for odh-llama-cpp-server hermetic",
                     "description": "hermetic build fix",
                     "status": "New", "type": "Task", "fix_versions": []},
                ], "total": 1}
            return {"issues": [], "total": 0}

        monkeypatch.setattr("jira_ops.search_issues", fake_search)
        aliases = {
            "odh-ogx-core-v3-5-ea-1": {"odh-ogx-core-v3-5-ea-1", "odh-llama-cpp-server-v3-5-ea-1"},
            "odh-llama-cpp-server-v3-5-ea-1": {"odh-ogx-core-v3-5-ea-1", "odh-llama-cpp-server-v3-5-ea-1"},
        }
        result = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
            aliases=aliases,
        )
        # Should find the ticket via the llama alias
        assert len(result["hermetic_task.hermetic"]) == 1
        ticket = result["hermetic_task.hermetic"][0]
        assert ticket["key"] == "RHOAIENG-70001"
        assert ticket["match_source"] == "component_inference"
        # JQL should include both stems (filter for pass-4 specific pattern)
        pass4_jql = [j for j in captured_jqls if 'text ~ "conforma"' in j]
        assert len(pass4_jql) == 1
        assert "odh-ogx-core" in pass4_jql[0]
        assert "odh-llama-cpp-server" in pass4_jql[0]

    def test_pass4_deduplicates_against_earlier_passes(self, monkeypatch):
        """Tickets already found by passes 1-3 are not duplicated by pass 4."""
        call_count = {"n": 0}

        def fake_search(jql, **kw):
            call_count["n"] += 1
            # Pass 1: finds the ticket by rule code
            if call_count["n"] == 1:
                return {"issues": [
                    {"key": "RHOAIENG-11111", "url": "https://redhat.atlassian.net/browse/RHOAIENG-11111",
                     "summary": "hermetic_task.hermetic for odh-ogx-core", "status": "New", "type": "Bug"},
                ], "total": 1}
            # Pass 4 would also find it
            if "conforma" in jql:
                return {"issues": [
                    {"key": "RHOAIENG-11111", "url": "https://redhat.atlassian.net/browse/RHOAIENG-11111",
                     "summary": "hermetic_task.hermetic for odh-ogx-core",
                     "description": "hermetic build conforma",
                     "status": "New", "type": "Bug", "fix_versions": []},
                ], "total": 1}
            return {"issues": [], "total": 0}

        monkeypatch.setattr("jira_ops.search_issues", fake_search)
        result = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )
        # Should only have 1 ticket (not duplicated)
        assert len(result["hermetic_task.hermetic"]) == 1
        # Should NOT have match_source since it was found by pass 1
        assert "match_source" not in result["hermetic_task.hermetic"][0]

    def test_pass4_unconfirmed_ticket_included(self, monkeypatch):
        """Tickets with unconfirmed rule inference are still included."""
        def fake_search(jql, **kw):
            if "conforma" in jql:
                return {"issues": [
                    {"key": "RHOAIENG-70002", "url": "https://redhat.atlassian.net/browse/RHOAIENG-70002",
                     "summary": "Conforma issue for odh-ogx-core",
                     "description": "Something about conforma for this component",
                     "status": "Open", "type": "Task", "fix_versions": []},
                ], "total": 1}
            return {"issues": [], "total": 0}

        monkeypatch.setattr("jira_ops.search_issues", fake_search)
        result = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )
        assert len(result["hermetic_task.hermetic"]) == 1
        ticket = result["hermetic_task.hermetic"][0]
        assert ticket["inference_confidence"] == "unconfirmed"

    def test_pass4_skipped_without_rule_to_components(self, monkeypatch):
        """Pass 4 is skipped when rule_to_components is not provided."""
        monkeypatch.setattr("jira_ops.search_issues", lambda jql, **kw: {"issues": [], "total": 0})
        result = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])
        assert result["hermetic_task.hermetic"] == []
