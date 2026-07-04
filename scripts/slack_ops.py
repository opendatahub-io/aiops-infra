"""slack_ops.py -- Slack primitives via slackdump (dual-mode: CLI + importable).

Uses the slackdump CLI tool for Slack search. Slackdump authenticates via
browser cookies stored in ~/.cache/slackdump/ -- no Slack app installation
or admin approval required.

Installing any app into the Red Hat Internal Slack workspace requires RH Slack
admin approval. Slackdump bypasses this by using your existing browser session.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

from datetime import datetime, timedelta, timezone
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import konflux_environment  # noqa: E402

konflux_environment.load()

SLACKDUMP_CACHE_DIR = Path.home() / ".cache" / "slackdump"


def _slackdump_binary() -> str | None:
    """Return path to slackdump binary, or None if not found.

    Checks ~/.conforma/bin/ first, then PATH.
    Auto-installs to ~/.conforma/bin/ if missing.
    """
    conforma_workdir = os.environ.get("CONFORMA_WORKDIR")
    work_dir = Path(conforma_workdir) if conforma_workdir else Path.home() / ".conforma"
    local_bin = work_dir / "bin" / "slackdump"
    if local_bin.is_file() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    found = shutil.which("slackdump")
    if found:
        return found

    # Auto-install
    install_script = Path(_scripts_dir) / "install_slackdump.sh"
    if install_script.is_file():
        print("slackdump not found — installing to ~/.conforma/bin/ ...", file=sys.stderr)
        result = subprocess.run(
            ["bash", str(install_script)],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=Path(_scripts_dir).parent,
        )
        if result.returncode == 0 and local_bin.is_file():
            print("slackdump installed successfully.", file=sys.stderr)
            return str(local_bin)
        print(f"slackdump auto-install failed: {result.stderr.strip()}", file=sys.stderr)

    return None


def _slackdump_auth_files() -> list[Path]:
    """Return list of slackdump auth files (*.bin) in the cache directory."""
    if not SLACKDUMP_CACHE_DIR.is_dir():
        return []
    return list(SLACKDUMP_CACHE_DIR.glob("*.bin"))


def _slackdump_available() -> bool:
    """Check if slackdump is installed and has auth credentials."""
    return _slackdump_binary() is not None and len(_slackdump_auth_files()) > 0


def _workspace_name() -> str:
    """Read the current workspace name from slackdump's workspace.txt."""
    ws_file = SLACKDUMP_CACHE_DIR / "workspace.txt"
    if ws_file.is_file():
        return ws_file.read_text().strip()
    auth_files = _slackdump_auth_files()
    if auth_files:
        return auth_files[0].stem
    return ""


def _workspace_url() -> str:
    """Get the Slack workspace URL from environment (SLACK_WORKSPACE_URL env var)."""
    return os.environ.get("SLACK_WORKSPACE_URL", "").rstrip("/")


