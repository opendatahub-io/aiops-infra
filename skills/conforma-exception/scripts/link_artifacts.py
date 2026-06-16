#!/usr/bin/env python3
"""Comment MR URL on Jira tickets and add provenance label.

For each Jira ticket (RHOAIENG, PSX, OCPEXCEPT):
  1. Adds a remote/web link to the GitLab MR (if JIRA_API_TOKEN is set)
  2. Adds a comment with the GitLab MR URL and provenance footer
  3. Adds the conforma-exception-ai-skill label

This ensures even pre-existing tickets (passed via URL) get marked.
Requires JIRA_API_TOKEN and JIRA_EMAIL env vars for remote links.
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import getpass
import json
import os
import platform
import re
import sys
import urllib.request
from pathlib import Path

import jira_ops

PROVENANCE_REPO = "opendatahub-io/aiops-infra"
PROVENANCE_LABEL = "conforma-exception-ai-skill"
VIOLATION_LABEL = "conforma-violation"

_SKILL_DIR = Path(__file__).resolve().parent.parent
WORK_DIR = _SKILL_DIR / ".work"


def _ensure_jira_env() -> None:
    """Ensure jira env vars are available (site_config.load() already handles this)."""
    pass


def _jira_auth() -> tuple[str, str] | None:
    """Return (email, base64-encoded auth header value) or None if not configured."""
    import base64

    token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    if not token or not email:
        return None
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    return email, auth


def _jira_rest_get(path: str, fields: str | None = None) -> dict | None:
    """GET a Jira REST API endpoint. Returns parsed JSON or None on failure."""
    creds = _jira_auth()
    if not creds:
        return None
    _, auth = creds

    url = f"https://redhat.atlassian.net/rest/api/3/{path}"
    if fields:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}fields={fields}"

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


def _jira_rest_put(path: str, payload: dict) -> dict:
    """PUT to a Jira REST API endpoint. Returns {ok: bool, status: int, error: str}."""
    import urllib.error

    creds = _jira_auth()
    if not creds:
        return {"ok": False, "status": 0, "error": "JIRA auth not configured"}
    _, auth = creds

    url = f"https://redhat.atlassian.net/rest/api/3/{path}"
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
            body = e.read().decode()[:300]
        except Exception:
            pass
        return {"ok": False, "status": e.code, "error": body}
    except Exception as e:
        return {"ok": False, "status": 0, "error": str(e)}


def _verify_link_exists(ticket_key: str, target_key: str) -> bool:
    """Verify a link exists between ticket_key and target_key via REST API."""
    data = _jira_rest_get(f"issue/{ticket_key}", fields="issuelinks")
    if not data:
        return True  # Can't verify, assume success
    links = data.get("fields", {}).get("issuelinks", [])
    for link in links:
        inward = link.get("inwardIssue", {}).get("key", "")
        outward = link.get("outwardIssue", {}).get("key", "")
        if target_key in (inward, outward):
            return True
    return False


def build_provenance_footer() -> str:
    """Standard provenance footer for comments."""
    return (
        "---\n"
        f"Created by 'conforma-exception' skill from {PROVENANCE_REPO}\n"
        f"User: {getpass.getuser()}@{platform.node()}"
    )


def _get_existing_remote_links(ticket_key: str) -> list[dict]:
    """Fetch existing remote/web links on a Jira ticket."""
    creds = _jira_auth()
    if not creds:
        return []
    _, auth = creds

    jira_url = f"https://redhat.atlassian.net/rest/api/3/issue/{ticket_key}/remotelink"
    req = urllib.request.Request(
        jira_url,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def add_remote_link(ticket_key: str, url: str, title: str, dry_run: bool = False) -> dict:
    """Add a web/remote link to a Jira ticket via REST API.

    Idempotent: checks for existing links with the same URL before adding.
    Requires JIRA_API_TOKEN and JIRA_EMAIL environment variables.
    Falls back gracefully if not available.
    """
    if dry_run:
        return {
            "status": "dry_run",
            "ticket_key": ticket_key,
            "remote_link": url,
        }

    api_token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    if not api_token or not email:
        return {
            "status": "skipped_no_token",
            "ticket_key": ticket_key,
            "remote_link": url,
        }

    existing = _get_existing_remote_links(ticket_key)
    for link in existing:
        if link.get("object", {}).get("url") == url:
            return {
                "status": "remote_link_already_exists",
                "ticket_key": ticket_key,
                "remote_link": url,
            }

    import base64

    jira_url = f"https://redhat.atlassian.net/rest/api/3/issue/{ticket_key}/remotelink"
    payload = json.dumps({"object": {"url": url, "title": title}}).encode("utf-8")
    auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()

    req = urllib.request.Request(
        jira_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status in (200, 201):
                return {
                    "status": "remote_link_added",
                    "ticket_key": ticket_key,
                    "remote_link": url,
                }
    except Exception as e:
        return {
            "status": "remote_link_failed",
            "ticket_key": ticket_key,
            "remote_link": url,
            "error": str(e),
        }
    return {
        "status": "remote_link_failed",
        "ticket_key": ticket_key,
        "remote_link": url,
    }


def add_label(ticket_key: str, dry_run: bool = False) -> dict:
    """Add provenance and violation labels to a Jira ticket via REST API (preserving existing)."""
    required_labels = [PROVENANCE_LABEL, VIOLATION_LABEL]
    if dry_run:
        return {
            "status": "dry_run",
            "ticket_key": ticket_key,
            "labels": required_labels,
        }

    data = _jira_rest_get(f"issue/{ticket_key}", fields="labels")
    existing = data.get("fields", {}).get("labels", []) if data else []

    missing = [lbl for lbl in required_labels if lbl not in existing]
    if not missing:
        return {
            "status": "label_already_present",
            "ticket_key": ticket_key,
            "labels": required_labels,
        }

    all_labels = list(set(existing + required_labels))
    put_result = _jira_rest_put(f"issue/{ticket_key}", {"fields": {"labels": all_labels}})

    if not put_result["ok"]:
        update_result = jira_ops.update_issue(ticket_key, labels=all_labels)
        if update_result.get("error"):
            return {
                "status": "label_failed",
                "ticket_key": ticket_key,
                "error": update_result["error"],
            }

    return {
        "status": "label_added",
        "ticket_key": ticket_key,
        "labels": all_labels,
    }


def _get_existing_comments(ticket_key: str) -> list[str]:
    """Fetch existing comment bodies (as plain text) on a Jira ticket."""
    creds = _jira_auth()
    if not creds:
        return []
    _, auth = creds

    url = f"https://redhat.atlassian.net/rest/api/3/issue/{ticket_key}/comment"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    texts = []
    for comment in data.get("comments", []):
        body_text = ""
        for block in comment.get("body", {}).get("content", []):
            for item in block.get("content", []):
                body_text += item.get("text", "")
        texts.append(body_text)
    return texts


def comment_on_ticket(ticket_key: str, mr_url: str, dry_run: bool = False) -> dict:
    """Add a comment with the MR URL to a Jira ticket.

    Idempotent: checks if a comment containing this MR URL already exists.
    """
    comment_text = f"Conforma exception MR created:\n{mr_url}\n\n{build_provenance_footer()}"

    if dry_run:
        return {
            "status": "dry_run",
            "ticket_key": ticket_key,
            "comment": comment_text,
        }

    existing = _get_existing_comments(ticket_key)
    for body in existing:
        if mr_url in body:
            return {
                "status": "comment_already_exists",
                "ticket_key": ticket_key,
                "mr_url": mr_url,
            }

    result = jira_ops.add_comment(ticket_key, comment_text)
    if result.get("ok"):
        return {
            "status": "commented",
            "ticket_key": ticket_key,
        }
    return {
        "status": "failed",
        "ticket_key": ticket_key,
        "error": result.get("error", "Unknown error"),
    }


def ensure_link(from_key: str, to_key: str, link_type: str = "Related", dry_run: bool = False) -> dict:
    """Ensure a link exists between two Jira tickets, with post-creation verification.

    Semantics: from_key <link_type> to_key.
      - ensure_link("A", "B", "Blocks") → A blocks B
      - ensure_link("A", "B", "Related") → A relates to B

    Uses jira_ops.link_issues() (python-jira library) with acli fallback.
    """
    if dry_run:
        return {
            "status": "dry_run",
            "from": from_key,
            "to": to_key,
            "link_type": link_type,
        }

    if _verify_link_exists(from_key, to_key):
        return {"status": "link_exists", "from": from_key, "to": to_key, "verified": True}

    _ensure_jira_env()
    link_result = jira_ops.link_issues(from_key, to_key, link_type=link_type)
    if link_result.get("ok"):
        import time

        time.sleep(1)
        verified = _verify_link_exists(from_key, to_key)
        return {
            "status": "linked" if verified else "link_unverified",
            "from": from_key,
            "to": to_key,
            "verified": verified,
        }

    error = link_result.get("error", "")
    if "already exists" in error.lower():
        return {"status": "link_exists", "from": from_key, "to": to_key, "verified": True}

    return {
        "status": "link_failed",
        "from": from_key,
        "to": to_key,
        "error": error,
        "verified": False,
    }



def delete_link(ticket_key: str, target_key: str, link_type: str | None = None, dry_run: bool = False) -> dict:
    """Delete a link between two Jira tickets by finding its ID via REST API.

    acli link delete requires --id (numeric), not --out/--in/--type.
    This function fetches links via REST, finds the matching one, and deletes by ID.
    """
    if dry_run:
        return {"status": "dry_run", "ticket_key": ticket_key, "target_key": target_key}

    data = _jira_rest_get(f"issue/{ticket_key}", fields="issuelinks")
    if not data:
        return {"status": "failed", "error": "Cannot fetch links via REST API"}

    links = data.get("fields", {}).get("issuelinks", [])
    for link in links:
        inward = link.get("inwardIssue", {}).get("key", "")
        outward = link.get("outwardIssue", {}).get("key", "")
        lt_name = link.get("type", {}).get("name", "")
        link_id = link.get("id")

        if target_key not in (inward, outward):
            continue
        if link_type and lt_name != link_type:
            continue

        del_result = jira_ops.delete_issue_link(str(link_id))
        if del_result.get("ok"):
            return {
                "status": "deleted",
                "link_id": str(link_id),
                "from": ticket_key,
                "to": target_key,
            }
        return {"status": "failed", "error": del_result.get("error", "delete failed")}

    return {"status": "not_found", "from": ticket_key, "to": target_key}


def _derive_mr_link_title(mr_url: str, mr_title: str | None = None) -> str:
    """Build a descriptive title for the remote link.

    If mr_title is provided, use it directly.
    Otherwise, derive from the MR URL (branch name contains version info).
    """
    if mr_title:
        return mr_title
    match = re.search(r"/merge_requests/(\d+)", mr_url)
    mr_num = match.group(1) if match else ""
    return f"Conforma Exception MR !{mr_num}" if mr_num else "Conforma Exception MR"


def link_all(
    mr_url: str,
    rhoaieng_url: str | None = None,
    psx_url: str | None = None,
    link_to: str | None = None,
    related_psx: str | None = None,
    mr_title: str | None = None,
    violation_jira_url: str | None = None,
    remediation_jira_url: str | None = None,
    approval_jira_url: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Comment MR URL, add provenance label, and link tickets to each other.

    Three-ticket model links:
      violation -> remediation (Related)
      violation -> approval (Related)
      approval -> ProdSec/prodsec_ticket (Blocks)
      MR linked (remote link + comment) to all provided tickets
    """
    results = []
    remote_link_title = _derive_mr_link_title(mr_url, mr_title)

    # Backward compat: if rhoaieng_url provided but no violation_jira_url, use it
    effective_violation_url = violation_jira_url or rhoaieng_url

    all_ticket_urls = [
        u for u in (effective_violation_url, remediation_jira_url, approval_jira_url, psx_url) if u
    ]

    for url in all_ticket_urls:
        ticket_key = _extract_key(url)
        if not ticket_key:
            continue
        results.append(add_remote_link(ticket_key, mr_url, remote_link_title, dry_run))
        results.append(comment_on_ticket(ticket_key, mr_url, dry_run))
        results.append(add_label(ticket_key, dry_run))

    # --- Deterministic link type rules ---
    violation_key = _extract_key(effective_violation_url) if effective_violation_url else None
    remediation_key = _extract_key(remediation_jira_url) if remediation_jira_url else None
    approval_key = _extract_key(approval_jira_url) if approval_jira_url else None
    psx_key = _extract_key(psx_url) if psx_url else None

    # violation -> remediation (Related)
    if violation_key and remediation_key and violation_key != remediation_key:
        results.append(ensure_link(violation_key, remediation_key, link_type="Related", dry_run=dry_run))

    # violation -> approval (Related)
    if violation_key and approval_key and violation_key != approval_key:
        results.append(ensure_link(violation_key, approval_key, link_type="Related", dry_run=dry_run))

    # approval -> ProdSec/prodsec_ticket (Blocks)
    if approval_key and psx_key and approval_key != psx_key:
        results.append(ensure_link(approval_key, psx_key, link_type="Blocks", dry_run=dry_run))

    # Backward compat: violation -> psx (Blocks) when no approval ticket
    if violation_key and psx_key and not approval_key and violation_key != psx_key:
        results.append(ensure_link(violation_key, psx_key, link_type="Blocks", dry_run=dry_run))

    if link_to:
        link_to_key = _extract_key(link_to) if "/" in link_to else link_to
        for key in (violation_key, remediation_key, approval_key, psx_key):
            if key and link_to_key and key != link_to_key:
                results.append(ensure_link(key, link_to_key, link_type="Related", dry_run=dry_run))

    if related_psx:
        related_key = _extract_key(related_psx) if "/" in related_psx else related_psx
        if related_key:
            if psx_key and psx_key != related_key:
                results.append(ensure_link(psx_key, related_key, link_type="Related", dry_run=dry_run))
            if violation_key and violation_key != related_key:
                results.append(ensure_link(violation_key, related_key, link_type="Related", dry_run=dry_run))

    success_statuses = (
        "commented",
        "comment_already_exists",
        "label_added",
        "label_already_present",
        "remote_link_added",
        "remote_link_already_exists",
        "skipped_no_token",
        "linked",
        "link_exists",
        "dry_run",
    )
    warn_statuses = ("link_unverified",)
    failures = [r for r in results if r["status"] not in (*success_statuses, *warn_statuses)]
    warnings = [r for r in results if r["status"] in warn_statuses]
    return {
        "status": "completed" if not failures else "partial_failure",
        "results": results,
        "failures": failures,
        "warnings": warnings,
    }


