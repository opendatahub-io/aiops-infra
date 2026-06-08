#!/usr/bin/env python3
"""Comment MR URL on Jira tickets and add provenance label.

For each Jira ticket (RHOAIENG, PSX, OCPEXCEPT):
  1. Adds a remote/web link to the GitLab MR (if JIRA_API_TOKEN is set)
  2. Adds a comment with the GitLab MR URL and provenance footer
  3. Adds the conforma-exception-create-ai-skill label

This ensures even pre-existing tickets (passed via URL) get marked.
Requires JIRA_API_TOKEN and JIRA_EMAIL env vars for remote links.
"""

from __future__ import annotations

import argparse
import getpass
import json
import platform
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

from cli_runner import run_acli

PROVENANCE_REPO = "opendatahub-io/ai-helpers"
PROVENANCE_LABEL = "conforma-exception-create-ai-skill"
VIOLATION_LABEL = "conforma-violation"


def _jira_auth() -> tuple[str, str] | None:
    """Return (email, base64-encoded auth header value) or None if not configured."""
    import base64

    from cli_runner import _resolve_env

    token = _resolve_env("JIRA_API_TOKEN") or ""
    email = _resolve_env("JIRA_EMAIL") or ""
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

    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    })
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
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="PUT")
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
        f"Created by 'conforma-exception-create' skill from {PROVENANCE_REPO}\n"
        f"User: {getpass.getuser()}@{platform.node()}"
    )


