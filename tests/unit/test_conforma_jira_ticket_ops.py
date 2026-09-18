"""Tests for scripts/conforma_jira_ticket_ops.py (dual-mode: CLI + importable).

All Jira and catalog I/O is mocked -- no live calls.
"""

from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

import conforma_jira_ticket_ops as mod
import pytest

JIRA_BASE = "https://redhat.atlassian.net"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
CATALOG = [
    {
        "konflux_components": ["odh-ogx-core"],
        "jira_components": [{"name": "AI-Guardrails"}],
        "team": "AI-Guardrails",
    },
    {
        "konflux_components": ["odh-vllm"],
        "jira_components": ["AI Serving"],
        "org": "Serving",
    },
]

OPEN_TICKET = {
    "key": "RHOAIENG-80001",
    "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef in odh-ogx-core",
    "description": "Components: odh-ogx-core",
    "status": "In Progress",
    "labels": ["conforma", "conforma-violation"],
    "components": ["AI-Guardrails"],
    "priority": "Blocker",
    "assignee": "Bob",
    "target_versions": ["RHOAI 3.6"],
    "url": f"{JIRA_BASE}/browse/RHOAIENG-80001",
}

CLOSED_TICKET = {
    "key": "RHOAIENG-70681",
    "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef in odh-ogx-core",
    "description": "Components: odh-ogx-core",
    "status": "Closed",
    "labels": ["conforma-exception-ai-skill"],
    "components": ["AI-Guardrails"],
    "priority": "Blocker",
    "assignee": None,
    "target_versions": ["RHOAI 3.6"],
    "url": f"{JIRA_BASE}/browse/RHOAIENG-70681",
}


def _violation(**overrides):
    violation = {
        "rule": "rpm_signature.allowed:1234567890abcdef",
        "coverage": "not_covered",
        "uncovered_components": ["odh-ogx-core-v3-6"],
        "all_components": ["odh-ogx-core-v3-6"],
        "jira_components": ["AI-Guardrails"],
        "detail": "RPM not signed with allowed key",
    }
    violation.update(overrides)
    return violation


def _search_result(*tickets):
    return {"issues": [dict(t) for t in tickets], "total": len(tickets)}


def test_discovery_rejects_projects_without_a_field_mapping(monkeypatch):
    with pytest.raises(ValueError, match="No Jira field mapping"):
        mod.discover_conforma_tickets(projects=["UNKNOWN"])


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestIsOpen:
    def test_unknown_or_empty_status_is_open(self):
        assert mod.is_open(None) is True
        assert mod.is_open("") is True
        assert mod.is_open("In Progress") is True

    def test_closed_statuses(self):
        for status in ("Done", "Closed", "CANCELED", " cancelled "):
            assert mod.is_open(status) is False, status


class TestBuildTicketSummary:
    def test_joins_components(self):
        assert (
            mod.build_ticket_summary("hermetic_task.hermetic", ["a", "b"])
            == "Conforma violation: hermetic_task.hermetic in a, b"
        )


class TestStripVersionSuffix:
    def test_strips_suffix(self):
        assert mod.strip_version_suffix("odh-ogx-core-v3-5-ea-1") == "odh-ogx-core"

    def test_no_suffix(self):
        assert mod.strip_version_suffix("odh-ogx-core") == "odh-ogx-core"


class TestComponentsOverlap:
    def test_ticket_stem_in_konflux_component(self):
        assert mod.components_overlap(OPEN_TICKET, ["odh-ogx-core-v3-6"], []) is True

    def test_konflux_stem_in_summary(self):
        ticket = {
            "summary": "Conforma issue for odh-vllm",
            "description": None,
            "components": [],
        }
        assert mod.components_overlap(ticket, ["odh-vllm-v3-6"], []) is True

    def test_jira_component_match(self):
        ticket = {
            "summary": "some unrelated text",
            "description": None,
            "components": ["AI-Guardrails"],
        }
        assert mod.components_overlap(ticket, ["zzz-unknown"], ["ai-guardrails"]) is True

    def test_no_overlap(self):
        ticket = {
            "summary": "unrelated",
            "description": None,
            "components": ["Other"],
        }
        assert mod.components_overlap(ticket, ["zzz-unknown"], ["Unrelated"]) is False

    def test_empty_stem_ignored(self):
        ticket = {"summary": "Conforma violation: r - -v3-6 - rhoai-3.6", "description": "", "components": []}
        # Keep the defensive empty-stem branch covered even if the summary
        # parser tightens its accepted component syntax in the future.
        original = mod.conforma_jira_ops._extract_component_stems
        mod.conforma_jira_ops._extract_component_stems = lambda *args: [""]
        try:
            assert mod.components_overlap(ticket, ["odh-ogx-core"], []) is False
        finally:
            mod.conforma_jira_ops._extract_component_stems = original
        assert mod.components_overlap(ticket, ["", " "], ["None"]) is False


class TestRuleMatches:
    def test_exact_rule_in_summary(self):
        assert mod.rule_matches(OPEN_TICKET, "rpm_signature.allowed:1234567890abcdef") is True

    def test_rule_from_description_text(self):
        ticket = {
            "summary": "RPM issue",
            "description": "key 1234567890abcdef used",
        }
        assert mod.rule_matches(ticket, "rpm_signature.allowed:1234567890abcdef") is True

    def test_no_match(self):
        ticket = {"summary": "completely unrelated", "description": ""}
        assert mod.rule_matches(ticket, "hermetic_task.hermetic") is False


class TestMatchViolationToTickets:
    def test_open_match_and_closed_prior(self):
        tickets = [OPEN_TICKET, CLOSED_TICKET]
        result = mod.match_violation_to_tickets(_violation(), tickets)
        assert result["existing"]["key"] == "RHOAIENG-80001"
        assert [p["key"] for p in result["prior_issues"]] == ["RHOAIENG-70681"]

    def test_no_match(self):
        tickets = [{"summary": "unrelated", "description": None, "status": "Open"}]
        result = mod.match_violation_to_tickets(_violation(), tickets)
        assert result == {"existing": None, "prior_issues": []}

    def test_falls_back_to_all_components(self):
        violation = _violation(uncovered_components=[])
        result = mod.match_violation_to_tickets(violation, [OPEN_TICKET])
        assert result["existing"]["key"] == "RHOAIENG-80001"

    def test_release_gate_rejects_possible_match(self):
        ticket = {**OPEN_TICKET, "target_versions": ["RHOAI 3.7"]}
        result = mod.match_violation_to_tickets(_violation(), [ticket], analyzed_release="rhoai-3.6")
        assert result == {"existing": None, "prior_issues": []}

    def test_rule_match_still_requires_component_overlap(self):
        ticket = {
            "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef",
            "description": "",
            "components": ["Other"],
            "status": "Open",
        }
        result = mod.match_violation_to_tickets(
            _violation(uncovered_components=["missing"], all_components=["missing"], jira_components=["Unknown"]),
            [ticket],
        )
        assert result == {"existing": None, "prior_issues": []}


