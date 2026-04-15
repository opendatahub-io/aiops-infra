#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jira>=3.0.0",
# ]
# ///
"""
Update an existing Jira issue, or clone a template issue and update the clone.

--- Updating an existing issue ---

  update_jira_issue.py <jira_url> [options]

At least one action flag must be provided.

--- Cloning a template issue ---

  update_jira_issue.py new --clone-from SOURCE_ID [options]

Clones SOURCE_ID, prints the new issue URL to stdout, then applies any additional
action flags to the newly created issue.

Authentication:
  JIRA_USER_EMAIL  — required; your Atlassian account email address
  JIRA_API_TOKEN   — required; API token from https://id.atlassian.com/manage-profile/security/api-tokens
  JIRA_SERVER      — optional; default: https://redhat.atlassian.net

Options:
  --clone-from SOURCE_ID        Clone SOURCE_ID to create a new issue (only valid when jira_url is "new")
  --set-title TITLE             Set the issue summary/title
  --link-related JIRA_ID        Add a "relates to" link between this issue and JIRA_ID
  --set-reporter-to-current     Set the reporter to the currently authenticated user
  --add-label LABEL             Add a label (existing labels are preserved)
  --remove-label LABEL          Remove a label (no-op if not present)
  --comment TEXT                Post a comment on the issue
  --status STATUS               Transition the issue to the named status (e.g. "In Progress")
  --attach FILE_PATH            Attach a file (replaces any existing attachment with the same filename)

Exit codes:
  0  All requested updates succeeded
  1  Error (auth failure, issue not found, invalid transition, file not found, etc.)

Examples:
  # Attach a file (replaces any existing attachment with the same name)
  update_jira_issue.py https://redhat.atlassian.net/browse/RHOAIENG-1234 \\
      --attach ./component_onboarding_details.yaml

  # Clone a template, set a new title, add a related link, set reporter
  NEW_URL=$(update_jira_issue.py new \\
      --clone-from RHOAIENG-35683 \\
      --set-title "Onboard my-component to Konflux CI" \\
      --remove-label template \\
      --link-related RHOAIENG-12345 \\
      --set-reporter-to-current)

  # Attach and post comment in one call
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


def clone_issue(jira: JIRA, source_id: str) -> str:
    """Clone a Jira issue and return the new issue key."""
    source = fetch_issue(jira, source_id)
    fields = {
        "project": {"key": source.fields.project.key},
        "summary": source.fields.summary,
        "issuetype": {"name": source.fields.issuetype.name},
    }
    if source.fields.description:
        fields["description"] = source.fields.description
    try:
        new_issue = jira.create_issue(fields=fields)
        print(f"  Cloned {source_id} → {new_issue.key}", file=sys.stderr)
        return new_issue.key
    except JIRAError as e:
        print(f"ERROR: Failed to clone {source_id}: {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)


def set_title(jira: JIRA, issue, title: str) -> None:
    """Update the issue summary/title."""
    try:
        issue.update(fields={"summary": title})
        print(f"  Title set: '{title}'", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to set title: {getattr(e, 'text', e)}", file=sys.stderr)
        sys.exit(1)


def link_related(jira: JIRA, issue, related_id: str) -> None:
    """Add a 'relates to' link between issue and related_id."""
    related_key = extract_issue_id(related_id)
    # Try common link type names in order
    for link_type in ["Relates", "relates to", "Relates To", "is related to"]:
        try:
            jira.create_issue_link(link_type, issue.key, related_key)
            print(f"  Linked '{issue.key}' relates to '{related_key}'", file=sys.stderr)
            return
        except JIRAError:
            continue
    print(
        f"ERROR: Could not create 'relates to' link between {issue.key} and {related_key}. "
        "None of the standard link type names matched. Check available link types with a Jira admin.",
        file=sys.stderr,
    )
    sys.exit(1)


def set_reporter_to_current(jira: JIRA, issue) -> None:
    """Set the issue reporter to the currently authenticated user."""
    try:
        myself = jira.myself()
        # Jira Cloud uses accountId; Jira Server/DC uses name/key
        account_id = myself.get("accountId")
        if account_id:
            issue.update(fields={"reporter": {"accountId": account_id}})
        else:
            name = myself.get("name") or myself.get("key")
            issue.update(fields={"reporter": {"name": name}})
        display = myself.get("displayName", account_id or myself.get("name", "unknown"))
        print(f"  Reporter set to current user: {display}", file=sys.stderr)
    except JIRAError as e:
        print(f"ERROR: Failed to set reporter: {getattr(e, 'text', e)}", file=sys.stderr)
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
    """Upload a file as an attachment, replacing any existing attachment with the same filename."""
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
    """Transition the issue to the named status."""
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
        help='Full URL of the Jira issue, or "new" when cloning a template (requires --clone-from)',
    )
    parser.add_argument(
        "--clone-from",
        metavar="SOURCE_ID",
        help='Clone this issue to create a new one (only valid when jira_url is "new")',
    )
    parser.add_argument(
        "--set-title",
        metavar="TITLE",
        help="Set the issue summary/title",
    )
    parser.add_argument(
        "--link-related",
        metavar="JIRA_ID",
        help='Add a "relates to" link between this issue and JIRA_ID',
    )
    parser.add_argument(
        "--set-reporter-to-current",
        action="store_true",
        help="Set the reporter to the currently authenticated user",
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
        help='Target status name to transition the issue to (e.g. "In Progress")',
    )
    parser.add_argument(
        "--attach",
        metavar="FILE_PATH",
        help="Path to a local file to upload as an attachment (replaces any existing attachment with the same filename)",
    )
    args = parser.parse_args()

    clone_mode = args.jira_url.strip().lower() == "new"

    # Validate mode-specific constraints
    if clone_mode and not args.clone_from:
        parser.error('--clone-from SOURCE_ID is required when jira_url is "new"')
    if not clone_mode and args.clone_from:
        parser.error('--clone-from can only be used when jira_url is "new"')

    action_flags = [
        args.set_title, args.link_related, args.set_reporter_to_current,
        args.add_label, args.remove_label, args.comment, args.status, args.attach,
    ]
    if not clone_mode and not any(action_flags):
        parser.error(
            "At least one of --set-title, --link-related, --set-reporter-to-current, "
            "--add-label, --remove-label, --comment, --status, or --attach must be provided."
        )

    jira = get_jira_client()

    if clone_mode:
        source_key = extract_issue_id(args.clone_from)
        print(f"Cloning Jira issue: {source_key}", file=sys.stderr)
        new_key = clone_issue(jira, source_key)
        issue = fetch_issue(jira, new_key)
        # Print the new URL to stdout so callers can capture it
        server = os.environ.get("JIRA_SERVER", DEFAULT_JIRA_SERVER)
        new_url = f"{server}/browse/{new_key}"
        print(new_url)
    else:
        issue_id = extract_issue_id(args.jira_url)
        print(f"Updating Jira issue: {issue_id}", file=sys.stderr)
        issue = fetch_issue(jira, issue_id)

    # Apply all requested operations (order: structural changes first, then labels/links, then comment)
    if args.set_title:
        set_title(jira, issue, args.set_title)
    if args.attach:
        attach_file(jira, issue, Path(args.attach))
    if args.add_label:
        add_label(jira, issue, args.add_label)
    if args.remove_label:
        remove_label(jira, issue, args.remove_label)
    if args.link_related:
        link_related(jira, issue, args.link_related)
    if args.set_reporter_to_current:
        set_reporter_to_current(jira, issue)
    if args.comment:
        add_comment(jira, issue, args.comment)
    if args.status:
        transition_status(jira, issue, args.status)

    action = "created and updated" if clone_mode else "updated"
    print(f"Done. Issue {issue.key} {action} successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
