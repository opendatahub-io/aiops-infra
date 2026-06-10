"""Tests for conforma-analyze violations_coverage.py."""

from __future__ import annotations

import conforma_mr_ops
import violations_coverage as mod


class TestBuildSearchUrls:
    def test_builds_all_urls(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.example.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "releng/konflux-release-data")
        urls = mod._build_search_urls("hermetic_task.hermetic", "https://test.slack.com")
        assert "gitlab.example.com" in urls["mr"]
        assert "hermetic_task.hermetic" in urls["jira"]
        assert "test.slack.com" in urls["slack"]

    def test_no_slack_url_without_team(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "gitlab.example.com")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "test/project")
        urls = mod._build_search_urls("test.rule", "")
        assert urls["slack"] == ""
        assert urls["mr"] != ""

    def test_no_mr_url_without_gitlab(self, monkeypatch):
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_HOST", "")
        monkeypatch.setattr(conforma_mr_ops, "GITLAB_PROJECT", "")
        urls = mod._build_search_urls("test.rule", "https://test.slack.com")
        assert urls["mr"] == ""
        assert urls["jira"] != ""


class TestRenderViolationsMarkdownTable:
    def test_includes_slack_column_when_enabled(self):
        results = [
            {
                "rule": "test.rule",
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "open_slack_label": "[#conforma](https://slack.com/p1)",
                "next_steps": "see resolution guide below",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary, include_slack=True)
        assert "Slack" in md
        assert "#conforma" in md

    def test_excludes_slack_column_when_disabled(self):
        results = [
            {
                "rule": "test.rule",
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "next_steps": "see resolution guide below",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary, include_slack=False)
        assert "Slack" not in md

    def test_next_steps_is_static_string(self):
        results = [
            {
                "rule": "test.rule",
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "next_steps": "see resolution guide below",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "see resolution guide below" in md

    def test_footer_references_violation_guide(self):
        results = [
            {
                "rule": "test.rule",
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "next_steps": "see resolution guide below",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "Violation Resolution Guide" in md
