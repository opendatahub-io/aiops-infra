#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""
Sync pipeline_state.json from Jira labels and comment URLs.

Reads labels from component_onboarding_details.json and updates pipeline_state.json
so state can be reconstructed even after a fresh checkout. Also extracts PR/MR URLs
from Jira comments and populates pr_url/mr_url fields where empty.

Usage:
  uv run --script sync_state_from_jira.py \
    --jira-details <component_onboarding_details.json> \
    --pipeline-state <pipeline_state.json>
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Maps Jira label → (step_key, field_to_set, value_to_set)
# "raised" labels: only upgrade from "pending" → "pr_raised" or "mr_raised"
# "done" labels: always set to "done" (overrides pr_raised/mr_raised)
LABEL_MAP: dict[str, tuple[str, str]] = {
    # raised labels
    "quay-mr-raised":          ("quay",             "mr_raised"),
    "konflux-mr-raised":       ("krd",              "mr_raised"),
    "okc-pr-raised":           ("okc",              "pr_raised"),
    "rkc-pr-raised":           ("okc",              "pr_raised"),
    "rkc-pull-pr-raised":      ("pull_pipelines",   "pr_raised"),
    "operator-pr-raised":      ("operator",         "pr_raised"),
    "bundle-pr-raised":        ("bundle",           "pr_raised"),
    "delivery-repo-mr-raised": ("delivery_repo",    "mr_raised"),
    "product-listing-mr-raised": ("product_listing","mr_raised"),
    "auto-merge-pr-raised":    ("auto_merge",       "pr_raised"),
    "renovate-pr-raised":      ("renovate",         "pr_raised"),
    # done labels
    "quay-mr-merged":            ("quay",             "done"),
    "konflux-mr-merged":         ("krd",              "done"),
    "okc-pr-merged":             ("okc",              "done"),
    "rkc-pr-merged":             ("okc",              "done"),
    "rkc-pull-changes-done":     ("pull_pipelines",   "done"),
    "operator-pr-merged":        ("operator",         "done"),
    "obc-changes-done":          ("bundle",           "done"),
    "delivery-repo-created":     ("delivery_repo",    "done"),
    "delivery-repo-exists":      ("delivery_repo",    "done"),
    "product-listing-created":   ("product_listing",  "done"),
    "product-listing-exists":    ("product_listing",  "done"),
    "auto-merge-setup-done":     ("auto_merge",       "done"),
    "renovate-changes-done":     ("renovate",         "done"),
    "renovate-sync-triggered":   ("renovate_sync",    "done"),
    "onboarder-workflow-triggered": ("onboarder_workflow", "done"),
    # validate
    "yaml-attached":             ("validate",         "done"),
}

# Keywords per step to match PR/MR URLs from Jira comments
STEP_COMMENT_PATTERNS: list[tuple[str, str, str]] = [
    # (step_key, url_field, keyword_pattern_in_comment)
    ("quay",           "mr_url",  r"quay"),
    ("krd",            "mr_url",  r"konflux.release"),
    ("okc",            "pr_url",  r"(?:odh|rhoai)-konflux-central"),
    ("pull_pipelines", "pr_url",  r"rhoai-konflux-central.*pull|pull.*rhoai-konflux-central"),
    ("operator",       "pr_url",  r"opendatahub-io/opendatahub-operator"),
    ("bundle",         "pr_url",  r"ODH-Build-Config|odh-build-config"),
    ("delivery_repo",  "mr_url",  r"pyxis.repo.configs|delivery.repo"),
    ("product_listing","mr_url",  r"product.listing|pyxis.repo.configs.*product"),
    ("auto_merge",     "pr_url",  r"auto.merge"),
    ("renovate",       "pr_url",  r"renovate"),
]

# Matches any GitHub PR or GitLab MR URL
_URL_RE = re.compile(r"https://(?:github\.com/[^\s/]+/[^\s/]+/pull/\d+|gitlab[^\s]+/-/merge_requests/\d+)")


def extract_urls_from_comment(body: str) -> list[str]:
    return _URL_RE.findall(body or "")


def sync_labels(state: dict, labels: list[str]) -> list[str]:
    changes = []
    for label in labels:
        mapping = LABEL_MAP.get(label)
        if not mapping:
            continue
        step_key, new_status = mapping
        step = state.get("steps", {}).get(step_key)
        if step is None:
            continue
        current = step.get("status", "pending")
        if new_status == "done":
            if current not in ("done",):
                step["status"] = "done"
                changes.append(f"{step_key}: {current} → done (label: {label})")
        else:
            # raised label — upgrade from pending or skipped (skipped can
            # happen when the initial state was created before is_operator
            # was known, but the PR was raised in a previous run)
            if current in ("pending", "skipped"):
                step["status"] = new_status
                changes.append(f"{step_key}: {current} → {new_status} (label: {label})")
    return changes


def sync_urls_from_comments(state: dict, comments: list[dict]) -> list[str]:
    changes = []
    all_comment_bodies = [(c.get("body") or "") for c in comments]

    for step_key, url_field, keyword_pattern in STEP_COMMENT_PATTERNS:
        step = state.get("steps", {}).get(step_key)
        if step is None:
            continue
        if step.get(url_field, ""):
            continue  # already populated

        kw_re = re.compile(keyword_pattern, re.IGNORECASE)
        for body in all_comment_bodies:
            if not kw_re.search(body):
                continue
            urls = extract_urls_from_comment(body)
            if urls:
                step[url_field] = urls[0]
                changes.append(f"{step_key}.{url_field} = {urls[0]} (from comment)")
                break

    return changes


def write_state(state: dict, path: Path) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.rename(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jira-details", required=True, help="Path to component_onboarding_details.json")
    parser.add_argument("--pipeline-state", required=True, help="Path to pipeline_state.json")
    args = parser.parse_args()

    jira_path = Path(args.jira_details)
    state_path = Path(args.pipeline_state)

    if not jira_path.exists():
        print(f"ERROR: Jira details file not found: {jira_path}", file=sys.stderr)
        sys.exit(1)
    if not state_path.exists():
        print(f"ERROR: Pipeline state file not found: {state_path}", file=sys.stderr)
        sys.exit(1)

    jira = json.loads(jira_path.read_text())
    state = json.loads(state_path.read_text())

    labels: list[str] = jira.get("fields", {}).get("labels", [])
    comments_raw = jira.get("fields", {}).get("comment", {}).get("comments", [])

    all_changes: list[str] = []

    label_changes = sync_labels(state, labels)
    all_changes.extend(label_changes)

    url_changes = sync_urls_from_comments(state, comments_raw)
    all_changes.extend(url_changes)

    if all_changes:
        write_state(state, state_path)
        for change in all_changes:
            print(f"[sync] {change}", file=sys.stderr)
        print(f"[sync] {len(all_changes)} field(s) updated in pipeline_state.json", file=sys.stderr)
    else:
        print("[sync] No changes — pipeline_state.json already matches Jira labels.", file=sys.stderr)


if __name__ == "__main__":
    main()
