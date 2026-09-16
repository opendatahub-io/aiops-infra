"""Tests for conforma_jira_ops.py."""

from __future__ import annotations

import json

import pytest

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


class TestExtractComponentsFromSummary:
    def test_standard_format(self):
        summary = "[Conforma Violation] hermetic_task.hermetic - odh-model-registry-v3-4, odh-vllm-cpu-v3-4 - rhoai-3.4"
        result = mod._extract_components_from_summary(summary)
        assert result == ["odh-model-registry", "odh-vllm-cpu"]

    def test_plus_n_more(self):
        summary = (
            "[Conforma Violation] hermetic_task.hermetic - comp-a-v3-4, comp-b-v3-4, comp-c-v3-4 (+2 more) - rhoai-3.4"
        )
        result = mod._extract_components_from_summary(summary)
        assert result == ["comp-a", "comp-b", "comp-c"]

    def test_with_vendor_tag(self):
        summary = "[prod] [Conforma Violation] hermetic_task.hermetic - odh-vllm-cpu-v3-4 - rhoai-3.4"
        result = mod._extract_components_from_summary(summary)
        assert result == ["odh-vllm-cpu"]

    def test_with_summary_context(self):
        summary = "[Conforma Violation] hermetic_task.hermetic - odh-vllm-cpu-v3-4 - rhoai-3.4 - some context"
        result = mod._extract_components_from_summary(summary)
        assert result == ["odh-vllm-cpu"]

    def test_freeform_summary(self):
        summary = "This is a manually created ticket about hermetic builds"
        assert mod._extract_components_from_summary(summary) == []

    def test_single_component(self):
        summary = "[Conforma Violation] hermetic_task.hermetic - odh-model-registry-job-async-upload-v3-4 - rhoai-3.4"
        result = mod._extract_components_from_summary(summary)
        assert result == ["odh-model-registry-job-async-upload"]

    def test_too_few_segments(self):
        summary = "hermetic_task.hermetic - rhoai-3.4"
        assert mod._extract_components_from_summary(summary) == []


class TestExtractComponentsFromDescription:
    def test_standard_format(self):
        desc = "Conforma Violation Report\n\nRule: hermetic_task.hermetic\nComponents: odh-model-registry-v3-4, odh-vllm-cpu-v3-4\nRHOAI Version: rhoai-3.4"
        result = mod._extract_components_from_description(desc)
        assert result == ["odh-model-registry", "odh-vllm-cpu"]

    def test_empty_description(self):
        assert mod._extract_components_from_description("") == []

    def test_none_description(self):
        assert mod._extract_components_from_description(None) == []

    def test_no_components_line(self):
        assert mod._extract_components_from_description("Just some text\nNo components here") == []

    def test_many_components(self):
        comps = ", ".join(f"comp-{i}-v3-4" for i in range(10))
        desc = f"Components: {comps}"
        result = mod._extract_components_from_description(desc)
        assert len(result) == 10
        assert result[0] == "comp-0"


class TestExtractComponentStems:
    def test_prefers_description_over_summary(self):
        summary = "[Conforma Violation] rule - comp-a-v3-4 (+2 more) - rhoai-3.4"
        desc = "Components: comp-a-v3-4, comp-b-v3-4, comp-c-v3-4"
        result = mod._extract_component_stems(summary, desc)
        assert result == ["comp-a", "comp-b", "comp-c"]

    def test_falls_back_to_summary(self):
        summary = "[Conforma Violation] rule - comp-a-v3-4 - rhoai-3.4"
        result = mod._extract_component_stems(summary, None)
        assert result == ["comp-a"]

    def test_empty_description_falls_back(self):
        summary = "[Conforma Violation] rule - comp-a-v3-4 - rhoai-3.4"
        result = mod._extract_component_stems(summary, "")
        assert result == ["comp-a"]

    def test_both_unparseable(self):
        result = mod._extract_component_stems("freeform text", "no components here")
        assert result == []


