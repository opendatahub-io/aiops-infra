#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jira>=3.0.0",
# ]
# ///
"""
Update a Jira issue: add/remove labels, post a comment, transition its status,
and/or attach a file (replacing any existing attachment with the same filename).

At least one of --add-label, --remove-label, --comment, --status, or --attach
must be provided.

Authentication:
  JIRA_USER_EMAIL  — required; your Atlassian account email address
  JIRA_API_TOKEN   — required; API token from https://id.atlassian.com/manage-profile/security/api-tokens
  JIRA_SERVER      — optional; default: https://redhat.atlassian.net

Usage:
  update_jira_issue.py <jira_url> [--add-label LABEL] [--remove-label LABEL]
                                  [--comment TEXT] [--status STATUS]
                                  [--attach FILE_PATH]

Arguments:
  jira_url              Full URL of the Jira issue, e.g.:
                        https://redhat.atlassian.net/browse/RHOAIENG-1234

Options:
  --add-label LABEL     Label to add to the issue (existing labels are preserved)
  --remove-label LABEL  Label to remove from the issue (no-op if not present)
  --comment TEXT        Comment text to post on the issue
  --status STATUS       Target status name to transition the issue to (e.g. "In Progress")
  --attach FILE_PATH    Path to a local file to upload as an attachment.
                        If an attachment with the same filename already exists on the
                        issue, it is deleted first before the new file is uploaded.

Exit codes:
  0  All requested updates succeeded
  1  Error (auth failure, issue not found, invalid transition, file not found, etc.)

Examples:
  # Add a label
  update_jira_issue.py https://redhat.atlassian.net/browse/RHOAIENG-1234 --add-label validated

  # Attach a file (replaces any existing attachment with the same name)
  update_jira_issue.py https://redhat.atlassian.net/browse/RHOAIENG-1234 \\
      --attach ./component_onboarding_details.yaml

  # Attach a file, add a label, and post a comment in one call
  update_jira_issue.py https://redhat.atlassian.net/browse/RHOAIENG-1234 \\
      --attach ./component_onboarding_details.yaml \\
      --add-label yaml-attached \\
      --comment "YAML attached and ready for validation."

  # Post a comment and transition status
  update_jira_issue.py https://redhat.atlassian.net/browse/RHOAIENG-1234 \\
      --comment "Validation passed. Ready for onboarding." \\
      --status "In Progress"
"""

import argparse
import os
import sys
from pathlib import Path

from jira import JIRA
from jira.exceptions import JIRAError

DEFAULT_JIRA_SERVER = "https://redhat.atlassian.net"


