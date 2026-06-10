"""Tests for conforma_slack_ops.py."""

from __future__ import annotations

from unittest.mock import patch

import conforma_slack_ops as mod


class TestComponentSearchStems:
    def test_strips_version_suffix(self):
        stems = mod._component_search_stems("odh-ogx-core-v3-5-ea-1")
        assert "odh-ogx-core-v3-5-ea-1" in stems
        assert "odh-ogx-core" in stems
        assert "ogx-core" in stems

    def test_strips_simple_version(self):
        stems = mod._component_search_stems("odh-spark-operator-v3-5")
        assert "odh-spark-operator" in stems
        assert "spark-operator" in stems

    def test_rhoai_prefix(self):
        stems = mod._component_search_stems("rhoai-fbc-fragment-v3-5")
        assert "rhoai-fbc-fragment" in stems
        assert "fbc-fragment" in stems

    def test_no_version_suffix(self):
        stems = mod._component_search_stems("odh-dashboard")
        assert stems == ["odh-dashboard", "dashboard"]

    def test_no_known_prefix(self):
        stems = mod._component_search_stems("custom-component-v1-2")
        assert "custom-component-v1-2" in stems
        assert "custom-component" in stems
        assert len(stems) == 2


class TestThreadMentionsComponent:
    def test_matches_case_insensitive(self):
        assert mod._thread_mentions_component("ODH-Dashboard issue", ["odh-dashboard"])

    def test_no_match(self):
        assert not mod._thread_mentions_component("something unrelated", ["odh-dashboard"])

    def test_empty_text(self):
        assert not mod._thread_mentions_component("", ["odh-dashboard"])


class TestPrefetchOpenSlackThreads:
    @patch("slack_ops.search_messages")
    def test_returns_threads_per_rule_without_components(self, mock_search):
        mock_search.return_value = [
            {
                "channel": "conforma",
                "channel_id": "C123",
                "permalink": "https://slack.com/p1",
                "thread_ts": "1700000000.000000",
                "thread_reply_count": 3,
                "user": "alice",
                "date": "2024-12-01",
                "text": "some message about hermetic",
            }
        ]
        result = mod.prefetch_open_slack_threads(["hermetic_task.hermetic"])
        assert len(result["hermetic_task.hermetic"]) == 1
        assert result["hermetic_task.hermetic"][0]["channel"] == "conforma"

    @patch("slack_ops.search_messages")
    def test_filters_by_component_when_provided(self, mock_search):
        mock_search.return_value = [
            {
                "channel": "conforma",
                "channel_id": "C123",
                "permalink": "https://slack.com/p1",
                "thread_ts": "1700000000.000000",
                "thread_reply_count": 0,
                "user": "alice",
                "date": "2024-12-01",
                "text": "hermetic_task.hermetic violation for odh-ogx-core",
            },
            {
                "channel": "general",
                "channel_id": "C456",
                "permalink": "https://slack.com/p2",
                "thread_ts": "1700000001.000000",
                "thread_reply_count": 0,
                "user": "bob",
                "date": "2024-12-01",
                "text": "hermetic_task.hermetic in odh-dashboard",
            },
        ]
        result = mod.prefetch_open_slack_threads(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )
        assert len(result["hermetic_task.hermetic"]) == 1
        assert result["hermetic_task.hermetic"][0]["channel"] == "conforma"

    @patch("slack_ops.search_messages")
    def test_matches_stemmed_component_name(self, mock_search):
        mock_search.return_value = [
            {
                "channel": "conforma",
                "channel_id": "C123",
                "permalink": "https://slack.com/p1",
                "thread_ts": "1700000000.000000",
                "thread_reply_count": 0,
                "user": "alice",
                "date": "2024-12-01",
                "text": "Need to fix spark-operator hermetic build",
            },
        ]
        result = mod.prefetch_open_slack_threads(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-spark-operator-v3-5-ea-1"]},
        )
        assert len(result["hermetic_task.hermetic"]) == 1

    @patch("slack_ops.search_messages")
    def test_strips_text_from_output(self, mock_search):
        mock_search.return_value = [
            {
                "channel": "conforma",
                "channel_id": "C123",
                "permalink": "https://slack.com/p1",
                "thread_ts": "1700000000.000000",
                "thread_reply_count": 0,
                "user": "alice",
                "date": "2024-12-01",
                "text": "hermetic_task.hermetic violation for ogx-core",
            },
        ]
        result = mod.prefetch_open_slack_threads(
            ["hermetic_task.hermetic"],
            rule_to_components={"hermetic_task.hermetic": ["odh-ogx-core-v3-5-ea-1"]},
        )
        assert "text" not in result["hermetic_task.hermetic"][0]

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
            "text": "some message",
        }
        mock_search.return_value = [thread, thread]
        result = mod.prefetch_open_slack_threads(["test.rule"])
        assert len(result["test.rule"]) == 1

    @patch("slack_ops.search_messages")
    def test_empty_results(self, mock_search):
        mock_search.return_value = []
        result = mod.prefetch_open_slack_threads(["no_match.rule"])
        assert result["no_match.rule"] == []