def add_remote_link(ticket_key: str, url: str, title: str, dry_run: bool = False) -> dict:
    """Add a web/remote link to a Jira ticket via REST API.

    Requires JIRA_API_TOKEN and JIRA_EMAIL environment variables.
    Falls back gracefully if not available.
    """
    if dry_run:
        return {
            "status": "dry_run",
            "ticket_key": ticket_key,
            "remote_link": url,
        }

    from cli_runner import _resolve_env

    api_token = _resolve_env("JIRA_API_TOKEN") or ""
    email = _resolve_env("JIRA_EMAIL") or ""
    if not api_token or not email:
        return {
            "status": "skipped_no_token",
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
    put_result = _jira_rest_put(
        f"issue/{ticket_key}", {"fields": {"labels": all_labels}}
    )

    if not put_result["ok"]:
        all_labels_str = ",".join(all_labels)
        result = run_acli(
            ["jira", "workitem", "edit", "--key", ticket_key,
             "--labels", all_labels_str, "--yes"],
            timeout=30,
        )
        if result.returncode != 0:
            return {
                "status": "label_failed",
                "ticket_key": ticket_key,
                "error": result.stderr.strip() or result.stdout.strip(),
            }

    return {
        "status": "label_added",
        "ticket_key": ticket_key,
        "labels": all_labels,
    }


def comment_on_ticket(ticket_key: str, mr_url: str, dry_run: bool = False) -> dict:
    """Add a comment with the MR URL to a Jira ticket."""
    comment_text = f"Conforma exception MR created:\n{mr_url}\n\n{build_provenance_footer()}"

    if dry_run:
        return {
            "status": "dry_run",
            "ticket_key": ticket_key,
            "comment": comment_text,
        }

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix="jira-comment-", delete=False)
    try:
        tmp.write(comment_text)
        tmp.close()

        result = run_acli(
            [
                "jira",
                "workitem",
                "comment",
                "create",
                "--key",
                ticket_key,
                "--body-file",
                tmp.name,
            ],
            timeout=30,
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "ticket_key": ticket_key,
                "error": result.stderr.strip() or result.stdout.strip(),
            }
        return {
            "status": "commented",
            "ticket_key": ticket_key,
        }
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def ensure_link(
    from_key: str, to_key: str, link_type: str = "Related", dry_run: bool = False
) -> dict:
    """Ensure a link exists between two Jira tickets, with post-creation verification."""
    if dry_run:
        return {
            "status": "dry_run",
            "from": from_key,
            "to": to_key,
            "link_type": link_type,
        }

    if _verify_link_exists(from_key, to_key):
        return {"status": "link_exists", "from": from_key, "to": to_key, "verified": True}

    result = run_acli(
        [
            "jira",
            "workitem",
            "link",
            "create",
            "--out",
            from_key,
            "--in",
            to_key,
            "--type",
            link_type,
            "--yes",
        ],
        timeout=30,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        if "already exists" in error.lower():
            return {"status": "link_exists", "from": from_key, "to": to_key, "verified": True}
        return {
            "status": "link_failed",
            "from": from_key,
            "to": to_key,
            "error": error,
            "verified": False,
        }

    import time
    time.sleep(1)
    verified = _verify_link_exists(from_key, to_key)
    return {
        "status": "linked" if verified else "link_unverified",
        "from": from_key,
        "to": to_key,
        "verified": verified,
    }


def delete_link(
    ticket_key: str, target_key: str, link_type: str | None = None, dry_run: bool = False
) -> dict:
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

        result = run_acli(
            ["jira", "workitem", "link", "delete", "--id", str(link_id), "--yes"],
            timeout=30,
        )
        if result.returncode == 0:
            return {
                "status": "deleted", "link_id": str(link_id),
                "from": ticket_key, "to": target_key,
            }
        return {"status": "failed", "error": result.stderr.strip() or result.stdout.strip()}

    return {"status": "not_found", "from": ticket_key, "to": target_key}


def link_all(
    mr_url: str,
    rhoaieng_url: str | None,
    psx_url: str | None,
    link_to: str | None = None,
    related_psx: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Comment MR URL, add provenance label, and link tickets to each other.

    Args:
        related_psx: An existing PSX ticket key/URL to link as "Related" only.
                     This is NOT the main exception ticket -- it's a pre-existing
                     ticket that should be cross-referenced but not used as the
                     exception's PSX ticket.
    """
    results = []

    for url in (rhoaieng_url, psx_url):
        if not url:
            continue
        ticket_key = _extract_key(url)
        if not ticket_key:
            continue
        results.append(add_remote_link(ticket_key, mr_url, "Conforma Exception MR", dry_run))
        results.append(comment_on_ticket(ticket_key, mr_url, dry_run))
        results.append(add_label(ticket_key, dry_run))

    rhoaieng_key = _extract_key(rhoaieng_url) if rhoaieng_url else None
    psx_key = _extract_key(psx_url) if psx_url else None
    if rhoaieng_key and psx_key:
        results.append(ensure_link(rhoaieng_key, psx_key, dry_run))

    if link_to:
        for key in (rhoaieng_key, psx_key):
            if key:
                results.append(ensure_link(key, link_to, dry_run))

    if related_psx:
        related_key = _extract_key(related_psx) if "/" in related_psx else related_psx
        if related_key:
            if psx_key:
                results.append(ensure_link(psx_key, related_key, dry_run))
            if rhoaieng_key:
                results.append(ensure_link(rhoaieng_key, related_key, dry_run))

    success_statuses = (
        "commented",
        "label_added",
        "label_already_present",
        "remote_link_added",
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
    parser = argparse.ArgumentParser(
        description="Link MR URL to Jira tickets and add provenance label"
    )
    parser.add_argument("--mr-url", required=True)
    parser.add_argument("--rhoaieng-url", default=None)
    parser.add_argument("--psx-url", default=None)
    parser.add_argument(
        "--link-to", default=None, help="Tracking ticket key to link all tickets to"
    )
    parser.add_argument(
        "--related-psx",
        default=None,
        help="Existing PSX ticket to link as Related only (not used as the exception ticket)",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = link_all(
        mr_url=args.mr_url,
        rhoaieng_url=args.rhoaieng_url,
        psx_url=args.psx_url,
        link_to=args.link_to,
        related_psx=args.related_psx,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
