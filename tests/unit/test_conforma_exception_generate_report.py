"""Tests for conforma-exception generate_report.py."""

from __future__ import annotations

import generate_report


def _minimal_expired_data() -> dict:
    """Assessment data for expired-only scope."""
    return {
        "generated_at": "2026-06-01T12:00:00Z",
        "scope": "expired",
        "releases_checked": ["rhoai-3.4"],
        "releases_not_checked": [],
        "report_created_at": {"rhoai-3.4": "2026-05-28T00:00:00Z"},
        "assessed_exceptions": [
            {
                "rule": "hermetic_task.hermetic",
                "comment_header_lines": ["# Hermetic build exception"],
                "effective_until": "2026-01-01T00:00:00Z",
                "is_expired": True,
                "expired_days_ago": 151,
                "classification": "still_needed",
                "recommended_action": "extend",
                "reference": "https://issues.redhat.com/browse/RHOAIENG-12345",
                "file": "config/prod/registry-rhoai-3.4.yaml",
                "component_names": ["odh-mlflow-v3-4"],
                "is_unscoped": False,
                "evidence": {
                    "still_violating_releases": ["rhoai-3.4"],
                    "still_violating_components": ["odh-mlflow-v3-4"],
                    "resolved_in_releases": [],
                    "report_urls": {},
                },
            },
            {
                "rule": "rpm_signature.allowed:abc123",
                "effective_until": "2025-12-01T00:00:00Z",
                "is_expired": True,
                "expired_days_ago": 182,
                "classification": "no_longer_needed",
                "recommended_action": "remove",
                "reference": "",
                "file": "config/prod/fbc-rhoai-3.4.yaml",
                "component_names": [],
                "image_url": "quay.io/rhoai/odh-operator-bundle",
                "is_unscoped": True,
                "evidence": {
                    "still_violating_releases": [],
                    "still_violating_components": [],
                    "resolved_in_releases": ["rhoai-3.4"],
                    "report_urls": {},
                },
            },
        ],
    }


def _minimal_all_scope_data() -> dict:
    """Assessment data for mixed expired + active scope."""
    return {
        "generated_at": "2026-06-01T12:00:00Z",
        "scope": "all",
        "releases_checked": ["rhoai-3.4", "rhoai-3.5"],
        "releases_not_checked": [
            {"release": "rhoai-3.3", "error": "report not found"},
        ],
        "report_created_at": {
            "rhoai-3.4": "2026-05-28T00:00:00Z",
            "rhoai-3.5": "2026-05-29T00:00:00Z",
        },
        "assessed_exceptions": [
            {
                "rule": "trusted_task.trusted",
                "effective_until": "2026-12-01T00:00:00Z",
                "is_expired": False,
                "expires_in_days": 183,
                "classification": "still_needed",
                "recommended_action": "keep",
                "reference": "https://github.com/org/repo/issues/42",
                "file": "config/prod/registry-rhoai-3.5.yaml",
                "component_names": ["odh-modelmesh-v3-5"],
                "is_unscoped": False,
                "evidence": {
                    "still_violating_releases": ["rhoai-3.5"],
                    "still_violating_components": ["odh-modelmesh-v3-5"],
                    "resolved_in_releases": ["rhoai-3.4"],
                    "report_urls": {},
                },
            },
            {
                "rule": "prefetch_mode.permissive",
                "effective_until": "2026-03-01T00:00:00Z",
                "is_expired": True,
                "expired_days_ago": 92,
                "classification": "partially_needed",
                "recommended_action": "narrow_and_extend",
                "reference": "https://redhat.atlassian.net/browse/PSX-999",
                "file": "config/prod/registry-rhoai-3.4.yaml",
                "component_names": ["odh-notebooks-v3-4", "odh-dashboard-v3-4"],
                "is_unscoped": False,
                "evidence": {
                    "still_violating_releases": ["rhoai-3.4"],
                    "still_violating_components": ["odh-notebooks-v3-4"],
                    "resolved_in_releases": ["rhoai-3.5"],
                    "report_urls": {},
                },
            },
        ],
    }


class TestGenerateMarkdown:
    def test_expired_scope_header_and_summary(self):
        md = generate_report.generate_markdown(_minimal_expired_data())
        assert "# RHOAI Conforma Expired Exceptions" in md
        assert "## Summary" in md
        assert "Expired | Still needed | Can remove | Need modernizing" in md
        assert "| 2 |" in md

    def test_expired_scope_includes_removable_section(self):
        md = generate_report.generate_markdown(_minimal_expired_data())
        assert "## Can remove" in md
        assert "## Exception / Release Matrix" in md
        assert "## Details per exception" in md
        assert "hermetic_task.hermetic" in md
        assert "[RHOAIENG-12345]" in md
        assert "`[fbc]`" in md

    def test_all_scope_header_and_summary(self):
        md = generate_report.generate_markdown(_minimal_all_scope_data())
        assert "# RHOAI Conforma Exception Assessment" in md
        assert "Total | Expired | Active | Can remove" in md
        assert "> **Not checked:** rhoai-3.3: report not found" in md
        assert "Effective Until" in md
        assert "in 183d" in md

    def test_footer_present(self):
        md = generate_report.generate_markdown(_minimal_expired_data())
        assert "Generated by conforma-analyze + conforma-exception skills" in md


class TestBuildActionPlan:
    def test_skips_keep_actions(self):
        plan = generate_report.build_action_plan(_minimal_all_scope_data())
        assert plan["total_skipped_keep"] == 1
        assert plan["total_actions"] == 1
        assert len(plan["actions"]) == 1

    def test_action_fields_and_sort_order(self):
        plan = generate_report.build_action_plan(_minimal_expired_data())
        assert plan["generated_at"] == "2026-06-01T12:00:00Z"
        assert plan["total_actions"] == 2
        actions = plan["actions"]
        assert actions[0]["action"] == "remove"
        assert actions[1]["action"] == "extend"
        assert actions[0]["label"]
        assert actions[0]["policy_file"].endswith(".yaml")
        assert "rhoai-3.4" in actions[1]["versions"]

    def test_unscoped_flag_preserved(self):
        plan = generate_report.build_action_plan(_minimal_expired_data())
        remove_action = plan["actions"][0]
        assert remove_action["is_unscoped"] is True
        assert remove_action["resolved_in"] == ["rhoai-3.4"]