# ---------------------------------------------------------------------------
# prefetch_open_jira_tickets -- label-first discovery cutover (C8)
# ---------------------------------------------------------------------------
def _issue(key, summary, status="Open", issue_type="Task", fix_versions=None):
    """A ticket in the normalized shape returned by discover_conforma_tickets()."""
    return {
        "key": key,
        "url": f"https://redhat.atlassian.net/browse/{key}",
        "summary": summary,
        "status": status,
        "type": issue_type,
        "fix_versions": fix_versions or [],
    }


def _mock_discover(monkeypatch, issues):
    monkeypatch.setattr("conforma_jira_ticket_ops.discover_conforma_tickets", lambda **kw: issues)


class TestPrefetchDiscoveryBase:
    """Core discovery behavior of the C8 cutover."""

    def test_single_discovery_call(self, monkeypatch):
        calls = {"n": 0}

        def fake_discover(**kw):
            calls["n"] += 1
            return []

        monkeypatch.setattr("conforma_jira_ticket_ops.discover_conforma_tickets", fake_discover)
        mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])
        assert calls["n"] == 1

    def test_no_open_tickets(self, monkeypatch):
        _mock_discover(monkeypatch, [])
        assert mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"]) == {"hermetic_task.hermetic": []}

    def test_closed_tickets_dropped(self, monkeypatch):
        issues = [
            _issue("RHOAIENG-1", "hermetic_task.hermetic in odh-a", status="Done"),
            _issue("RHOAIENG-2", "hermetic_task.hermetic in odh-b", status="Closed"),
            _issue("RHOAIENG-3", "hermetic_task.hermetic in odh-c", status="Cancelled"),
        ]
        _mock_discover(monkeypatch, issues)
        assert mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"] == []

    def test_unknown_status_treated_open(self, monkeypatch):
        issues = [_issue("RHOAIENG-9", "hermetic_task.hermetic in odh-a", status="")]
        _mock_discover(monkeypatch, issues)
        result = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])
        assert [t["key"] for t in result["hermetic_task.hermetic"]] == ["RHOAIENG-9"]

    def test_all_rules_present_in_result(self, monkeypatch):
        _mock_discover(monkeypatch, [])
        result = mod.prefetch_open_jira_tickets(["r1", "r2", "r3"])
        assert result == {"r1": [], "r2": [], "r3": []}


class TestPrefetchPass1ExactRule:
    def test_exact_rule_in_summary_untagged(self, monkeypatch):
        issues = [
            _issue(
                "RHOAIENG-66102",
                "Conforma violation: hermetic_task.hermetic in odh-a - rhoai-3.4",
            ),
        ]
        _mock_discover(monkeypatch, issues)
        tickets = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"]
        assert len(tickets) == 1
        assert tickets[0]["key"] == "RHOAIENG-66102"
        assert "match_source" not in tickets[0]
        assert "inference_confidence" not in tickets[0]

    def test_output_shape_base_fields(self, monkeypatch):
        issues = [
            _issue(
                "RHOAIENG-66102",
                "Conforma violation: hermetic_task.hermetic in odh-a-v3-4, odh-b-v3-4 - rhoai-3.4",
            ),
        ]
        _mock_discover(monkeypatch, issues)
        ticket = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"][0]
        assert set(ticket) == {
            "key",
            "type",
            "status",
            "summary",
            "url",
            "fix_versions",
            "components",
            "matched_component_stems",
        }

    def test_components_default_from_deterministic_summary(self, monkeypatch):
        issues = [
            _issue(
                "RHOAIENG-66102",
                "Conforma violation: hermetic_task.hermetic in odh-a-v3-4, odh-b-v3-4 - rhoai-3.4",
            ),
        ]
        _mock_discover(monkeypatch, issues)
        ticket = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"][0]
        assert ticket["components"] == ["odh-a-v3-4", "odh-b-v3-4"]
        assert ticket["matched_component_stems"] == ["odh-a", "odh-b"]

    def test_legacy_summary_fallback(self, monkeypatch):
        issues = [
            _issue(
                "RHOAIENG-LEGACY",
                "[Conforma Violation] hermetic_task.hermetic - odh-model-registry-v3-4 - rhoai-3.4",
            ),
        ]
        _mock_discover(monkeypatch, issues)
        ticket = mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"][0]
        assert ticket["components"] == ["odh-model-registry"]
        assert ticket["matched_component_stems"] == ["odh-model-registry"]

    def test_freeform_summary_no_rule_match(self, monkeypatch):
        issues = [_issue("RHOAIENG-99999", "manually created ticket about hermetic builds")]
        _mock_discover(monkeypatch, issues)
        # No rule code in the summary and no rule_to_components -> no match at all.
        assert mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"] == []