class TestC14EvidenceGate:
    def test_empty_release_has_no_version_evidence(self):
        assert mod._version_evidence(OPEN_TICKET, "") == []

    def test_component_identity_and_release_mismatches_are_rejected(self):
        unrelated = {
            **OPEN_TICKET,
            "summary": "manual ticket for another-component-v3-6",
            "description": "Components: another-component-v3-6",
            "components": [],
        }
        wrong_release = {
            **OPEN_TICKET,
            "summary": "manual ticket for odh-ogx-core-v3-7",
            "description": "Components: odh-ogx-core-v3-7",
            "components": [],
            "target_versions": [],
        }
        assert mod.classify_ticket_evidence(unrelated, _violation(), "rhoai-3.6")["component_match"] is False
        assert mod.classify_ticket_evidence(wrong_release, _violation(), "rhoai-3.6")["component_match"] is False

    def test_versioned_component_and_target_version_confirm_match(self):
        ticket = {
            **OPEN_TICKET,
            "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef in odh-ogx-core-v3-6-ea-2",
            "description": "Components: odh-ogx-core-v3-6-ea-2",
            "target_versions": ["RHOAI 3.6"],
        }
        result = mod.classify_ticket_evidence(ticket, _violation(), "rhoai-3.6-ea.2")
        assert result["classification"] == "confirmed_conforma_violation"
        assert result["component_match"] is True
        assert result["version_match"] is True

    def test_unversioned_component_needs_separate_matching_version(self):
        ticket = {
            **OPEN_TICKET,
            "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef in odh-ogx-core",
            "description": "Components: odh-ogx-core",
            "target_versions": ["RHOAI 3.6"],
        }
        result = mod.classify_ticket_evidence(ticket, _violation(), "rhoai-3.6")
        assert result["classification"] == "confirmed_conforma_violation"

    def test_missing_or_future_version_cannot_confirm_match(self):
        missing = mod.classify_ticket_evidence({**OPEN_TICKET, "target_versions": []}, _violation(), "rhoai-3.6-ea.2")
        future = mod.classify_ticket_evidence(
            {**OPEN_TICKET, "target_versions": ["RHOAI 3.7"]}, _violation(), "rhoai-3.6-ea.2"
        )
        assert missing["classification"] == "possible_conforma_related"
        assert "version_match" in missing["missing_evidence"]
        assert future["classification"] == "possible_conforma_related"
        assert future["version_match"] is False

    def test_comment_can_supply_rule_component_and_version_evidence(self):
        ticket = {
            "key": "RHOAIENG-99",
            "summary": "Conforma follow-up",
            "description": "",
            "status": "Open",
            "labels": [],
            "comments": [
                {
                    "body": "rpm_signature.allowed:1234567890abcdef affects odh-ogx-core-v3-6-ea-2",
                }
            ],
            "target_versions": [],
        }
        result = mod.classify_ticket_evidence(ticket, _violation(), "rhoai-3.6-ea.2")
        assert result["classification"] == "confirmed_conforma_violation"
        assert any(item["field"] == "comments" for item in result["version_evidence"])

    def test_history_and_jira_component_can_supply_evidence(self):
        ticket = {
            "summary": "manual remediation",
            "description": "",
            "components": ["AI-Guardrails"],
            "target_versions": ["RHOAI 3.6"],
            "history": [{"items": [{"field": "summary", "to": "hermetic_task.hermetic"}]}],
        }
        violation = {**_violation(), "rule": "hermetic_task.hermetic", "uncovered_components": []}
        result = mod.classify_ticket_evidence(ticket, violation, "rhoai-3.6")
        assert result["classification"] == "confirmed_conforma_violation"
        assert result["component_evidence"][0]["field"] == "jira_components"

    def test_unparseable_release_and_field_errors_are_reported(self):
        result = mod.classify_ticket_evidence(
            {
                "summary": "unrelated",
                "description": "",
                "field_errors": ["versions unavailable"],
                "target_versions": ["not-a-release"],
            },
            _violation(),
            "rhoai-3.6",
        )
        assert result["classification"] == "unrelated"
        assert "versions unavailable" in result["missing_evidence"]


class TestC14CandidateDetails:
    def test_candidate_details_record_direct_references_and_access_failures(self, monkeypatch):
        calls = []

        def search(jql, **kwargs):
            calls.append(jql)
            if jql.startswith("key in"):
                return {
                    "issues": [{**OPEN_TICKET, "key": "RHOAIENG-2"}],
                    "total": 1,
                    "pages": [{"start_at": 0, "count": 1, "total": 1}],
                    "complete": True,
                }
            return {
                "issues": [dict(OPEN_TICKET), {"summary": "missing key"}],
                "total": 2,
                "pages": [{"start_at": 0, "count": 2, "total": 2}],
                "complete": True,
            }

        monkeypatch.setattr(mod.jira_ops, "search_issues_paginated", search)
        monkeypatch.setattr(
            mod.conforma_mr_ops,
            "discover_jira_references",
            lambda: [{"key": "RHOAIENG-2", "source": "merge_request"}],
        )
        monkeypatch.setattr(mod.jira_ops, "get_comments", lambda key: {"ok": False, "error": "denied"})
        monkeypatch.setattr(mod.jira_ops, "get_issue_history", lambda key: {"ok": False, "error": "hidden"})
        result = mod.discover_conforma_candidates([_violation()], "rhoai-3.6", include_details=True)
        assert {ticket["key"] for ticket in result["tickets"]} == {"RHOAIENG-80001", "RHOAIENG-2"}
        direct = next(ticket for ticket in result["tickets"] if ticket["key"] == "RHOAIENG-2")
        assert "direct_reference" in direct["match_sources"]
        assert direct["comment_evidence_status"] == "unavailable"
        assert direct["history_evidence_status"] == "unavailable"
        assert len(result["audit"]) == 5
        assert len(calls) == 5

    def test_incomplete_candidate_pass_is_a_hard_error(self, monkeypatch):
        monkeypatch.setattr(
            mod.jira_ops,
            "search_issues_paginated",
            lambda *args, **kwargs: {
                "issues": [],
                "total": 1,
                "pages": [],
                "complete": False,
            },
        )
        monkeypatch.setattr(mod.conforma_mr_ops, "discover_jira_references", lambda: [])
        with pytest.raises(RuntimeError, match="candidate pass incomplete"):
            mod.discover_conforma_candidates([_violation()], "rhoai-3.6")

    def test_unknown_project_and_unsupported_mapping_fields_are_rejected(self, monkeypatch):
        with pytest.raises(ValueError, match="No Jira field mapping"):
            mod.discover_conforma_candidates([_violation()], "rhoai-3.6", projects=["UNKNOWN"])

        monkeypatch.setattr(
            mod.conforma_jira_mapping_ops,
            "load_project_mapping",
            lambda: {
                "mapping_version": "test",
                "projects": {"RHOAIENG": {"field_paths": {"unsupported": ["fields.foo"]}}},
            },
        )
        with pytest.raises(ValueError, match="Unsupported Jira mapping field"):
            mod.discover_conforma_candidates([_violation()], "rhoai-3.6", projects=["RHOAIENG"])

    def test_direct_reference_pass_requires_complete_results_and_keys(self, monkeypatch):
        def incomplete_direct(jql, **kwargs):
            if jql.startswith("key in"):
                return {"issues": [], "total": 1, "pages": [], "complete": False}
            return {"issues": [], "total": 0, "pages": [], "complete": True}

        monkeypatch.setattr(mod.jira_ops, "search_issues_paginated", incomplete_direct)
        monkeypatch.setattr(
            mod.conforma_mr_ops,
            "discover_jira_references",
            lambda: [{"key": "RHOAIENG-2", "source": "merge_request"}],
        )
        with pytest.raises(RuntimeError, match="direct_reference"):
            mod.discover_conforma_candidates([_violation()], "rhoai-3.6")

        def missing_direct_key(jql, **kwargs):
            return {
                "issues": [{"summary": "missing key"}] if jql.startswith("key in") else [],
                "total": 1 if jql.startswith("key in") else 0,
                "pages": [],
                "complete": True,
            }

        monkeypatch.setattr(mod.jira_ops, "search_issues_paginated", missing_direct_key)
        result = mod.discover_conforma_candidates([_violation()], "rhoai-3.6")
        assert result["tickets"] == []

    def test_returned_ticket_without_a_known_project_mapping_is_explicitly_incomplete(self, monkeypatch):
        monkeypatch.setattr(
            mod.jira_ops,
            "search_issues_paginated",
            lambda *args, **kwargs: {
                "issues": [{"key": "UNKNOWN-1"}],
                "total": 1,
                "pages": [],
                "complete": True,
            },
        )
        monkeypatch.setattr(mod.conforma_mr_ops, "discover_jira_references", lambda: [])
        result = mod.discover_conforma_candidates([_violation()], "rhoai-3.6")
        ticket = result["tickets"][0]
        assert ticket["jira_field_mapping_status"] == "unavailable"
        assert "No Jira field mapping exists for returned ticket project UNKNOWN" in ticket["field_errors"]

    def test_evidence_records_label_rule_component_and_direct_reference_sources(self, monkeypatch):
        ticket = {
            **OPEN_TICKET,
            "merge_request_references": [{"key": OPEN_TICKET["key"], "source": "merge_request"}],
        }
        monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **kwargs: [ticket])
        evidence = mod.discover_conforma_evidence([_violation()], "rhoai-3.6")
        assert evidence[0]["match_sources"] == ["component_version", "direct_reference", "label", "rule_text"]

    def test_independent_ticket_discovery_attaches_audit(self, monkeypatch):
        audit = [{"pass": "label", "complete": True}]
        monkeypatch.setattr(
            mod,
            "discover_conforma_candidates",
            lambda *args, **kwargs: {"tickets": [dict(OPEN_TICKET)], "audit": audit},
        )
        tickets = mod.discover_conforma_tickets(violations=[_violation()], release="rhoai-3.6", independent=True)
        assert tickets[0]["discovery_audit"] == audit

    def test_legacy_discovery_marks_unknown_returned_project_incomplete(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "search_issues", lambda *args, **kwargs: {"issues": [{"key": "UNKNOWN-1"}]})
        tickets = mod.discover_conforma_tickets()
        assert tickets[0]["jira_field_mapping_status"] == "unavailable"

    def test_unmapped_project_cannot_be_confirmed_by_advisory_evidence(self):
        ticket = {
            **OPEN_TICKET,
            "jira_field_mapping_status": "unavailable",
            "field_errors": ["mapping unavailable"],
        }
        result = mod.classify_ticket_evidence(ticket, _violation(), "rhoai-3.6")
        assert result["classification"] == "possible_conforma_related"
        assert "jira_field_mapping" in result["missing_evidence"]

    def test_evidence_adjudicator_can_confirm_only_after_gate(self, monkeypatch):
        ticket = {
            "summary": "manual follow-up for odh-ogx-core-v3-6",
            "description": "Target RHOAI 3.6",
            "target_versions": [],
        }
        monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **kwargs: [ticket])
        result = mod.discover_conforma_evidence(
            [_violation(rule="not-extracted")],
            "rhoai-3.6",
            adjudicator=lambda payload: {
                "decision": "violation",
                "confidence": "high",
                "evidence_references": ["summary"],
            },
        )
        assert result[0]["classification"] == "confirmed_conforma_violation"
        assert result[0]["adjudication"]["status"] == "adjudicated_violation"

    def test_single_ticket_audit_confirms_unlabelled_freeform_evidence(self, monkeypatch):
        ticket = {
            "key": "RHOAIENG-70681",
            "summary": "Conforma violation: rpm_packages.unique_version in guardrails-detectors HuggingFace runtime",
            "description": (
                "The odh-guardrails-detector-huggingface-runtime-rhel9 component fails "
                "rpm_packages.unique_version on rhoai-3.5-ea.2."
            ),
            "status": "Closed",
            "labels": [],
            "components": [],
            "fix_versions": [],
            "target_versions": [],
            "affected_versions": [],
        }
        monkeypatch.setattr(mod.jira_ops, "search_issues", lambda *args, **kwargs: {"issues": [dict(ticket)]})
        monkeypatch.setattr(mod.jira_ops, "get_comments", lambda key: {"ok": True, "comments": []})
        monkeypatch.setattr(mod.jira_ops, "get_issue_history", lambda key: {"ok": True, "history": []})
        result = mod.audit_ticket_evidence(
            "RHOAIENG-70681",
            {
                "rule": "rpm_packages.unique_version",
                "uncovered_components": ["odh-guardrails-detector-huggingface-runtime-v3-5-ea-2"],
                "jira_components": [],
            },
            "rhoai-3.5-ea.2",
        )
        assert result["status"] == "audited"
        assert result["ticket"]["labels"] == []
        assert result["evidence"]["classification"] == "confirmed_conforma_violation"

    def test_single_ticket_audit_reports_not_found(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "search_issues", lambda *args, **kwargs: {"issues": []})
        assert mod.audit_ticket_evidence("RHOAIENG-1", _violation(), "rhoai-3.6") == {
            "key": "RHOAIENG-1",
            "status": "not_found",
            "evidence": None,
        }


