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

    def test_next_steps_renders_in_table(self):
        results = [
            {
                "rule": "test.rule",
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "next_steps": "untracked, needs fix or exception — see resolution guide",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "see resolution guide" in md
        assert "untracked" in md

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

    def test_violation_count_column(self):
        results = [
            {
                "rule": "test.rule",
                "violation_count": 5,
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "next_steps": "see resolution guide",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary)
        assert "| 5 |" in md

    def test_column_header_says_merge_requests(self):
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
        assert "Open Merge Requests" in md
        assert "Open MRs" not in md


class TestSummarizeNextSteps:
    """Tests for _summarize_next_steps context-sensitive hints."""

    def test_fully_covered(self):
        result = mod._summarize_next_steps("fully_covered", [], [], 0)
        assert "covered by existing exceptions" in result
        assert "resolution guide" in result

    def test_not_covered_no_mr_no_jira(self):
        result = mod._summarize_next_steps("not_covered", [], [], 3)
        assert "untracked" in result
        assert "needs fix or exception" in result

    def test_not_covered_with_jira(self):
        tickets = [{"key": "RHOAIENG-1", "status": "Open"}]
        result = mod._summarize_next_steps("not_covered", [], tickets, 3)
        assert "Jira tracked" in result
        assert "needs fix or exception" in result

    def test_not_covered_with_exception_mr(self):
        mrs = [{"suggestion": "fully_covered", "mr_type": "exception", "iid": 1}]
        result = mod._summarize_next_steps("not_covered", mrs, [], 3)
        assert "exception Merge Request open" in result

    def test_not_covered_with_remedy_mr(self):
        mrs = [{"suggestion": "no_overlap", "mr_type": "remedy", "iid": 2}]
        result = mod._summarize_next_steps("not_covered", mrs, [], 3)
        assert "remedy Merge Request open" in result

    def test_not_covered_with_both_mr_types(self):
        mrs = [
            {"suggestion": "fully_covered", "mr_type": "exception", "iid": 1},
            {"suggestion": "no_overlap", "mr_type": "remedy", "iid": 2},
        ]
        result = mod._summarize_next_steps("not_covered", mrs, [], 3)
        assert "exception + remedy Merge Requests open" in result

    def test_partially_covered_with_uncovered_count(self):
        mrs = [{"suggestion": "extend_mr", "mr_type": "exception", "iid": 1}]
        result = mod._summarize_next_steps("partially_covered", mrs, [], 5)
        assert "5 component(s) still uncovered" in result
        assert "exception Merge Request open" in result

    def test_partially_covered_no_mr(self):
        result = mod._summarize_next_steps("partially_covered", [], [], 2)
        assert "2 component(s) still uncovered" in result

    def test_all_results_end_with_resolution_guide(self):
        for cov in ["fully_covered", "partially_covered", "not_covered"]:
            result = mod._summarize_next_steps(cov, [], [], 1)
            assert result.endswith("— see resolution guide")
