#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jira>=3.0.0",
#     "requests>=2.31.0",
# ]
# ///
"""
Download a named attachment from a Jira issue to the current working directory.

Connects to the Atlassian Cloud Jira instance at https://redhat.atlassian.net using
basic authentication (email + API token). Searches the issue's attachments for the
given filename and downloads it to the current working directory, overwriting any
existing file with the same name.

Authentication:
  JIRA_USER_EMAIL  — required; your Atlassian account email address
  JIRA_API_TOKEN   — required; API token from https://id.atlassian.com/manage-profile/security/api-tokens
  JIRA_SERVER      — optional; default: https://redhat.atlassian.net

Usage:
  download_jira_attachment.py <jira_url> <attachment_filename>

Arguments:
  jira_url              Full URL of the Jira issue, e.g.:
                        https://redhat.atlassian.net/browse/RHOAIENG-1234
  attachment_filename   Exact filename of the attachment to download, e.g.:
                        odh_component_details.yaml

Output:
  ./<attachment_filename>  — Downloaded file (written to CWD, always overwrites)

Exit codes:
  0  Success
  1  Error (auth failure, issue not found, attachment not found, download error)
"""

import argparse
import os
import sys
from pathlib import Path

from jira import JIRA
from jira.exceptions import JIRAError

DEFAULT_JIRA_SERVER = "https://redhat.atlassian.net"


def get_jira_client() -> JIRA:
    """Create an authenticated JIRA client using Atlassian Cloud basic auth (email + API token)."""
    email = os.environ.get("JIRA_USER_EMAIL")
    token = os.environ.get("JIRA_API_TOKEN")
    if not email:
        print("ERROR: JIRA_USER_EMAIL environment variable is not set.", file=sys.stderr)
        print("Set it to your Atlassian account email: export JIRA_USER_EMAIL='you@example.com'", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("ERROR: JIRA_API_TOKEN environment variable is not set.", file=sys.stderr)
        print("Create an API token at: https://id.atlassian.com/manage-profile/security/api-tokens", file=sys.stderr)
        print("Then: export JIRA_API_TOKEN='your-token-here'", file=sys.stderr)
        sys.exit(1)
    server = os.environ.get("JIRA_SERVER", DEFAULT_JIRA_SERVER)
    return JIRA(server=server, basic_auth=(email, token))


def extract_issue_id(jira_url: str) -> str:
    """Extract issue ID from a Jira URL or return the input if already an ID."""
    return jira_url.strip().rstrip("/").split("/")[-1]


def find_attachment(jira: JIRA, issue_id: str, filename: str):
    """Find an attachment by exact filename. Exits with code 1 if not found."""
    try:
        issue = jira.issue(issue_id)
    except JIRAError as e:
        status = getattr(e, "status_code", "unknown")
        text = getattr(e, "text", str(e))
        messages = {
            401: "Authentication failed (HTTP 401). Check your JIRA_API_TOKEN.",
            403: f"Access denied (HTTP 403). You do not have permission to view {issue_id}.",
            404: f"Issue not found (HTTP 404): {issue_id}. Check the issue key.",
        }
        msg = messages.get(status, f"Failed to fetch {issue_id} (HTTP {status}): {text}")
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error fetching {issue_id}: {e}", file=sys.stderr)
        sys.exit(1)

    attachments = getattr(issue.fields, "attachment", []) or []

    for att in attachments:
        if att.filename == filename:
            return att

    # Not found — list available attachments for debugging
    available = sorted(att.filename for att in attachments)
    print(f"ERROR: Attachment '{filename}' not found on issue {issue_id}.", file=sys.stderr)
    if available:
        print(f"Available attachments on {issue_id} ({len(available)} total):", file=sys.stderr)
        for name in available:
            print(f"  - {name}", file=sys.stderr)
    else:
        print(f"  No attachments found on {issue_id}.", file=sys.stderr)
    sys.exit(1)


def download_attachment(jira: JIRA, attachment, output_filename: str) -> None:
    """Download an attachment using the authenticated Jira session.

    Uses jira._session (a requests.Session with auth headers already set)
    to GET the attachment content URL, so authentication is applied automatically.
    """
    url = attachment.content  # URL pointing to the raw attachment bytes

    try:
        response = jira._session.get(url, stream=True)
        response.raise_for_status()
    except Exception as e:
        print(f"ERROR: Failed to download attachment from {url}: {e}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(output_filename)
    try:
        with output_path.open("wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    except OSError as e:
        print(f"ERROR: Failed to write file {output_path}: {e}", file=sys.stderr)
        sys.exit(1)

    size = output_path.stat().st_size
    print(f"Downloaded '{output_filename}' ({size} bytes) to {output_path.resolve()}", file=sys.stderr)


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
        "attachment_filename",
        help="Exact filename of the attachment to download (e.g., odh_component_details.yaml)",
    )
    args = parser.parse_args()

    issue_id = extract_issue_id(args.jira_url)
    print(f"Searching for attachment '{args.attachment_filename}' on {issue_id}", file=sys.stderr)

    jira = get_jira_client()
    attachment = find_attachment(jira, issue_id, args.attachment_filename)
    download_attachment(jira, attachment, args.attachment_filename)


if __name__ == "__main__":
    main()
