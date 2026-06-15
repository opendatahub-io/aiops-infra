#!/usr/bin/env python3
"""Deterministic pre-flight check for conforma-exception.

Resolves ALL parameters from authoritative sources (Jira, GitLab, RPA files).
The agent MUST run this script FIRST and present its output to the user for
confirmation. The agent MUST NOT make decisions about any of these values.

Outputs a JSON with:
  - resolved values (rule, components, versions, dates, links)
  - existing state (duplicate tickets, existing exceptions, related PSX)
  - hard-rule defaults (link types, MR-per-version strategy)
  - items requiring user confirmation

Usage:
  # Existing exception gate check (no Jira required — run FIRST)
  python3 scripts/preflight_check.py --check-existing-exception \
    --rule hermetic_task.hermetic \
    --components odh-model-registry-v3-4

  # Full pre-flight check (requires Jira URL)
  python3 scripts/preflight_check.py --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38389

Batch violations coverage has moved to:
  skills/conforma-analyze/scripts/violations_coverage.py
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import conforma_policy_ops

_SKILL_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = _SKILL_DIR / ".work"


# Hard rules — NOT configurable by the agent or user
HARD_RULES = {
    "mr_strategy": "one_mr_per_rule_all_versions",
    "link_type_rhoaieng_to_prodsec": "Blocks",
    "link_type_rhoaieng_to_psx": "Blocks",  # legacy alias
    "link_type_related_psx": "Related",
    "link_type_tracking_ticket": "Related",
    "no_self_links": True,
    "remote_links_are_idempotent": True,
    "old_style_exception_handling": "leave_intact_append_new_with_componentNames",
    "matching_componentNames_exception_handling": "extend_effectiveUntil_in_place",
}

# Default end-of-support dates (pre-calculated with +7 day buffer; buffer only applies to EOS-sourced dates)
DEFAULT_EOS_DATES: dict[str, str] = {
    "rhoai-2.25": "2027-04-26",
    "rhoai-3.3": "2026-10-05",
    "rhoai-3.4": "2026-08-12",
    "rhoai-3.5-ea.1": "2026-06-19",
}


def _run_acli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    from cli_runner import run_acli

    return run_acli(args, timeout=timeout)


def _extract_ticket_key(url: str) -> str | None:
    match = re.search(r"([A-Z]+-\d+)", url)
    return match.group(1) if match else None


def fetch_rhoaieng_ticket(url: str) -> dict:
    """Fetch RHOAIENG ticket details and extract rule/version/component info."""
    ticket_key = _extract_ticket_key(url)
    if not ticket_key:
        return {"error": f"Cannot extract ticket key from: {url}"}

    result = _run_acli(["jira", "workitem", "view", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return {"error": f"Cannot fetch {ticket_key}: {result.stderr.strip()}"}

    data = json.loads(result.stdout)
    fields = data.get("fields", {})

    info = {
        "key": ticket_key,
        "url": url,
        "summary": fields.get("summary", ""),
        "type": fields.get("issuetype", {}).get("name", "Unknown"),
        "priority": fields.get("priority", {}).get("name", "Unknown"),
        "status": fields.get("status", {}).get("name", "Unknown"),
        "labels": fields.get("labels", []),
    }

    if info["type"] != "Bug" or info["priority"] != "Blocker":
        info["type_warning"] = (
            f"{ticket_key} is a '{info['type']}' (priority: {info['priority']}). "
            f"Exception process expects a Blocker Bug cloned from RHOAIENG-62569."
        )

    rule = _extract_rule_from_summary(info["summary"])
    if rule:
        info["detected_rule"] = rule

    return info


def _extract_rule_from_summary(summary: str) -> str | None:
    """Extract conforma rule from ticket summary."""
    match = re.search(r"(rpm_signature\.allowed:[0-9a-fA-F]+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"signed with ([0-9a-fA-F]{16})(?![0-9a-fA-F])", summary)
    if match:
        return f"rpm_signature.allowed:{match.group(1)}"
    match = re.search(r"signing key ([0-9a-fA-F]{16})(?![0-9a-fA-F])", summary)
    if match:
        return f"rpm_signature.allowed:{match.group(1)}"
    match = re.search(r"(hermetic_task\.\w+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"(schedule\.\w+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"(test\.\w+:\S+)", summary)
    if match:
        return match.group(1)
    return None


def search_related_psx(rule: str) -> list[dict]:
    """Search for existing PSX tickets related to this rule."""
    rule_fragment = rule
    if ":" in rule:
        rule_fragment = rule.split(":", 1)[1]

    result = _run_acli(
        ["jira", "workitem", "search", "--jql", f"project = PSX AND text ~ '{rule_fragment}'"],
        timeout=30,
    )
    if result.returncode != 0:
        return []

    tickets = []
    for line in result.stdout.splitlines():
        match = re.search(r"(PSX-\d+)", line)
        if match:
            key = match.group(1)
            if key not in [t["key"] for t in tickets]:
                summary_match = re.search(r"PSX-\d+\s*│\s*.*?│.*?│.*?│\s*(.*)", line)
                summary = summary_match.group(1).strip() if summary_match else ""
                tickets.append({"key": key, "summary_fragment": summary})
    return tickets


def check_rhoaieng_approval_status(url: str) -> dict:
    """Check whether the RHOAIENG approval Jira ticket has been approved.

    Fetches the ticket and inspects its status and resolution. An approved
    ticket is one that is Closed/Resolved with a resolution indicating
    approval (Done, Fixed, Approved, etc.) or has a comment from a known
    senior manager confirming approval.

    Returns:
        {
            "url": str,
            "key": str,
            "status": str,          # Jira status name
            "resolution": str|None, # Jira resolution name
            "approved": bool,       # deterministic verdict
            "reason": str,          # human-readable explanation
            "approval_comment": str|None,  # matching comment if found
        }
    """
    ticket_key = _extract_ticket_key(url)
    if not ticket_key:
        return {
            "url": url,
            "key": None,
            "status": "unknown",
            "resolution": None,
            "approved": False,
            "reason": f"Cannot extract ticket key from: {url}",
            "approval_comment": None,
        }

    result = _run_acli(["jira", "workitem", "view", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return {
            "url": url,
            "key": ticket_key,
            "status": "unknown",
            "resolution": None,
            "approved": False,
            "reason": f"Cannot fetch {ticket_key}: {result.stderr.strip()}",
            "approval_comment": None,
        }

    data = json.loads(result.stdout)
    fields = data.get("fields", {})
    status_name = fields.get("status", {}).get("name", "Unknown")
    status_category = fields.get("status", {}).get("statusCategory", {}).get("key", "")
    resolution = fields.get("resolution")
    resolution_name = resolution.get("name", "") if resolution else None

    approved_statuses = {"done", "closed", "resolved"}
    approved_resolutions = {"done", "fixed", "approved", "won't do", "complete", "completed"}

    is_done = status_category == "done" or status_name.lower() in approved_statuses
    has_approved_resolution = resolution_name is not None and resolution_name.lower() in approved_resolutions

    approval_comment = None
    if not (is_done and has_approved_resolution):
        approval_comment = _search_approval_comments(ticket_key)

    approved = (is_done and has_approved_resolution) or approval_comment is not None

    if approved and is_done:
        reason = (
            f"{ticket_key} is {status_name}"
            + (f" (resolution: {resolution_name})" if resolution_name else "")
            + ". Approval requirement satisfied."
        )
    elif approved and approval_comment:
        reason = (
            f"{ticket_key} is {status_name} (not yet closed) but has an "
            f"approval comment. Approval requirement satisfied."
        )
    else:
        reason = (
            f"{ticket_key} is {status_name}"
            + (f" (resolution: {resolution_name})" if resolution_name else "")
            + ". RHOAIENG approval is required before submitting the ProdSec "
            + "form, creating OCPEXCEPT tickets, or the GitLab Merge Request."
        )

    return {
        "url": url,
        "key": ticket_key,
        "status": status_name,
        "resolution": resolution_name,
        "approved": approved,
        "reason": reason,
        "approval_comment": approval_comment,
    }


def _search_approval_comments(ticket_key: str) -> str | None:
    """Search a ticket's comments for approval from a senior manager."""
    result = _run_acli(["jira", "workitem", "comments", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    comments = data if isinstance(data, list) else data.get("comments", [])
    approval_keywords = [
        "approved",
        "approve",
        "lgtm",
        "go ahead",
        "exception approved",
        "approval granted",
    ]
    for comment in comments:
        body = ""
        if isinstance(comment, dict):
            body = comment.get("body", "") or ""
            if isinstance(body, dict):
                body = json.dumps(body)
        elif isinstance(comment, str):
            body = comment
        body_lower = body.lower()
        if any(kw in body_lower for kw in approval_keywords):
            author = ""
            if isinstance(comment, dict):
                author = (
                    comment.get("author", {}).get("displayName", "") if isinstance(comment.get("author"), dict) else ""
                )
            snippet = body[:200] + ("..." if len(body) > 200 else "")
            return f"[{author}]: {snippet}"

    return None


def check_duplicate_psx_tickets(rule: str, rhoai_versions: list[str]) -> list[dict]:
    """Check if PSX tickets already exist for this exact rule+versions combo."""
    search_term = rule.split(":", 1)[1] if ":" in rule else rule
    result = _run_acli(
        [
            "jira",
            "workitem",
            "search",
            "--jql",
            f"project = PSX AND summary ~ '{search_term}' AND labels = 'conforma-exception-ai-skill'",
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return []

    tickets = []
    for line in result.stdout.splitlines():
        match = re.search(r"(PSX-\d+)", line)
        if match:
            key = match.group(1)
            if key not in [t["key"] for t in tickets]:
                tickets.append({"key": key})
    return tickets


def lookup_components_from_rpa(
    image_bases: list[str], rhoai_versions: list[str], rpa_dir: str | None = None
) -> dict[str, list[str]]:
    """Look up Konflux component names from ReleasePlanAdmission files."""
    from validate_inputs import lookup_component_names

    results: dict[str, list[str]] = {}
    for ver in rhoai_versions:
        all_matches = []
        for img in image_bases:
            found = lookup_component_names(img, [ver], rpa_dir)
            all_matches.extend(found.get(ver, []))
        results[ver] = sorted(set(all_matches))
    return results


def resolve_effective_until_dates(rhoai_versions: list[str]) -> dict[str, dict]:
    """Resolve effectiveUntil dates from defaults (end-of-support + 7 day buffer).

    The +7 day buffer is only applied to dates sourced from this EOS table.
    User-provided or Jira-sourced dates are used as-is.
    """
    results = {}
    for ver in rhoai_versions:
        if ver in DEFAULT_EOS_DATES:
            results[ver] = {
                "effectiveUntil": f"{DEFAULT_EOS_DATES[ver]}T00:00:00Z",
                "source": "default_eos_table",
                "note": "End-of-support date + 7 day buffer (pre-calculated)",
            }
        else:
            results[ver] = {
                "effectiveUntil": None,
                "source": "unknown",
                "note": f"No default EOS date for {ver}. User must provide.",
            }
    return results


def evaluate_decision(
    existing_exceptions: dict,
    components_per_version: dict[str, list[str]],
    environment: str = "prod",
) -> dict:
    """Deterministic go/no-go decision based on existing state.

    Decision rules (hardcoded, not configurable):
    1. If rule has a permanent global exclusion in the TARGET environment file
       (in `exclude:` section, no componentNames, no effectiveUntil) → ABORT.
       The rule is already permanently approved for all components in that env.
    2. If rule has a volatile exception with matching componentNames and no effectiveUntil
       (permanent scoped) → ABORT for those components (already permanently covered).
    3. If rule has a volatile exception with matching componentNames and effectiveUntil
       → PROCEED with action "extend" (update the date).
    4. If rule has a volatile exception without componentNames (old-style, time-bounded)
       → PROCEED with action "append_new_style" (leave old intact, add new block).
    5. If no existing exception found → PROCEED with action "create_new".

    The `environment` parameter determines which file(s) are relevant. A permanent
    exclusion in stage does NOT block creation in prod, and vice versa.

    Returns:
        {
            "proceed": bool,
            "action": str,  # "abort" | "create_new" | "extend" | "append_new_style"
            "reason": str,  # human-readable explanation
            "details": dict # additional context
        }
    """
    if not existing_exceptions.get("checked"):
        return {
            "proceed": True,
            "action": "create_new",
            "reason": (
                "Could not check existing exceptions "
                f"({existing_exceptions.get('reason', 'unknown')}). "
                "Proceeding with creation — dedup will be handled at MR time."
            ),
            "details": {},
        }

    permanent = existing_exceptions.get("permanent_exclusions", [])
    relevant_permanent = [p for p in permanent if f"-{environment}." in Path(p["file"]).name]
    if relevant_permanent:
        return {
            "proceed": False,
            "action": "abort",
            "reason": (
                f"Rule is already permanently excluded globally in "
                f"{relevant_permanent[0]['file']} (line {relevant_permanent[0]['line']}). "
                f"No componentNames-scoped exception needed — all components "
                f"are covered forever in {environment}. "
                f"Creating a new exception would be redundant."
            ),
            "details": {"permanent_exclusions": relevant_permanent},
        }

    volatile = existing_exceptions.get("existing_exceptions", [])
    volatile = [v for v in volatile if f"-{environment}." in Path(v["file"]).name]
    if not volatile:
        return {
            "proceed": True,
            "action": "create_new",
            "reason": "No existing exception found for this rule. Will create new.",
            "details": {},
        }

    all_requested_components = set()
    for comps in components_per_version.values():
        all_requested_components.update(comps)

    for exc in volatile:
        if exc["has_componentNames"]:
            if not exc["effectiveUntil"]:
                exc_comps = set(exc["componentNames"])
                if all_requested_components.issubset(exc_comps):
                    return {
                        "proceed": False,
                        "action": "abort",
                        "reason": (
                            f"Rule already has a permanent scoped exception in "
                            f"{exc['file']} covering all requested components. "
                            f"No new exception needed."
                        ),
                        "details": {"matching_exception": exc},
                    }
            else:
                exc_comps = set(exc["componentNames"])
                if all_requested_components == exc_comps or all_requested_components.issubset(exc_comps):
                    return {
                        "proceed": True,
                        "action": "extend",
                        "reason": (
                            f"Existing exception with matching componentNames found in "
                            f"{exc['file']} (effectiveUntil: {exc['effectiveUntil']}). "
                            f"Will extend the effectiveUntil date."
                        ),
                        "details": {"matching_exception": exc},
                    }

    has_old_style = any(not exc["has_componentNames"] for exc in volatile)
    if has_old_style:
        return {
            "proceed": True,
            "action": "append_new_style",
            "reason": (
                "Old-style exception (no componentNames) found. "
                "Will leave it intact and append a new componentNames-based block."
            ),
            "details": {"old_style_exceptions": [e for e in volatile if not e["has_componentNames"]]},
        }

    return {
        "proceed": True,
        "action": "create_new",
        "reason": (
            "Existing exceptions found but with different componentNames. "
            "Will create a new block for the requested components."
        ),
        "details": {"existing_exceptions": volatile},
    }


def discover_user_groups() -> dict:
    """Discover the current user's Jira groups and their members dynamically.

    Uses the Jira REST API:
    1. GET /rest/api/3/myself → current user's accountId and displayName
    2. GET /rest/api/3/user/groups?accountId=... → groups the user belongs to
    3. GET /rest/api/3/group/member?groupname=... → members of each group

    Returns a SUGGESTION — the agent MUST present this to the user for
    confirmation before adding anyone as watchers.
    """
    import base64
    import getpass
    import urllib.error
    import urllib.request

    from cli_runner import _resolve_env

    try:
        current_user = getpass.getuser()
    except Exception:
        current_user = "unknown"

    token = _resolve_env("JIRA_API_TOKEN") or ""
    email = _resolve_env("JIRA_EMAIL") or ""
    if not token or not email:
        return {
            "source": "none",
            "user": current_user,
            "user_display_name": None,
            "groups_found": [],
            "suggested_members": [],
            "note": "Jira API unavailable (JIRA_API_TOKEN/JIRA_EMAIL not configured). Cannot discover watchers.",
        }

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    }

    # Step 1: Get current user's accountId
    try:
        req = urllib.request.Request(
            "https://redhat.atlassian.net/rest/api/3/myself",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            myself = json.loads(resp.read())
    except Exception as e:
        return {
            "source": "none",
            "user": current_user,
            "user_display_name": None,
            "groups_found": [],
            "suggested_members": [],
            "note": f"Jira API unavailable (GET /myself failed: {e}). Cannot discover watchers.",
        }

    account_id = myself.get("accountId", "")
    display_name = myself.get("displayName", "")

    # Step 2: Get user's groups
    try:
        groups_url = f"https://redhat.atlassian.net/rest/api/3/user/groups?accountId={urllib.request.quote(account_id)}"
        req = urllib.request.Request(groups_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            groups = json.loads(resp.read())
    except Exception as e:
        return {
            "source": "none",
            "user": current_user,
            "user_display_name": display_name,
            "groups_found": [],
            "suggested_members": [],
            "note": f"Jira API unavailable (GET /user/groups failed: {e}). Cannot discover watchers.",
        }

    if not groups:
        return {
            "source": "jira_groups",
            "user": current_user,
            "user_display_name": display_name,
            "groups_found": [],
            "suggested_members": [],
            "note": "User belongs to no Jira groups. No watchers suggested.",
        }

    # Step 3: Fetch members for each group
    group_names = [g.get("name", "") for g in groups if g.get("name")]
    all_members: list[dict] = []
    groups_with_members: list[dict] = []

    for gname in group_names:
        members = _fetch_group_members(gname, headers)
        if members:
            groups_with_members.append(
                {
                    "group_name": gname,
                    "member_count": len(members),
                }
            )
            for m in members:
                if m.get("accountId") != account_id:
                    all_members.append(m)

    # Deduplicate by accountId
    seen_ids: set[str] = set()
    unique_members: list[dict] = []
    for m in all_members:
        aid = m.get("accountId", "")
        if aid and aid not in seen_ids:
            seen_ids.add(aid)
            unique_members.append(
                {
                    "displayName": m.get("displayName", ""),
                    "accountId": aid,
                }
            )

    unique_members.sort(key=lambda x: x["displayName"])

    return {
        "source": "jira_groups",
        "user": current_user,
        "user_display_name": display_name,
        "groups_found": [g["group_name"] for g in groups_with_members],
        "all_groups": group_names,
        "groups_with_members": groups_with_members,
        "suggested_members": unique_members,
        "note": "SUGGESTION ONLY — present to user for confirmation before adding as watchers",
    }


def _fetch_group_members(group_name: str, headers: dict) -> list[dict]:
    """Fetch all members of a Jira group. Returns list of {displayName, accountId}."""
    import urllib.request

    members: list[dict] = []
    start_at = 0
    max_results = 50

    while True:
        url = (
            f"https://redhat.atlassian.net/rest/api/3/group/member"
            f"?groupname={urllib.request.quote(group_name)}"
            f"&startAt={start_at}&maxResults={max_results}"
        )
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception:
            break

        values = data.get("values", [])
        if not values:
            break

        for v in values:
            members.append(
                {
                    "displayName": v.get("displayName", ""),
                    "accountId": v.get("accountId", ""),
                }
            )

        if data.get("isLast", True):
            break
        start_at += max_results

    return members


def run_preflight(
    rhoaieng_url: str,
    rule_override: str | None = None,
    versions_override: list[str] | None = None,
    image_bases: list[str] | None = None,
    rpa_dir: str | None = None,
    clone_dir: str | None = None,
    environment: str = "prod",
) -> dict:
    """Run all pre-flight checks and return structured result."""
    output: dict = {
        "hard_rules": HARD_RULES,
        "decision": {},
        "rhoaieng": {},
        "rhoaieng_approval_status": {},
        "rule": {},
        "versions": {},
        "components": {},
        "effective_until": {},
        "related_psx": {},
        "existing_exceptions": {},
        "duplicate_check": {},
        "psx_watchers": {},
        "user_confirmation_required": [],
    }

    # 1. Fetch RHOAIENG ticket
    rhoaieng = fetch_rhoaieng_ticket(rhoaieng_url)
    output["rhoaieng"] = rhoaieng
    if "error" in rhoaieng:
        output["user_confirmation_required"].append(f"Cannot fetch RHOAIENG ticket: {rhoaieng['error']}")
        return output

    # 1b. Check RHOAIENG approval status
    approval_status = check_rhoaieng_approval_status(rhoaieng_url)
    output["rhoaieng_approval_status"] = approval_status
    if not approval_status["approved"]:
        output["user_confirmation_required"].append(
            f"RHOAIENG APPROVAL REQUIRED: {approval_status['reason']} "
            f"ProdSec form submission, OCPEXCEPT ticket creation, and GitLab "
            f"Merge Request creation will be blocked until this ticket is "
            f"approved. Use --skip-approval-gate to override (not recommended)."
        )

    # 2. Resolve rule
    if rule_override:
        resolved_rule = rule_override
        output["rule"] = {"value": resolved_rule, "source": "user_override"}
    elif rhoaieng.get("detected_rule"):
        resolved_rule = rhoaieng["detected_rule"]
        output["rule"] = {"value": resolved_rule, "source": "extracted_from_summary"}
        output["user_confirmation_required"].append(f"Confirm rule: {resolved_rule} (extracted from ticket summary)")
    else:
        resolved_rule = ""
        output["rule"] = {"value": None, "source": "not_found"}
        output["user_confirmation_required"].append("Could not extract rule from ticket. User must provide --rule.")

    # 3. Resolve versions
    if versions_override:
        versions = versions_override
        output["versions"] = {"values": versions, "source": "user_override"}
    else:
        output["versions"] = {"values": [], "source": "not_provided"}
        output["user_confirmation_required"].append("RHOAI versions not provided. User must specify.")
        versions = []

    # 4. Look up components
    if image_bases and versions:
        components = lookup_components_from_rpa(image_bases, versions, rpa_dir)
        output["components"] = {"per_version": components, "source": "rpa_lookup"}
        output["user_confirmation_required"].append(f"Confirm component names per version: {json.dumps(components)}")
    else:
        output["components"] = {"per_version": {}, "source": "not_resolved"}
        if not image_bases:
            output["user_confirmation_required"].append("Image base names not provided. Cannot look up components.")

    # 5. Resolve effectiveUntil dates
    if versions:
        dates = resolve_effective_until_dates(versions)
        output["effective_until"] = dates
        missing_dates = [v for v, d in dates.items() if d["effectiveUntil"] is None]
        if missing_dates:
            output["user_confirmation_required"].append(
                f"No default EOS dates for: {missing_dates}. User must provide."
            )
        else:
            output["user_confirmation_required"].append(
                "Confirm effectiveUntil dates (end-of-support + 7 day buffer): "
                + ", ".join(f"{v}={d['effectiveUntil']}" for v, d in dates.items())
            )

    # 6. Search related PSX
    if resolved_rule:
        related = search_related_psx(resolved_rule)
        output["related_psx"] = {"found": related, "count": len(related)}
    else:
        output["related_psx"] = {"found": [], "count": 0}

    # 7. Check existing exceptions in GitLab
    if resolved_rule:
        existing = conforma_policy_ops.search_existing_exceptions(resolved_rule, clone_dir)
        output["existing_exceptions"] = existing

    # 8. Discover user's Jira groups for watcher suggestion
    watcher_info = discover_user_groups()
    output["psx_watchers"] = watcher_info
    suggested = watcher_info.get("suggested_members", [])
    if suggested:
        member_names = [m["displayName"] for m in suggested[:5]]
        suffix = f" (+{len(suggested) - 5} more)" if len(suggested) > 5 else ""
        output["user_confirmation_required"].append(
            f"Ticket visibility: Found {len(suggested)} potential watchers from "
            f"group(s) {watcher_info.get('groups_found', [])}. "
            f"Suggested: {', '.join(member_names)}{suffix}. "
            f"Add as watchers on RHOAIENG/OCPEXCEPT tickets? (source: {watcher_info['source']})"
        )

    # 9. Evaluate decision (deterministic go/no-go)
    components_per_version = output["components"].get("per_version", {})
    decision = evaluate_decision(
        existing_exceptions=output["existing_exceptions"] if output["existing_exceptions"] else {},
        components_per_version=components_per_version,
        environment=environment,
    )
    output["decision"] = decision

    if not decision["proceed"]:
        output["user_confirmation_required"] = [
            f"DECISION: ABORT — {decision['reason']}",
            "No further action required. The agent MUST NOT proceed with exception creation.",
        ]
        return output

    # 10. Check for duplicate PSX tickets
    if resolved_rule and versions:
        dupes = check_duplicate_psx_tickets(resolved_rule, versions)
        output["duplicate_check"] = {
            "existing_skill_created_psx": dupes,
            "count": len(dupes),
        }
        if dupes:
            output["user_confirmation_required"].append(
                f"WARNING: Found {len(dupes)} existing PSX ticket(s) created by this "
                f"skill for the same rule: {[d['key'] for d in dupes]}. "
                f"Confirm whether to reuse or create new."
            )

    # 11. RHOAIENG type warning
    if rhoaieng.get("type_warning"):
        output["user_confirmation_required"].append(rhoaieng["type_warning"])

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic pre-flight check for conforma-exception")
    parser.add_argument(
        "--check-existing-exception",
        action="store_true",
        help=(
            "Check if an active exception already exists for the given rule + components. "
            "No Jira required. Requires --rule and --components. Outputs JSON gate result."
        ),
    )
    parser.add_argument("--rhoaieng-url", default=None, help="RHOAIENG Jira ticket URL")
    parser.add_argument("--rule", default=None, help="Override rule (skip extraction)")
    parser.add_argument(
        "--components",
        default=None,
        help="Comma-separated Konflux component names (required for --check-existing-exception)",
    )
    parser.add_argument("--versions", default=None, help="Comma-separated RHOAI versions (e.g. rhoai-2.25,rhoai-3.3)")
    parser.add_argument(
        "--image-bases",
        default=None,
        help="Comma-separated image base names for RPA lookup (e.g. odh-vllm-cpu,odh-vllm-gaudi)",
    )
    parser.add_argument("--rpa-dir", default=None, help="Path to RPA directory")
    parser.add_argument("--clone-dir", default=None, help="Path to konflux-release-data clone")
    parser.add_argument(
        "--environment",
        default="prod",
        choices=["prod", "stage"],
        help="Target environment (filters decision to relevant policy files)",
    )
    args = parser.parse_args()

    if args.check_existing_exception:
        if not args.rule:
            parser.error("--check-existing-exception requires --rule")
        if not args.components:
            parser.error("--check-existing-exception requires --components")
    elif not args.rhoaieng_url:
        parser.error("--rhoaieng-url is required (unless using --check-existing-exception)")

    return args


def main() -> int:
    args = parse_args()

    if args.check_existing_exception:
        components = [c.strip() for c in args.components.split(",")]
        result = conforma_policy_ops.check_existing_exception_gate(
            rule=args.rule,
            components=components,
            clone_dir=args.clone_dir,
            environment=args.environment,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] != "blocked" else 1

    versions = [v.strip() for v in args.versions.split(",")] if args.versions else None
    image_bases = [i.strip() for i in args.image_bases.split(",")] if args.image_bases else None

    result = run_preflight(
        rhoaieng_url=args.rhoaieng_url,
        rule_override=args.rule,
        versions_override=versions,
        image_bases=image_bases,
        rpa_dir=args.rpa_dir,
        clone_dir=args.clone_dir,
        environment=args.environment,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