class TestGroupComponentsByJira:
    def test_groups_by_jira_component_and_team(self, monkeypatch):
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {"odh-ogx-core": "AI-Guardrails", "odh-vllm": "AI Serving"},
        )
        groups = mod.group_components_by_jira(["odh-ogx-core", "odh-vllm"], CATALOG)
        by_jc = {g["jira_component"]: g for g in groups}
        assert by_jc["AI-Guardrails"]["konflux_components"] == ["odh-ogx-core"]
        assert by_jc["AI-Guardrails"]["team"] == "AI-Guardrails"
        assert by_jc["AI Serving"]["konflux_components"] == ["odh-vllm"]
        assert by_jc["AI Serving"]["team"] == "Serving"

    def test_multiple_components_same_group(self, monkeypatch):
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {"a": "J", "b": "J"},
        )
        groups = mod.group_components_by_jira(["a", "b"], CATALOG)
        assert groups == [{"jira_component": "J", "team": None, "konflux_components": ["a", "b"]}]

    def test_unmapped_fallback(self, monkeypatch):
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {"odh-unknown": None},
        )
        groups = mod.group_components_by_jira(["odh-unknown"], CATALOG)
        assert groups == [{"jira_component": None, "team": None, "konflux_components": ["odh-unknown"]}]


class TestTeamForComponent:
    def test_dict_component_name(self):
        assert mod._team_for_component("AI-Guardrails", CATALOG) == "AI-Guardrails"

    def test_string_component_name_uses_org(self):
        assert mod._team_for_component("AI Serving", CATALOG) == "Serving"

    def test_unknown_or_none(self):
        assert mod._team_for_component("Nope", CATALOG) is None
        assert mod._team_for_component(None, CATALOG) is None

    def test_string_component_entry_skipped_until_dict_match(self):
        catalog = [
            {"konflux_components": ["a"], "jira_components": ["Other"], "team": "Wrong"},
            {"konflux_components": ["b"], "jira_components": [{"name": "Target"}], "team": "Right"},
        ]
        assert mod._team_for_component("Target", catalog) == "Right"


class TestResolveTargetVersion:
    def test_empty_release_returns_none(self):
        assert mod.resolve_target_version("") is None

    def test_normalizes_release(self):
        assert mod.resolve_target_version(" rhoai-3.6 ") == "rhoai-3.6"


class TestBuildTicketDescription:
    def test_full_description(self):
        text = mod.build_ticket_description(
            rule="r.x",
            release="rhoai-3.6",
            environment="prod",
            konflux_components=["a", "b"],
            jira_component="JComp",
            team="TeamX",
            violation_details="details here",
            source_csv_url="https://example.com/report.csv",
            prior_issues=[{"key": "PSX-1", "status": "Closed"}],
        )
        assert "Conforma violation: r.x" in text
        assert "Release: rhoai-3.6" in text
        assert "Environment: prod" in text
        assert "Konflux components: a, b" in text
        assert "Jira component: JComp" in text
        assert "Owning team/org: TeamX" in text
        assert "details here" in text
        assert "Source report: https://example.com/report.csv" in text
        assert "Relates to prior issue:" in text
        assert "PSX-1 (Closed)" in text

    def test_optional_sections_omitted(self):
        text = mod.build_ticket_description(
            rule="r.x",
            release="rhoai-3.6",
            environment="prod",
            konflux_components=["a"],
            jira_component=None,
            team=None,
            violation_details="",
            source_csv_url="",
            prior_issues=[],
        )
        assert "Jira component" not in text
        assert "Owning team" not in text
        assert "Source report" not in text
        assert "Relates to prior issue" not in text


class TestBuildCreateFields:
    def test_with_components_and_target_version(self):
        fields = mod.build_create_fields("r.x", ["a"], ["JComp"], "rhoai-3.6", "desc")
        assert fields["project"] == {"key": "RHOAIENG"}
        assert fields["issuetype"] == {"name": "Task"}
        assert fields["labels"] == ["conforma", "conforma-violation"]
        assert fields["priority"] == {"name": "Blocker"}
        assert fields["components"] == [{"name": "JComp"}]
        assert fields[mod.TARGET_VERSION_FIELD] == [{"name": "rhoai-3.6"}]
        assert fields["summary"] == "Conforma violation: r.x in a"
        assert fields["description"] == "desc"

    def test_without_components_and_target_version(self):
        fields = mod.build_create_fields("r.x", ["a"], [], None, "desc")
        assert "components" not in fields
        assert mod.TARGET_VERSION_FIELD not in fields


class TestBuildPrefillUrl:
    def test_all_params_encoded(self):
        url = mod.build_prefill_url("10350", "r.x", ["a", "b"], ["J Comp"], "rhoai-3.6", "line1\nline2")
        assert url.startswith(f"{JIRA_BASE}/secure/CreateIssueDetails!init.jspa?")
        assert "pid=10350" in url
        assert "issuetype=10001" in url
        assert "priority=Blocker" in url
        assert "labels=conforma%2Cconforma-violation" in url
        assert "components=J+Comp" in url
        assert "customfield_10855=rhoai-3.6" in url
        assert "Conforma+violation" in url
        assert "%0A" in url

    def test_omits_optional_params(self):
        url = mod.build_prefill_url("10350", "r.x", ["a"], [], None, "desc")
        assert "components" not in url
        assert "customfield_10855" not in url

    def test_uses_unique_label_when_release_is_known(self):
        url = mod.build_prefill_url("10350", "hermetic_task.hermetic", ["odh-vllm-v3-6"], [], None, "desc", "rhoai-3.6")
        assert "labels=conforma%2Cconforma-violation%2Cconforma-rhoai-3-6-odh-vllm-hermetic-task-hermetic" in url


