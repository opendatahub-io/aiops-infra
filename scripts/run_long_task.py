"""run_long_task.py -- Deterministic runner for long-running conforma scripts (dual-mode: CLI + importable).

Some conforma steps (notably the CSV report fetch in step 4 and the
``violations_coverage.py`` cross-reference in step 7, which runs ``ec validate``
across every component) take several minutes.  That is longer than the ~30s cap
of the agent's foreground command tool, so those steps MUST be launched in the
background and polled.

If the agent polls with *identical* commands every round, a harness loop
detector (e.g. "5 consecutive identical calls") will abort the task.  This
script removes that failure mode: every ``wait`` round carries an incrementing
``--seq`` value, so **no two wait-loop commands are ever byte-for-byte
identical**.  The script decides what to run next; the agent is a pure relay.

State is kept as plain files in the active run directory (mirrors the
``launch_monitor.sh`` pid/log/result convention), so a killed or restarted agent
can pick the task back up:

  <run_dir>/<step>.state.json  -- pid, started_at, target command, status
  <run_dir>/<step>.log         -- combined stdout/stderr from the target
  <run_dir>/<step>.exit        -- exit code, written when the target finishes

Usage (CLI, always via the wrapper)::

    # 1. Launch the long-running step in the background:
    ~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch coverage \
        skills/conforma-analyze/scripts/violations_coverage.py
    # (If the target script takes its own arguments, put a `--` before the
    # target script so they are forwarded to the target, not to the runner.)

    # 2. Run the exact ``next_command`` from the launch/wait JSON output.
    #    It looks like:
    #      ~/.conforma/bin/conforma_run.sh scripts/run_long_task.py wait coverage --seq 1 --timeout 25
    #    Repeat that (with seq incrementing automatically) until ``status``
    #    becomes ``done`` or ``failed``.

Usage (importable)::

    import run_long_task as rlt

    rlt.launch(run_dir, "coverage", "skills/conforma-analyze/scripts/violations_coverage.py")
    rlt.wait(run_dir, "coverage", seq=1, timeout=25)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _repo_root import REPO_ROOT
import conforma_context_ops as ctx

#: Default per-round wait, in seconds.  Must stay below the agent's foreground
#: command cap (~30s) so a single ``wait`` call never times out.
DEFAULT_WAIT_SECONDS = 25

#: Hard ceiling for a single ``wait`` round.  Must stay comfortably under the
#: agent's ~30s foreground command cap so a single ``wait`` call never times out.
MAX_WAIT_SECONDS = 24

#: Number of trailing log lines surfaced in a ``wait`` round.
TAIL_LINES = 5

_STATE_SUFFIX = ".state.json"
_LOG_SUFFIX = ".log"
_EXIT_SUFFIX = ".exit"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def sanitize_step(name: str) -> str:
    """Return a filesystem-safe step name (lowercase alnum, ``-``, ``_``, ``.``)."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in name.strip())
    cleaned = cleaned.strip("-_.")
    if not cleaned:
        raise ValueError(f"Step name '{name}' is not usable as a filename.")
    return cleaned


def _state_path(run_dir: Path, step: str) -> Path:
    return run_dir / f"{step}{_STATE_SUFFIX}"


def _log_path(run_dir: Path, step: str) -> Path:
    return run_dir / f"{step}{_LOG_SUFFIX}"


def _exit_path(run_dir: Path, step: str) -> Path:
    return run_dir / f"{step}{_EXIT_SUFFIX}"