class TestPrefetchPass2ComponentInference:
    def test_component_inference_confirmed(self, monkeypatch):
        issues = [_issue("RHOAIENG-70001", "hermetic build fix in odh-ogx-core")]
        _mock_discover(monkeypatch, issues)
        tickets = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )["hermetic_task.hermetic"]
        assert len(tickets) == 1
        assert tickets[0]["key"] == "RHOAIENG-70001"
        assert tickets[0]["match_source"] == "component_inference"
        assert tickets[0]["inference_confidence"] == "confirmed"

    def test_component_inference_unconfirmed(self, monkeypatch):
        issues = [_issue("RHOAIENG-70002", "conforma issue in odh-ogx-core")]
        _mock_discover(monkeypatch, issues)
        tickets = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )["hermetic_task.hermetic"]
        assert len(tickets) == 1
        assert tickets[0]["match_source"] == "component_inference"
        assert tickets[0]["inference_confidence"] == "unconfirmed"

    def test_no_rule_to_components_skips_pass2(self, monkeypatch):
        issues = [_issue("RHOAIENG-70003", "conforma issue in odh-ogx-core")]
        _mock_discover(monkeypatch, issues)
        assert mod.prefetch_open_jira_tickets(["hermetic_task.hermetic"])["hermetic_task.hermetic"] == []

    def test_empty_konflux_components_skipped(self, monkeypatch):
        issues = [_issue("RHOAIENG-70004", "conforma issue in odh-ogx-core")]
        _mock_discover(monkeypatch, issues)
        assert (
            mod.prefetch_open_jira_tickets(
                ["hermetic_task.hermetic"],
                rule_to_components={"hermetic_task.hermetic": []},
            )["hermetic_task.hermetic"]
            == []
        )

    def test_alias_only_text_match(self, monkeypatch):
        issues = [_issue("RHOAIENG-70005", "conforma issue in odh-llama-cpp-server")]
        _mock_discover(monkeypatch, issues)
        aliases = {
            "odh-ogx-core-v3-5-ea-1": {
                "odh-ogx-core-v3-5-ea-1",
                "odh-llama-cpp-server-v3-5-ea-1",
            },
        }
        tickets = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
            aliases=aliases,
        )["hermetic_task.hermetic"]
        assert len(tickets) == 1
        assert tickets[0]["key"] == "RHOAIENG-70005"
        assert tickets[0]["match_source"] == "component_inference"

    def test_already_assigned_ticket_not_duplicated(self, monkeypatch):
        # T1 carries the rule code (pass 1 -> rule A) and also names rule B's
        # component -> it is assigned only to A, never duplicated into B.
        issues = [_issue("RHOAIENG-11111", "hermetic_task.hermetic for odh-ogx-core")]
        _mock_discover(monkeypatch, issues)
        result = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic", "other.rule"],
            rule_to_components={"other.rule": ["odh-ogx-core-v3-5-ea-1"]},
        )
        assert [t["key"] for t in result["hermetic_task.hermetic"]] == ["RHOAIENG-11111"]
        assert result["other.rule"] == []

    def test_component_inference_tagged_shape(self, monkeypatch):
        issues = [_issue("RHOAIENG-70006", "conforma issue in odh-ogx-core")]
        _mock_discover(monkeypatch, issues)
        ticket = mod.prefetch_open_jira_tickets(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )["hermetic_task.hermetic"][0]
        assert set(ticket) == {
            "key",
            "type",
            "status",
            "summary",
            "url",
            "fix_versions",
            "components",
            "matched_component_stems",
            "match_source",
            "inference_confidence",
        }


