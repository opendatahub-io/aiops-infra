#!/usr/bin/env python3
"""Consolidate multiple per-version GitLab Merge Requests into a single Merge Request.

When exception Merge Requests were created one-per-version (violating the
``one_mr_per_rule_all_versions`` hard rule), this script:

  1. Discovers all open Merge Requests for a given PSX/OCPEXCEPT ticket
  2. Extracts version-specs (version, components, effectiveUntil) from each MR diff
  3. Creates a single consolidated Merge Request covering all versions
  4. Closes the old per-version Merge Requests with a comment pointing to the new one
  5. Updates the Jira ticket: replaces old remote links with the consolidated MR,
     adds a summary comment

All operations are idempotent and deterministic from the provided parameters.
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import gitlab_ops
import jira_ops

GITLAB_HOST = os.environ.get("GITLAB_HOST", "")
GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")
GITLAB_PROJECT_ENCODED = urllib.parse.quote(GITLAB_PROJECT, safe="")


def _fetch_jira_title(ticket_key: str) -> str | None:
    """Fetch the current summary/title of a Jira ticket via acli."""
    import subprocess

    try:
        result = subprocess.run(
            ["acli", "jira", "workitem", "view", ticket_key],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Summary:"):
                    return line.split(":", 1)[1].strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_gitlab_token() -> str:
    """Retrieve GitLab token via shared gitlab_ops."""
    token = gitlab_ops.discover_token(GITLAB_HOST)
    if token:
        return token
    token = os.environ.get("GITLAB_TOKEN", "")
    if token:
        return token
    raise RuntimeError("Cannot resolve GitLab token for " + GITLAB_HOST)


def _gitlab_api_get(path: str, token: str) -> dict | list:
    """GET from GitLab API using python-gitlab's HTTP layer."""
    gl = gitlab_ops.get_client(instance_url=GITLAB_HOST, token=token)
    return gl.http_get(f"/api/v4/{path}")


def _gitlab_api_post(path: str, payload: dict, token: str) -> dict:
    """POST to GitLab API using python-gitlab's HTTP layer."""
    gl = gitlab_ops.get_client(instance_url=GITLAB_HOST, token=token)
    return gl.http_post(f"/api/v4/{path}", post_data=payload)


def _gitlab_api_put(path: str, payload: dict, token: str) -> dict:
    """PUT to GitLab API using python-gitlab's HTTP layer."""
    gl = gitlab_ops.get_client(instance_url=GITLAB_HOST, token=token)
    return gl.http_put(f"/api/v4/{path}", post_data=payload)


# ---------------------------------------------------------------------------
# Step 1: Discover open Merge Requests for a PSX ticket
# ---------------------------------------------------------------------------


def find_open_mrs(psx_key: str, token: str) -> list[dict]:
    """Find all open Merge Requests in konflux-release-data referencing the PSX ticket."""
    path = f"projects/{GITLAB_PROJECT_ENCODED}/merge_requests?state=opened&search={psx_key}&in=title,description"
    mrs = _gitlab_api_get(path, token)
    matched = []
    for mr in mrs:
        body = (mr.get("title", "") + " " + mr.get("description", "")).lower()
        if psx_key.lower() in body:
            matched.append(mr)
    return matched


# ---------------------------------------------------------------------------
# Step 2: Extract version-specs from MR diffs
# ---------------------------------------------------------------------------


def extract_version_specs_from_mr(mr_iid: int, token: str) -> dict | None:
    """Parse the diff of a single MR to extract version, components, and effectiveUntil.

    Returns {"version": ..., "components": [...], "effective_until": ...}
    or None if parsing fails.
    """
    path = f"projects/{GITLAB_PROJECT_ENCODED}/merge_requests/{mr_iid}/changes"
    data = _gitlab_api_get(path, token)

    added_text = ""
    for change in data.get("changes", []):
        for line in change.get("diff", "").split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                added_text += line[1:] + "\n"

    version_match = re.search(r"# impacted versions:\s*(\S+)", added_text)
    version = version_match.group(1).strip() if version_match else None

    components: list[str] = []
    in_components = False
    for line in added_text.split("\n"):
        stripped = line.strip()
        if "componentNames:" in stripped:
            in_components = True
            continue
        if in_components:
            if stripped.startswith("- ") and not stripped.startswith("- value:"):
                comp = stripped.lstrip("- ").strip()
                if comp:
                    components.append(comp)
            else:
                in_components = False

    eu_match = re.search(r'effectiveUntil:\s*"([^"]+)"', added_text)
    effective_until = eu_match.group(1) if eu_match else None

    if not version or not components or not effective_until:
        return None

    return {
        "version": version,
        "components": components,
        "effective_until": effective_until,
    }


# ---------------------------------------------------------------------------
# Step 3: Close old Merge Requests
# ---------------------------------------------------------------------------


