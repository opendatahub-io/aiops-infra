#!/usr/bin/env python3
"""Main orchestrator for the conforma-exception skill.

Orchestrates the full exception lifecycle:
  validate -> path detection -> auth -> Jira(s) -> approval -> MR -> link

Supports three paths:
  A: Standard (RHOAIENG + PSX + MR)
  B: FIPS (RHOAIENG + OCPEXCEPT + MR)
  C: Self-service (RHOAIENG + MR to exceptions/ file)

Usage:
  python3 scripts/create_exception.py \\
    --rhoai-version rhoai-3.3 \\
    --rule hermetic_task.hermetic \\
    --components odh-mlflow-v3-3 \\
    --justification 2 \\
    --effective-until-date 2026-10-03 \\
    --environment prod \\
    --dry-run
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent


def _get_reference_title(result: dict, reference_url: str) -> str | None:
    """Extract the Jira ticket title from previous stage results or fetch it live.

    Checks if the PSX/RHOAIENG stage already captured the summary (when we created the
    ticket ourselves). If not, fetches it from Jira using acli.
    """
    for stage_key in ("psx", "rhoaieng"):
        stage = result.get("stages", {}).get(stage_key, {})
        if stage.get("ticket_url") == reference_url and stage.get("summary"):
            return stage["summary"]

    if not reference_url:
        return None

    import re

    match = re.search(r"([A-Z]+-\d+)", reference_url)
    if not match:
        return None
    ticket_key = match.group(1)

    try:
        acli_result = subprocess.run(
            ["acli", "jira", "workitem", "view", ticket_key, "--json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if acli_result.returncode == 0:
            data = json.loads(acli_result.stdout)
            return data.get("fields", {}).get("summary") or data.get("summary")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return None


def run_script(script_name: str, args: list[str]) -> dict:
    """Run a sibling script and parse its JSON output."""
    script_path = SCRIPTS_DIR / script_name
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        timeout=600,
    )
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        output = {"raw_stdout": result.stdout, "raw_stderr": result.stderr}

    if result.returncode != 0 and "errors" not in output:
        output["_script_error"] = result.stderr.strip()
        output["_returncode"] = result.returncode
    return output


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Conforma exception create orchestrator")
    parser.add_argument("--rhoai-version", required=True)
    parser.add_argument("--rule", required=True)
    parser.add_argument("--components", required=True)
    parser.add_argument("--justification", default=None)
    parser.add_argument("--effective-until-date", default=None)
    parser.add_argument("--environment", default="prod", choices=["prod", "stage"])
    parser.add_argument("--rhoaieng-url", default=None)
    parser.add_argument("--psx-url", default=None)
    parser.add_argument("--fips", action="store_true")
    parser.add_argument("--self-service", action="store_true")
    parser.add_argument("--image-ref", default=None, help="SHA digest for weekday_restriction")
    parser.add_argument(
        "--link-to",
        default=None,
        help="Tracking ticket key to link all created tickets to (e.g. RHAISTRAT-576)",
    )
    parser.add_argument(
        "--summary-context",
        default=None,
        help="Brief description for ticket titles",
    )
    parser.add_argument("--psx-scope", default=None, help="PSX: scope/affected components")
    parser.add_argument("--psx-risk", default=None, help="PSX: risk acceptance details")
    parser.add_argument("--psx-remediation", default=None, help="PSX: remediation plan")
    parser.add_argument("--psx-impact", default=None, help="PSX: impact if not approved")
    parser.add_argument(
        "--authorized-party",
        default=None,
        help="Senior manager accepting risk (Authorized Party in PSX workflow)",
    )
    parser.add_argument(
        "--spreadsheet-url",
        default=None,
        help="Tracking spreadsheet URL (added as YAML comment in MR)",
    )
    parser.add_argument(
        "--vendor-tag",
        default=None,
        help="Vendor/distinguisher tag prepended to ticket titles (e.g. AMD, Intel, FIPS)",
    )
    parser.add_argument(
        "--related-psx",
        default=None,
        help="Existing PSX ticket to link as Related only (not used as exception ticket)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=None, help="Write result JSON to file")
    args = parser.parse_args()

    result: dict = {"stages": {}}

    # --- Stage 1: Validate inputs ---
    validate_args = [
        "--rhoai-version",
        args.rhoai_version,
        "--rule",
        args.rule,
        "--components",
        args.components,
        "--environment",
        args.environment,
    ]
    if args.justification:
        validate_args.extend(["--justification", args.justification])
    if args.effective_until_date:
        validate_args.extend(["--effective-until-date", args.effective_until_date])
    if args.rhoaieng_url:
        validate_args.extend(["--rhoaieng-url", args.rhoaieng_url])
    if args.psx_url:
        validate_args.extend(["--psx-url", args.psx_url])
    if args.fips:
        validate_args.append("--fips")
    if args.self_service:
        validate_args.append("--self-service")
    if args.dry_run:
        validate_args.append("--dry-run")

    validation = run_script("validate_inputs.py", validate_args)
    result["stages"]["validate"] = validation

    if not validation.get("valid", False):
        print(json.dumps(result, indent=2))
        print("\nValidation failed:", file=sys.stderr)
        for err in validation.get("errors", []):
            print(f"  - {err}", file=sys.stderr)
        return 1

    path = validation["path"]
    effective_until = validation["effective_until"]
    justification = validation["justification"]
    requires_approval = validation["requires_approval"]

    for warning in validation.get("warnings", []):
        print(f"WARNING: {warning}", file=sys.stderr)

    # --- Stage 2: Pre-flight auth ---
    auth_result = run_script("verify_auth.py", ["--path", path])
    result["stages"]["auth"] = auth_result

    if not auth_result.get("passed", False):
        failed_checks = [c for c in auth_result.get("checks", []) if not c.get("passed")]
        push_only = all(c["check"] == "glab_push_access" for c in failed_checks)
        if push_only and args.dry_run:
            print(
                "WARNING: No push access to upstream repo (dry-run continues).",
                file=sys.stderr,
            )
        elif push_only:
            print(
                "WARNING: No direct push access. Will attempt fork-based MR.",
                file=sys.stderr,
            )
        else:
            print(json.dumps(result, indent=2))
            print(
                "\nAuthentication check failed. See output for fix instructions.",
                file=sys.stderr,
            )
            return 1

    # --- Stage 3: RHOAIENG ticket ---
    rhoaieng_url = args.rhoaieng_url
    if not rhoaieng_url:
        rhoaieng_args = [
            "--project",
            "RHOAIENG",
            "--rule",
            args.rule,
            "--components",
            args.components,
            "--justification",
            justification,
            "--rhoai-version",
            args.rhoai_version,
            "--effective-until",
            effective_until or "",
        ]
        if args.psx_url:
            rhoaieng_args.extend(["--psx-url", args.psx_url])
        if args.link_to:
            rhoaieng_args.extend(["--link-to", args.link_to])
        if args.summary_context:
            rhoaieng_args.extend(["--summary-context", args.summary_context])
        if args.vendor_tag:
            rhoaieng_args.extend(["--vendor-tag", args.vendor_tag])
        if args.dry_run:
            rhoaieng_args.append("--dry-run")

        rhoaieng_result = run_script("create_jira_ticket.py", rhoaieng_args)
        result["stages"]["rhoaieng"] = rhoaieng_result

        if rhoaieng_result.get("status") == "failed":
            print(json.dumps(result, indent=2))
            err = rhoaieng_result.get("error")
            print(f"\nFailed to create RHOAIENG ticket: {err}", file=sys.stderr)
            return 1

        rhoaieng_url = rhoaieng_result.get("ticket_url")

        if requires_approval and not args.dry_run:
            print(
                f"\n{'=' * 70}\n"
                f"RHOAIENG ticket created: {rhoaieng_url}\n\n"
                f"This version ({args.rhoai_version}) requires senior manager approval.\n"
                f"Before proceeding, get approval from one of:\n"
                f"  - Lindani Phiri\n"
                f"  - Jay Koehler\n"
                f"  - Sherard Griffin (or another member of Steven Huel's staff)\n\n"
                f"A comment on the ticket confirming approval is sufficient.\n"
                f"{'=' * 70}\n",
                file=sys.stderr,
            )
        elif not args.dry_run:
            print(
                f"\nRHOAIENG ticket created: {rhoaieng_url}\n"
                f"Note: versions before rhoai-3.5-ea.1 do not require "
                f"senior manager approval.\n",
                file=sys.stderr,
            )
    else:
        result["stages"]["rhoaieng"] = {"status": "provided", "ticket_url": rhoaieng_url}

    # --- Stage 4: PSX/OCPEXCEPT ticket (Paths A and B only) ---
    psx_url = args.psx_url
    if path in ("A", "B") and not psx_url:
        psx_project = "OCPEXCEPT" if args.fips else "PSX"
        psx_args = [
            "--project",
            psx_project,
            "--rule",
            args.rule,
            "--components",
            args.components,
            "--justification",
            justification,
            "--rhoai-version",
            args.rhoai_version,
            "--effective-until",
            effective_until or "",
            "--rhoaieng-url",
            rhoaieng_url or "",
        ]
        if args.link_to:
            psx_args.extend(["--link-to", args.link_to])
        if args.summary_context:
            psx_args.extend(["--summary-context", args.summary_context])
        if args.vendor_tag:
            psx_args.extend(["--vendor-tag", args.vendor_tag])
        if args.psx_scope:
            psx_args.extend(["--psx-scope", args.psx_scope])
        if args.psx_risk:
            psx_args.extend(["--psx-risk", args.psx_risk])
        if args.psx_remediation:
            psx_args.extend(["--psx-remediation", args.psx_remediation])
        if args.psx_impact:
            psx_args.extend(["--psx-impact", args.psx_impact])
        if args.authorized_party:
            psx_args.extend(["--authorized-party", args.authorized_party])
        if args.dry_run:
            psx_args.append("--dry-run")

        psx_result = run_script("create_jira_ticket.py", psx_args)
        result["stages"]["psx"] = psx_result

        if psx_result.get("status") == "failed":
            print(json.dumps(result, indent=2))
            err = psx_result.get("error")
            print(f"\nFailed to create PSX/OCPEXCEPT ticket: {err}", file=sys.stderr)
            return 1

        psx_url = psx_result.get("ticket_url")
    elif path == "C":
        result["stages"]["psx"] = {"status": "skipped", "reason": "Path C (self-service)"}
    else:
        result["stages"]["psx"] = {"status": "provided", "ticket_url": psx_url}

    # --- Stage 5: GitLab MR ---
    reference_url = psx_url or rhoaieng_url or ""
    reference_title = _get_reference_title(result, reference_url)
    mr_args = [
        "--rule",
        args.rule,
        "--components",
        args.components,
        "--effective-until",
        effective_until or "",
        "--reference-url",
        reference_url,
        "--rhoai-version",
        args.rhoai_version,
        "--environment",
        args.environment,
    ]
    if reference_title:
        mr_args.extend(["--reference-title", reference_title])
    if rhoaieng_url:
        mr_args.extend(["--rhoaieng-url", rhoaieng_url])
    if args.spreadsheet_url:
        mr_args.extend(["--spreadsheet-url", args.spreadsheet_url])
    if path == "C":
        mr_args.append("--self-service")
    if args.image_ref:
        mr_args.extend(["--image-ref", args.image_ref])
    if args.dry_run:
        mr_args.append("--dry-run")

    mr_result = run_script("create_gitlab_mr.py", mr_args)
    result["stages"]["gitlab_mr"] = mr_result

    if mr_result.get("status") == "failed":
        print(json.dumps(result, indent=2))
        print(f"\nFailed to create GitLab MR: {mr_result.get('error')}", file=sys.stderr)
        return 1

    mr_url = mr_result.get("mr_url")

    # --- Stage 6: Link artifacts ---
    if mr_url and not args.dry_run:
        link_args = ["--mr-url", mr_url]
        if rhoaieng_url:
            link_args.extend(["--rhoaieng-url", rhoaieng_url])
        if psx_url:
            link_args.extend(["--psx-url", psx_url])
        if args.link_to:
            link_args.extend(["--link-to", args.link_to])
        if args.related_psx:
            link_args.extend(["--related-psx", args.related_psx])
        if args.dry_run:
            link_args.append("--dry-run")

        link_result = run_script("link_artifacts.py", link_args)
        result["stages"]["link"] = link_result
    else:
        result["stages"]["link"] = {"status": "skipped", "reason": "dry_run or no MR URL"}

    # --- Final output ---
    result["summary"] = {
        "path": path,
        "rhoaieng_url": rhoaieng_url,
        "psx_url": psx_url,
        "mr_url": mr_url,
        "dry_run": args.dry_run,
    }

    output_json = json.dumps(result, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)

    if not args.dry_run and mr_url:
        print(f"\nDone. MR: {mr_url}", file=sys.stderr)
        if rhoaieng_url:
            print(f"RHOAIENG: {rhoaieng_url}", file=sys.stderr)
        if psx_url:
            print(f"PSX/OCPEXCEPT: {psx_url}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