# ---------------------------------------------------------------------------
# Direct helper coverage (C8) -- deterministic component / matching primitives
# ---------------------------------------------------------------------------
class TestSummaryComponentNames:
    def test_deterministic_format(self):
        assert mod._summary_component_names(
            "Conforma violation: hermetic_task.hermetic in odh-a-v3-4, odh-b-v3-4 - rhoai-3.4"
        ) == ["odh-a-v3-4", "odh-b-v3-4"]

    def test_no_in_part_returns_empty(self):
        assert mod._summary_component_names("Conforma violation: hermetic_task.hermetic") == []

    def test_non_conforma_prefix_returns_empty(self):
        assert (
            mod._summary_component_names("[Conforma Violation] hermetic_task.hermetic - odh-a-v3-4 - rhoai-3.4") == []
        )


class TestDescriptionComponentNames:
    def test_standard_components_line(self):
        desc = (
            "Conforma Violation Report\n\n"
            "Rule: hermetic_task.hermetic\n"
            "Components: odh-a-v3-4, odh-b\n"
            "RHOAI Version: rhoai-3.4"
        )
        assert mod._description_component_names(desc) == ["odh-a-v3-4", "odh-b"]

    def test_components_line_empty_returns_empty(self):
        assert mod._description_component_names("Components:   ") == []

    def test_no_components_line_returns_empty(self):
        assert mod._description_component_names("just some text\nno components here") == []

    def test_empty_and_none_description(self):
        assert mod._description_component_names("") == []
        assert mod._description_component_names(None) == []


class TestNormalizeTicketDirect:
    def test_base_fields_without_tags(self):
        ticket = {
            "key": "RHOAIENG-1",
            "url": "https://j/RHOAIENG-1",
            "summary": "Conforma violation: r in odh-a-v3-4",
            "status": "Open",
            "type": "Bug",
            "fix_versions": [],
        }
        result = mod._normalize_ticket(ticket)
        assert "match_source" not in result
        assert "inference_confidence" not in result
        assert result["components"] == ["odh-a-v3-4"]
        assert result["matched_component_stems"] == ["odh-a"]

    def test_explicit_components_override(self):
        ticket = {"key": "K", "summary": "Conforma violation: r in odh-a-v3-4"}
        assert mod._normalize_ticket(ticket, components=["odh-z"])["components"] == ["odh-z"]

    def test_with_inference_tags(self):
        ticket = {"key": "K", "summary": "conforma issue in odh-ogx-core"}
        result = mod._normalize_ticket(
            ticket,
            match_source="component_inference",
            inference_confidence="unconfirmed",
        )
        assert result["match_source"] == "component_inference"
        assert result["inference_confidence"] == "unconfirmed"


class TestRuleMatches:
    def test_exact_rule_in_summary(self):
        assert mod.rule_matches({"summary": "hermetic_task.hermetic issue"}, "hermetic_task.hermetic") is True

    def test_confirmed_by_text(self):
        ticket = {"summary": "conforma issue in odh-x", "description": "make the build hermetic"}
        assert mod.rule_matches(ticket, "hermetic_task.hermetic") is True

    def test_no_match(self):
        assert mod.rule_matches({"summary": "unrelated"}, "hermetic_task.hermetic") is False


