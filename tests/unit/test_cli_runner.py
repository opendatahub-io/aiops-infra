"""Tests for scripts/cli_runner.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "shared_cli_runner",
    _REPO_ROOT / "scripts/cli_runner.py",
)
cli_runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli_runner)


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestRun:
    def test_success(self):
        with patch.object(
            cli_runner.subprocess,
            "run",
            return_value=_completed(stdout="hello\n", stderr=""),
        ) as mock_run:
            result = cli_runner.run(["echo", "hello"])

        assert result == {
            "returncode": 0,
            "stdout": "hello\n",
            "stderr": "",
            "timed_out": False,
        }
        mock_run.assert_called_once()

    def test_failure(self):
        with patch.object(
            cli_runner.subprocess,
            "run",
            return_value=_completed(returncode=2, stderr="command failed"),
        ):
            result = cli_runner.run(["false"])

        assert result["returncode"] == 2
        assert result["stderr"] == "command failed"
        assert result["timed_out"] is False

    def test_timeout(self):
        with patch.object(
            cli_runner.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("cmd", 5, output="partial", stderr=""),
        ):
            result = cli_runner.run(["sleep", "999"], timeout=5)

        assert result == {
            "returncode": -1,
            "stdout": "partial",
            "stderr": "",
            "timed_out": True,
        }


class TestRunWithRetry:
    def test_succeeds_on_retry(self):
        responses = [
            _completed(returncode=1, stderr="temporary"),
            _completed(stdout="ok"),
        ]
        with patch.object(cli_runner.subprocess, "run", side_effect=responses), \
             patch.object(cli_runner.time, "sleep") as mock_sleep:
            result = cli_runner.run_with_retry(["flaky"], max_retries=3, delay=1)

        assert result == {
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "attempts": 2,
        }
        mock_sleep.assert_called_once_with(1)

    def test_exhausts_retries(self):
        with patch.object(
            cli_runner.subprocess,
            "run",
            return_value=_completed(returncode=1, stderr="still failing"),
        ), patch.object(cli_runner.time, "sleep"):
            result = cli_runner.run_with_retry(["flaky"], max_retries=3, delay=0)

        assert result["returncode"] == 1
        assert result["attempts"] == 3
        assert "still failing" in result["stderr"]


class TestRunJson:
    def test_valid_json(self):
        payload = {"status": "ok", "count": 3}
        with patch.object(
            cli_runner,
            "run",
            return_value={
                "returncode": 0,
                "stdout": json.dumps(payload),
                "stderr": "",
                "timed_out": False,
            },
        ):
            result = cli_runner.run_json(["cmd"])

        assert result == {
            "returncode": 0,
            "data": payload,
            "error": None,
        }

    def test_invalid_json(self):
        with patch.object(
            cli_runner,
            "run",
            return_value={
                "returncode": 0,
                "stdout": "not-json",
                "stderr": "",
                "timed_out": False,
            },
        ):
            result = cli_runner.run_json(["cmd"])

        assert result["data"] is None
        assert "Invalid JSON output" in result["error"]
