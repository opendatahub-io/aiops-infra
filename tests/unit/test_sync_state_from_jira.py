"""Tests for scripts/sync_state_from_jira.py slack_handle skip restoration."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import sync_state_from_jira as sync  # noqa: E402


def _state(status: str = "pending", pr_url: str = "") -> dict:
    return {"steps": {"slack_handle": {"status": status, "pr_url": pr_url}}}


class TestYamlSlackTeamHandle(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(sync.yaml_slack_team_handle(None), "")
        self.assertEqual(sync.yaml_slack_team_handle(Path("/no/such/file.yaml")), "")

    def test_reads_bare_and_quoted_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "component_onboarding_details.yaml"
            path.write_text("component_name: odh-x\n  slack_team_handle: rhai-agentops\n")
            self.assertEqual(sync.yaml_slack_team_handle(path), "rhai-agentops")
            path.write_text('slack_team_handle: "rhai-agentops"\n')
            self.assertEqual(sync.yaml_slack_team_handle(path), "rhai-agentops")

    def test_empty_value_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "component_onboarding_details.yaml"
            path.write_text('slack_team_handle: ""\n')
            self.assertEqual(sync.yaml_slack_team_handle(path), "")


class TestSyncSlackHandleSkip(unittest.TestCase):
    def test_label_restores_skipped_when_handle_absent(self):
        state = _state()
        changes = sync.sync_slack_handle_skip(
            state, ["slack-routing-not-provided"], None
        )
        self.assertEqual(state["steps"]["slack_handle"]["status"], "skipped")
        self.assertEqual(len(changes), 1)

    def test_already_skipped_does_not_report_a_change(self):
        state = _state("skipped")
        changes = sync.sync_slack_handle_skip(
            state, ["slack-routing-not-provided"], None
        )
        self.assertEqual(changes, [])
        self.assertEqual(state["steps"]["slack_handle"]["status"], "skipped")

    def test_does_not_downgrade_pr_raised_or_done(self):
        for status in ("pr_raised", "merged", "done"):
            state = _state(status)
            sync.sync_slack_handle_skip(state, ["slack-routing-not-provided"], None)
            self.assertEqual(state["steps"]["slack_handle"]["status"], status)

    def test_no_label_leaves_pending(self):
        state = _state()
        changes = sync.sync_slack_handle_skip(state, ["yaml-attached"], None)
        self.assertEqual(changes, [])
        self.assertEqual(state["steps"]["slack_handle"]["status"], "pending")

    def test_handle_in_yaml_is_not_re_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "component_onboarding_details.yaml"
            path.write_text("slack_team_handle: rhai-agentops\n")
            state = _state()
            changes = sync.sync_slack_handle_skip(
                state, ["slack-routing-not-provided"], path
            )
            self.assertEqual(changes, [])
            self.assertEqual(state["steps"]["slack_handle"]["status"], "pending")

    def test_handle_in_yaml_reopens_a_previous_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "component_onboarding_details.yaml"
            path.write_text("slack_team_handle: rhai-agentops\n")
            state = _state("skipped")
            changes = sync.sync_slack_handle_skip(
                state, ["slack-routing-not-provided"], path
            )
            self.assertEqual(state["steps"]["slack_handle"]["status"], "pending")
            self.assertEqual(len(changes), 1)

    def test_handle_does_not_reopen_when_pr_url_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "component_onboarding_details.yaml"
            path.write_text("slack_team_handle: rhai-agentops\n")
            state = _state("skipped", pr_url="https://github.com/example/pull/1")
            changes = sync.sync_slack_handle_skip(
                state, ["slack-routing-not-provided"], path
            )
            self.assertEqual(changes, [])
            self.assertEqual(state["steps"]["slack_handle"]["status"], "skipped")


class TestMainRestoresSkip(unittest.TestCase):
    def test_fresh_state_with_label_becomes_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "component_onboarding_details.yaml").write_text(
                "component_name: odh-openshell-e2e\n"
            )
            (root / "component_onboarding_details.json").write_text(
                json.dumps(
                    {
                        "fields": {
                            "labels": ["slack-routing-not-provided", "yaml-attached"],
                            "comment": {"comments": []},
                        }
                    }
                )
            )
            state_path = root / "pipeline_state.json"
            state_path.write_text(json.dumps(_state()))
            old_argv = sys.argv
            try:
                sys.argv = [
                    "sync_state_from_jira.py",
                    "--jira-details",
                    str(root / "component_onboarding_details.json"),
                    "--pipeline-state",
                    str(state_path),
                ]
                sync.main()
            finally:
                sys.argv = old_argv
            restored = json.loads(state_path.read_text())
            self.assertEqual(restored["steps"]["slack_handle"]["status"], "skipped")

    def test_raised_label_wins_over_not_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "component_onboarding_details.yaml").write_text(
                "component_name: odh-openshell-e2e\n"
            )
            (root / "component_onboarding_details.json").write_text(
                json.dumps(
                    {
                        "fields": {
                            "labels": [
                                "slack-routing-not-provided",
                                "slack-routing-pr-raised",
                            ],
                            "comment": {"comments": []},
                        }
                    }
                )
            )
            state_path = root / "pipeline_state.json"
            state_path.write_text(json.dumps(_state()))
            old_argv = sys.argv
            try:
                sys.argv = [
                    "sync_state_from_jira.py",
                    "--jira-details",
                    str(root / "component_onboarding_details.json"),
                    "--pipeline-state",
                    str(state_path),
                ]
                sync.main()
            finally:
                sys.argv = old_argv
            restored = json.loads(state_path.read_text())
            self.assertEqual(restored["steps"]["slack_handle"]["status"], "pr_raised")


if __name__ == "__main__":
    unittest.main()
