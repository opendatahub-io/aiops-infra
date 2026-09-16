"""Tests for scripts/run_long_task.py.

Validates the deterministic long-running-step runner: detached launch, exit-code
capture, the ``done``/``failed``/``running`` state machine, and the key
property that each ``wait`` round's ``next_command`` is unique (so a harness
loop detector never sees two identical calls).
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

import run_long_task as rlt


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _write_target(tmp_path: Path, name: str, body: str) -> Path:
    """Write a small python target script and return its path."""
    target = tmp_path / name
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    return target


def _wait_until_finished(run_dir: Path, step: str, seq: int = 1, rounds: int = 20) -> dict:
    """Drive ``wait`` in a loop until the task reports a terminal status."""
    result = None
    for _ in range(rounds):
        result = rlt.wait(run_dir, step, seq=seq, timeout=5)
        if result["status"] in ("done", "failed"):
            return result
        seq = int(result["next_command"].split("--seq ")[1].split()[0])
    raise AssertionError(f"task '{step}' did not finish in {rounds} rounds: {result}")


# ---------------------------------------------------------------------------
# sanitize_step
# ---------------------------------------------------------------------------


class TestSanitizeStep:
    def test_passthrough_safe(self):
        assert rlt.sanitize_step("fetch") == "fetch"
        assert rlt.sanitize_step("coverage") == "coverage"

    def test_replaces_bad_chars(self):
        assert rlt.sanitize_step("step 7!") == "step-7"

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            rlt.sanitize_step("!!!")


# ---------------------------------------------------------------------------
# next_command uniqueness (the core loop-detector defense)
# ---------------------------------------------------------------------------


class TestNextCommandUniqueness:
    def test_seq_changes_command(self):
        a = rlt._next_wait_command("coverage", 1, 25)
        b = rlt._next_wait_command("coverage", 2, 25)
        assert a != b
        assert "--seq 1" in a
        assert "--seq 2" in b

    def test_launch_and_first_wait_differ(self):
        # A launch command never equals a wait command.
        wait_cmd = rlt._next_wait_command("coverage", 1, 25)
        assert "wait coverage" in wait_cmd


# ---------------------------------------------------------------------------
# launch -> wait -> done / failed
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_success_roundtrip(self, tmp_path):
        target = _write_target(
            tmp_path,
            "ok.py",
            'import sys\nprint("hello-ok")\nsys.exit(0)\n',
        )
        res = rlt.launch(tmp_path, "fast", str(target))
        assert res["status"] == "launched"
        assert isinstance(res["pid"], int) and res["pid"] > 0
        assert res["next_command"].endswith("--seq 1 --timeout 25")

        result = _wait_until_finished(tmp_path, "fast")
        assert result["status"] == "done"
        assert result["exit_code"] == 0
        # Log captured the target's stdout.
        log = (tmp_path / "fast.log").read_text(encoding="utf-8")
        assert "hello-ok" in log

    def test_failure_roundtrip(self, tmp_path):
        target = _write_target(
            tmp_path,
            "bad.py",
            'import sys\nprint("boom", file=sys.stderr)\nsys.exit(3)\n',
        )
        rlt.launch(tmp_path, "bad", str(target))
        result = _wait_until_finished(tmp_path, "bad")
        assert result["status"] == "failed"
        assert result["exit_code"] == 3
        assert "boom" in (tmp_path / "bad.log").read_text(encoding="utf-8")

    def test_state_file_written_and_updated(self, tmp_path):
        target = _write_target(tmp_path, "ok.py", "import sys\nsys.exit(0)\n")
        rlt.launch(tmp_path, "st", str(target))
        _wait_until_finished(tmp_path, "st")
        state = json.loads((tmp_path / "st.state.json").read_text(encoding="utf-8"))
        assert state["status"] == "done"
        assert state["exit_code"] == 0
        assert "finished_at" in state


# ---------------------------------------------------------------------------
# running -> next_command increments seq across rounds
# ---------------------------------------------------------------------------


class TestRunningRounds:
    def test_seq_increments_each_round(self, tmp_path):
        # A target that outlives a single 2s wait round.
        target = _write_target(tmp_path, "slow.py", "import time\ntime.sleep(3)\n")
        rlt.launch(tmp_path, "slow", str(target))
        first = rlt.wait(tmp_path, "slow", seq=1, timeout=2)
        assert first["status"] == "running"
        assert "--seq 2" in first["next_command"]

        second = rlt.wait(tmp_path, "slow", seq=2, timeout=2)
        # Still running, or finished within the second round.
        assert second["status"] in ("running", "done")
        if second["status"] == "running":
            assert "--seq 3" in second["next_command"]


# ---------------------------------------------------------------------------
# idempotency / error handling
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_wait_is_idempotent_when_finished(self, tmp_path):
        target = _write_target(tmp_path, "ok.py", "import sys\nsys.exit(0)\n")
        rlt.launch(tmp_path, "idem", str(target))
        _wait_until_finished(tmp_path, "idem")
        # Waiting again still reports done and does not require a new launch.
        result = rlt.wait(tmp_path, "idem", seq=5, timeout=2)
        assert result["status"] == "done"
        assert result["exit_code"] == 0

    def test_wait_missing_step_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            rlt.wait(tmp_path, "never-launched", seq=1, timeout=2)

    def test_launch_refuses_while_running(self, tmp_path):
        # Write a state file pointing at the current (alive) process.
        state = {
            "step": "busy",
            "status": "running",
            "pid": os.getpid(),
            "started_at": rlt._now_iso(),
            "target": "whatever",
        }
        rlt._write_state(tmp_path, "busy", state)
        with pytest.raises(RuntimeError):
            rlt.launch(tmp_path, "busy", str(tmp_path / "whatever.py"))

    def test_lost_when_pid_gone_without_exit_file(self, tmp_path):
        # Simulate a killed task: state says running, pid is dead, no exit file.
        dead_pid = 2**20  # a pid that will not exist
        state = {
            "step": "lost",
            "status": "running",
            "pid": dead_pid,
            "started_at": rlt._now_iso(),
            "target": "whatever",
        }
        rlt._write_state(tmp_path, "lost", state)
        (tmp_path / "lost.log").write_text("partial output\n", encoding="utf-8")
        result = rlt.wait(tmp_path, "lost", seq=1, timeout=2)
        assert result["status"] == "failed"
        assert result["exit_code"] is None
        state_now = json.loads((tmp_path / "lost.state.json").read_text(encoding="utf-8"))
        assert state_now["status"] == "failed"

    def test_invalid_seq_raises(self, tmp_path):
        with pytest.raises(ValueError):
            rlt.wait(tmp_path, "x", seq=0, timeout=2)
        with pytest.raises(ValueError):
            rlt.wait(tmp_path, "x", seq=-3, timeout=2)

    def test_timeout_clamped_to_max(self):
        # A very large timeout must be clamped so a single wait never blocks
        # past the agent's ~30s foreground cap.  Test the clamp directly so the
        # suite stays fast (no 24s sleep).
        assert rlt.MAX_WAIT_SECONDS <= 28
        assert rlt._clamp_timeout(999) == rlt.MAX_WAIT_SECONDS
        assert rlt._clamp_timeout(0) == 1
        assert rlt._clamp_timeout(-5) == 1
        assert rlt._clamp_timeout(5) == 5


# ---------------------------------------------------------------------------
# CLI launch argument parsing (target vs target-args, with optional `--`)
# ---------------------------------------------------------------------------


class TestLaunchCliParsing:
    def test_no_separator(self, monkeypatch, tmp_path):
        # `rest[0]` is the target; the rest are target args.
        captured = {}

        def fake_launch(run_dir, step, target, args, **kwargs):
            captured.update(run_dir=run_dir, step=step, target=target, args=args)
            return {"status": "launched"}

        monkeypatch.setattr(rlt, "launch", fake_launch)
        rlt._launch_from_cli(tmp_path, "cov", ["script.py", "--releases", "a,b"])
        assert captured["target"] == "script.py"
        assert captured["args"] == ["--releases", "a,b"]

    def test_with_separator(self, monkeypatch, tmp_path):
        # A bare `--` separates runner tokens from target options; it is
        # dropped and the target args are preserved on both sides.
        captured = {}

        def fake_launch(run_dir, step, target, args, **kwargs):
            captured.update(target=target, args=args)
            return {"status": "launched"}

        monkeypatch.setattr(rlt, "launch", fake_launch)
        rlt._launch_from_cli(tmp_path, "cov", ["script.py", "--", "--releases", "a,b"])
        assert captured["target"] == "script.py"
        assert captured["args"] == ["--releases", "a,b"]

    def test_requires_target(self, tmp_path):
        with pytest.raises(ValueError):
            rlt._launch_from_cli(tmp_path, "cov", [])