def _extract_key(url: str) -> str | None:
    """Extract Jira ticket key from URL."""
    match = re.search(r"([A-Z]+-\d+)", url)
    return match.group(1) if match else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Link MR URL to Jira tickets and add provenance label")
    parser.add_argument("--mr-url", required=True)
    parser.add_argument("--rhoaieng-url", default=None, help="Deprecated alias for --violation-jira-url")
    parser.add_argument("--violation-jira-url", default=None, help="RHOAIENG violation report ticket URL")
    parser.add_argument("--remediation-jira-url", default=None, help="RHOAIENG remediation ticket URL")
    parser.add_argument("--approval-jira-url", default=None, help="RHOAIENG approval ticket URL")
    parser.add_argument("--prodsec-ticket-url", default=None, help="ProdSec ticket URL (from form or OCPEXCEPT)")
    parser.add_argument("--psx-url", default=None, help="Alias for --prodsec-ticket-url (backward compat)")
    parser.add_argument("--link-to", default=None, help="Tracking ticket key to link all tickets to")
    parser.add_argument(
        "--related-psx",
        default=None,
        help="Existing PSX ticket to link as Related only (not used as the exception ticket)",
    )
    parser.add_argument(
        "--mr-title",
        default=None,
        help="Descriptive title for the remote web link in Jira (e.g. 'Exception MR rhoai-2.25')",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prodsec_url = args.prodsec_ticket_url or args.psx_url
    result = link_all(
        mr_url=args.mr_url,
        rhoaieng_url=args.rhoaieng_url,
        psx_url=prodsec_url,
        link_to=args.link_to,
        related_psx=args.related_psx,
        mr_title=args.mr_title,
        violation_jira_url=args.violation_jira_url,
        remediation_jira_url=args.remediation_jira_url,
        approval_jira_url=args.approval_jira_url,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