class TestUniqueViolationLabels:
    def test_label_is_stable_and_version_stripped(self):
        assert (
            mod.build_violation_label("rhoai-3.6-ea.2", "odh-vllm-v3-6-ea-2", "hermetic_task.hermetic")
            == "conforma-rhoai-3-6-ea-2-odh-vllm-hermetic-task-hermetic"
        )

    def test_related_search_url_uses_exact_label(self):
        url = mod.build_related_search_url("conforma-rhoai-3-6-odh-vllm-hermetic-task-hermetic")
        assert "project%20%3D%20RHOAIENG" in url
        assert "labels%20%3D%20%22conforma-rhoai-3-6-odh-vllm-hermetic-task-hermetic%22" in url


class TestPlanSelfHealLabels:
    def test_missing_conforma_added(self):
        plan = mod.plan_self_heal_labels([{"key": "K-1", "labels": ["x"], "summary": "s"}])
        assert plan == [{"key": "K-1", "add": ["conforma"], "current": ["x"]}]

    def test_violation_gets_both_labels(self):
        plan = mod.plan_self_heal_labels([{"key": "K-1", "labels": [], "summary": "Conforma violation: r in a"}])
        assert plan[0]["add"] == ["conforma", "conforma-violation"]

    def test_legacy_exception_never_gets_violation_label(self):
        plan = mod.plan_self_heal_labels(
            [
                {
                    "key": "K-1",
                    "labels": ["conforma-exception-ai-skill"],
                    "summary": "Conforma violation: r in a",
                }
            ]
        )
        assert plan[0]["add"] == ["conforma"]

    def test_already_labeled_skipped(self):
        tickets = [
            {
                "key": "K-1",
                "labels": ["conforma", "conforma-violation"],
                "summary": "Conforma violation: r in a",
            }
        ]
        assert mod.plan_self_heal_labels(tickets) == []

    def test_confirmed_only_skips_unconfirmed_evidence(self):
        tickets = [
            {
                "key": "K-1",
                "labels": [],
                "summary": "Conforma violation: r in a",
                "c14_evidence": [{"classification": "possible_conforma_related"}],
            }
        ]
        assert mod.plan_self_heal_labels(tickets, confirmed_only=True) == []


# ---------------------------------------------------------------------------
# I/O operations (Jira + catalog mocked)
# ---------------------------------------------------------------------------
class TestDiscoverConformaTickets:
    def test_uses_label_discovery_jql_and_returns_issues(self, monkeypatch):
        captured = {}

        def fake_search(jql, **kwargs):
            captured["jql"] = jql
            captured["fields"] = kwargs.get("fields")
            return _search_result(OPEN_TICKET)

        monkeypatch.setattr(mod.jira_ops, "search_issues", fake_search)
        tickets = mod.discover_conforma_tickets()
        assert [t["key"] for t in tickets] == ["RHOAIENG-80001"]
        assert "project in (RHOAIENG, PSX, OCPEXCEPT, PRODSECRM, RHAI, RHAIENG, AIPCC)" in captured["jql"]
        assert "labels in (conforma, conforma-violation, conforma-exception-ai-skill)" in captured["jql"]
        assert "status" not in captured["jql"]  # all statuses
        assert "key" in captured["fields"] and "target_versions" in captured["fields"]

    def test_propagates_jira_search_error(self, monkeypatch):
        def boom(jql, **kwargs):
            raise mod.jira_ops.JiraSearchError("bad jql", jql)

        monkeypatch.setattr(mod.jira_ops, "search_issues", boom)
        try:
            mod.discover_conforma_tickets(projects=["RHAI"], labels=["conforma"])
            raise AssertionError("expected JiraSearchError")
        except mod.jira_ops.JiraSearchError:
            pass

    def test_adds_rule_component_candidates_for_related_tickets(self, monkeypatch):
        captured = {}

        def fake_search(jql, **kwargs):
            captured["jql"] = jql
            return {"issues": []}

        monkeypatch.setattr(mod.jira_ops, "search_issues", fake_search)
        monkeypatch.setattr(mod.conforma_mr_ops, "discover_jira_references", lambda: [])
        mod.discover_conforma_tickets(violations=[_violation()], release="rhoai-3.6")
        assert 'summary ~ "rpm_signature.allowed"' in captured["jql"]
        assert 'summary ~ "odh-ogx-core"' in captured["jql"]
        assert "conforma-rhoai-3-6-odh-ogx-core-rpm-signature-allowed" in captured["jql"]

    def test_merges_tickets_referenced_by_merge_requests(self, monkeypatch):
        monkeypatch.setattr(
            mod.jira_ops,
            "search_issues",
            lambda jql, **kwargs: (
                {"issues": []}
                if "key in" not in jql
                else {"issues": [{"key": "RHOAIENG-88509", "summary": "tracked", "status": "Open"}]}
            ),
        )
        monkeypatch.setattr(
            mod.conforma_mr_ops,
            "discover_jira_references",
            lambda: [{"key": "RHOAIENG-88509", "mr_iid": 22104, "source": "merge_request"}],
        )

        tickets = mod.discover_conforma_tickets(violations=[_violation()], release="rhoai-3.6")

        assert tickets[0]["key"] == "RHOAIENG-88509"
        assert tickets[0]["merge_request_references"][0]["mr_iid"] == 22104

    def test_independent_candidates_merge_pass_sources_and_pagination(self, monkeypatch):
        calls = []

        def fake_search(jql, **kwargs):
            calls.append(jql)
            return {
                "issues": [dict(OPEN_TICKET)],
                "total": 1,
                "complete": True,
                "pages": [{"start_at": 0, "count": 1, "total": 1}],
            }

        monkeypatch.setattr(mod.jira_ops, "search_issues_paginated", fake_search)
        monkeypatch.setattr(mod.conforma_mr_ops, "discover_jira_references", lambda: [])
        result = mod.discover_conforma_candidates([_violation()], "rhoai-3.6")
        assert len(calls) >= 3
        assert result["tickets"][0]["match_sources"] == [
            "component_version",
            "label",
            "rule_label",
            "rule_text",
        ]
        assert all(entry["complete"] is True for entry in result["audit"])


class TestSelfHealLabels:
    def test_labels_and_verifies(self, monkeypatch):
        tickets = [
            {
                "key": "K-1",
                "labels": ["other"],
                "summary": "Conforma violation: r in a",
            }
        ]
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda key, labels=None: {"key": key, "updated": ["labels"]})
        monkeypatch.setattr(
            mod.jira_ops,
            "get_issue",
            lambda key, fields=None: {"key": key, "labels": ["other", "conforma", "conforma-violation"]},
        )
        actions = mod.self_heal_labels(tickets)
        assert actions == ["labeled K-1 +conforma+conforma-violation"]

    def test_update_error_recorded(self, monkeypatch):
        tickets = [{"key": "K-1", "labels": [], "summary": "s"}]
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda key, labels=None: {"key": key, "error": "boom"})
        actions = mod.self_heal_labels(tickets)
        assert actions == ["label-failed K-1 (add conforma): boom"]

    def test_verification_failure_recorded(self, monkeypatch):
        tickets = [{"key": "K-1", "labels": [], "summary": "s"}]
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda key, labels=None: {"key": key, "updated": ["labels"]})
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": []})
        actions = mod.self_heal_labels(tickets)
        assert actions and "label-verify-failed K-1" in actions[0]

    def test_plan_item_without_matching_ticket_skipped(self, monkeypatch):
        calls = {}
        monkeypatch.setattr(
            mod,
            "plan_self_heal_labels",
            lambda tickets: [{"key": "MISSING", "add": ["conforma"], "current": []}],
        )
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, labels=None: calls.update(key=key) or {},
        )
        assert mod.self_heal_labels([{"key": "K-1", "labels": ["conforma"], "summary": "s"}]) == []
        assert calls == {}


