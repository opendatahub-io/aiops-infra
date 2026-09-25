#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Insert a component's Slack routing entry into team-slack-handles.yaml.

Target file lives in the private `red-hat-data-services/rhods-devops-infra`
repo at `src/config/team-slack-handles.yaml` (see RHOAIENG-85559). Format:

    components:
      <component-name>:
        slack_team_handle: <lowercase-handle>
        slack_team_channel: <optional-channel>   # omitted when not given

Entries are kept alphabetically sorted by component name. This intentionally
does not depend on PyYAML (consistent with the other `uv run --script`
helpers in this repo) and edits the file as text so a human-authored file
with comments above `components:` is left untouched.

Exit codes:
  0  entry added (file rewritten)
  2  entry already present with the same handle/channel
  1  error (missing 'components:' key, invalid handle, or conflicting entry)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HANDLE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMPONENT_ENTRY_RE = re.compile(
    r"^  (?P<name>[A-Za-z0-9][A-Za-z0-9._-]*):\n"
    r"(?:    slack_team_handle: (?P<handle>\S+)\n)?"
    r"(?:    slack_team_channel: (?P<channel>\S+)\n)?",
    re.MULTILINE,
)
HANDLE_FIELD_RE = re.compile(r"^    slack_team_handle:\s*(\S+)\s*$", re.MULTILINE)


def normalize_handle(raw: str) -> str:
    value = (raw or "").strip().lstrip("@")
    return value.lower()


def extract_known_handles(yaml_text: str) -> set[str]:
    """All `slack_team_handle` values already present in the file (any layout)."""
    return {match.group(1).strip() for match in HANDLE_FIELD_RE.finditer(yaml_text)}


def normalize_channel(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip().lstrip("#") or None


def _components_block_start(yaml_text: str) -> int:
    match = re.search(r"^components:\s*\n", yaml_text, re.MULTILINE)
    if not match:
        raise ValueError(
            "YAML does not contain a top-level 'components:' mapping."
        )
    return match.end()


def _iter_entries(yaml_text: str, start: int) -> list[re.Match]:
    """All component entries found from `start` to the next top-level key (or EOF)."""
    end_match = re.search(r"^\S", yaml_text[start:], re.MULTILINE)
    end = start + end_match.start() if end_match else len(yaml_text)
    return list(COMPONENT_ENTRY_RE.finditer(yaml_text, start, end)), end


def upsert_component_contact(
    yaml_text: str,
    component_name: str,
    slack_team_handle: str,
    slack_team_channel: str | None = None,
) -> dict:
    handle = normalize_handle(slack_team_handle)
    if not HANDLE_RE.match(handle):
        raise ValueError(
            f"Invalid slack_team_handle '{slack_team_handle}'. "
            "Use a lowercase Slack user-group handle such as ai-core-platform."
        )
    channel = normalize_channel(slack_team_channel)

    start = _components_block_start(yaml_text)
    entries, block_end = _iter_entries(yaml_text, start)

    for entry in entries:
        if entry.group("name") != component_name:
            continue
        existing_handle = entry.group("handle") or ""
        existing_channel = entry.group("channel") or None
        if existing_handle == handle and existing_channel == channel:
            return {"status": "already_present", "text": yaml_text}
        raise ValueError(
            f"Component '{component_name}' already exists with "
            f"slack_team_handle={existing_handle}"
            + (f", slack_team_channel={existing_channel}" if existing_channel else "")
            + f" (requested handle={handle}"
            + (f", channel={channel}" if channel else "")
            + ")."
        )

    lines = [f"  {component_name}:\n", f"    slack_team_handle: {handle}\n"]
    if channel:
        lines.append(f"    slack_team_channel: {channel}\n")
    new_entry = "".join(lines)

    insert_at = block_end
    for entry in entries:
        if entry.group("name") > component_name:
            insert_at = entry.start()
            break

    updated = yaml_text[:insert_at] + new_entry + yaml_text[insert_at:]
    return {"status": "added", "text": updated}


def main() -> int:
    parser = argparse.ArgumentParser(description="Upsert a component's Slack routing entry")
    parser.add_argument("file", help="Path to team-slack-handles.yaml")
    parser.add_argument("--component-name", required=True)
    parser.add_argument("--slack-team-handle", required=True)
    parser.add_argument("--slack-team-channel", default="")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_file():
        print(json.dumps({"error": f"File not found: {path}"}), file=sys.stderr)
        return 1

    try:
        result = upsert_component_contact(
            path.read_text(encoding="utf-8"),
            args.component_name,
            args.slack_team_handle,
            args.slack_team_channel or None,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    if result["status"] == "already_present":
        print(json.dumps({"status": "already_present"}))
        return 2

    path.write_text(result["text"], encoding="utf-8")
    print(json.dumps({"status": "added"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
