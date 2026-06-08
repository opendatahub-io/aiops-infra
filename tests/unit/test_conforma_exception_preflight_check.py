"""Tests for conforma-exception preflight_check.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import preflight_check as mod


class TestImageUrlCoversComponent:
    def test_rhel9_image_covers_versioned_component(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-dashboard-rhel9",
            "odh-dashboard-v3-4",
        )

    def test_ubi9_image_covers_ea_component(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-vllm-cpu-ubi9",
            "odh-vllm-cpu-v3-5-ea-1",
        )

    def test_different_base_names_do_not_match(self):
        assert not mod.image_url_covers_component(
            "quay.io/rhoai/odh-dashboard-rhel9",
            "odh-modelmesh-v3-4",
        )

    def test_same_base_different_versions(self):
        assert mod.image_url_covers_component(
            "quay.io/rhoai/odh-mlmd-grpc-server-rhel9",
            "odh-mlmd-grpc-server-v2-25",
        )


class TestEvaluateDecision:
    def test_proceed_create_new_when_not_checked(self):
        result = mod.evaluate_decision(
            existing_exceptions={"checked": False, "reason": "No local clone"},
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "create_new"

    def test_abort_on_permanent_global_exclusion_in_target_env(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [
                    {
                        "file": "config/.../registry-rhoai-prod.yaml",
                        "line": 10,
                        "type": "permanent_global_exclusion",
                    }
                ],
                "existing_exceptions": [],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is False
        assert result["action"] == "abort"
        assert "permanently excluded" in result["reason"]

    def test_abort_on_permanent_scoped_exception(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": True,
                        "componentNames": ["odh-dashboard-v3-4", "odh-model-v3-4"],
                        "effectiveUntil": None,
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is False
        assert result["action"] == "abort"

    def test_extend_when_matching_component_names_and_effective_until(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": True,
                        "componentNames": ["odh-dashboard-v3-4"],
                        "effectiveUntil": "2026-12-01T00:00:00Z",
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "extend"

    def test_append_new_style_when_old_style_exists(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": False,
                        "componentNames": [],
                        "effectiveUntil": "2026-12-01T00:00:00Z",
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "append_new_style"

    def test_create_new_when_different_component_names(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [],
                "existing_exceptions": [
                    {
                        "file": "registry-rhoai-prod.yaml",
                        "has_componentNames": True,
                        "componentNames": ["odh-other-v3-4"],
                        "effectiveUntil": "2026-12-01T00:00:00Z",
                    }
                ],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "create_new"

    def test_stage_permanent_exclusion_does_not_block_prod(self):
        result = mod.evaluate_decision(
            existing_exceptions={
                "checked": True,
                "permanent_exclusions": [
                    {
                        "file": "config/.../registry-rhoai-stage.yaml",
                        "line": 5,
                    }
                ],
                "existing_exceptions": [],
            },
            components_per_version={"rhoai-3.4": ["odh-dashboard-v3-4"]},
            environment="prod",
        )
        assert result["proceed"] is True
        assert result["action"] == "create_new"


class TestAnalyzeMrComponentCoverage:
    def setup_method(self):
        mod._mr_cache._diffs.clear()

    def test_fully_covered_from_prefetched_diff(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - odh-dashboard-v3-4\n"
            "+              - odh-model-v3-4\n"
        )
        mod._mr_cache.store(
            42,
            [
                {
                    "new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml",
                    "diff": diff,
                }
            ],
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=42,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["source"] == "diff"
        assert result["suggestion"] == "fully_covered"
        assert result["covered"] == ["odh-dashboard-v3-4", "odh-model-v3-4"]
        assert result["missing"] == []

    def test_extend_mr_when_partial_overlap_from_diff(self):
        diff = (
            "+++ b/config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml\n"
            "+          - value: hermetic_task.hermetic\n"
            "+            componentNames:\n"
            "+              - odh-dashboard-v3-4\n"
        )
        mod._mr_cache.store(
            7,
            [
                {
                    "new_path": "config/.../EnterpriseContractPolicy/registry-rhoai-prod.yaml",
                    "diff": diff,
                }
            ],
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=7,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4", "odh-model-v3-4"],
        )

        assert result["suggestion"] == "extend_mr"
        assert result["covered"] == ["odh-dashboard-v3-4"]
        assert result["missing"] == ["odh-model-v3-4"]

    def test_falls_back_to_description_when_diff_empty(self):
        description = (
            "## Exception: `trusted_task.trusted` for `rhoai-3.4`\n\n"
            "### Components\n"
            "- `odh-modelmesh-v3-4`\n"
            "- `odh-dashboard-v3-4`\n"
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=99,
            rule="trusted_task.trusted",
            requested_components=["odh-dashboard-v3-4"],
            mr_description=description,
        )

        assert result["source"] == "description"
        assert result["suggestion"] == "fully_covered"
        assert "odh-dashboard-v3-4" in result["covered"]

    def test_no_overlap_when_diff_and_description_missing(self):
        result = mod.analyze_mr_component_coverage(
            mr_iid=1,
            rule="hermetic_task.hermetic",
            requested_components=["odh-dashboard-v3-4"],
        )
        assert result["suggestion"] == "no_overlap"
        assert result["source"] == "none"
        assert result["missing"] == ["odh-dashboard-v3-4"]

    @patch("cli_runner.run_glab")
    def test_fetches_diff_on_demand_when_not_cached(self, mock_run_glab):
        mock_run_glab.return_value = MagicMock(
            returncode=0,
            stdout=(
                '{"changes": [{"new_path": "exceptions/registry-rhoai-prod.yaml", '
                '"diff": "+- value: schedule.weekday_restriction\\n'
                '+  componentNames:\\n+    - odh-operator-v3-4\\n"}]}'
            ),
        )

        result = mod.analyze_mr_component_coverage(
            mr_iid=55,
            rule="schedule.weekday_restriction",
            requested_components=["odh-operator-v3-4"],
        )

        mock_run_glab.assert_called_once()
        assert result["source"] == "diff"
        assert result["suggestion"] == "fully_covered"
        assert mod._mr_cache.has(55)


class TestPrefetchOpenSlackThreads:
    @patch("slack_ops.search_messages")
    def test_returns_threads_per_rule(self, mock_search):
        mock_search.return_value = [
            {
                "channel": "conforma",
                "channel_id": "C123",
                "permalink": "https://slack.com/p1",
                "thread_ts": "1700000000.000000",
                "thread_reply_count": 3,
                "user": "alice",
                "date": "2024-12-01",
            }
        ]
        result = mod.prefetch_open_slack_threads(["hermetic_task.hermetic"])
        assert len(result["hermetic_task.hermetic"]) == 1
        assert result["hermetic_task.hermetic"][0]["channel"] == "conforma"

    @patch("slack_ops.search_messages")
    def test_deduplicates_by_thread(self, mock_search):
        thread = {
            "channel": "conforma",
            "channel_id": "C123",
            "permalink": "https://slack.com/p1",
            "thread_ts": "1700000000.000000",
            "thread_reply_count": 3,
            "user": "alice",
            "date": "2024-12-01",
        }
        mock_search.return_value = [thread, thread]
        result = mod.prefetch_open_slack_threads(["test.rule"])
        assert len(result["test.rule"]) == 1

    @patch("slack_ops.search_messages")
    def test_empty_results(self, mock_search):
        mock_search.return_value = []
        result = mod.prefetch_open_slack_threads(["no_match.rule"])
        assert result["no_match.rule"] == []


class TestBuildSearchUrls:
    def test_builds_all_urls(self, monkeypatch):
        monkeypatch.setattr(mod, "GITLAB_HOST", "gitlab.example.com")
        monkeypatch.setattr(mod, "GITLAB_PROJECT", "releng/konflux-release-data")
        urls = mod._build_search_urls("hermetic_task.hermetic", "https://test.slack.com")
        assert "gitlab.example.com" in urls["mr"]
        assert "hermetic_task.hermetic" in urls["jira"]
        assert "test.slack.com" in urls["slack"]

    def test_no_slack_url_without_team(self, monkeypatch):
        monkeypatch.setattr(mod, "GITLAB_HOST", "gitlab.example.com")
        monkeypatch.setattr(mod, "GITLAB_PROJECT", "test/project")
        urls = mod._build_search_urls("test.rule", "")
        assert urls["slack"] == ""
        assert urls["mr"] != ""

    def test_no_mr_url_without_gitlab(self, monkeypatch):
        monkeypatch.setattr(mod, "GITLAB_HOST", "")
        monkeypatch.setattr(mod, "GITLAB_PROJECT", "")
        urls = mod._build_search_urls("test.rule", "https://test.slack.com")
        assert urls["mr"] == ""
        assert urls["jira"] != ""


class TestRenderViolationsMarkdownTableSlack:
    def test_includes_slack_column_when_enabled(self):
        results = [
            {
                "rule": "test.rule",
                "display_components": "comp-v1",
                "open_mr_label": "",
                "open_jira_label": "",
                "open_slack_label": "[#conforma](https://slack.com/p1)",
                "next_steps": "resolve",
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
                "next_steps": "resolve",
            }
        ]
        summary = {"total_violations": 1, "fully_covered": 0, "partially_covered": 0, "not_covered": 1}
        md = mod._render_violations_markdown_table(results, summary, include_slack=False)
        assert "Slack" not in md