class TestIndependentLabelling:
    def test_read_only_plan_does_not_depend_on_sync_output(self, monkeypatch, tmp_path):
        captured = {}
        monkeypatch.setattr(
            mod,
            "_load_context",
            lambda: (tmp_path, {"application": {"release": "rhoai-3.6"}, "environment": "prod"}),
        )

        def discover(**kwargs):
            captured.update(kwargs)
            return [{"key": "K-1", "labels": [], "summary": "Conforma violation: r in a"}]

        monkeypatch.setattr(mod, "discover_conforma_tickets", discover)
        monkeypatch.setattr(mod.conforma_context_ops, "update_step", lambda *args, **kwargs: {})

        result = mod.label_conforma_tickets()

        assert result["apply"] is False
        assert result["actions"] == [{"key": "K-1", "status": "planned", "add": ["conforma", "conforma-violation"]}]
        assert captured == {"violations": None, "release": "rhoai-3.6", "independent": True}
        assert json.loads((tmp_path / "jira_labelling.json").read_text())["planned"] == 1

    def test_apply_adds_labels_and_set_then_verifies(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            mod,
            "_load_context",
            lambda: (tmp_path, {"application": {"release": "rhoai-3.6"}}),
        )
        monkeypatch.setattr(
            mod,
            "discover_conforma_tickets",
            lambda **kwargs: [{"key": "K-1", "labels": ["other"], "summary": "Conforma violation: r in a"}],
        )
        calls = []
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, labels=None: calls.append((key, labels)) or {"key": key, "updated": ["labels"]},
        )
        monkeypatch.setattr(
            mod.jira_ops,
            "get_issue",
            lambda key, fields=None: {"key": key, "labels": ["other", "conforma", "conforma-violation"]},
        )
        monkeypatch.setattr(mod.conforma_context_ops, "update_step", lambda *args, **kwargs: {})

        result = mod.label_conforma_tickets(apply=True)

        assert calls == [("K-1", ["other", "conforma", "conforma-violation"])]
        assert result["actions"] == [{"key": "K-1", "status": "labeled", "added": ["conforma", "conforma-violation"]}]

    def test_apply_records_update_failure_without_losing_other_candidates(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "_load_context", lambda: (tmp_path, {}))
        monkeypatch.setattr(
            mod,
            "discover_conforma_tickets",
            lambda **kwargs: [
                {"key": "K-1", "labels": [], "summary": "Conforma violation: r in a"},
                {"key": "K-2", "labels": [], "summary": "Conforma issue"},
            ],
        )
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, labels=None: (
                {"key": key, "error": "denied"} if key == "K-1" else {"key": key, "updated": ["labels"]}
            ),
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"labels": ["conforma"]})
        monkeypatch.setattr(mod.conforma_context_ops, "update_step", lambda *args, **kwargs: {})

        result = mod.label_conforma_tickets(apply=True)

        assert result["actions"][0] == {"key": "K-1", "status": "failed", "error": "denied"}
        assert result["actions"][1] == {"key": "K-2", "status": "labeled", "added": ["conforma"]}

    def test_existing_coverage_is_loaded_and_apply_records_skip_and_verification_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "_load_context", lambda: (tmp_path, {"application": {"release": "rhoai-3.6"}}))
        (tmp_path / "coverage.json").write_text(json.dumps({"violations": [_violation()]}))
        monkeypatch.setattr(
            mod,
            "_load_coverage_violations",
            lambda run_dir: [_violation()],
        )
        monkeypatch.setattr(
            mod,
            "discover_conforma_tickets",
            lambda **kwargs: [{"key": "K-1", "labels": [], "summary": "Conforma violation: r in a"}],
        )
        monkeypatch.setattr(
            mod,
            "plan_self_heal_labels",
            lambda tickets, confirmed_only=False: [{"key": "MISSING", "add": ["conforma"], "current": []}],
        )
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda *args, **kwargs: {"updated": ["labels"]})
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda *args, **kwargs: {"labels": []})
        monkeypatch.setattr(mod.conforma_context_ops, "update_step", lambda *args, **kwargs: {})
        result = mod.label_conforma_tickets(apply=True)
        assert result["actions"] == [
            {"key": "MISSING", "status": "skipped", "reason": "ticket not in discovery result"}
        ]

    def test_apply_records_verification_failure(self, monkeypatch, tmp_path):
        monkeypatch.setattr(mod, "_load_context", lambda: (tmp_path, {}))
        monkeypatch.setattr(
            mod,
            "discover_conforma_tickets",
            lambda **kwargs: [{"key": "K-1", "labels": [], "summary": "Conforma issue"}],
        )
        monkeypatch.setattr(
            mod,
            "plan_self_heal_labels",
            lambda tickets, confirmed_only=False: [{"key": "K-1", "add": ["conforma"], "current": []}],
        )
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda *args, **kwargs: {"updated": ["labels"]})
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda *args, **kwargs: {"labels": []})
        monkeypatch.setattr(mod.conforma_context_ops, "update_step", lambda *args, **kwargs: {})
        result = mod.label_conforma_tickets(apply=True)
        assert result["actions"] == [
            {"key": "K-1", "status": "verification_failed", "expected": ["conforma"], "actual": []}
        ]


class TestCreateViolationTicket:
    def test_creates_with_target_version_and_verifies(self, monkeypatch):
        created_mock = {"key": "RHOAIENG-90000", "url": f"{JIRA_BASE}/browse/RHOAIENG-90000"}
        create_calls = {}

        def fake_create(**kwargs):
            create_calls.update(kwargs)
            return created_mock

        monkeypatch.setattr(mod.jira_ops, "create_issue", fake_create)
        monkeypatch.setattr(
            mod.jira_ops,
            "get_issue",
            lambda key, fields=None: {
                "key": key,
                "labels": ["conforma", "conforma-violation"],
                "priority": "Blocker",
                "components": ["AI-Guardrails"],
            },
        )
        result = mod.create_violation_ticket("r.x", ["odh-ogx-core"], ["AI-Guardrails"], "rhoai-3.6", "desc")
        assert result["created"]["key"] == "RHOAIENG-90000"
        assert result["created"]["labels_ok"] is True
        assert result["created"]["priority_ok"] is True
        assert result["created"]["components"] == ["AI-Guardrails"]
        assert create_calls["extra_fields"] == {mod.TARGET_VERSION_FIELD: [{"name": "rhoai-3.6"}]}
        assert create_calls["priority"] == "Blocker"
        assert create_calls["labels"] == ["conforma", "conforma-violation"]

    def test_no_target_version_omits_extra_fields(self, monkeypatch):
        create_calls = {}

        def fake_create(**kwargs):
            create_calls.update(kwargs)
            return {"key": "K-2", "url": "u"}

        monkeypatch.setattr(mod.jira_ops, "create_issue", fake_create)
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key})
        result = mod.create_violation_ticket("r.x", ["a"], [], None, "desc")
        assert create_calls["extra_fields"] is None
        assert result["created"]["labels_ok"] is False

    def test_create_error_returned(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "create_issue", lambda **kw: {"key": None, "url": None, "error": "no"})
        result = mod.create_violation_ticket("r.x", ["a"], [], None, "desc")
        assert result["created"] is None
        assert result["error"] == "no"


class TestExtendPartialMatch:
    def test_no_missing_components(self):
        result = mod.extend_partial_match("K-1", [])
        assert result == {"extended": None, "reason": "no missing components"}

    def test_extends_and_comments(self, monkeypatch):
        monkeypatch.setattr(
            mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "components": ["Existing"]}
        )
        updates = {}
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, components=None: (
                updates.update(key=key, components=components) or {"key": key, "updated": ["components"]}
            ),
        )
        comments = []
        monkeypatch.setattr(mod.jira_ops, "add_comment", lambda key, body: comments.append((key, body)))
        result = mod.extend_partial_match("K-1", ["New", "Existing"])
        assert result["extended"] == {"key": "K-1", "components_added": ["New", "Existing"]}
        assert updates["components"] == ["Existing", "New"]  # deduped union
        assert comments and comments[0][0] == "K-1" and "New" in comments[0][1]

    def test_update_error(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "components": []})
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda key, components=None: {"key": key, "error": "denied"})
        result = mod.extend_partial_match("K-1", ["New"])
        assert result["extended"] is None
        assert result["error"] == "denied"


class TestLinkTicket:
    def test_success(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "link_issues", lambda a, b, link_type=None: {"ok": True})
        assert mod.link_ticket("A-1", "B-2") is True

    def test_error(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "link_issues", lambda a, b, link_type=None: {"error": "no"})
        assert mod.link_ticket("A-1", "B-2") is False


class TestAddGuideUrlComment:
    def test_comments_each_key(self, monkeypatch):
        calls = []
        monkeypatch.setattr(mod.jira_ops, "add_comment", lambda key, body: calls.append((key, body)) or {"ok": True})
        actions = mod.add_guide_url_comment(["K-1", "K-2"], "https://g.example/x")
        assert actions == ["guide-commented K-1", "guide-commented K-2"]
        assert all("Resolution guide: https://g.example/x" in body for _, body in calls)

    def test_error_is_non_blocking(self, monkeypatch):
        def flaky(key, body):
            if key == "K-1":
                return {"key": key, "ok": False, "error": "denied"}
            raise RuntimeError("network down")

        monkeypatch.setattr(mod.jira_ops, "add_comment", flaky)
        actions = mod.add_guide_url_comment(["K-1", "K-2"], "u")
        assert actions == [
            "guide-comment-failed K-1: denied",
            "guide-comment-failed K-2: network down",
        ]


