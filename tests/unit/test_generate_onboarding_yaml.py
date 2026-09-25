"""Tests for scripts/generate_onboarding_yaml.py."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "generate_onboarding_yaml.py"

ODH_BASE = [
    sys.executable,
    str(SCRIPT),
    "--product-context",
    "ODH",
    "--component-name",
    "odh-lighthouse",
    "--repo-url",
    "https://github.com/opendatahub-io/lighthouse",
    "--repo-branch",
    "main",
    "--context-path",
    "./",
    "--dockerfile-path",
    "Dockerfile",
    "--build-type",
    "CI",
]


class TestGenerateOnboardingYaml(unittest.TestCase):
    def _run(self, extra: list[str]) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as handle:
            output = handle.name
        try:
            return subprocess.run(
                [*ODH_BASE, "--output", output, *extra],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            Path(output).unlink(missing_ok=True)

    def test_requires_slack_team_handle(self):
        result = self._run([])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("slack-team-handle", result.stderr)

    def test_writes_handle_and_optional_channel(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as handle:
            output = Path(handle.name)
        try:
            result = subprocess.run(
                [
                    *ODH_BASE,
                    "--output",
                    str(output),
                    "--slack-team-handle",
                    "@ai-core-platform",
                    "--slack-team-channel",
                    "#forum-openshift-ai-operator",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertIn("slack_team_handle: ai-core-platform", text)
            self.assertIn("slack_team_channel: forum-openshift-ai-operator", text)
        finally:
            output.unlink(missing_ok=True)

    def test_omits_channel_when_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as handle:
            output = Path(handle.name)
        try:
            result = subprocess.run(
                [
                    *ODH_BASE,
                    "--output",
                    str(output),
                    "--slack-team-handle",
                    "ai-core-platform",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = output.read_text(encoding="utf-8")
            self.assertIn("slack_team_handle: ai-core-platform", text)
            self.assertNotIn("slack_team_channel:", text)
        finally:
            output.unlink(missing_ok=True)

    def test_rejects_invalid_handle(self):
        result = self._run(["--slack-team-handle", "Not Valid"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("slack-team-handle", result.stderr)


if __name__ == "__main__":
    unittest.main()
