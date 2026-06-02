#!/usr/bin/env python3
"""Main orchestrator for the conforma-exception skill.

Orchestrates the full exception lifecycle by reading workflow steps from
exception_templates.yaml and executing them in order:
  validate -> auth -> workflow steps (Jira tickets + MR) -> link

The workflow is determined by the --rule matching a template category.
Each category defines its own sequence of steps (Jira projects, ticket
types, assignees, MR target).

Usage:
  # List known exception types (7 most common)
  python3 scripts/create_exception.py --list-exception-types

  # List all exception types including non-common and catch-all
  python3 scripts/create_exception.py --list-exception-types --all

  # Create an exception
  python3 scripts/create_exception.py \\
    --rhoai-version rhoai-3.3 \\
    --rule hermetic_task.hermetic \\
    --components odh-mlflow-v3-3 \\
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
    """Extract the Jira ticket title from previous stage results or fetch it live."""
    for stage_key in ("psx_exception_jira", "rhoaieng_approval_jira"):
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


def _summarise_workflow(steps: list[dict]) -> str:
    """Build a human-readable workflow summary from template steps."""
    plan_parts: list[str] = []
    approval_parts: list[str] = []
    has_self_service = False

    step_labels = {
        "rhoaieng_resolution_plan_jira": "Resolution plan (team)",
        "rhoaieng_approval_jira": "Senior Management approval (RHOAIENG Jira)",
        "psx_exception_jira": None,
        "exception_merge_request": "GitLab Merge Request",
    }

    for s in steps:
        sid = s.get("step", "")
        track = s.get("track", "exception_approval")

        if sid == "psx_exception_jira":
            project = s.get("project", "PSX")
            label = f"{project} Jira"
        elif sid == "exception_merge_request" and s.get("self_service"):
            label = "GitLab Merge Request (self-service)"
            has_self_service = True
        else:
            label = step_labels.get(sid, sid)

        if track == "remediation_plan":
            plan_parts.append(label)
        else:
            approval_parts.append(label)

    parts = []
    if plan_parts:
        parts.append("Plan: " + " -> ".join(plan_parts))
    if approval_parts:
        parts.append(" -> ".join(approval_parts))
    return " | ".join(parts)


def _extract_example_links(cat: dict) -> dict:
    """Extract search URLs and example ticket links from a category."""
    find = cat.get("find_examples", {})
    examples = cat.get("example_tickets", []) or []

    import re

    jira_links: list[dict] = []
    if find.get("jira_search"):
        jira_links.append({"label": "Search Jira", "url": find["jira_search"]})
    for ex in examples:
        if ex.get("jira"):
            m = re.search(r"/browse/([A-Z]+-\d+)", ex["jira"])
            key = m.group(1) if m else ex["jira"]
            jira_links.append({"label": key, "url": ex["jira"]})

    mr_links: list[dict] = []
    if find.get("gitlab_mr_search"):
        mr_links.append({"label": "Search MRs", "url": find["gitlab_mr_search"]})
    for ex in examples:
        if ex.get("mr"):
            m = re.search(r"/merge_requests/(\d+)", ex["mr"])
            key = f"!{m.group(1)}" if m else ex["mr"]
            mr_links.append({"label": key, "url": ex["mr"]})

    return {"jira": jira_links, "gitlab_mrs": mr_links}


def list_exception_types(show_all: bool = False) -> dict:
    """List exception types as structured JSON.

    By default returns only common categories. With show_all=True,
    includes non-common and the catch-all 'other' category.
    """
    import yaml

    templates_file = SCRIPTS_DIR / "exception_templates.yaml"
    with open(templates_file) as f:
        data = yaml.safe_load(f)

    catalog_path = SCRIPTS_DIR.parent / "references" / "conforma-release-policy-rules.yaml"
    total_catalog_rules = 0
    if catalog_path.is_file():
        with open(catalog_path) as f:
            catalog = yaml.safe_load(f)
        total_catalog_rules = len(catalog.get("rules", []))

    common: list[dict] = []
    non_common: list[dict] = []
    catch_all: dict | None = None

    for cat_id, cat in data.get("categories", {}).items():
        entry = {
            "id": cat_id,
            "display_name": cat["display_name"],
            "workflow_summary": _summarise_workflow(cat.get("workflow", [])),
            "links": _extract_example_links(cat),
        }
        if cat.get("is_catch_all"):
            entry["is_catch_all"] = True
            entry["display_name"] += " (interactive — all text fields gathered from user)"
            entry["workflow_summary"] += " [configurable: PSX Jira (default) / OCPEXCEPT Jira / self-service]"
            catch_all = entry
        elif cat.get("common"):
            common.append(entry)
        else:
            non_common.append(entry)

    result: dict = {
        "common": common,
        "common_count": len(common),
        "non_common_count": len(non_common),
        "total_catalog_rules": total_catalog_rules,
        "conforma_rules_url": "https://conforma.dev/docs/policy/release_policy.html",
    }

    if show_all:
        result["non_common"] = non_common
        if catch_all:
            result["catch_all"] = catch_all

    return result


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
    parser.add_argument(
        "--list-exception-types",
        action="store_true",
        help="List known exception types as JSON and exit. Shows only the 7 most "
             "common RHOAI types by default. Combine with --all to include all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="show_all",
        help="With --list-exception-types: include non-common and catch-all categories.",
    )
    parser.add_argument("--rhoai-version", default=None)
    parser.add_argument("--rule", default=None)
    parser.add_argument("--components", default=None)
    parser.add_argument("--effective-until-date", default=None)
    parser.add_argument("--environment", default="prod", choices=["prod", "stage"])
    parser.add_argument("--rhoaieng-url", default=None)
    parser.add_argument("--psx-url", default=None)
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
    parser.add_argument("--exception-scope", default=None, help="Exception scope (overrides template)")
    parser.add_argument("--exception-risk", default=None, help="Exception risk acceptance (overrides template)")
    parser.add_argument("--exception-remediation", default=None, help="Exception remediation plan (overrides template)")
    parser.add_argument("--exception-impact", default=None, help="Exception impact if not approved (overrides template)")
    parser.add_argument("--justification", default=None,
                        help="Justification template ID (e.g., dev_preview, code_frozen)")
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

    if args.list_exception_types:
        output = list_exception_types(show_all=args.show_all)
        print(json.dumps(output, indent=2))
        return 0

    for required in ("rhoai_version", "rule", "components"):
        if not getattr(args, required):
            parser.error(f"--{required.replace('_', '-')} is required when creating exceptions")

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
    if args.effective_until_date:
        validate_args.extend(["--effective-until-date", args.effective_until_date])
    if args.rhoaieng_url:
        validate_args.extend(["--rhoaieng-url", args.rhoaieng_url])
    if args.psx_url:
        validate_args.extend(["--psx-url", args.psx_url])
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

    workflow_steps = validation["workflow_steps"]
    workflow_category = validation["workflow_category"]
    effective_until = validation["effective_until"]
    requires_approval = validation["requires_approval"]
    is_self_service = validation["is_self_service"]

    for warning in validation.get("warnings", []):
        print(f"WARNING: {warning}", file=sys.stderr)

    # --- Stage 2: Pre-flight auth ---
    auth_result = run_script("verify_auth.py", [])
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

    def _add_template_and_justification_args(script_args: list[str]) -> None:
        """Append --template and --justification to a script call."""
        if workflow_category:
            script_args.extend(["--template", workflow_category])
        if args.justification:
            script_args.extend(["--justification", args.justification])

    def _add_exception_overrides(script_args: list[str]) -> None:
        """Append --exception-* override flags if provided."""
        if args.exception_scope:
            script_args.extend(["--exception-scope", args.exception_scope])
        if args.exception_risk:
            script_args.extend(["--exception-risk", args.exception_risk])
        if args.exception_remediation:
            script_args.extend(["--exception-remediation", args.exception_remediation])
        if args.exception_impact:
            script_args.extend(["--exception-impact", args.exception_impact])

    # --- Execute workflow steps ---
    rhoaieng_url = args.rhoaieng_url
    psx_url = args.psx_url
    remediation_plan_url: str | None = None
    all_ticket_urls: list[str] = []

    for step in workflow_steps:
        step_id = step.get("step")
        project = step.get("project")

        if step_id == "rhoaieng_resolution_plan_jira":
            jira_args = [
                "--project", "RHOAIENG",
                "--purpose", "resolution_plan",
                "--rule", args.rule,
                "--components", args.components,
                "--rhoai-version", args.rhoai_version,
                "--effective-until", effective_until or "",
            ]
            if args.link_to:
                jira_args.extend(["--link-to", args.link_to])
            if args.summary_context:
                jira_args.extend(["--summary-context", args.summary_context])
            if args.vendor_tag:
                jira_args.extend(["--vendor-tag", args.vendor_tag])
            _add_template_and_justification_args(jira_args)
            _add_exception_overrides(jira_args)
            if args.dry_run:
                jira_args.append("--dry-run")

            jira_result = run_script("create_jira_ticket.py", jira_args)
            result["stages"]["rhoaieng_resolution_plan_jira"] = jira_result

            if jira_result.get("status") == "failed":
                print(json.dumps(result, indent=2))
                print(f"\nFailed to create RHOAIENG resolution plan ticket: {jira_result.get('error')}", file=sys.stderr)
                return 1

            remediation_plan_url = jira_result.get("ticket_url")
            if remediation_plan_url:
                all_ticket_urls.append(remediation_plan_url)

        elif step_id == "rhoaieng_approval_jira":
            if rhoaieng_url:
                result["stages"]["rhoaieng_approval_jira"] = {
                    "status": "provided", "ticket_url": rhoaieng_url,
                }
                all_ticket_urls.append(rhoaieng_url)
                continue

            jira_args = [
                "--project", "RHOAIENG",
                "--purpose", "approval",
                "--rule", args.rule,
                "--components", args.components,
                "--rhoai-version", args.rhoai_version,
                "--effective-until", effective_until or "",
            ]
            if remediation_plan_url:
                jira_args.extend(["--remediation-plan-url", remediation_plan_url])
            if args.psx_url:
                jira_args.extend(["--psx-url", args.psx_url])
            if args.link_to:
                jira_args.extend(["--link-to", args.link_to])
            if args.summary_context:
                jira_args.extend(["--summary-context", args.summary_context])
            if args.vendor_tag:
                jira_args.extend(["--vendor-tag", args.vendor_tag])
            default_assignee = step.get("default_assignee")
            if default_assignee:
                jira_args.extend(["--assignee", default_assignee])
            _add_template_and_justification_args(jira_args)
            _add_exception_overrides(jira_args)
            if args.dry_run:
                jira_args.append("--dry-run")

            jira_result = run_script("create_jira_ticket.py", jira_args)
            result["stages"]["rhoaieng_approval_jira"] = jira_result

            if jira_result.get("status") == "failed":
                print(json.dumps(result, indent=2))
                print(f"\nFailed to create RHOAIENG approval ticket: {jira_result.get('error')}", file=sys.stderr)
                return 1

            rhoaieng_url = jira_result.get("ticket_url")
            if rhoaieng_url:
                all_ticket_urls.append(rhoaieng_url)

            if requires_approval and not args.dry_run:
                print(
                    f"\n{'=' * 70}\n"
                    f"RHOAIENG approval ticket created: {rhoaieng_url}\n\n"
                    f"This version ({args.rhoai_version}) requires senior manager approval.\n"
                    f"Before proceeding, get approval from one of:\n"
                    f"  - Lindani Phiri\n"
                    f"  - Jay Koehler\n"
                    f"  - Sherard Griffin (or another member of Steven Huel's staff)\n\n"
                    f"A comment on the ticket confirming approval is sufficient.\n"
                    f"{'=' * 70}\n",
                    file=sys.stderr,
                )

        elif step_id == "psx_exception_jira":
            if psx_url:
                result["stages"]["psx_exception_jira"] = {
                    "status": "provided", "ticket_url": psx_url,
                }
                all_ticket_urls.append(psx_url)
                continue

            psx_project = project or "PSX"
            jira_args = [
                "--project", psx_project,
                "--rule", args.rule,
                "--components", args.components,
                "--rhoai-version", args.rhoai_version,
                "--effective-until", effective_until or "",
                "--rhoaieng-url", rhoaieng_url or "",
            ]
            if remediation_plan_url:
                jira_args.extend(["--remediation-plan-url", remediation_plan_url])
            if args.link_to:
                jira_args.extend(["--link-to", args.link_to])
            if args.summary_context:
                jira_args.extend(["--summary-context", args.summary_context])
            if args.vendor_tag:
                jira_args.extend(["--vendor-tag", args.vendor_tag])
            _add_exception_overrides(jira_args)
            if args.authorized_party:
                jira_args.extend(["--authorized-party", args.authorized_party])
            _add_template_and_justification_args(jira_args)
            if args.dry_run:
                jira_args.append("--dry-run")

            jira_result = run_script("create_jira_ticket.py", jira_args)
            result["stages"]["psx_exception_jira"] = jira_result

            if jira_result.get("status") == "failed":
                print(json.dumps(result, indent=2))
                print(f"\nFailed to create {psx_project} ticket: {jira_result.get('error')}", file=sys.stderr)
                return 1

            psx_url = jira_result.get("ticket_url")
            if psx_url:
                all_ticket_urls.append(psx_url)

        elif step_id == "exception_merge_request":
            step_self_service = step.get("self_service", False) or is_self_service
            reference_url = psx_url or rhoaieng_url or ""
            reference_title = _get_reference_title(result, reference_url)
            mr_args = [
                "--rule", args.rule,
                "--components", args.components,
                "--effective-until", effective_until or "",
                "--reference-url", reference_url,
                "--rhoai-version", args.rhoai_version,
                "--environment", args.environment,
            ]
            if reference_title:
                mr_args.extend(["--reference-title", reference_title])
            if rhoaieng_url:
                mr_args.extend(["--rhoaieng-url", rhoaieng_url])
            if remediation_plan_url:
                mr_args.extend(["--remediation-plan-url", remediation_plan_url])
            if args.spreadsheet_url:
                mr_args.extend(["--spreadsheet-url", args.spreadsheet_url])
            if args.vendor_tag:
                mr_args.extend(["--vendor-tag", args.vendor_tag])
            if step_self_service:
                mr_args.append("--self-service")
            if args.image_ref:
                mr_args.extend(["--image-ref", args.image_ref])
            _add_template_and_justification_args(mr_args)
            if args.exception_risk:
                mr_args.extend(["--exception-risk", args.exception_risk])
            if args.exception_remediation:
                mr_args.extend(["--exception-remediation", args.exception_remediation])
            if args.dry_run:
                mr_args.append("--dry-run")

            mr_result = run_script("create_gitlab_mr.py", mr_args)
            result["stages"]["exception_merge_request"] = mr_result

            if mr_result.get("status") == "failed":
                print(json.dumps(result, indent=2))
                print(f"\nFailed to create GitLab MR: {mr_result.get('error')}", file=sys.stderr)
                return 1

    # --- Link artifacts ---
    mr_url = result.get("stages", {}).get("exception_merge_request", {}).get("mr_url")
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

        link_result = run_script("link_artifacts.py", link_args)
        result["stages"]["link"] = link_result
    else:
        result["stages"]["link"] = {"status": "skipped", "reason": "dry_run or no MR URL"}

    # --- Final output ---
    result["summary"] = {
        "workflow_steps": [s.get("step") for s in workflow_steps],
        "rhoaieng_url": rhoaieng_url,
        "remediation_plan_url": remediation_plan_url,
        "psx_url": psx_url,
        "mr_url": mr_url,
        "all_ticket_urls": all_ticket_urls,
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
        for url in all_ticket_urls:
            print(f"Ticket: {url}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
