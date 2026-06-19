#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Generate markdown progress summaries for Jira comments from pipeline_state.json.

Usage:
  uv run --script build_progress_summary.py \
    --state <pipeline_state.json> \
    --mode full|changes-only \
    [--newly-merged <step,step,...>] \
    [--assignee <name>] \
    [--idle-days <N>]

Output (stdout): Jira wiki markup comment body ready to post.
"""

import argparse
import json
import sys
from pathlib import Path

# Ordered step definitions for display
# (step_key, label, rhoai_only, url_field)
STEPS_ODH = [
    ("validate", "Validate Jira", None),
    ("quay", "Create Quay repo", "mr_url"),
    ("krd", "Onboard to Konflux release data", "mr_url"),
    ("okc", "Add to ODH Konflux central", "pr_url"),
    ("onboarder_workflow", "Trigger ODH onboarder workflow", "pr_url"),
    ("operator", "Integrate with ODH Operator", "pr_url"),
    ("bundle", "Integrate with bundle", "pr_url"),
]

STEPS_RHOAI = [
    ("validate", "Validate Jira", None),
    ("quay", "Create Quay repo", "mr_url"),
    ("krd", "Onboard to Konflux release data", "mr_url"),
    ("okc", "Add to RHOAI Konflux central", "pr_url"),
    ("pull_pipelines", "Add pull pipelines (RHOAI Konflux)", "pr_url"),
    ("operator", "Integrate with ODH Operator", "pr_url"),
    ("bundle", "Integrate with bundle", "pr_url"),
    ("delivery_repo", "Create RHOAI delivery repo", "mr_url"),
    ("product_listing", "Update RHOAI product listing", "mr_url"),
    ("auto_merge", "Setup auto-merge", "pr_url"),
    ("renovate", "Enable Renovate", "pr_url"),
    ("renovate_sync", "Sync Renovate configs (workflow)", "run_url"),
]

# Which steps are "blocking" (i.e. have a PR/MR that must merge to progress).
# Keys present in _ODH but absent in _RHOAI (and vice versa) are product-specific.
_DEPENDENCY_ODH: dict[str, str] = {
    "krd": "onboarder_workflow (when okc also merged)",
    "okc": "onboarder_workflow (when krd also merged)",
}
_DEPENDENCY_RHOAI: dict[str, str] = {
    "delivery_repo": "product_listing",
    "renovate": "renovate_sync",
}


def _dependency_map(product_context: str) -> dict[str, str]:
    if product_context == "RHOAI":
        return _DEPENDENCY_RHOAI
    return _DEPENDENCY_ODH


def status_emoji(status: str) -> str:
    return {
        "done": "✅ done",
        "merged": "✅ merged",
        "pr_raised": "🔄 PR raised",
        "mr_raised": "🔄 MR raised",
        "pending": "⏳ pending",
        "skipped": "⏭️ skipped",
        "closed": "❌ closed",
    }.get(status, status)


def url_cell(step: dict, url_field: str | None) -> str:
    if url_field is None:
        return "—"
    url = step.get(url_field, "")
    return url if url else "—"


def _all_done(steps: dict) -> bool:
    for step in steps.values():
        s = step.get("status", "pending")
        if s == "skipped":
            continue
        if s not in ("done", "merged"):
            return False
    return True


def build_full_summary(state: dict, component_name: str, product_context: str) -> str:
    steps_def = STEPS_RHOAI if product_context == "RHOAI" else STEPS_ODH
    steps = state.get("steps", {})

    heading = "Component Onboarding - Completed" if _all_done(steps) else "Component Onboarding - Progress"
    lines = [
        f"h2. {heading}: {{{{{component_name}}}}}",
        "",
        "||#||Step||Status||PR / MR||",
    ]

    for i, (key, label, url_field) in enumerate(steps_def, 1):
        step = steps.get(key, {})
        status = step.get("status", "pending")
        if status == "skipped":
            continue
        status_str = status_emoji(status)
        url_str = url_cell(step, url_field)
        lines.append(f"|{i}|{label}|{status_str}|{url_str}|")

    lines.append("")

    dep_map = _dependency_map(product_context)
    pending_deps = []
    for dep_step, next_label in dep_map.items():
        step = steps.get(dep_step, {})
        if step.get("status") in ("pr_raised", "mr_raised"):
            pending_deps.append(f"* {{{{{dep_step}}}}} merged → triggers {{{{{next_label}}}}}")

    if pending_deps:
        lines.append("*Next steps pending merge of:*")
        lines.extend(pending_deps)
        lines.append("")

    return "\n".join(lines)


def build_changes_summary(
    state: dict,
    component_name: str,
    product_context: str,
    newly_merged: list[str],
) -> str:
    if not newly_merged:
        return ""

    steps = state.get("steps", {})
    steps_def = STEPS_RHOAI if product_context == "RHOAI" else STEPS_ODH
    label_map = {k: label for k, label, _ in steps_def}
    url_field_map = {k: uf for k, _, uf in steps_def}

    lines = [
        f"h2. Status update: {{{{{component_name}}}}}",
        "",
        "The following Pull Requests / Merge Requests changed status since the last run:",
        "",
        "||Step||PR / MR||Status||Next action||",
    ]

    for key in newly_merged:
        step = steps.get(key, {})
        label = label_map.get(key, key)
        url_field = url_field_map.get(key)
        url_str = url_cell(step, url_field)
        dep_map = _dependency_map(product_context)
        next_action = dep_map.get(key, "—")
        lines.append(f"|{label}|{url_str}|✅ merged|{next_action}|")

    lines.append("")
    return "\n".join(lines)


def build_pending_summary(
    state: dict,
    component_name: str,
    product_context: str,
    assignee: str,
) -> str:
    steps_def = STEPS_RHOAI if product_context == "RHOAI" else STEPS_ODH
    steps = state.get("steps", {})

    pending_rows = []
    for i, (key, label, url_field) in enumerate(steps_def, 1):
        step = steps.get(key, {})
        status = step.get("status", "pending")
        if status not in ("pr_raised", "mr_raised"):
            continue
        url_str = url_cell(step, url_field)
        dep_map = _dependency_map(product_context)
        next_action = dep_map.get(key, "—")
        pending_rows.append(f"|{label}|{url_str}|{next_action}|")

    if not pending_rows:
        return ""

    tag_line = f"[~accountid:{assignee}] — please review the open Pull Requests / Merge Requests.\n\n" if assignee else ""

    lines = [
        "||Step||PR / MR||Next action on merge||",
    ]
    lines.extend(pending_rows)
    lines.append("")
    return tag_line + "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--component-name", required=True)
    parser.add_argument("--product-context", required=True, choices=["ODH", "RHOAI"])
    parser.add_argument("--mode", required=True, choices=["full", "changes-only", "pending-only"])
    parser.add_argument("--newly-merged", default="", help="Comma-separated step keys")
    parser.add_argument("--assignee", default="", help="Jira assignee display name for tagging")
    parser.add_argument("--idle-days", type=int, default=0, help="Days since last status change")
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"ERROR: {state_path} not found", file=sys.stderr)
        sys.exit(1)

    state = json.loads(state_path.read_text())
    newly_merged = [k.strip() for k in args.newly_merged.split(",") if k.strip()]

    prefix = ""
    if args.idle_days >= 2 and args.assignee:
        prefix = (
            f"[~accountid:{args.assignee}] — Reminder: this onboarding has had no PR/MR merges "
            f"for {args.idle_days} day(s). Please review the open Pull Requests / Merge Requests below.\n\n"
        )

    if args.mode == "full":
        body = build_full_summary(state, args.component_name, args.product_context)
    elif args.mode == "pending-only":
        body = build_pending_summary(state, args.component_name, args.product_context, args.assignee)
        if not body:
            sys.exit(0)
        print(body)
        return
    else:
        body = build_changes_summary(state, args.component_name, args.product_context, newly_merged)
        if not body:
            # Nothing changed — print nothing; caller should suppress empty post
            sys.exit(0)

    print(prefix + body)


if __name__ == "__main__":
    main()