class TestKonfluxStemsInText:
    def test_empty_components(self):
        assert mod._konflux_stems_in_text({"summary": "anything"}, [], None) == []

    def test_direct_stem_in_summary(self):
        ticket = {"summary": "conforma issue in odh-ogx-core"}
        assert mod._konflux_stems_in_text(ticket, ["odh-ogx-core-v3-5-ea-1"], None) == ["odh-ogx-core"]

    def test_alias_expansion(self):
        ticket = {"summary": "conforma issue in odh-llama-cpp-server"}
        aliases = {
            "odh-ogx-core-v3-5-ea-1": {
                "odh-ogx-core-v3-5-ea-1",
                "odh-llama-cpp-server-v3-5-ea-1",
            },
        }
        assert mod._konflux_stems_in_text(ticket, ["odh-ogx-core-v3-5-ea-1"], aliases) == ["odh-llama-cpp-server"]

    def test_no_stem_in_text(self):
        assert mod._konflux_stems_in_text({"summary": "unrelated"}, ["odh-ogx-core-v3-5-ea-1"], None) == []


class TestPrefetchPass2NoStem:
    def test_ticket_without_component_skipped(self, monkeypatch):
        issues = [_issue("RHOAIENG-80001", "conforma issue in odh-unrelated")]
        _mock_discover(monkeypatch, issues)
        assert (
            mod.prefetch_open_jira_tickets(
                ["hermetic_task.hermetic"],
                rule_to_components={"hermetic_task.hermetic": ["odh-target"]},
            )["hermetic_task.hermetic"]
            == []
        )


# ---------------------------------------------------------------------------
# Pure helper edge cases
# ---------------------------------------------------------------------------
class TestExtractComponentsFromSummaryEdges:
    def test_three_parts_with_plus_n_more(self):
        summary = "rule - odh-a-v3-4, odh-b-v3-4 (+3 more) - context"
        assert mod._extract_components_from_summary(summary) == ["odh-a", "odh-b"]

    def test_four_parts_uses_second_segment(self):
        summary = "[tag1] [tag2] rule - odh-a-v3-4 - rhoai-3.4 - context"
        assert mod._extract_components_from_summary(summary) == ["odh-a"]

    def test_blank_component_segment(self):
        assert mod._extract_components_from_summary("a -  - c") == []

    def test_too_few_parts(self):
        assert mod._extract_components_from_summary("rule - comp") == []


class TestExtractComponentsFromDescriptionEdges:
    def test_empty_description(self):
        assert mod._extract_components_from_description("") == []
        assert mod._extract_components_from_description(None) == []

    def test_components_line_empty(self):
        assert mod._extract_components_from_description("Components:") == []

    def test_components_line_parsed(self):
        assert mod._extract_components_from_description("Components: odh-a-v3-4, odh-b") == [
            "odh-a",
            "odh-b",
        ]

    def test_no_components_line(self):
        assert mod._extract_components_from_description("no list here") == []


class TestInferRuleFromTextEdges:
    def test_same_rule_prefix_different_suffix_confirmed_by_suffix_in_text(self):
        text = "about rpm_signature.allowed:aaaa111122223333 and 1234567890abcdef"
        assert mod._infer_rule_from_text(text, "rpm_signature.allowed:1234567890abcdef") == "confirmed"

    def test_rule_family_with_colon_in_first_segment(self):
        # rule.split(".")[0] contains a colon -> rule_family is re-split
        text = "weird:prefix.name:suffix appears here"
        assert mod._infer_rule_from_text(text, "weird:prefix.name:suffix") == "confirmed"


class TestMain:
    def test_search_tickets(self, monkeypatch, capsys):
        monkeypatch.setattr(
            "sys.argv",
            ["conforma_jira_ops.py", "search-tickets", "--rules", "r1,r2"],
        )
        monkeypatch.setattr("conforma_jira_ticket_ops.discover_conforma_tickets", lambda **kw: [])
        mod.main()
        assert json.loads(capsys.readouterr().out) == {"r1": [], "r2": []}

    def test_no_command_prints_help_and_exits(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["conforma_jira_ops.py"])
        with pytest.raises(SystemExit):
            mod.main()
        assert "usage" in capsys.readouterr().out.lower()
