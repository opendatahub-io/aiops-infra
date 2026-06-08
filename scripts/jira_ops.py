"""jira_ops.py -- Jira primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os

from jira import JIRA
from jira.exceptions import JIRAError

DEFAULT_JIRA_URL = "https://redhat.atlassian.net"


def get_client(url: str | None = None, email: str | None = None, token: str | None = None) -> JIRA:
    """Get authenticated Jira client. Auto-discovers credentials from environment."""
    resolved_url = url or os.environ.get("JIRA_URL", DEFAULT_JIRA_URL)
    resolved_email = email or os.environ.get("JIRA_EMAIL")
    resolved_token = token or os.environ.get("JIRA_API_TOKEN")

    if not resolved_email:
        raise ValueError("JIRA_EMAIL environment variable is not set")
    if not resolved_token:
        raise ValueError("JIRA_API_TOKEN environment variable is not set")

    return JIRA(server=resolved_url, basic_auth=(resolved_email, resolved_token))


def _issue_url(client: JIRA, issue_key: str) -> str:
    server = client._options.get("server", DEFAULT_JIRA_URL).rstrip("/")
    return f"{server}/browse/{issue_key}"


def verify_auth(url: str | None = None) -> dict:
    """Check auth works. Returns {"ok": bool, "user": str|None, "error": str|None}."""
    try:
        client = get_client(url=url)
        myself = client.myself()
        user = myself.get("displayName") or myself.get("emailAddress") or myself.get("accountId")
        return {"ok": True, "user": user, "error": None}
    except Exception as exc:
        return {"ok": False, "user": None, "error": str(exc)}


def get_issue(issue_key: str) -> dict:
    """Get issue details."""
    try:
        client = get_client()
        issue = client.issue(issue_key)
        assignee = None
        if issue.fields.assignee is not None:
            assignee = getattr(issue.fields.assignee, "displayName", None)
        return {
            "key": issue.key,
            "summary": issue.fields.summary,
            "status": issue.fields.status.name,
            "issue_type": issue.fields.issuetype.name,
            "assignee": assignee,
        }
    except JIRAError as exc:
        return {
            "key": issue_key,
            "summary": None,
            "status": None,
            "issue_type": None,
            "assignee": None,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "key": issue_key,
            "summary": None,
            "status": None,
            "issue_type": None,
            "assignee": None,
            "error": str(exc),
        }


def create_issue(
    project: str,
    summary: str,
    description: str,
    issue_type: str = "Task",
) -> dict:
    """Create issue. Returns {"key": str, "url": str}."""
    try:
        client = get_client()
        issue = client.create_issue(
            fields={
                "project": {"key": project},
                "summary": summary,
                "description": description,
                "issuetype": {"name": issue_type},
            }
        )
        return {"key": issue.key, "url": _issue_url(client, issue.key)}
    except Exception as exc:
        return {"key": None, "url": None, "error": str(exc)}


def update_issue(
    issue_key: str,
    summary: str | None = None,
    description: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    """Update issue fields."""
    fields: dict = {}
    updated: list[str] = []

    if summary is not None:
        fields["summary"] = summary
        updated.append("summary")
    if description is not None:
        fields["description"] = description
        updated.append("description")
    if labels is not None:
        fields["labels"] = labels
        updated.append("labels")

    if not fields:
        return {"key": issue_key, "updated": [], "error": "No fields to update"}

    try:
        client = get_client()
        issue = client.issue(issue_key)
        issue.update(fields=fields)
        return {"key": issue_key, "updated": updated}
    except JIRAError as exc:
        return {"key": issue_key, "updated": [], "error": str(exc)}
    except Exception as exc:
        return {"key": issue_key, "updated": [], "error": str(exc)}


def add_watchers(issue_key: str, account_ids: list[str]) -> dict:
    """Add watchers. Returns {"added": list, "failed": list}."""
    added: list[str] = []
    failed: list[str] = []

    try:
        client = get_client()
        for account_id in account_ids:
            try:
                client.add_watcher(issue_key, account_id)
                added.append(account_id)
            except Exception:
                failed.append(account_id)
        return {"added": added, "failed": failed}
    except Exception as exc:
        remaining = [account_id for account_id in account_ids if account_id not in added]
        return {"added": added, "failed": remaining, "error": str(exc)}


def search_user(display_name: str) -> dict:
    """Find user by display name. Returns {"account_id": str|None, "display_name": str, "found": bool}."""
    try:
        client = get_client()
        users = client.search_users(query=display_name, maxResults=10)
        for user in users:
            if user.displayName.lower() == display_name.lower():
                return {
                    "account_id": user.accountId,
                    "display_name": user.displayName,
                    "found": True,
                }
        return {
            "account_id": None,
            "display_name": display_name,
            "found": False,
        }
    except Exception as exc:
        return {
            "account_id": None,
            "display_name": display_name,
            "found": False,
            "error": str(exc),
        }


def link_issues(from_key: str, to_key: str, link_type: str = "Related") -> dict:
    """Link two issues."""
    try:
        client = get_client()
        client.create_issue_link(
            type={"name": link_type},
            inwardIssue=from_key,
            outwardIssue=to_key,
        )
        return {
            "from_key": from_key,
            "to_key": to_key,
            "link_type": link_type,
            "ok": True,
        }
    except JIRAError as exc:
        return {
            "from_key": from_key,
            "to_key": to_key,
            "link_type": link_type,
            "ok": False,
            "error": str(exc),
        }
    except Exception as exc:
        return {
            "from_key": from_key,
            "to_key": to_key,
            "link_type": link_type,
            "ok": False,
            "error": str(exc),
        }


def transition_issue(issue_key: str, transition_name: str) -> dict:
    """Transition issue status."""
    try:
        client = get_client()
        issue = client.issue(issue_key)
        current_status = issue.fields.status.name
        transitions = client.transitions(issue)
        match = next(
            (
                transition
                for transition in transitions
                if transition["name"].lower() == transition_name.lower()
                or transition["to"]["name"].lower() == transition_name.lower()
            ),
            None,
        )
        if match is None:
            return {
                "key": issue_key,
                "ok": False,
                "current_status": current_status,
                "error": f"Transition '{transition_name}' not found",
                "available_transitions": [transition["name"] for transition in transitions],
            }

        client.transition_issue(issue, match["id"])
        return {
            "key": issue_key,
            "ok": True,
            "from_status": current_status,
            "to_status": match["to"]["name"],
        }
    except JIRAError as exc:
        return {"key": issue_key, "ok": False, "error": str(exc)}
    except Exception as exc:
        return {"key": issue_key, "ok": False, "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Jira primitives")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("verify-auth")

    get_issue_parser = sub.add_parser("get-issue")
    get_issue_parser.add_argument("--key", required=True)

    create_issue_parser = sub.add_parser("create-issue")
    create_issue_parser.add_argument("--project", required=True)
    create_issue_parser.add_argument("--summary", required=True)
    create_issue_parser.add_argument("--description", required=True)
    create_issue_parser.add_argument("--issue-type", default="Task")

    update_issue_parser = sub.add_parser("update-issue")
    update_issue_parser.add_argument("--key", required=True)
    update_issue_parser.add_argument("--summary")
    update_issue_parser.add_argument("--description")

    search_user_parser = sub.add_parser("search-user")
    search_user_parser.add_argument("--name", required=True)

    link_issues_parser = sub.add_parser("link-issues")
    link_issues_parser.add_argument("--from", dest="from_key", required=True)
    link_issues_parser.add_argument("--to", dest="to_key", required=True)
    link_issues_parser.add_argument("--link-type", default="Related")

    transition_parser = sub.add_parser("transition")
    transition_parser.add_argument("--key", required=True)
    transition_parser.add_argument("--transition", required=True)

    args = parser.parse_args()

    if args.command == "verify-auth":
        result = verify_auth()
    elif args.command == "get-issue":
        result = get_issue(args.key)
    elif args.command == "create-issue":
        result = create_issue(args.project, args.summary, args.description, args.issue_type)
    elif args.command == "update-issue":
        result = update_issue(args.key, summary=args.summary, description=args.description)
    elif args.command == "search-user":
        result = search_user(args.name)
    elif args.command == "link-issues":
        result = link_issues(args.from_key, args.to_key, args.link_type)
    elif args.command == "transition":
        result = transition_issue(args.key, args.transition)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
