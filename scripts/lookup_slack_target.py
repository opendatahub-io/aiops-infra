#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Look up Slack user-group handles and channel names via slackdump.

slackdump can list channels but cannot list user groups. Handle verification
therefore uses:
  1. Optional routing YAML (team-slack-handles.yaml) — known handles
  2. Otherwise status=unknown (caller must confirm with the user)

Channel lookup uses `slackdump list channels`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import upsert_team_slack_handle as routing  # noqa: E402

SLACKDUMP_CACHE_DIR = Path.home() / ".cache" / "slackdump"
CHANNEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-_]*$")
CHANNEL_URL_RE = re.compile(r"slack\.com/archives/([A-Z0-9]+)", re.I)
# team-slack-handles.yaml lives in the private red-hat-data-services/rhods-devops-infra
# GitHub repo (RH-employees-only via org membership) — see RHOAIENG-85559.
DEFAULT_ROUTING_API_URL = (
    "https://api.github.com/repos/red-hat-data-services/rhods-devops-infra"
    "/contents/src/config/team-slack-handles.yaml?ref=main"
)


def _slackdump_binary() -> str | None:
    conforma_workdir = os.environ.get("CONFORMA_WORKDIR")
    work_dir = Path(conforma_workdir) if conforma_workdir else Path.home() / ".conforma"
    local_bin = work_dir / "bin" / "slackdump"
    if local_bin.is_file() and os.access(local_bin, os.X_OK):
        return str(local_bin)
    return shutil.which("slackdump")


def _auth_available() -> bool:
    if not SLACKDUMP_CACHE_DIR.is_dir():
        return False
    return bool(list(SLACKDUMP_CACHE_DIR.glob("*.bin")))


