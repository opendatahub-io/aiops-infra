"""Tests for scripts/upsert_team_slack_handle.py."""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import upsert_team_slack_handle as upsert  # noqa: E402

FIXTURE = """# Component -> Slack team handle mapping (RHOAIENG-85559).
# Auto-maintained by the component-onboarding pipeline (slack_handle step).
# Manual edits are fine; keep entries alphabetically sorted by component name.
components:
  odh-dashboard:
    slack_team_handle: openshift-ai-dashboard
  odh-kube-auth-proxy:
    slack_team_handle: ai-core-platform
    slack_team_channel: forum-openshift-ai-operator
  odh-zzz:
    slack_team_handle: openshift-ai-devtestops-ic
"""


class TestUpsertAdd(unittest.TestCase):
    def test_inserts_alphabetically(self):
        result = upsert.upsert_component_contact(
            FIXTURE, "odh-lighthouse", "ai-core-platform"
        )
        self.assertEqual(result["status"], "added")
        text = result["text"]
        dashboard = text.index("odh-dashboard:")
        lighthouse = text.index("odh-lighthouse:")
        proxy = text.index("odh-kube-auth-proxy:")
        self.assertLess(dashboard, proxy)
        self.assertLess(proxy, lighthouse)
        self.assertIn("odh-lighthouse:\n    slack_team_handle: ai-core-platform\n", text)

    def test_inserts_at_end_when_alphabetically_last(self):
        result = upsert.upsert_component_contact(
            FIXTURE, "odh-zzzz", "openshift-ai-devtestops-ic"
        )
        text = result["text"]
        zzz = text.index("odh-zzz:")
        zzzz = text.index("odh-zzzz:")
        self.assertLess(zzz, zzzz)

    def test_inserts_channel_when_provided(self):
        result = upsert.upsert_component_contact(
            FIXTURE,
            "odh-lighthouse",
            "ai-core-platform",
            slack_team_channel="forum-openshift-ai-operator",
        )
        self.assertIn(
            "odh-lighthouse:\n    slack_team_handle: ai-core-platform\n"
            "    slack_team_channel: forum-openshift-ai-operator\n",
            result["text"],
        )

    def test_strips_at_and_hash(self):
        result = upsert.upsert_component_contact(
            FIXTURE, "odh-lighthouse", "@ai-core-platform", "#forum-openshift-ai-operator"
        )
        self.assertIn("slack_team_handle: ai-core-platform\n", result["text"])
        self.assertIn("slack_team_channel: forum-openshift-ai-operator\n", result["text"])


class TestUpsertIdempotent(unittest.TestCase):
    def test_already_present_same_values(self):
        result = upsert.upsert_component_contact(
            FIXTURE,
            "odh-kube-auth-proxy",
            "ai-core-platform",
            slack_team_channel="forum-openshift-ai-operator",
        )
        self.assertEqual(result["status"], "already_present")
        self.assertEqual(result["text"], FIXTURE)

    def test_conflict_when_handle_differs(self):
        with self.assertRaises(ValueError) as ctx:
            upsert.upsert_component_contact(
                FIXTURE, "odh-dashboard", "some-other-team"
            )
        self.assertIn("already exists", str(ctx.exception))


class TestUpsertValidation(unittest.TestCase):
    def test_rejects_missing_components_key(self):
        with self.assertRaises(ValueError):
            upsert.upsert_component_contact("foo: bar\n", "odh-x", "ai-core-platform")

    def test_rejects_invalid_handle(self):
        with self.assertRaises(ValueError):
            upsert.upsert_component_contact(FIXTURE, "odh-x", "Not A Handle")


if __name__ == "__main__":
    unittest.main()
