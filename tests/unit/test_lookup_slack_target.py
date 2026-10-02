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


if __name__ == "__main__":
    unittest.main()
