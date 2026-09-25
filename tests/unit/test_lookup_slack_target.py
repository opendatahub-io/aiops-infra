"""Tests for scripts/lookup_slack_target.py."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import lookup_slack_target as lookup  # noqa: E402

ROUTING = """
components:
  odh-dashboard:
    slack_team_handle: openshift-ai-dashboard
"""


class TestNormalize(unittest.TestCase):
    def test_channel_strips_hash(self):
        self.assertEqual(lookup.normalize_channel_name("#forum-openshift-ai-operator"), "forum-openshift-ai-operator")

    def test_handle_strips_at(self):
        self.assertEqual(lookup.normalize_handle("@ai-core-platform"), "ai-core-platform")


class TestLookupUsergroup(unittest.TestCase):
    def test_found_in_routing_yaml(self):
        result = lookup.lookup_usergroup("openshift-ai-dashboard", routing_yaml=ROUTING)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "found")

    def test_unknown_when_not_in_yaml(self):
        result = lookup.lookup_usergroup("brand-new-team", routing_yaml=ROUTING)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unknown")

    def test_unknown_without_yaml(self):
        result = lookup.lookup_usergroup("ai-core-platform")
        self.assertEqual(result["status"], "unknown")

    def test_fetch_routing_yaml_returns_none_on_error(self):
        with patch.object(lookup.urllib.request, "urlopen", side_effect=lookup.urllib.error.URLError("down")):
            self.assertIsNone(lookup.fetch_routing_yaml())

    def test_invalid_handle(self):
        result = lookup.lookup_usergroup("Not Valid")
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["ok"])


class TestLookupChannel(unittest.TestCase):
    def test_found(self):
        listed = {
            "ok": True,
            "channels": [{"name": "forum-openshift-ai-operator", "id": "C123"}],
            "error": None,
        }
        with patch.object(lookup, "list_channels", return_value=listed):
            result = lookup.lookup_channel("#forum-openshift-ai-operator")
        self.assertTrue(result["ok"])
        self.assertEqual(result["id"], "C123")

    def test_not_found(self):
        listed = {"ok": True, "channels": [{"name": "general", "id": "C000"}], "error": None}
        with patch.object(lookup, "list_channels", return_value=listed):
            result = lookup.lookup_channel("does-not-exist")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "not_found")

    def test_empty_name(self):
        result = lookup.lookup_channel("   ")
        self.assertEqual(result["status"], "invalid")

    def test_auth_error_propagates(self):
        listed = {"ok": False, "channels": [], "error": "slackdump session expired. Run: slackdump login"}
        with patch.object(lookup, "list_channels", return_value=listed):
            result = lookup.lookup_channel("general")
        self.assertEqual(result["status"], "error")
        self.assertIn("expired", result["error"])


class TestIterChannelRecords(unittest.TestCase):
    def test_list_payload(self):
        records = lookup._iter_channel_records([{"name": "general", "id": "C1"}])
        self.assertEqual(records, [{"name": "general", "id": "C1"}])

    def test_wrapped_payload(self):
        records = lookup._iter_channel_records({"channels": [{"name_normalized": "random", "id": "C2"}]})
        self.assertEqual(records[0]["name"], "random")


if __name__ == "__main__":
    unittest.main()