class TestAuditConformaIndex:
    def test_healthy_ticket_no_gap(self):
        ticket = {
            "key": "K-1",
            "summary": "Conforma violation: r in a",
            "status": "Open",
            "labels": ["conforma", "conforma-violation"],
            "components": ["J"],
            "priority": "Blocker",
            "target_versions": ["RHOAI 3.6"],
            "assignee": "Bob",
        }
        report = mod.audit_conforma_index([ticket], "rhoai-3.6")
        assert report == {"checked": 1, "gaps": []}

    def test_gaps_detected(self):
        ticket = {
            "key": "K-1",
            "summary": "Conforma violation: r in a",
            "status": "Open",
            "labels": ["conforma-exception-ai-skill"],  # conforma missing
            "components": [],
            "priority": "Medium",
            "target_versions": [],
            "assignee": "",
        }
        report = mod.audit_conforma_index([ticket], "rhoai-3.6")
        gap = report["gaps"][0]
        assert gap["key"] == "K-1"
        assert "conforma" in gap["missing"]
        assert "conforma-violation" not in gap["missing"]  # legacy exception exempt
        assert "components" in gap["missing"]
        assert "priority" in gap["missing"]
        assert "target_versions" in gap["missing"]
        assert any(n.startswith("unassigned") for n in gap["notes"])

    def test_closed_ticket_exempt_note(self):
        ticket = {
            "key": "K-2",
            "summary": "Conforma violation: r in a",
            "status": "Closed",
            "labels": ["conforma", "conforma-violation"],
            "components": ["J"],
            "priority": "Blocker",
            "target_versions": ["RHOAI 3.5"],
            "assignee": "Bob",
        }
        report = mod.audit_conforma_index([ticket], "rhoai-3.6")
        gap = report["gaps"][0]
        assert gap["missing"] == []
        assert any(n.startswith("closed") for n in gap["notes"])

    def test_empty_tickets(self):
        assert mod.audit_conforma_index([], "") == {"checked": 0, "gaps": []}

    def test_violation_without_violation_label_is_reported(self):
        ticket = {
            "key": "K-3",
            "summary": "Conforma violation: r in a",
            "labels": ["conforma"],
            "components": ["J"],
            "priority": "Blocker",
            "target_versions": ["RHOAI 3.6"],
            "assignee": "Bob",
        }
        assert "conforma-violation" in mod.audit_conforma_index([ticket], "rhoai-3.6")["gaps"][0]["missing"]


class TestRepairIndex:
    def _base_ticket(self, **overrides):
        ticket = {
            "key": "K-1",
            "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef in odh-ogx-core",
            "description": "Components: odh-ogx-core",
            "status": "Open",
            "labels": ["conforma", "conforma-violation"],
            "components": [],
            "priority": "Medium",
        }
        ticket.update(overrides)
        return ticket

    def test_repairs_priority(self, monkeypatch):
        updates = {}
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, priority=None, components=None, extra_fields=None: (
                updates.update(key=key, priority=priority, components=components, extra_fields=extra_fields)
                or {"key": key, "updated": ["priority"]}
            ),
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        actions = mod.repair_index(
            [self._base_ticket(components=["J"], target_versions=["RHOAI 3.6"])], "rhoai-3.6", []
        )
        assert any(a.startswith("repaired K-1") for a in actions)
        assert updates["priority"] == "Blocker"
        assert updates["extra_fields"] is None  # target already set -> not refilled

    def test_resolves_components_from_catalog(self, monkeypatch):
        updates = {}
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, priority=None, components=None, extra_fields=None: (
                updates.update(components=components) or {"key": key, "updated": ["components"]}
            ),
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {n: "AI-Guardrails" for n in names},
        )
        actions = mod.repair_index(
            [self._base_ticket(priority="Blocker", target_versions=["RHOAI 3.6"])], "rhoai-3.6", []
        )
        assert updates["components"] == ["AI-Guardrails"]
        assert any(a.startswith("repaired K-1") for a in actions)

    def test_fills_target_version_when_missing(self, monkeypatch):
        updates = {}
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, priority=None, components=None, extra_fields=None: (
                updates.update(extra_fields=extra_fields) or {"key": key, "updated": [mod.TARGET_VERSION_FIELD]}
            ),
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        # open ticket without target_versions -> filled from release context
        ticket = self._base_ticket(priority="Blocker", components=["J"], target_versions=[])
        actions = mod.repair_index([ticket], "rhoai-3.6", [])
        assert updates["extra_fields"] == {mod.TARGET_VERSION_FIELD: [{"name": "rhoai-3.6"}]}
        assert any(a.startswith("repaired K-1") for a in actions)

    def test_closed_ticket_exempt_from_target_fill(self, monkeypatch):
        def no_update(*a, **k):
            raise AssertionError("closed ticket must be exempt from fills")

        monkeypatch.setattr(mod.jira_ops, "update_issue", no_update)
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        # closed ticket: priority/components already fine, only target_versions missing
        # -> the target fill must NOT apply to closed tickets
        ticket = self._base_ticket(status="Closed", priority="Blocker", components=["J"], target_versions=[])
        assert mod.repair_index([ticket], "rhoai-3.6", []) == []

    def test_repair_update_error(self, monkeypatch):
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, priority=None, components=None, extra_fields=None: {"key": key, "error": "denied"},
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        actions = mod.repair_index([self._base_ticket(components=["J"], target_versions=["RHOAI 3.6"])], "", [])
        assert any(a.startswith("repair-failed K-1") for a in actions)

    def test_ticket_without_key_skipped(self, monkeypatch):
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected update")),
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        assert mod.repair_index([self._base_ticket(key=None)], "", []) == []

    def test_no_gaps_no_update(self, monkeypatch):
        def no_update(*a, **k):
            raise AssertionError("unexpected update")

        monkeypatch.setattr(mod.jira_ops, "update_issue", no_update)
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "labels": ["conforma"]})
        ticket = self._base_ticket(priority="Blocker", components=["J"], target_versions=["RHOAI 3.6"])
        assert mod.repair_index([ticket], "", []) == []


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------
def _patch_sync_env(monkeypatch, tmp_path, *, tickets=(), violations, catalog=CATALOG, context=None):
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    if context is None:
        context = {"environment": "prod", "application": {"release": "rhoai-3.6"}}
    monkeypatch.setattr(mod.conforma_context_ops, "discover_run_dir", lambda explicit=None: run_dir)
    monkeypatch.setattr(mod.conforma_context_ops, "load", lambda run_dir: context)
    monkeypatch.setattr(mod.component_catalog_ops, "load_catalog", lambda *a, **k: list(catalog))
    monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **k: [dict(t) for t in tickets])
    (run_dir / "coverage.json").write_text(json.dumps({"violations": list(violations)}))
    return run_dir


def _mock_create_success(monkeypatch, key="RHOAIENG-90000"):
    monkeypatch.setattr(mod.jira_ops, "create_issue", lambda **kw: {"key": key, "url": f"{JIRA_BASE}/browse/{key}"})
    monkeypatch.setattr(
        mod.jira_ops,
        "get_issue",
        lambda key, fields=None: {
            "key": key,
            "labels": ["conforma", "conforma-violation"],
            "priority": "Blocker",
            "components": [],
        },
    )