def close_mr_with_comment(mr_iid: int, consolidated_mr_iid: int, token: str) -> dict:
    """Close an MR with a comment pointing to the consolidated one."""
    comment = (
        f"Closing in favor of consolidated MR !{consolidated_mr_iid} "
        f"which covers all RHOAI versions in a single merge request."
    )
    _gitlab_api_post(
        f"projects/{GITLAB_PROJECT_ENCODED}/merge_requests/{mr_iid}/notes",
        {"body": comment},
        token,
    )
    result = _gitlab_api_put(
        f"projects/{GITLAB_PROJECT_ENCODED}/merge_requests/{mr_iid}",
        {"state_event": "close"},
        token,
    )
    return {"iid": mr_iid, "state": result.get("state", "unknown")}


# ---------------------------------------------------------------------------
# Step 4: Update Jira (remote links + comment)
# ---------------------------------------------------------------------------


def _comment_via_acli(ticket_key: str, comment_text: str) -> dict:
    """Add a comment via acli (works for restricted projects where REST API fails)."""
    import subprocess
    import tempfile

    work_dir = Path(__file__).resolve().parent.parent / ".work"
    work_dir.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="consolidate-comment-",
        delete=False,
        dir=work_dir,
    )
    try:
        tmp.write(comment_text)
        tmp.close()
        result = subprocess.run(
            ["acli", "jira", "workitem", "comment", "create", "--key", ticket_key, "--body-file", tmp.name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {
                "status": "comment_failed",
                "ticket_key": ticket_key,
                "error": result.stderr.strip() or result.stdout.strip(),
            }
        return {"status": "commented", "ticket_key": ticket_key}
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _check_jira_rest_api() -> dict:
    """Pre-check whether the JIRA_API_TOKEN is configured and valid.

    Returns {"available": bool, "detail": str}.
    """
    token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")
    if not token or not email:
        return {
            "available": False,
            "detail": (
                "JIRA_API_TOKEN or JIRA_EMAIL is not configured. "
                "Add them to .work/.env. Generate a token at: "
                "https://id.atlassian.com/manage-profile/security/api-tokens"
            ),
        }
    result = jira_ops.verify_auth()
    if result["ok"]:
        return {"available": True, "detail": "JIRA_API_TOKEN validated"}
    return {
        "available": False,
        "detail": (
            f"JIRA_API_TOKEN is invalid: {result['error']}. "
            f"Remote link operations will be skipped. "
            f"Generate a new token at: "
            f"https://id.atlassian.com/manage-profile/security/api-tokens"
        ),
    }


def update_jira_links(
    ticket_key: str,
    old_mr_urls: list[str],
    consolidated_mr_url: str,
    consolidated_mr_title: str,
    version_specs: list[dict] | None = None,
    dry_run: bool = False,
) -> dict:
    """Replace old per-version remote links with the consolidated one, add comment.

    If version_specs is provided, sets the PSX due date to the furthest
    effectiveUntil date across all versions.

    Operation capabilities by auth mechanism:
      - REST API (JIRA_API_TOKEN): remote links (add/delete/list), labels, due date
      - acli CLI (acli token):     comments, issue links, view, edit, watchers, due date (fallback)

    These are independent — the script tests REST API availability first and
    reports clearly if the token is missing or invalid instead of silently
    degrading.
    """
    from link_artifacts import (
        _get_existing_remote_links,
        add_remote_link,
        comment_on_ticket,
        compute_furthest_due_date,
        delete_remote_link,
        set_due_date,
    )

    results: list[dict] = []

    rest_api = _check_jira_rest_api()
    if not rest_api["available"]:
        results.append(
            {
                "status": "rest_api_unavailable",
                "detail": rest_api["detail"],
                "skipped_operations": ["delete_old_remote_links", "add_consolidated_remote_link"],
                "manual_action_required": (
                    f"Remove old MR web links and add the consolidated MR link "
                    f"manually in Jira UI: https://redhat.atlassian.net/browse/{ticket_key}"
                ),
                "old_mr_urls": old_mr_urls,
                "consolidated_mr_url": consolidated_mr_url,
            }
        )
    else:
        existing_links = _get_existing_remote_links(ticket_key)
        for link in existing_links:
            link_url = link.get("object", {}).get("url", "")
            link_id = str(link.get("id", ""))
            if link_url in old_mr_urls and link_id:
                results.append(delete_remote_link(ticket_key, link_id, dry_run))

        results.append(add_remote_link(ticket_key, consolidated_mr_url, consolidated_mr_title, dry_run))

    old_mr_iids = []
    for url in old_mr_urls:
        m = re.search(r"merge_requests/(\d+)", url)
        if m:
            old_mr_iids.append(f"!{m.group(1)}")

    from link_artifacts import build_provenance_footer

    comment_text = (
        f"Consolidated {len(old_mr_urls)} per-version Merge Requests into one:\n\n"
        f"Consolidated MR: {consolidated_mr_url}\n\n"
        f"Closed (superseded): {', '.join(old_mr_iids)}\n\n"
        f"{build_provenance_footer()}"
    )

    comment_result = comment_on_ticket(ticket_key, consolidated_mr_url, dry_run)
    if comment_result.get("status") == "failed":
        comment_result = _comment_via_acli(ticket_key, comment_text)
    results.append(comment_result)

    if version_specs:
        furthest = compute_furthest_due_date(version_specs)
        if furthest:
            results.append(set_due_date(ticket_key, furthest, dry_run))

    failures = [r for r in results if r.get("status", "").endswith("failed")]
    warnings = [r for r in results if r.get("status") in ("rest_api_unavailable",)]
    return {
        "status": "completed" if not failures else "partial_failure",
        "results": results,
        "failures": failures,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def consolidate(
    psx_url: str,
    rule: str,
    environment: str,
    rhoaieng_url: str | None = None,
    vendor_tag: str | None = None,
    spreadsheet_url: str | None = None,
    template: str | None = None,
    consolidated_mr_url: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Consolidate per-version Merge Requests into one.

    If ``consolidated_mr_url`` is provided, skip Merge Request creation (already exists)
    and only close old Merge Requests + update Jira.
    """
    psx_key_match = re.search(r"([A-Z]+-\d+)", psx_url)
    if not psx_key_match:
        return {"status": "failed", "error": f"Cannot extract ticket key from: {psx_url}"}
    psx_key = psx_key_match.group(1)

    token = _get_gitlab_token()

    # Step 1: Find open Merge Requests
    open_mrs = find_open_mrs(psx_key, token)
    if not open_mrs:
        return {"status": "failed", "error": f"No open Merge Requests found referencing {psx_key}"}

    if len(open_mrs) < 2 and not consolidated_mr_url:
        return {
            "status": "skipped",
            "detail": f"Only {len(open_mrs)} open MR(s) found — nothing to consolidate",
            "mrs": [{"iid": m["iid"], "title": m["title"]} for m in open_mrs],
        }

    # Step 2: Extract version-specs from each MR
    version_specs: list[dict] = []
    old_mr_urls: list[str] = []
    old_mr_iids: list[int] = []

    for mr in open_mrs:
        if consolidated_mr_url and mr["web_url"] == consolidated_mr_url:
            continue
        spec = extract_version_specs_from_mr(mr["iid"], token)
        if not spec:
            return {
                "status": "failed",
                "error": f"Cannot parse version-specs from MR !{mr['iid']}: {mr['title']}",
            }
        version_specs.append(spec)
        old_mr_urls.append(mr["web_url"])
        old_mr_iids.append(mr["iid"])

    if not version_specs:
        return {"status": "skipped", "detail": "No per-version Merge Requests to consolidate"}

    version_specs.sort(key=lambda s: s["version"])

    # Step 2b: Validate effectiveUntil dates against release_dates.yaml (expects EOS + 7d buffer)
    from preflight_check import validate_effective_until_date

    date_corrections: list[dict] = []
    for spec in version_specs:
        ver = spec["version"]
        eu = spec.get("effective_until", "")
        if not eu:
            continue
        check = validate_effective_until_date(ver, eu)
        if not check["valid"] and check["expected"]:
            date_corrections.append(
                {
                    "version": ver,
                    "was": check["provided"],
                    "corrected_to": check["expected"],
                    "detail": check["detail"],
                }
            )
            spec["effective_until"] = f"{check['expected']}T00:00:00Z"
        spec.setdefault("effective_until_source", "eos")

    # Step 3: Create consolidated MR (unless already provided)
    if not consolidated_mr_url:
        import subprocess

        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "create_gitlab_mr.py"),
            "--rule",
            rule,
            "--reference-url",
            psx_url,
            "--environment",
            environment,
            "--version-specs-json",
            json.dumps(version_specs),
        ]
        if rhoaieng_url:
            cmd.extend(["--rhoaieng-url", rhoaieng_url])
        if vendor_tag:
            cmd.extend(["--vendor-tag", vendor_tag])
        if spreadsheet_url:
            cmd.extend(["--spreadsheet-url", spreadsheet_url])
        if template:
            cmd.extend(["--template", template])

        psx_title = _fetch_jira_title(psx_key) or f"[Exception Approval] {rule}"
        cmd.extend(["--reference-title", psx_title])

        if dry_run:
            cmd.append("--dry-run")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=Path(__file__).resolve().parent,
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "error": f"create_gitlab_mr.py failed: {result.stderr.strip() or result.stdout.strip()}",
            }

        mr_result = json.loads(result.stdout)
        consolidated_mr_url = mr_result.get("mr_url")
        if not consolidated_mr_url and not dry_run:
            return {"status": "failed", "error": "No MR URL in create_gitlab_mr.py output", "detail": mr_result}
    else:
        mr_result = {"status": "provided", "mr_url": consolidated_mr_url}

    consolidated_iid_match = re.search(r"merge_requests/(\d+)", consolidated_mr_url or "")
    consolidated_iid = int(consolidated_iid_match.group(1)) if consolidated_iid_match else 0

    if consolidated_iid and (date_corrections or mr_result.get("status") == "provided"):
        from create_gitlab_mr import (
            _build_mr_title_consolidated,
            _build_mr_body_consolidated,
            get_target_file,
            detect_component_type,
        )

        all_comps = [c for s in version_specs for c in s["components"]]
        comp_type = detect_component_type(all_comps)
        target_file = get_target_file(comp_type, environment, False)
        new_title = _build_mr_title_consolidated(rule, version_specs, environment, vendor_tag)
        new_body = _build_mr_body_consolidated(
            rule=rule,
            version_specs=version_specs,
            rhoaieng_url=rhoaieng_url,
            reference_url=psx_url,
            spreadsheet_url=spreadsheet_url,
            target_file=target_file,
        )
        gitlab_ops.update_mr(GITLAB_PROJECT, consolidated_iid, title=new_title, description=new_body)

    if dry_run:
        dry_out: dict = {
            "status": "dry_run",
            "consolidated_mr": mr_result,
            "would_close": [{"iid": iid, "url": url} for iid, url in zip(old_mr_iids, old_mr_urls)],
            "version_specs": version_specs,
            "psx_key": psx_key,
        }
        if date_corrections:
            dry_out["date_corrections"] = date_corrections
        return dry_out

    # Step 4: Close old Merge Requests
    close_results = []
    for iid in old_mr_iids:
        close_results.append(close_mr_with_comment(iid, consolidated_iid, token))

    # Step 5: Update Jira links
    versions_str = ", ".join(s["version"] for s in version_specs)
    mr_title = f"Consolidated exception MR: {rule} ({versions_str})"
    if vendor_tag:
        mr_title = f"[{vendor_tag}] {mr_title}"

    jira_result = update_jira_links(
        ticket_key=psx_key,
        old_mr_urls=old_mr_urls,
        consolidated_mr_url=consolidated_mr_url,
        consolidated_mr_title=mr_title,
        version_specs=version_specs,
    )

    # Step 6: Post-creation verification
    verification: dict | None = None
    if consolidated_iid:
        try:
            from create_gitlab_mr import verify_mr_dates

            verification = verify_mr_dates(consolidated_iid)
        except Exception as exc:
            verification = {"valid": False, "errors": [{"detail": str(exc)}], "checked": 0}

    result_out: dict = {
        "status": "completed",
        "consolidated_mr_url": consolidated_mr_url,
        "consolidated_mr": mr_result,
        "closed_mrs": close_results,
        "jira_update": jira_result,
        "version_specs": version_specs,
        "psx_key": psx_key,
    }
    if date_corrections:
        result_out["date_corrections"] = date_corrections
    if verification:
        result_out["date_verification"] = verification
        if not verification.get("valid"):
            result_out["status"] = "completed_with_warnings"
    return result_out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consolidate per-version exception Merge Requests into a single Merge Request")
    parser.add_argument(
        "--psx-url",
        required=True,
        help="PSX/OCPEXCEPT Jira ticket URL (e.g. https://redhat.atlassian.net/browse/PSX-1097)",
    )
    parser.add_argument(
        "--rule",
        required=True,
        help="Conforma rule (e.g. rpm_signature.allowed:9386b48a1a693c5c)",
    )
    parser.add_argument("--rhoaieng-url", default=None, help="RHOAIENG Jira ticket URL")
    parser.add_argument("--environment", required=True, choices=["prod", "stage"])
    parser.add_argument("--vendor-tag", default=None, help="Vendor tag (e.g. AMD, Intel)")
    parser.add_argument("--spreadsheet-url", default=None, help="Tracking spreadsheet URL")
    parser.add_argument("--template", default=None, help="Template category ID")
    parser.add_argument(
        "--consolidated-mr-url",
        default=None,
        help="Skip MR creation; use this existing consolidated MR URL instead",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = consolidate(
        psx_url=args.psx_url,
        rule=args.rule,
        rhoaieng_url=args.rhoaieng_url,
        environment=args.environment,
        vendor_tag=args.vendor_tag,
        spreadsheet_url=args.spreadsheet_url,
        template=args.template,
        consolidated_mr_url=args.consolidated_mr_url,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in ("completed", "dry_run", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
