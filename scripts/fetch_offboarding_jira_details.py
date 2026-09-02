#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#     "jira>=3.0.0",
# ]
# ///
"""
Fetch all details of a Jira issue and save them as JSON (offboarding variant).

Offboarding-specific copy of fetch_jira_details.py. Identical behavior except the
output file is component_offboarding_details.json instead of the onboarding filename.

Connects to the Atlassian Cloud Jira instance at https://redhat.atlassian.net using
basic authentication (email + API token). Writes all issue fields to
component_offboarding_details.json in the current working directory, overwriting any existing file.

Authentication:
  JIRA_USER_EMAIL  — required; your Atlassian account email address
  JIRA_API_TOKEN   — required; API token from https://id.atlassian.com/manage-profile/security/api-tokens
  JIRA_SERVER      — optional; default: https://redhat.atlassian.net

Usage:
  fetch_jira_details.py <jira_url>

Arguments:
  jira_url    Full URL of the Jira issue, e.g.:
              https://redhat.atlassian.net/browse/RHOAIENG-1234

Output:
  ./component_offboarding_details.json  — All issue fields as JSON (written to CWD)

Exit codes:
  0  Success
  1  Error (auth failure, issue not found, network error, etc.)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from jira import JIRA
from jira.exceptions import JIRAError

DEFAULT_JIRA_SERVER = "https://redhat.atlassian.net"
OUTPUT_FILENAME = "component_offboarding_details.json"


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
    """Extract issue ID from a Jira URL or return the input if already an ID.

    Examples:
      https://redhat.atlassian.net/browse/RHOAIENG-1234  ->  RHOAIENG-1234
      RHOAIENG-1234                                   ->  RHOAIENG-1234
    """
    return jira_url.strip().rstrip("/").split("/")[-1]


def serialize_field(value) -> object:
    """Recursively convert a Jira field value to a JSON-serializable type."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [serialize_field(item) for item in value]
    if isinstance(value, dict):
        return {k: serialize_field(v) for k, v in value.items()}
    if hasattr(value, "__dict__"):
        return {k: serialize_field(v) for k, v in vars(value).items() if not k.startswith("_")}
    return str(value)


def fetch_issue_as_dict(jira: JIRA, issue_id: str) -> dict:
    """Fetch a Jira issue and return all its fields as a plain dict."""
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
        msg = messages.get(status, f"Failed to fetch issue {issue_id} (HTTP {status}): {text}")
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Unexpected error fetching issue {issue_id}: {e}", file=sys.stderr)
        sys.exit(1)

    fields_raw = vars(issue.fields) if hasattr(issue.fields, "__dict__") else {}
    return {
        "id": issue.id,
        "key": issue.key,
        "self": issue.self,
        "fields": {k: serialize_field(v) for k, v in fields_raw.items() if not k.startswith("_")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "jira_url",
        help="Full URL of the Jira issue (e.g., https://redhat.atlassian.net/browse/RHOAIENG-1234)",
    )
    args = parser.parse_args()

    issue_id = extract_issue_id(args.jira_url)
    print(f"Fetching Jira issue: {issue_id}", file=sys.stderr)

    jira = get_jira_client()
    issue_dict = fetch_issue_as_dict(jira, issue_id)

    output_path = Path(OUTPUT_FILENAME)
    output_path.write_text(json.dumps(issue_dict, indent=2), encoding="utf-8")
    print(f"Saved issue details to {output_path.resolve()}", file=sys.stderr)
    print(f"  Summary: {issue_dict['fields'].get('summary', '(no summary)')}", file=sys.stderr)


if __name__ == "__main__":
    main()