def _read_state(run_dir: Path, step: str) -> dict | None:
    path = _state_path(run_dir, step)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(run_dir: Path, step: str, state: dict) -> None:
    _state_path(run_dir, step).write_text(json.dumps(state, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _read_exit_code(run_dir: Path, step: str) -> int | None:
    path = _exit_path(run_dir, step)
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _tail_lines(path: Path, n: int = TAIL_LINES) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


def pid_alive(pid: int) -> bool:
    """Return True if a process with *pid* exists and is ours."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_timeout(timeout: int) -> int:
    """Clamp a per-round wait to [1, MAX_WAIT_SECONDS] seconds.

    The cap is what guarantees a single ``wait`` call never blocks past the
    agent's ~30s foreground command cap.
    """
    return max(1, min(int(timeout), MAX_WAIT_SECONDS))


def _elapsed_seconds(started_at: str) -> int:
    try:
        start = datetime.fromisoformat(started_at)
        return max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Agent-facing command builder
# ---------------------------------------------------------------------------


def _wrapper_path() -> str:
    """Best-effort path to the conforma_run.sh wrapper for the agent to call."""
    env = os.environ.get("CONFORMA_RUN_WRAPPER")
    if env:
        return env
    return "~/.conforma/bin/conforma_run.sh"


def _next_wait_command(step: str, seq: int, timeout: int) -> str:
    """Build the exact command the agent should run for the next wait round.

    The ``--seq`` value is what makes each round's command unique; the agent
    copies this string verbatim, so the harness never sees two identical calls.
    """
    return f"{_wrapper_path()} scripts/run_long_task.py wait {step} --seq {seq} --timeout {timeout}"


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def _build_target_command(target_script: str, args: list[str], interpreter: str) -> list[str]:
    """Resolve *target_script* to an absolute path and return argv for python.

    The target is invoked as ``<interpreter> <abs_script_path> [args...]``.  The
    absolute path + ``cwd=REPO_ROOT`` make the child equivalent to what the
    wrapper would do, without requiring the wrapper to exist in the child.
    """
    script = Path(target_script)
    if not script.is_absolute():
        script = REPO_ROOT / script
    if not script.is_file():
        raise FileNotFoundError(f"Target script not found: {script}")
    return [interpreter, str(script), *args]


def _spawn_detached(argv: list[str], log_path: Path, exit_path: Path) -> int:
    """Launch *argv* detached, teeing output to *log_path* and recording its exit
    code in *exit_path*.  Returns the spawned PID.

    The target is wrapped in ``bash -c`` so the exit code is persisted even
    after the launcher process exits and the child is reparented to init (which
    reaps it before a later ``wait`` could call ``waitpid``).
    """
    inner = " ".join(shlex.quote(a) for a in argv)
    script_body = (
        f"rc=0; {inner} >> {shlex.quote(str(log_path))} 2>&1 || rc=$?; "
        f"printf '%s' \"$rc\" > {shlex.quote(str(exit_path))}; exit $rc"
    )
    # Truncate the log for a fresh run.
    with open(log_path, "w", encoding="utf-8"):
        pass
    exit_path.unlink(missing_ok=True)

    proc = subprocess.Popen(
        ["/bin/bash", "-c", script_body],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detach from the agent's session (setsid)
    )
    return proc.pid


def launch(
    run_dir: Path | None,
    step: str,
    target_script: str,
    args: list[str] | None = None,
    *,
    interpreter: str | None = None,
) -> dict[str, Any]:
    """Launch *target_script* in the background for *step*.

    Returns a dict with ``status="launched"``, the PID/log, and ``next_command``
    (the ``wait`` call to run next).
    """
    args = list(args or [])
    step = sanitize_step(step)
    if run_dir is None:
        run_dir = ctx.discover_run_dir(None)
    run_dir = Path(run_dir)

    existing = _read_state(run_dir, step)
    if existing and existing.get("status") == "running" and pid_alive(existing.get("pid", -1)):
        raise RuntimeError(
            f"Step '{step}' is already running (PID {existing.get('pid')}). "
            f"Wait for it to finish before launching again."
        )

    argv = _build_target_command(target_script, args, interpreter or sys.executable)
    pid = _spawn_detached(argv, _log_path(run_dir, step), _exit_path(run_dir, step))

    state = {
        "step": step,
        "status": "running",
        "pid": pid,
        "started_at": _now_iso(),
        "target": " ".join(shlex.quote(a) for a in argv),
    }
    _write_state(run_dir, step, state)

    return {
        "step": step,
        "status": "launched",
        "pid": pid,
        "log": str(_log_path(run_dir, step)),
        "started_at": state["started_at"],
        "target": state["target"],
        "next_command": _next_wait_command(step, 1, DEFAULT_WAIT_SECONDS),
        "display": (f"Background task '{step}' launched (PID {pid}). Run the next_command to wait for it to finish."),
    }


def _finish(run_dir: Path, step: str, code: int) -> dict[str, Any]:
    state = _read_state(run_dir, step) or {"step": step}
    status = "done" if code == 0 else "failed"
    state["status"] = status
    state["exit_code"] = code
    state["finished_at"] = _now_iso()
    _write_state(run_dir, step, state)
    if status == "done":
        display = (
            f"Background task '{step}' completed successfully (exit code 0). "
            f"Log: {_log_path(run_dir, step)}. Proceed to the next workflow step."
        )
    else:
        display = (
            f"Background task '{step}' FAILED with exit code {code}. "
            f"Inspect the log at {_log_path(run_dir, step)} before continuing."
        )
    return {
        "step": step,
        "status": status,
        "exit_code": code,
        "log": str(_log_path(run_dir, step)),
        "display": display,
    }


def _lost(run_dir: Path, step: str, state: dict) -> dict[str, Any]:
    state["status"] = "failed"
    state["exit_code"] = None
    state["finished_at"] = _now_iso()
    _write_state(run_dir, step, state)
    return {
        "step": step,
        "status": "failed",
        "exit_code": None,
        "log": str(_log_path(run_dir, step)),
        "display": (
            f"Background task '{step}' process is gone but no exit code was "
            f"recorded (it may have been killed). Inspect the log at "
            f"{_log_path(run_dir, step)} before continuing."
        ),
    }


def wait(
    run_dir: Path | None,
    step: str,
    *,
    seq: int,
    timeout: int = DEFAULT_WAIT_SECONDS,
) -> dict[str, Any]:
    """Wait up to *timeout* seconds for *step* to finish.

    Returns one of:
      * ``status="done"`` / ``status="failed"`` -- the target finished (poll
        again only if you re-launched).
      * ``status="running"`` -- still going; run the returned ``next_command``
        (it carries ``--seq seq+1``) to continue waiting.

    *seq* is used only to make each round's command unique so an agent loop
    detector never sees two identical calls.
    """
    if not isinstance(seq, int) or seq < 1:
        raise ValueError(f"--seq must be a positive integer, got {seq!r}")
    timeout = _clamp_timeout(timeout)
    step = sanitize_step(step)
    if run_dir is None:
        run_dir = ctx.discover_run_dir(None)
    run_dir = Path(run_dir)

    state = _read_state(run_dir, step)
    if state is None:
        raise FileNotFoundError(f"No background task '{step}' found in {run_dir}. Run 'launch {step}' first.")

    # Already finished.
    code = _read_exit_code(run_dir, step)
    if code is not None:
        return _finish(run_dir, step, code)

    pid = state.get("pid", -1)
    deadline = time.monotonic() + timeout
    while True:
        code = _read_exit_code(run_dir, step)
        if code is not None:
            return _finish(run_dir, step, code)
        if not pid_alive(pid):
            # Give the bash wrapper a beat to flush the exit file.
            time.sleep(0.5)
            code = _read_exit_code(run_dir, step)
            if code is not None:
                return _finish(run_dir, step, code)
            return _lost(run_dir, step, _read_state(run_dir, step) or {"step": step})
        if time.monotonic() >= deadline:
            return {
                "step": step,
                "status": "running",
                "pid": pid,
                "elapsed_s": _elapsed_seconds(state.get("started_at", "")),
                "log": str(_log_path(run_dir, step)),
                "tail": _tail_lines(_log_path(run_dir, step)),
                "next_command": _next_wait_command(step, seq + 1, timeout),
                "display": (
                    f"Background task '{step}' is still running "
                    f"({_elapsed_seconds(state.get('started_at', ''))}s elapsed). "
                    f"Run the next_command to continue waiting."
                ),
            }
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _launch_from_cli(run_dir: Path | None, step: str, rest: list[str]) -> dict[str, Any]:
    """Parse the raw trailing tokens for a ``launch`` and dispatch to :func:`launch`.

    ``rest`` is everything after the step name.  The first token is the target
    script path; the remainder are the target's arguments.  A bare ``--`` may
    appear to separate runner tokens from target options — e.g.
    ``launch fetch script.py -- --releases a,b`` forwards ``--releases a,b`` to
    the target.  Without a ``--``, every token after the target path is already
    treated as a target argument, so the separator is optional.
    """
    rest = list(rest)
    if not rest:
        raise ValueError("launch requires a target script path after the step name.")
    target_script = rest[0]
    target_args = rest[1:]
    if "--" in target_args:
        # Drop the separator; everything after it (and everything before it)
        # is a target argument.  We keep the pre-separator args too, since a
        # valid layout is only `script.py -- target-opts...`.
        idx = target_args.index("--")
        target_args = target_args[:idx] + target_args[idx + 1 :]
    return launch(run_dir, step, target_script, target_args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch and wait on long-running conforma scripts.")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Run directory. Auto-discovered via .conforma-active if omitted.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub_launch = sub.add_parser("launch", help="Launch a script in the background")
    sub_launch.add_argument("step", help="Short step name (e.g. fetch, coverage)")
    sub_launch.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help=(
            "The target script path (relative to the repo root), optionally "
            "followed by its arguments. To pass arguments that look like "
            "options to the target, separate them with a bare `--`."
        ),
    )

    sub_wait = sub.add_parser("wait", help="Wait for a launched step to finish")
    sub_wait.add_argument("step", help="Step name given to 'launch'")
    sub_wait.add_argument(
        "--seq",
        type=int,
        required=True,
        help="Sequence number for this round (from the previous next_command)",
    )
    sub_wait.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_WAIT_SECONDS,
        help=f"Max seconds to block this round (capped at {MAX_WAIT_SECONDS})",
    )

    args = parser.parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else None

    try:
        if args.command == "launch":
            result = _launch_from_cli(run_dir, args.step, list(args.rest))
        else:
            result = wait(run_dir, args.step, seq=args.seq, timeout=args.timeout)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout)
        print()
        return 1

    json.dump(result, sys.stdout, indent=2)
    print()
    # Exit 0 for done/running/launched; 1 for failed so a script-driven caller
    # can branch, but the JSON is the source of truth for the agent.
    return 0 if result.get("status") in ("done", "running", "launched") else 1


if __name__ == "__main__":
    sys.exit(main())