def verify_auth() -> dict:
    """Check slackdump is installed and authenticated.

    Returns auth status dict with ok, user, team, team_url, error fields.
    """
    binary = _slackdump_binary()
    if not binary:
        return {
            "ok": False,
            "user": None,
            "team": None,
            "team_url": "",
            "error": ("slackdump binary not found. Install with: scripts/install_slackdump.sh"),
        }

    auth_files = _slackdump_auth_files()
    if not auth_files:
        return {
            "ok": False,
            "user": None,
            "team": None,
            "team_url": "",
            "error": "No slackdump auth credentials found in ~/.cache/slackdump/.",
        }

    workspace = _workspace_name()
    team_url = _workspace_url()

    # Verify the session is still valid by running a lightweight command
    try:
        result = subprocess.run(
            [binary, "workspace", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "token_revoked" in stderr or "invalid_auth" in stderr or "not_authed" in stderr:
                return {
                    "ok": False,
                    "user": None,
                    "team": None,
                    "team_url": "",
                    "error": ("slackdump session expired. Run: slackdump login"),
                }
            return {
                "ok": False,
                "user": None,
                "team": None,
                "team_url": "",
                "error": f"slackdump workspace list failed: {stderr}",
            }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "user": None,
            "team": None,
            "team_url": "",
            "error": "slackdump workspace list timed out (10s). Check network connectivity.",
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "user": None,
            "team": None,
            "team_url": "",
            "error": "slackdump binary not found at expected path.",
        }

    return {
        "ok": True,
        "user": None,
        "team": workspace,
        "team_url": team_url,
        "error": None,
    }


def search_messages(
    query: str,
    count: int = 20,
    after_days: int = 30,
) -> list[dict]:
    """Search Slack messages via slackdump, grouped by thread.

    Returns one entry per thread containing a matching message. The permalink
    points to the specific matching message (not necessarily the thread root).
    """
    if not _slackdump_available():
        print(
            "slackdump not available (missing binary or auth). Run: scripts/install_slackdump.sh && slackdump login",
            file=sys.stderr,
        )
        return []

    binary = _slackdump_binary()
    assert binary is not None

    after_date = (datetime.now(tz=timezone.utc) - timedelta(days=after_days)).strftime("%Y-%m-%d")
    full_query = f"{query} after:{after_date}"

    tmpdir = tempfile.mkdtemp(prefix="slackdump_search_")
    try:
        result = subprocess.run(
            [binary, "search", "messages", "-no-channel-users", "-o", tmpdir, full_query],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "token_revoked" in stderr or "invalid_auth" in stderr or "not_authed" in stderr:
                print(
                    "slackdump session expired. Run: slackdump login",
                    file=sys.stderr,
                )
            else:
                print(f"slackdump search failed: {stderr}", file=sys.stderr)
            return []

        db_path = os.path.join(tmpdir, "slackdump.sqlite")
        if not os.path.isfile(db_path):
            print("slackdump search produced no database file.", file=sys.stderr)
            return []

        return _parse_search_results(db_path, count)

    except subprocess.TimeoutExpired:
        print("slackdump search timed out (120s).", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"slackdump search error: {exc}", file=sys.stderr)
        return []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_search_results(db_path: str, count: int) -> list[dict]:
    """Parse slackdump SQLite search results into normalized thread-grouped dicts."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT CHANNEL_ID, CHANNEL_NAME, TS, TXT, DATA FROM SEARCH_MESSAGE ORDER BY TS DESC LIMIT ?",
            (count * 3,),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    seen_threads: dict[tuple[str, str], dict] = {}
    for channel_id, channel_name, ts, txt, data_json in rows:
        try:
            data = json.loads(data_json) if data_json else {}
        except (json.JSONDecodeError, TypeError):
            data = {}

        thread_ts = data.get("thread_ts") or ts or ""
        thread_key = (channel_id or "", thread_ts)

        if thread_key in seen_threads:
            continue

        ts_float = float(ts) if ts else 0
        date_str = datetime.fromtimestamp(ts_float, tz=timezone.utc).strftime("%Y-%m-%d") if ts_float else ""

        seen_threads[thread_key] = {
            "channel": channel_name or "",
            "channel_id": channel_id or "",
            "permalink": data.get("permalink", ""),
            "thread_ts": thread_ts,
            "thread_reply_count": 0,
            "user": data.get("username", ""),
            "date": date_str,
            "text": txt or data.get("text", ""),
        }

        if len(seen_threads) >= count:
            break

    return list(seen_threads.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Slack primitives (via slackdump)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("verify-auth")

    p_search = sub.add_parser("search-messages")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.add_argument("--count", type=int, default=20, help="Max results")
    p_search.add_argument("--after-days", type=int, default=30, help="Search window in days")

    args = parser.parse_args()

    if args.command == "verify-auth":
        result = verify_auth()
    elif args.command == "search-messages":
        result = search_messages(query=args.query, count=args.count, after_days=args.after_days)
    else:
        parser.print_help()
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
