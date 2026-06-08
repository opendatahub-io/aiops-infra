"""cli_runner.py -- Generic subprocess wrapper (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from typing import Mapping, Sequence


def run(
    cmd: Sequence[str],
    timeout: int = 60,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Run command. Returns {"returncode": int, "stdout": str, "stderr": str, "timed_out": bool}."""
    try:
        completed = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": -1,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "timed_out": True,
        }
    except FileNotFoundError as exc:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }


def run_with_retry(
    cmd: Sequence[str],
    max_retries: int = 3,
    delay: int = 2,
    timeout: int = 60,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Run command with retries on failure."""
    attempts = 0
    last_result = {
        "returncode": -1,
        "stdout": "",
        "stderr": "",
        "timed_out": False,
    }

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        last_result = run(cmd, timeout=timeout, cwd=cwd, env=env)
        if last_result["returncode"] == 0 and not last_result["timed_out"]:
            break
        if attempt < max_retries:
            time.sleep(delay)

    return {
        "returncode": last_result["returncode"],
        "stdout": last_result["stdout"],
        "stderr": last_result["stderr"],
        "attempts": attempts,
    }


def run_json(cmd: Sequence[str], timeout: int = 60, cwd: str | None = None) -> dict:
    """Run command expecting JSON stdout."""
    result = run(cmd, timeout=timeout, cwd=cwd)
    if result["timed_out"]:
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": "Command timed out",
        }
    if result["returncode"] != 0:
        error = result["stderr"].strip() or f"Command failed with exit code {result['returncode']}"
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": error,
        }

    stdout = result["stdout"].strip()
    if not stdout:
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": "Command produced no stdout",
        }

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": f"Invalid JSON output: {exc}",
        }

    if not isinstance(data, dict):
        return {
            "returncode": result["returncode"],
            "data": None,
            "error": f"Expected JSON object, got {type(data).__name__}",
        }

    return {
        "returncode": result["returncode"],
        "data": data,
        "error": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generic subprocess wrapper")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run")
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")

    run_json_parser = sub.add_parser("run-json")
    run_json_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command after --")

    args = parser.parse_args()

    if args.command in {"run", "run-json"}:
        cmd = list(args.cmd)
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            parser.error("a command is required after --")

        if args.command == "run":
            result = run(cmd)
        else:
            result = run_json(cmd)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
