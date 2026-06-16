"""jira_ops.py -- Jira primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from jira import JIRA  # noqa: E402
from jira.exceptions import JIRAError  # noqa: E402

import site_config  # noqa: E402

site_config.load()

DEFAULT_JIRA_URL = "https://redhat.atlassian.net"


def get_client(url: str | None = None, email: str | None = None, token: str | None = None) -> JIRA:
    """Get authenticated Jira client. Auto-discovers credentials from environment."""
    resolved_url = url or os.environ.get("JIRA_URL", DEFAULT_JIRA_URL)
    resolved_email = email or os.environ.get("JIRA_EMAIL")
    resolved_token = token or os.environ.get("JIRA_API_TOKEN")

    if not resolved_email:
        raise ValueError("JIRA_EMAIL is not set. Add to .work/.env: JIRA_EMAIL=you@redhat.com")
    if not resolved_token:
        raise ValueError(
            "JIRA_API_TOKEN is not set. "
            "Create a token at: https://id.atlassian.com/manage-profile/security/api-tokens — "
            "then add to .work/.env: JIRA_API_TOKEN=ATATT3x..."
        )

    return JIRA(server=resolved_url, basic_auth=(resolved_email, resolved_token))


get_jira_client = get_client


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


def get_issue(issue_key: str, fields: list[str] | None = None) -> dict:
    """Get issue details.

    Args:
        issue_key: Jira issue key (e.g. "RHOAIENG-123").
        fields: Optional list of fields to return. Supported values:
            key, summary, status, issue_type, assignee (always included),
            description, labels, created, creator, reporter, components,
            fix_versions, priority, resolution, url.
            If None, returns the base set (key/summary/status/issue_type/assignee).
    """
    extra = set(fields or [])
    try:
        client = get_client()
        issue = client.issue(issue_key)
        assignee = None
        if issue.fields.assignee is not None:
            assignee = getattr(issue.fields.assignee, "displayName", None)
        result: dict = {
            "key": issue.key,
            "summary": issue.fields.summary,
            "status": issue.fields.status.name,
            "issue_type": issue.fields.issuetype.name,
            "assignee": assignee,
        }
        if extra:
            if "description" in extra:
                result["description"] = issue.fields.description
            if "labels" in extra:
                result["labels"] = issue.fields.labels
            if "created" in extra:
                result["created"] = str(issue.fields.created)
            if "creator" in extra:
                result["creator"] = getattr(issue.fields.creator, "displayName", None) if issue.fields.creator else None
            if "reporter" in extra:
                result["reporter"] = (
                    getattr(issue.fields.reporter, "displayName", None) if issue.fields.reporter else None
                )
            if "components" in extra:
                result["components"] = [c.name for c in issue.fields.components] if issue.fields.components else []
            if "fix_versions" in extra:
                result["fix_versions"] = [v.name for v in issue.fields.fixVersions] if issue.fields.fixVersions else []
            if "priority" in extra:
                result["priority"] = issue.fields.priority.name if issue.fields.priority else None
            if "resolution" in extra:
                result["resolution"] = issue.fields.resolution.name if issue.fields.resolution else None
            if "url" in extra:
                result["url"] = _issue_url(client, issue.key)
        return result
    except JIRAError as exc:
        return {"key": issue_key, "error": str(exc)}
    except Exception as exc:
        return {"key": issue_key, "error": str(exc)}


def get_comments(issue_key: str) -> dict:
    """Get all comments for an issue.

    Returns {"ok": True, "comments": [{"id": str, "author": str, "body": str, "created": str}]}
    """
    try:
        client = get_client()
        issue = client.issue(issue_key, fields="comment")
        comments = []
        for c in issue.fields.comment.comments:
            author = getattr(c.author, "displayName", "") if c.author else ""
            comments.append({
                "id": c.id,
                "author": author,
                "body": c.body or "",
                "created": str(c.created),
            })
        return {"ok": True, "comments": comments}
    except JIRAError as exc:
        return {"ok": False, "comments": [], "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "comments": [], "error": str(exc)}


def add_comment(issue_key: str, body: str) -> dict:
    """Add a comment to an issue.

    Returns {"key": str, "comment_id": str, "ok": True} on success.
    """
    try:
        client = get_client()
        comment = client.add_comment(issue_key, body)
        return {"key": issue_key, "comment_id": comment.id, "ok": True}
    except JIRAError as exc:
        return {"key": issue_key, "ok": False, "error": str(exc)}
    except Exception as exc:
        return {"key": issue_key, "ok": False, "error": str(exc)}


def create_issue(
    project: str,
    summary: str,
    description: str | dict | None = None,
    issue_type: str = "Task",
    components: list[str] | None = None,
    labels: list[str] | None = None,
    priority: str | None = None,
    extra_fields: dict | None = None,
) -> dict:
    """Create issue. Returns {"key": str, "url": str}.

    Args:
        description: Plain text string or ADF dict (Atlassian Document Format).
        extra_fields: Additional fields dict merged directly into the create payload.
    """
    try:
        client = get_client()
        fields: dict = {
            "project": {"key": project},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description is not None:
            fields["description"] = description
        if components:
            fields["components"] = [{"name": c} for c in components]
        if labels:
            fields["labels"] = labels
        if priority:
            fields["priority"] = {"name": priority}
        if extra_fields:
            fields.update(extra_fields)
        issue = client.create_issue(fields=fields)
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


def search_issues(jql: str, max_results: int = 50, fields: list[str] | None = None) -> dict:
    """Search issues via JQL. Returns {"issues": list[dict], "total": int}."""
    default_fields = ["key", "summary", "status", "issuetype", "assignee"]
    requested = fields if fields else default_fields
    field_str = ",".join(requested)

    try:
        client = get_client()
        issues = client.search_issues(jql, maxResults=max_results, fields=field_str)

        results = []
        for issue in issues:
            entry: dict = {"key": issue.key, "url": _issue_url(client, issue.key)}
            if "summary" in requested:
                entry["summary"] = issue.fields.summary
            if "status" in requested:
                entry["status"] = str(issue.fields.status)
            if "issuetype" in requested:
                entry["type"] = str(issue.fields.issuetype)
            if "assignee" in requested:
                assignee = issue.fields.assignee
                entry["assignee"] = str(assignee) if assignee else "Unassigned"
            if "created" in requested:
                entry["created"] = str(issue.fields.created)
            if "labels" in requested:
                entry["labels"] = issue.fields.labels
            if "fixVersions" in requested:
                entry["fix_versions"] = (
                    [v.name for v in issue.fields.fixVersions] if issue.fields.fixVersions else []
                )
            results.append(entry)

        return {"issues": results, "total": issues.total}
    except JIRAError as exc:
        return {"issues": [], "total": 0, "error": str(exc)}
    except Exception as exc:
        return {"issues": [], "total": 0, "error": str(exc)}


def link_issues(from_key: str, to_key: str, link_type: str = "Related") -> dict:
    """Link two issues."""
    try:
        client = get_client()
        client.create_issue_link(link_type, from_key, to_key)
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


def delete_issue_link(link_id: str) -> dict:
    """Delete an issue link by ID.

    Returns {"ok": True, "link_id": str} on success.
    """
    try:
        client = get_client()
        client._session.delete(f"{client._options['server']}/rest/api/2/issueLink/{link_id}")
        return {"ok": True, "link_id": link_id}
    except JIRAError as exc:
        return {"ok": False, "link_id": link_id, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "link_id": link_id, "error": str(exc)}


def transition_issue(issue_key: str, transition_name: str, resolution: str | None = None) -> dict:
    """Transition issue status.

    Args:
        issue_key: Jira issue key.
        transition_name: Name of the transition or target status.
        resolution: Optional resolution name (e.g. "Duplicate", "Done", "Won't Do").
            Required by some transitions like "Closed".
    """
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

        fields: dict = {}
        if resolution:
            fields["resolution"] = {"name": resolution}

        client.transition_issue(issue, match["id"], fields=fields if fields else None)
        return {
            "key": issue_key,
            "ok": True,
            "from_status": current_status,
            "to_status": match["to"]["name"],
            "resolution": resolution,
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
    get_issue_parser.add_argument(
        "--fields",
        default=None,
        help="Comma-separated extra fields: description,labels,created,creator,reporter,components,fix_versions,priority,resolution,url",
    )

    add_comment_parser = sub.add_parser("add-comment")
    add_comment_parser.add_argument("--key", required=True)
    add_comment_parser.add_argument("--body", required=True)

    create_issue_parser = sub.add_parser("create-issue")
    create_issue_parser.add_argument("--project", required=True)
    create_issue_parser.add_argument("--summary", required=True)
    create_issue_parser.add_argument("--description", required=True)
    create_issue_parser.add_argument("--issue-type", default="Task")
    create_issue_parser.add_argument("--components", default=None, help="Comma-separated Jira Component names")

    update_issue_parser = sub.add_parser("update-issue")
    update_issue_parser.add_argument("--key", required=True)
    update_issue_parser.add_argument("--summary")
    update_issue_parser.add_argument("--description")

    search_parser = sub.add_parser("search")
    search_parser.add_argument("--jql", required=True, help="JQL query string")
    search_parser.add_argument("--max-results", type=int, default=50)
    search_parser.add_argument(
        "--fields",
        default=None,
        help="Comma-separated fields: key,summary,status,issuetype,assignee,created,labels",
    )

    search_user_parser = sub.add_parser("search-user")
    search_user_parser.add_argument("--name", required=True)

    link_issues_parser = sub.add_parser("link-issues")
    link_issues_parser.add_argument("--from", dest="from_key", required=True)
    link_issues_parser.add_argument("--to", dest="to_key", required=True)
    link_issues_parser.add_argument("--link-type", default="Related")

    transition_parser = sub.add_parser("transition")
    transition_parser.add_argument("--key", required=True)
    transition_parser.add_argument("--transition", required=True)
    transition_parser.add_argument(
        "--resolution", default=None, help="Resolution name (e.g. Duplicate, Done, Won't Do)"
    )

    args = parser.parse_args()

    if args.command == "verify-auth":
        result = verify_auth()
    elif args.command == "get-issue":
        field_list = [f.strip() for f in args.fields.split(",")] if args.fields else None
        result = get_issue(args.key, fields=field_list)
    elif args.command == "add-comment":
        result = add_comment(args.key, args.body)
    elif args.command == "create-issue":
        comp_list = [c.strip() for c in args.components.split(",")] if args.components else None
        result = create_issue(args.project, args.summary, args.description, args.issue_type, components=comp_list)
    elif args.command == "update-issue":
        result = update_issue(args.key, summary=args.summary, description=args.description)
    elif args.command == "search":
        field_list = [f.strip() for f in args.fields.split(",")] if args.fields else None
        result = search_issues(args.jql, max_results=args.max_results, fields=field_list)
    elif args.command == "search-user":
        result = search_user(args.name)
    elif args.command == "link-issues":
        result = link_issues(args.from_key, args.to_key, args.link_type)
    elif args.command == "transition":
        result = transition_issue(args.key, args.transition, resolution=args.resolution)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
