#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Cross-check a Slack user-group handle against team-slack-handles.yaml.

This does not contact Slack. A handle already present in the routing file is
reported as found; anything else is unknown and the caller must confirm it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import upsert_team_slack_handle as routing  # noqa: E402

# team-slack-handles.yaml lives in the private red-hat-data-services/rhods-devops-infra
# GitHub repo (RH-employees-only via org membership) — see RHOAIENG-85559.
DEFAULT_ROUTING_API_URL = (
    "https://api.github.com/repos/red-hat-data-services/rhods-devops-infra"
    "/contents/src/config/team-slack-handles.yaml?ref=main"
)


def normalize_handle(raw: str) -> str:
    return routing.normalize_handle(raw)


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
                "Confirm the handle with the user."
            ),
        }
    return {
        "ok": False,
        "status": "unknown",
        "handle": normalized,
        "error": (
            f"Cannot verify Slack user-group '{normalized}' against the routing file. "
            "Confirm the handle with the user."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cross-check a Slack user-group handle against team-slack-handles.yaml"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ug = sub.add_parser("lookup-usergroup")
    p_ug.add_argument("--handle", required=True)
    p_ug.add_argument("--routing-yaml", default="", help="Optional path to team-slack-handles.yaml")
    p_ug.add_argument(
        "--no-fetch-routing",
        action="store_true",
        help="Do not fetch the routing YAML from GitHub when --routing-yaml is omitted",
    )

    args = parser.parse_args()
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