def normalize_channel_name(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    url_match = CHANNEL_URL_RE.search(value)
    if url_match:
        return url_match.group(1)
    value = value.lstrip("#")
    if value.startswith("https://"):
        return value
    return value.lower()


def normalize_handle(raw: str) -> str:
    return routing.normalize_handle(raw)


def _load_json_files(directory: Path) -> list:
    payloads: list = []
    for path in directory.rglob("*"):
        if path.suffix.lower() not in {".json"}:
            continue
        try:
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return payloads


def _iter_channel_records(payload) -> list[dict]:
    records: list[dict] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("channels") or payload.get("Channels") or payload.get("items") or []
        if isinstance(payload.get("id"), str) and (
            payload.get("name") or payload.get("name_normalized")
        ):
            items = [payload]
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("name_normalized") or item.get("Name") or ""
        channel_id = item.get("id") or item.get("ID") or item.get("channel_id") or ""
        if name or channel_id:
            records.append({"name": str(name), "id": str(channel_id)})
    return records


def list_channels() -> dict:
    """Return {ok, channels: [{name, id}], error}."""
    binary = _slackdump_binary()
    if not binary:
        return {
            "ok": False,
            "channels": [],
            "error": "slackdump binary not found. Install with scripts/install_slackdump.sh if available, or see the slack-auth skill.",
        }
    if not _auth_available():
        return {
            "ok": False,
            "channels": [],
            "error": "No slackdump auth credentials found in ~/.cache/slackdump/. Run: slackdump login",
        }

    tmpdir = tempfile.mkdtemp(prefix="slackdump_channels_")
    try:
        result = subprocess.run(
            [
                binary,
                "list",
                "channels",
                "-chan-types",
                "public_channel,private_channel",
                "-enterprise",
                "-q",
                "-o",
                tmpdir,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "token_revoked" in stderr or "invalid_auth" in stderr or "not_authed" in stderr:
                return {
                    "ok": False,
                    "channels": [],
                    "error": "slackdump session expired. Run: slackdump login",
                }
            return {
                "ok": False,
                "channels": [],
                "error": f"slackdump list channels failed: {stderr or result.stdout.strip()}",
            }

        channels: list[dict] = []
        seen: set[str] = set()
        for payload in _load_json_files(Path(tmpdir)):
            for record in _iter_channel_records(payload):
                key = f"{record['id']}:{record['name']}"
                if key in seen:
                    continue
                seen.add(key)
                channels.append(record)
        return {"ok": True, "channels": channels, "error": None}
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "channels": [],
            "error": "slackdump list channels timed out (180s).",
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def lookup_channel(name: str) -> dict:
    normalized = normalize_channel_name(name)
    if not normalized:
        return {
            "ok": False,
            "status": "invalid",
            "name": "",
            "id": "",
            "error": "Channel name is empty.",
        }
    listed = list_channels()
    if not listed["ok"]:
        return {
            "ok": False,
            "status": "error",
            "name": normalized,
            "id": "",
            "error": listed["error"],
        }
    needle = normalized.lower()
    for record in listed["channels"]:
        rec_name = (record.get("name") or "").lower()
        rec_id = record.get("id") or ""
        if rec_name == needle or rec_id.lower() == needle.lower():
            return {
                "ok": True,
                "status": "found",
                "name": record.get("name") or normalized,
                "id": rec_id,
                "error": None,
            }
    return {
        "ok": False,
        "status": "not_found",
        "name": normalized,
        "id": "",
        "error": f"Slack channel '{normalized}' was not found in this workspace.",
    }


def fetch_routing_yaml(url: str | None = None) -> str | None:
    """Fetch team-slack-handles.yaml from the private rhods-devops-infra GitHub
    repo (raw content via the Contents API). Returns None on any failure
    (including auth/network issues — callers fall back to status=unknown)."""
    target = url or os.environ.get("TEAM_SLACK_HANDLES_URL") or DEFAULT_ROUTING_API_URL
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    request = urllib.request.Request(target)
    request.add_header("Accept", "application/vnd.github.raw")
    if token:
        request.add_header("Authorization", f"token {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            if response.status != 200:
                return None
            return body.decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, UnicodeDecodeError):
        return None


def lookup_usergroup(handle: str, routing_yaml: str | None = None) -> dict:
    normalized = normalize_handle(handle)
    if not routing.HANDLE_RE.match(normalized):
        return {
            "ok": False,
            "status": "invalid",
            "handle": normalized,
            "error": (
                f"Invalid Slack user-group handle '{handle}'. "
                "Use lowercase letters, numbers, and hyphens only (for example: ai-core-platform)."
            ),
        }
    if routing_yaml:
        known = routing.extract_known_handles(routing_yaml)
        if normalized in known:
            return {
                "ok": True,
                "status": "found",
                "handle": normalized,
                "error": None,
            }
        return {
            "ok": False,
            "status": "unknown",
            "handle": normalized,
            "error": (
                f"User-group handle '{normalized}' is not in the existing routing file. "
                "slackdump cannot list Slack user groups; confirm the handle exists."
            ),
        }
    return {
        "ok": False,
        "status": "unknown",
        "handle": normalized,
        "error": (
            f"Cannot verify Slack user-group '{normalized}'. "
            "slackdump cannot list user groups. Confirm the handle exists in Slack."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Look up Slack channels and user-group handles")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ch = sub.add_parser("lookup-channel")
    p_ch.add_argument("--name", required=True)

    p_ug = sub.add_parser("lookup-usergroup")
    p_ug.add_argument("--handle", required=True)
    p_ug.add_argument("--routing-yaml", default="", help="Optional path to team-slack-handles.yaml")
    p_ug.add_argument(
        "--no-fetch-routing",
        action="store_true",
        help="Do not fetch the routing YAML from GitHub when --routing-yaml is omitted",
    )

    args = parser.parse_args()
    if args.command == "lookup-channel":
        result = lookup_channel(args.name)
    else:
        yaml_text = None
        if args.routing_yaml:
            path = Path(args.routing_yaml)
            if not path.is_file():
                print(json.dumps({"ok": False, "status": "error", "error": f"File not found: {path}"}))
                return 1
            yaml_text = path.read_text(encoding="utf-8")
        elif not args.no_fetch_routing:
            yaml_text = fetch_routing_yaml()
        result = lookup_usergroup(args.handle, routing_yaml=yaml_text)

    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
