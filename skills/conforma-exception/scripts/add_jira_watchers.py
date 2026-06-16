#!/usr/bin/env python3
"""Add watchers to Jira tickets across different projects.

Automatically selects the right mechanism per project:

  PSX / OCPEXCEPT  →  'Additional watchers' custom field (customfield_10705)
                      because the standard watcher API requires PSX view
                      permissions that most users lack.

  Everything else  →  Standard Jira watchers API (POST /issue/{key}/watchers).
      (RHOAIENG, …)

Editing the PSX custom field requires the caller to be the reporter or
assignee on the ticket (PSX project permission scheme).

Usage:
  python3 add_jira_watchers.py --tickets PSX-1038,PSX-1039 --watchers 'Akshay Ghodake'
  python3 add_jira_watchers.py --tickets RHOAIENG-38414 --watchers 'Akshay Ghodake,Jane Doe'
  python3 add_jira_watchers.py --tickets PSX-1040,RHOAIENG-38414 --watchers 'Akshay Ghodake' --dry-run
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import json
import os
import sys

import jira_ops

JIRA_BASE = "https://redhat.atlassian.net"

# PSX and OCPEXCEPT use a custom multi-user picker instead of standard watchers.
CUSTOM_FIELD_PROJECTS = {"PSX", "OCPEXCEPT"}
ADDITIONAL_WATCHERS_FIELD = "customfield_10705"


def _ensure_jira_env() -> None:
    """Ensure jira env vars are available (site_config.load() already handles this)."""
    pass


# ---------------------------------------------------------------------------
# REST helpers
# ---------------------------------------------------------------------------


def _jira_auth() -> tuple[str, str] | None:
    """Return (email, base64-encoded Basic auth value) or None."""
    import base64

    token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    if not token or not email:
        return None
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return email, auth


def _jira_get(path: str) -> dict | list | None:
    """GET a Jira REST API v3 path.  Returns parsed JSON or None."""
    import urllib.request

    creds = _jira_auth()
    if not creds:
        return None
    _, auth = creds

    url = f"{JIRA_BASE}/rest/api/3/{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _jira_put(path: str, payload: dict) -> dict:
    """PUT JSON to a Jira REST API v3 path.  Returns structured result."""
    import urllib.error
    import urllib.request

    creds = _jira_auth()
    if not creds:
        return {"ok": False, "status": 0, "error": "JIRA_API_TOKEN/EMAIL not configured"}
    _, auth = creds

    url = f"{JIRA_BASE}/rest/api/3/{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"ok": resp.status in (200, 204), "status": resp.status, "error": ""}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _jira_post(path: str, payload: str | dict) -> dict:
    """POST to a Jira REST API v3 path.  Returns structured result."""
    import urllib.error
    import urllib.request

    creds = _jira_auth()
    if not creds:
        return {"ok": False, "status": 0, "error": "JIRA_API_TOKEN/EMAIL not configured"}
    _, auth = creds

    url = f"{JIRA_BASE}/rest/api/3/{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return {"ok": resp.status in (200, 204), "status": resp.status, "error": ""}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _search_user(display_name: str) -> dict | None:
    """Search Jira for a user by display name (exact match).

    Returns {"accountId", "displayName", "emailAddress"} or None.
    Delegates to jira_ops.search_user() with conforma credential bridging.
    """
    _ensure_jira_env()
    try:
        result = jira_ops.search_user(display_name)
    except Exception:
        return None
    if result.get("found"):
        return {
            "accountId": result["account_id"],
            "displayName": result["display_name"],
            "emailAddress": "",
        }
    return None


def _project_from_key(ticket_key: str) -> str:
    """Extract the project prefix from a ticket key (e.g. PSX-1040 → PSX)."""
    return ticket_key.rsplit("-", 1)[0]


# ---------------------------------------------------------------------------
# Custom-field watcher path (PSX / OCPEXCEPT)
# ---------------------------------------------------------------------------


def _add_via_custom_field(
    ticket_key: str,
    watcher_accounts: list[dict],
    *,
    dry_run: bool,
) -> dict:
    """Add users via the 'Additional watchers' custom field."""
    result: dict = {
        "ticket_key": ticket_key,
        "method": "custom_field",
        "field": ADDITIONAL_WATCHERS_FIELD,
        "added": [],
        "already_present": [],
        "errors": [],
    }

    issue = _jira_get(f"issue/{ticket_key}?fields={ADDITIONAL_WATCHERS_FIELD},reporter,assignee")
    if issue is None:
        result["errors"].append("Cannot read ticket (auth failure or ticket not found)")
        result["status"] = "error"
        return result

    fields = issue.get("fields", {})
    current = fields.get(ADDITIONAL_WATCHERS_FIELD) or []
    current_ids = {w["accountId"] for w in current}

    reporter = fields.get("reporter", {}).get("displayName", "unknown")
    assignee = fields.get("assignee", {}).get("displayName", "unassigned") if fields.get("assignee") else "unassigned"
    result["reporter"] = reporter
    result["assignee"] = assignee

    to_add = [a for a in watcher_accounts if a["accountId"] not in current_ids]
    result["already_present"] = [a["displayName"] for a in watcher_accounts if a["accountId"] in current_ids]

    if not to_add:
        result["status"] = "no_change"
        return result

    if dry_run:
        result["status"] = "dry_run"
        result["would_add"] = [a["displayName"] for a in to_add]
        return result

    new_watchers = [{"accountId": uid} for uid in current_ids] + [{"accountId": a["accountId"]} for a in to_add]
    put_result = _jira_put(
        f"issue/{ticket_key}",
        {"fields": {ADDITIONAL_WATCHERS_FIELD: new_watchers}},
    )

    if put_result["ok"]:
        result["added"] = [a["displayName"] for a in to_add]
        result["status"] = "updated"
    else:
        error_body = put_result["error"]
        if put_result["status"] == 400 and "cannot be set" in error_body.lower():
            result["errors"].append(
                f"Field not editable on this ticket. "
                f"Your account must be the reporter or assignee "
                f"(reporter={reporter}, assignee={assignee})."
            )
        else:
            result["errors"].append(f"HTTP {put_result['status']}: {error_body}")
        result["status"] = "error"

    return result


# ---------------------------------------------------------------------------
# Standard watcher path (RHOAIENG, etc.)
# ---------------------------------------------------------------------------


def _get_standard_watchers(ticket_key: str) -> set[str] | None:
    """Return the set of accountIds currently watching via the standard API, or None on failure."""
    data = _jira_get(f"issue/{ticket_key}/watchers")
    if data is None:
        return None
    return {w.get("accountId", "") for w in data.get("watchers", [])}


def _add_via_standard_api(
    ticket_key: str,
    watcher_accounts: list[dict],
    *,
    dry_run: bool,
) -> dict:
    """Add users via the standard POST /issue/{key}/watchers API."""
    result: dict = {
        "ticket_key": ticket_key,
        "method": "standard_api",
        "added": [],
        "already_present": [],
        "errors": [],
    }

    existing = _get_standard_watchers(ticket_key)
    if existing is None:
        result["errors"].append("Cannot read watchers (auth failure or ticket not found)")
        result["status"] = "error"
        return result

    to_add = [a for a in watcher_accounts if a["accountId"] not in existing]
    result["already_present"] = [a["displayName"] for a in watcher_accounts if a["accountId"] in existing]

    if not to_add:
        result["status"] = "no_change"
        return result

    if dry_run:
        result["status"] = "dry_run"
        result["would_add"] = [a["displayName"] for a in to_add]
        return result

    for account in to_add:
        post_result = _jira_post(
            f"issue/{ticket_key}/watchers",
            account["accountId"],
        )
        if post_result["ok"]:
            result["added"].append(account["displayName"])
        else:
            error_body = post_result["error"]
            if "does not have permission" in error_body:
                result["errors"].append(f"{account['displayName']}: user lacks view permission on this ticket")
            else:
                result["errors"].append(f"{account['displayName']}: HTTP {post_result['status']}: {error_body}")

    result["status"] = "updated" if result["added"] else "error"
    return result


# ---------------------------------------------------------------------------
# Team auto-discovery
# ---------------------------------------------------------------------------


MAX_TEAM_GROUP_SIZE = 100


def discover_team() -> dict:
    """Discover the caller's Jira group members for automatic watcher addition.

    Queries the Jira REST API:
      1. GET /myself → caller's accountId
      2. GET /user/groups → groups the caller belongs to
      3. For each group ≤ MAX_TEAM_GROUP_SIZE members: fetch all members

    Groups larger than MAX_TEAM_GROUP_SIZE are skipped (org-wide groups like
    jira-users, employee, etc. that are not actual teams).

    Returns:
        {
            "caller": {"displayName", "accountId", "emailAddress"},
            "groups_checked": [{"name", "size", "included": bool}],
            "members": [{"displayName", "accountId"}],
            "errors": [str],
        }
    Members list excludes the caller and is deduplicated by accountId.
    """
    import urllib.parse
    import urllib.request

    creds = _jira_auth()
    if not creds:
        return {
            "caller": None,
            "groups_checked": [],
            "members": [],
            "errors": ["JIRA_API_TOKEN/EMAIL not configured"],
        }
    _, auth = creds
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    result: dict = {"caller": None, "groups_checked": [], "members": [], "errors": []}

    # Step 1: current user
    try:
        req = urllib.request.Request(f"{JIRA_BASE}/rest/api/3/myself", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            myself = json.loads(resp.read())
    except Exception as e:
        result["errors"].append(f"GET /myself failed: {e}")
        return result

    caller_id = myself.get("accountId", "")
    result["caller"] = {
        "displayName": myself.get("displayName", ""),
        "accountId": caller_id,
        "emailAddress": myself.get("emailAddress", ""),
    }

    # Step 2: caller's groups
    try:
        groups_url = f"{JIRA_BASE}/rest/api/3/user/groups?accountId={urllib.parse.quote(caller_id)}"
        req = urllib.request.Request(groups_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            groups = json.loads(resp.read())
    except Exception as e:
        result["errors"].append(f"GET /user/groups failed: {e}")
        return result

    group_names = [g.get("name", "") for g in groups if g.get("name")]

    if not group_names:
        return result

    # Step 3: probe each group's size, only fetch members for small groups
    seen_ids: set[str] = set()
    members: list[dict] = []
    groups_checked: list[dict] = []

    for gname in group_names:
        try:
            probe_url = (
                f"{JIRA_BASE}/rest/api/3/group/member?groupname={urllib.parse.quote(gname)}&startAt=0&maxResults=1"
            )
            req = urllib.request.Request(probe_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                probe = json.loads(resp.read())
        except Exception:
            groups_checked.append({"name": gname, "size": -1, "included": False})
            continue

        total = probe.get("total", 0)
        if total > MAX_TEAM_GROUP_SIZE:
            groups_checked.append({"name": gname, "size": total, "included": False})
            continue

        groups_checked.append({"name": gname, "size": total, "included": True})

        # Fetch all members (group is small enough)
        start_at = 0
        while True:
            try:
                url = (
                    f"{JIRA_BASE}/rest/api/3/group/member"
                    f"?groupname={urllib.parse.quote(gname)}"
                    f"&startAt={start_at}&maxResults=50"
                )
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read())
            except Exception:
                break

            page = data.get("values", [])
            if not page:
                break

            for m in page:
                aid = m.get("accountId", "")
                if aid and aid != caller_id and aid not in seen_ids:
                    seen_ids.add(aid)
                    members.append(
                        {
                            "displayName": m.get("displayName", ""),
                            "accountId": aid,
                        }
                    )

            if data.get("isLast", True):
                break
            start_at += len(page)

    members.sort(key=lambda x: x["displayName"])
    result["groups_checked"] = groups_checked
    result["members"] = members
    return result


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def resolve_watchers(display_names: list[str]) -> dict:
    """Resolve display names to Jira accountIds.

    Returns {"resolved": [{"accountId", "displayName", "emailAddress"}],
             "not_found": [str]}.
    """
    resolved: list[dict] = []
    not_found: list[str] = []
    for name in display_names:
        user = _search_user(name)
        if user:
            resolved.append(user)
        else:
            not_found.append(name)
    return {"resolved": resolved, "not_found": not_found}


def add_watchers_to_ticket(
    ticket_key: str,
    watcher_accounts: list[dict],
    *,
    dry_run: bool = False,
) -> dict:
    """Add watchers to a ticket, auto-selecting the mechanism by project."""
    project = _project_from_key(ticket_key)
    if project in CUSTOM_FIELD_PROJECTS:
        return _add_via_custom_field(ticket_key, watcher_accounts, dry_run=dry_run)
    return _add_via_standard_api(ticket_key, watcher_accounts, dry_run=dry_run)


def add_watchers_to_tickets(
    ticket_keys: list[str],
    display_names: list[str] | None = None,
    *,
    auto_discover: bool = False,
    dry_run: bool = False,
) -> dict:
    """Batch-add watchers to multiple Jira tickets.

    Args:
        ticket_keys: list of Jira ticket keys
        display_names: explicit display names to add (optional if auto_discover)
        auto_discover: if True, discover the caller's team members and add them
        dry_run: preview without writing

    Returns structured result with per-ticket outcomes and a summary.
    """
    all_names: list[str] = list(display_names) if display_names else []
    team_discovery: dict | None = None

    if auto_discover:
        team_discovery = discover_team()
        for member in team_discovery.get("members", []):
            name = member["displayName"]
            if name not in all_names:
                all_names.append(name)

    if not all_names:
        return {
            "status": "error",
            "error": "No watcher names provided and team discovery found no members.",
            "team_discovery": team_discovery,
            "tickets": [],
        }

    user_resolution = resolve_watchers(all_names)
    if user_resolution["not_found"]:
        return {
            "status": "error",
            "error": (
                f"Cannot resolve Jira user(s): {user_resolution['not_found']}. "
                f"Check spelling — search must match the exact Jira display name."
            ),
            "user_resolution": user_resolution,
            "team_discovery": team_discovery,
            "tickets": [],
        }

    resolved = user_resolution["resolved"]
    tickets: list[dict] = []
    for key in ticket_keys:
        ticket_result = add_watchers_to_ticket(key, resolved, dry_run=dry_run)
        tickets.append(ticket_result)

    summary = {
        "total": len(ticket_keys),
        "updated": sum(1 for t in tickets if t.get("status") == "updated"),
        "no_change": sum(1 for t in tickets if t.get("status") == "no_change"),
        "dry_run": sum(1 for t in tickets if t.get("status") == "dry_run"),
        "errors": sum(1 for t in tickets if t.get("status") == "error"),
    }

    out: dict = {
        "status": "completed",
        "watchers_added": [u["displayName"] for u in resolved],
        "user_resolution": user_resolution,
        "summary": summary,
        "tickets": tickets,
    }
    if team_discovery is not None:
        out["team_discovery"] = {
            "caller": team_discovery.get("caller"),
            "groups_checked": team_discovery.get("groups_checked", []),
            "members_discovered": len(team_discovery.get("members", [])),
        }
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Add watchers to Jira tickets.  Auto-selects the right mechanism: "
            "custom 'Additional watchers' field for PSX/OCPEXCEPT, "
            "standard watcher API for everything else."
        ),
    )
    parser.add_argument(
        "--tickets",
        required=True,
        help="Comma-separated ticket keys (e.g. PSX-1038,RHOAIENG-38414)",
    )
    parser.add_argument(
        "--watchers",
        default=None,
        help=(
            "Comma-separated Jira display names to add as watchers. "
            "Names must match the exact Jira display name. "
            "Example: --watchers 'Akshay Ghodake,Jane Doe'"
        ),
    )
    parser.add_argument(
        "--auto-discover",
        action="store_true",
        help=(
            "Discover the caller's Jira team members and add them as watchers. "
            "Can be combined with --watchers to add both team and explicit names."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ticket_keys = [k.strip() for k in args.tickets.split(",") if k.strip()]
    display_names = [n.strip() for n in args.watchers.split(",") if n.strip()] if args.watchers else None

    if not ticket_keys:
        print(json.dumps({"status": "error", "error": "No ticket keys provided"}, indent=2))
        return 1
    if not display_names and not args.auto_discover:
        print(json.dumps({"status": "error", "error": "Provide --watchers and/or --auto-discover"}, indent=2))
        return 1

    result = add_watchers_to_tickets(
        ticket_keys,
        display_names,
        auto_discover=args.auto_discover,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("summary", {}).get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