class TestSync:
    def test_creates_and_writes_jira_sync_json(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[], violations=[_violation()])
        _mock_create_success(monkeypatch)
        steps = {}
        monkeypatch.setattr(
            mod.conforma_context_ops,
            "update_step",
            lambda run_dir, step, status, **outputs: steps.update(step=step, status=status, **outputs) or {},
        )
        out = mod.sync()
        assert out["dry_run"] is False
        assert out["release"] == "rhoai-3.6"
        assert out["environment"] == "prod"
        group = out["violations"][0]["groups"][0]
        assert group["created"]["key"] == "RHOAIENG-90000"
        assert any(a.startswith("created RHOAIENG-90000") for a in out["actions"])
        sync_file = tmp_path / "run" / "jira_sync.json"
        assert sync_file.is_file()
        written = json.loads(sync_file.read_text())
        assert written["violations"][0]["groups"][0]["created"]["key"] == "RHOAIENG-90000"
        assert steps["step"] == "jira_sync" and steps["created"] == 1

    def test_dry_run_plans_no_writes(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[], violations=[_violation()])

        def no_write(*a, **k):
            raise AssertionError("dry run must not write")

        monkeypatch.setattr(mod.jira_ops, "create_issue", no_write)
        monkeypatch.setattr(mod.jira_ops, "update_issue", no_write)
        out = mod.sync(dry_run=True)
        assert out["dry_run"] is True
        group = out["violations"][0]["groups"][0]
        assert group["created"] == {
            "dry_run": True,
            "summary": "Conforma violation: rpm_signature.allowed:1234567890abcdef in odh-ogx-core-v3-6",
        }
        assert group["create_url"].startswith(f"{JIRA_BASE}/secure/CreateIssueDetails!init.jspa?")
        assert not (tmp_path / "run" / "jira_sync.json").exists()
        assert any(a.startswith("[dry-run] would create") for a in out["actions"])

    def test_existing_open_ticket_blocks_create(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[OPEN_TICKET], violations=[_violation()])

        def no_write(*a, **k):
            raise AssertionError("existing ticket must block creation")

        monkeypatch.setattr(mod.jira_ops, "create_issue", no_write)
        out = mod.sync()
        group = out["violations"][0]["groups"][0]
        assert group["existing"]["key"] == "RHOAIENG-80001"
        assert "created" not in group
        assert "create_url" not in group

    def test_existing_partial_match_extends(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[OPEN_TICKET], violations=[_violation()])
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {n: "New Comp" for n in names},
        )
        updates = {}
        monkeypatch.setattr(
            mod.jira_ops,
            "update_issue",
            lambda key, components=None: (
                updates.update(key=key, components=components) or {"key": key, "updated": ["components"]}
            ),
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "components": ["Old"]})
        monkeypatch.setattr(mod.jira_ops, "add_comment", lambda key, body: {"ok": True})
        out = mod.sync()
        group = out["violations"][0]["groups"][0]
        assert group["extended"]["key"] == "RHOAIENG-80001"
        assert updates["components"] == ["Old", "New Comp"]
        assert any(a.startswith("extended RHOAIENG-80001") for a in out["actions"])

    def test_existing_partial_match_extension_failure_is_recorded(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[OPEN_TICKET], violations=[_violation()])
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {n: "New Comp" for n in names},
        )
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"key": key, "components": ["Old"]})
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda *args, **kwargs: {"error": "denied"})
        out = mod.sync()
        assert any(a.startswith("extend-failed RHOAIENG-80001") for a in out["actions"])

    def test_dry_run_with_existing_ticket_emits_no_create(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[OPEN_TICKET], violations=[_violation()])
        out = mod.sync(dry_run=True)
        group = out["violations"][0]["groups"][0]
        assert group["existing"]["key"] == "RHOAIENG-80001"
        assert "created" not in group and "create_url" not in group
        assert not any(a.startswith("created ") for a in out["actions"])

    def test_create_failure_recorded(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[], violations=[_violation()])
        monkeypatch.setattr(mod.jira_ops, "create_issue", lambda **kw: {"key": None, "url": None, "error": "denied"})
        out = mod.sync()
        group = out["violations"][0]["groups"][0]
        assert group["create_error"] == "denied"
        assert any(a.startswith("create-failed") for a in out["actions"])

    def test_prior_issue_linked_after_create(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[CLOSED_TICKET], violations=[_violation()])
        _mock_create_success(monkeypatch)
        links = []
        monkeypatch.setattr(
            mod.jira_ops, "link_issues", lambda a, b, link_type=None: links.append((a, b)) or {"ok": True}
        )
        monkeypatch.setattr(
            mod.jira_ops,
            "get_issue",
            lambda key, fields=None: {
                "key": key,
                "labels": ["conforma", "conforma-exception-ai-skill"],
                "priority": "Blocker",
                "components": [],
            },
        )
        monkeypatch.setattr(mod.jira_ops, "update_issue", lambda key, labels=None: {"key": key, "updated": ["labels"]})
        out = mod.sync()
        assert any(a.startswith("created RHOAIENG-90000") for a in out["actions"])
        assert links == [("RHOAIENG-90000", "RHOAIENG-70681")]
        assert any(a.startswith("linked RHOAIENG-90000 -> RHOAIENG-70681 (relates)") for a in out["actions"])
        assert out["violations"][0]["groups"][0]["prior_issues"][0]["key"] == "RHOAIENG-70681"

    def test_fully_covered_violation_skipped(self, monkeypatch, tmp_path):
        _patch_sync_env(
            monkeypatch,
            tmp_path,
            tickets=[],
            violations=[_violation(uncovered_components=[], all_components=[])],
        )
        out = mod.sync(dry_run=True)
        assert out["violations"] == []

    def test_empty_groups_appended(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[], violations=[_violation()])
        monkeypatch.setattr(mod, "group_components_by_jira", lambda uncovered, catalog: [])
        out = mod.sync(dry_run=True)
        assert out["violations"][0]["groups"] == []

    def test_discovery_error_propagates(self, monkeypatch, tmp_path):
        _patch_sync_env(monkeypatch, tmp_path, tickets=[], violations=[_violation()])
        monkeypatch.setattr(
            mod,
            "discover_conforma_tickets",
            lambda **k: (_ for _ in ()).throw(mod.jira_ops.JiraSearchError("bad", "jql")),
        )
        try:
            mod.sync()
            raise AssertionError("expected JiraSearchError")
        except mod.jira_ops.JiraSearchError:
            pass


class TestPrivateHelpers:
    def test_release_from_context_variants(self):
        assert mod._release_from_context({"application": {"release": "r1"}}) == "r1"
        assert mod._release_from_context({"application": {"version": "v1"}}) == "v1"
        assert mod._release_from_context({"user_query": "q1"}) == "q1"
        assert mod._release_from_context({}) == ""

    def test_load_coverage_violations_missing_file(self, tmp_path):
        try:
            mod._load_coverage_violations(tmp_path)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "coverage.json not found" in str(exc)

    def test_load_catalog_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "load_catalog",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no clone")),
        )
        assert mod._load_catalog() == []

    def test_ticket_ref_with_and_without_analyzed_release(self):
        ref = mod._ticket_ref(
            {
                "key": "K",
                "status": "Open",
                "url": "u",
                "_analyzed_release": "rhoai-3.6",
                "fix_versions": ["RHOAI 3.6"],
            }
        )
        assert ref["release_relevance"] == "targets_current"
        assert mod._ticket_ref({"key": "K"})["release_relevance"] == "unknown"

    def test_jira_component_for_group(self):
        assert mod._jira_component_for_group({"jira_component": "J"}) == "J"
        assert mod._jira_component_for_group({"jira_component": "Unmapped"}) is None
        assert mod._jira_component_for_group({"jira_component": None}) is None

    def test_map_jira_components_dedupes(self):
        groups = [
            {"jira_component": "J"},
            {"jira_component": "J"},
            {"jira_component": "Unmapped"},
            {"jira_component": "K"},
        ]
        assert mod._map_jira_components(groups) == ["J", "K"]

    def test_existing_component_names(self, monkeypatch):
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"components": ["A", "B"]})
        assert mod._existing_component_names("K") == ["A", "B"]
        monkeypatch.setattr(mod.jira_ops, "get_issue", lambda key, fields=None: {"error": "x"})
        assert mod._existing_component_names("K") == []

    def test_now_iso_format(self):
        import re

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", mod._now_iso())

    def test_compact_summary_with_values(self):
        out = {
            "discovered": [{"key": "A"}, {"key": "B"}],
            "actions": [
                "created RHOAIENG-1",
                "created RHOAIENG-2",
                "extended RHOAIENG-3 +X",
                "labeled RHOAIENG-4 +conforma",
                "linked RHOAIENG-1 -> RHOAIENG-4 (relates)",
            ],
            "violations": [
                {"groups": [{"prior_issues": [{"key": "P1"}, {"key": "P2"}]}]},
                {"groups": []},
            ],
        }
        text = mod.compact_summary(out)
        assert "Discovered: 2 tickets" in text
        assert "Created: 2 (RHOAIENG-1, RHOAIENG-2)" in text
        assert "Extended: 1 (RHOAIENG-3" in text
        assert "Self-healed labels: 1 (RHOAIENG-4)" in text
        assert "Linked: 1" in text
        assert "Prior issues (closed, context only): 2" in text

    def test_compact_summary_empty(self):
        text = mod.compact_summary({"actions": [], "violations": []})
        assert "Discovered: 0 tickets" in text
        assert "Created: 0" in text
        assert "Linked: 0" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