def get_jira_client() -> JIRA:
    """Create an authenticated JIRA client from environment variables."""
    email = os.environ.get("JIRA_USER_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email:
        print("ERROR: JIRA_USER_EMAIL environment variable is not set.", file=sys.stderr)
        print("  export JIRA_USER_EMAIL='you@example.com'", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("ERROR: JIRA_API_TOKEN environment variable is not set.", file=sys.stderr)
        print("  Create a token at: https://id.atlassian.com/manage-profile/security/api-tokens", file=sys.stderr)
        print("  export JIRA_API_TOKEN='your-token-here'", file=sys.stderr)
        sys.exit(1)
    server = os.environ.get("JIRA_SERVER", DEFAULT_JIRA_SERVER)
    return JIRA(server=server, basic_auth=(email, token))


def extract_issue_id(jira_url: str) -> str:
    """Extract the issue key from a Jira URL or return it unchanged if already a key."""
    return jira_url.strip().rstrip("/").split("/")[-1]


def fetch_issue(jira: JIRA, issue_id: str):
    """Fetch a Jira issue, exiting with a clear message on failure."""
    try:
        return jira.issue(issue_id)
    except JIRAError as e:
        status = getattr(e, "status_code", "unknown")
        messages = {
            401: "Authentication failed (HTTP 401). Check your JIRA_API_TOKEN.",
            403: f"Access denied (HTTP 403). You do not have permission to view {issue_id}.",
            404: f"Issue not found (HTTP 404): {issue_id}. Check the issue key.",
        }
        msg = messages.get(status, f"Failed to fetch {issue_id} (HTTP {status}): {getattr(e, 'text', e)}")
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error fetching {issue_id}: {e}", file=sys.stderr)
        sys.exit(1)


def add_label(jira: JIRA, issue, label: str) -> None:
    """Add a label to the issue, preserving all existing labels."""
    existing = list(issue.fields.labels or [])
    if label in existing:
        print(f"  Label '{label}' is already present — skipping.", file=sys.stderr)
        return
    existing.append(label)
    try:
        issue.update(fields={"labels": existing})
        print(f"  Label added: '{label}'", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to add label '{label}': {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)


def remove_label(jira: JIRA, issue, label: str) -> None:
    """Remove a label from the issue, leaving all other labels intact."""
    existing = list(issue.fields.labels or [])
    if label not in existing:
        print(f"  Label '{label}' is not present — skipping.", file=sys.stderr)
        return
    existing.remove(label)
    try:
        issue.update(fields={"labels": existing})
        print(f"  Label removed: '{label}'", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to remove label '{label}': {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)


def add_comment(jira: JIRA, issue, comment: str) -> None:
    """Post a comment on the issue."""
    try:
        jira.add_comment(issue, comment)
        preview = comment[:80] + ("…" if len(comment) > 80 else "")
        print(f"  Comment posted: \"{preview}\"", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to post comment: {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)


def attach_file(jira: JIRA, issue, file_path: Path) -> None:
    """Upload a file as an attachment, replacing any existing attachment with the same filename.

    Deletes all existing attachments on the issue whose filename matches
    file_path.name, then uploads the new file.
    """
    if not file_path.exists():
        print(f"ERROR: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)
    if not file_path.is_file():
        print(f"ERROR: Not a file: {file_path}", file=sys.stderr)
        sys.exit(1)

    attachments = getattr(issue.fields, "attachment", []) or []
    deleted = 0
    for att in attachments:
        if att.filename == file_path.name:
            try:
                jira.delete_attachment(att.id)
                print(f"  Deleted existing attachment '{att.filename}' (id={att.id})", file=sys.stderr)
                deleted += 1
            except JIRAError as e:
                print(
                    f"ERROR: Failed to delete attachment '{att.filename}' (id={att.id}): "
                    f"{getattr(e, 'text', e)}",
                    file=sys.stderr,
                )
                sys.exit(1)

    if deleted == 0:
        print(f"  No existing '{file_path.name}' attachment found — uploading fresh.", file=sys.stderr)

    try:
        jira.add_attachment(issue=issue.key, attachment=str(file_path))
        size = file_path.stat().st_size
        print(f"  Attached '{file_path.name}' ({size} bytes)", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to attach '{file_path.name}': {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error attaching '{file_path.name}': {e}", file=sys.stderr)
        sys.exit(1)


def transition_status(jira: JIRA, issue, target_status: str) -> None:
    """Transition the issue to the named status.

    Fetches available transitions and matches by name (case-insensitive).
    Exits with code 1 if the target status is not a valid transition from
    the current state, listing all available transitions for debugging.
    """
    current = issue.fields.status.name
    if current.lower() == target_status.lower():
        print(f"  Status is already '{current}' — skipping transition.", file=sys.stderr)
        return

    try:
        transitions = jira.transitions(issue)
    except JIRAError as e:
        print(f"ERROR: Failed to fetch transitions: {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)

    match = next(
        (t for t in transitions if t["to"]["name"].lower() == target_status.lower()),
        None,
    )

    if match is None:
        available = sorted(t["to"]["name"] for t in transitions)
        print(
            f"ERROR: '{target_status}' is not a valid transition from '{current}'.",
            file=sys.stderr,
        )
        print(f"  Available transitions from '{current}':", file=sys.stderr)
        for name in available:
            print(f"    - {name}", file=sys.stderr)
        sys.exit(1)

    try:
        jira.transition_issue(issue, match["id"])
        print(f"  Status transitioned: '{current}' → '{match['to']['name']}'", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to transition to '{target_status}': {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "jira_url",
        help="Full URL of the Jira issue (e.g., https://redhat.atlassian.net/browse/RHOAIENG-1234)",
    )
    parser.add_argument(
        "--add-label",
        metavar="LABEL",
        help="Label to add to the issue (existing labels are preserved)",
    )
    parser.add_argument(
        "--remove-label",
        metavar="LABEL",
        help="Label to remove from the issue (no-op if not present)",
    )
    parser.add_argument(
        "--comment",
        metavar="TEXT",
        help="Comment text to post on the issue",
    )
    parser.add_argument(
        "--status",
        metavar="STATUS",
        help="Target status name to transition the issue to (e.g. 'In Progress')",
    )
    parser.add_argument(
        "--attach",
        metavar="FILE_PATH",
        help="Path to a local file to upload as an attachment (replaces any existing attachment with the same filename)",
    )
    args = parser.parse_args()

    if not any([args.add_label, args.remove_label, args.comment, args.status, args.attach]):
        parser.error("At least one of --add-label, --remove-label, --comment, --status, or --attach must be provided.")

    issue_id = extract_issue_id(args.jira_url)
    print(f"Updating Jira issue: {issue_id}", file=sys.stderr)

    jira = get_jira_client()
    issue = fetch_issue(jira, issue_id)

    if args.attach:
        attach_file(jira, issue, Path(args.attach))

    if args.add_label:
        add_label(jira, issue, args.add_label)

    if args.remove_label:
        remove_label(jira, issue, args.remove_label)

    if args.comment:
        add_comment(jira, issue, args.comment)

    if args.status:
        transition_status(jira, issue, args.status)

    print(f"Done. Issue {issue_id} updated successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