class TestCmdFind:
    def test_prints_table_no_writes(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **k: [dict(OPEN_TICKET), dict(CLOSED_TICKET)])

        def no_write(tickets):
            raise AssertionError("find must not self-heal (read-only)")

        monkeypatch.setattr(mod, "self_heal_labels", no_write)
        assert mod.cmd_find() == 0
        out = capsys.readouterr().out
        assert "Discovered 2 conforma tickets:" in out
        assert "RHOAIENG-80001  [existing]  In Progress" in out
        assert "RHOAIENG-70681  [prior-issue]  Closed" in out
        assert "labeled" not in out

    def test_find_is_read_only_even_for_unlabeled_tickets(self, monkeypatch, capsys):
        monkeypatch.setattr(
            mod,
            "discover_conforma_tickets",
            lambda **k: [{"key": "K-1", "labels": [], "summary": "Conforma violation: r in a"}],
        )

        def no_write(tickets):
            raise AssertionError("find must not self-heal (read-only)")

        monkeypatch.setattr(mod, "self_heal_labels", no_write)
        assert mod.cmd_find() == 0
        assert "Discovered 1" in capsys.readouterr().out


class TestCmdLabel:
    def test_prints_json_and_passes_apply_flag(self, monkeypatch, capsys):
        captured = {}
        monkeypatch.setattr(
            mod,
            "label_conforma_tickets",
            lambda apply=False: captured.update(apply=apply) or {"apply": apply, "actions": []},
        )

        assert mod.cmd_label(apply=True) == 0
        assert captured == {"apply": True}
        assert '"apply": true' in capsys.readouterr().out


class TestCmdAudit:
    def test_reports_gaps(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **k: [dict(OPEN_TICKET)])
        monkeypatch.setattr(mod, "self_heal_labels", lambda tickets: ["labeled RHOAIENG-80001 +conforma"])
        assert mod.cmd_audit() == 0
        out = capsys.readouterr().out
        assert "labeled RHOAIENG-80001 +conforma" in out
        assert "Audited 1 tickets" in out
        assert "with gaps:" in out

    def test_prints_gap_details(self, monkeypatch, capsys):
        ticket = {**OPEN_TICKET, "labels": ["conforma"]}
        monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **k: [ticket])
        monkeypatch.setattr(mod, "self_heal_labels", lambda tickets: [])
        assert mod.cmd_audit() == 0
        assert "RHOAIENG-80001: missing=" in capsys.readouterr().out


class TestCmdAuditTicket:
    def test_prints_single_ticket_evidence(self, monkeypatch, capsys):
        monkeypatch.setattr(
            mod,
            "audit_ticket_evidence",
            lambda key, violation, release: {
                "key": key,
                "status": "audited",
                "evidence": {"classification": "possible"},
            },
        )
        assert mod.cmd_audit_ticket("K-1", "rule", "component-v3-6", "rhoai-3.6") == 0
        assert '"status": "audited"' in capsys.readouterr().out


class TestModuleEntryPoint:
    def test_script_entry_point_runs_help(self, monkeypatch, capsys):
        script_path = str(Path(mod.__file__).resolve())
        scripts_dir = str(Path(script_path).parent)
        original_path = list(sys.path)
        original_argv = list(sys.argv)
        sys.path[:] = [item for item in sys.path if item != scripts_dir]
        sys.argv[:] = [script_path, "--help"]
        try:
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_path(script_path, run_name="__main__")
            assert exc_info.value.code == 0
        finally:
            sys.path[:] = original_path
            sys.argv[:] = original_argv
        assert "usage:" in capsys.readouterr().out


class TestCmdRepair:
    def test_prints_actions(self, monkeypatch, tmp_path, capsys):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        monkeypatch.setattr(mod, "discover_conforma_tickets", lambda **k: [dict(OPEN_TICKET)])
        monkeypatch.setattr(mod, "_load_catalog", lambda: CATALOG)
        monkeypatch.setattr(mod.conforma_context_ops, "discover_run_dir", lambda explicit=None: run_dir)
        monkeypatch.setattr(
            mod.conforma_context_ops,
            "load",
            lambda run_dir: {"application": {"release": "rhoai-3.6"}},
        )
        monkeypatch.setattr(mod, "repair_index", lambda tickets, release, catalog: ["repaired K: x"])
        assert mod.cmd_repair() == 0
        assert "repaired K: x" in capsys.readouterr().out


class TestCmdPrefillUrl:
    def test_prints_prefill_url(self, monkeypatch, capsys):
        monkeypatch.setattr(mod, "_load_catalog", lambda: CATALOG)
        monkeypatch.setattr(mod.conforma_context_ops, "discover_run_dir", lambda explicit=None: Path("/tmp/run"))
        monkeypatch.setattr(
            mod.conforma_context_ops,
            "load",
            lambda run_dir: {"environment": "stage", "application": {"release": "rhoai-3.6"}},
        )
        monkeypatch.setattr(
            mod.component_catalog_ops,
            "resolve_jira_components",
            lambda names, catalog: {n: "AI-Guardrails" for n in names},
        )
        assert mod.cmd_prefill_url("hermetic_task.hermetic", " odh-ogx-core , odh-vllm ", "10350") == 0
        url = capsys.readouterr().out.strip()
        assert url.startswith(f"{JIRA_BASE}/secure/CreateIssueDetails!init.jspa?")
        assert "pid=10350" in url
        assert "customfield_10855=rhoai-3.6" in url
        assert "components=AI-Guardrails%2CAI+Serving" in url or "components=" in url


class TestMain:
    def _set_argv(self, monkeypatch, *argv):
        monkeypatch.setattr("sys.argv", ["conforma_jira_ticket_ops.py", *argv])

    def test_sync_dry_run_prints_json_and_summary(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "create-jiras-for-conforma-violations", "--dry-run")
        monkeypatch.setattr(mod, "sync", lambda dry_run=False: {"actions": [], "violations": [], "dry_run": dry_run})
        assert mod.main() == 0
        out = capsys.readouterr().out
        assert '"dry_run": true' in out
        assert "## Jira sync summary" in out

    def test_find_dispatch(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "find")
        monkeypatch.setattr(mod, "cmd_find", lambda: 0)
        assert mod.main() == 0

    def test_audit_ticket_dispatch(self, monkeypatch):
        self._set_argv(
            monkeypatch,
            "audit-ticket",
            "--key",
            "K-1",
            "--rule",
            "rule",
            "--components",
            "component-v3-6",
            "--release",
            "rhoai-3.6",
        )
        monkeypatch.setattr(mod, "cmd_audit_ticket", lambda key, rule, components, release: 0)
        assert mod.main() == 0

    def test_label_dispatch(self, monkeypatch):
        self._set_argv(monkeypatch, "label-conforma-tickets", "--apply")
        monkeypatch.setattr(mod, "cmd_label", lambda apply=False: 0 if apply else 1)
        assert mod.main() == 0

    def test_audit_dispatch(self, monkeypatch):
        self._set_argv(monkeypatch, "audit")
        monkeypatch.setattr(mod, "cmd_audit", lambda: 0)
        assert mod.main() == 0

    def test_repair_dispatch(self, monkeypatch):
        self._set_argv(monkeypatch, "repair")
        monkeypatch.setattr(mod, "cmd_repair", lambda: 0)
        assert mod.main() == 0

    def test_prefill_url_dispatch(self, monkeypatch):
        self._set_argv(monkeypatch, "prefill-url", "--rule", "r", "--components", "a", "--project-id", "1")
        monkeypatch.setattr(mod, "cmd_prefill_url", lambda rule, components, project_id: 0)
        assert mod.main() == 0

    def test_search_error_returns_1_with_json(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "create-jiras-for-conforma-violations")
        monkeypatch.setattr(
            mod,
            "sync",
            lambda dry_run=False: (_ for _ in ()).throw(mod.jira_ops.JiraSearchError("bad jql", "jql", 400)),
        )
        assert mod.main() == 1
        err = capsys.readouterr().err
        payload = json.loads(err)
        assert payload["error"] == "bad jql"
        assert payload["jql"] == "jql"
        assert payload["status"] == 400

    def test_runtime_error_returns_1(self, monkeypatch, capsys):
        self._set_argv(monkeypatch, "audit")
        monkeypatch.setattr(mod, "cmd_audit", lambda: (_ for _ in ()).throw(RuntimeError("no active run")))
        assert mod.main() == 1
        assert "ERROR: no active run" in capsys.readouterr().err
