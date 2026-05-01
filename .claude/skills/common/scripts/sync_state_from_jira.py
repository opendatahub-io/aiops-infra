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
    "renovate-sync-triggered":      ("renovate_sync",       "done"),
    "tekton-pr-raised":             ("onboarder_workflow",  "pr_raised"),
    "onboarder-workflow-triggered": ("onboarder_workflow",  "pr_raised"),
    "tekton-pr-merged":             ("onboarder_workflow",  "done"),
    # validate
    "yaml-attached":             ("validate",         "done"),
}

# ── URL extraction ────────────────────────────────────────────────────────────
#
# PR/MR URLs are the primary matching key.  Jira labels are only used to
# disambiguate when multiple steps share the same repo URL pattern.
#
#   Phase 1 – Unique URL patterns:
#             The repo name in the URL uniquely identifies the step.
#             No labels needed.
#
#   Phase 2 – Shared URL patterns + label disambiguation:
#             URL pattern matches multiple steps (same repo).  The step's
#             Jira label must also be present to claim the URL, preventing
#             one step from stealing another's URL.
#
#   Phase 3 – Unclaimed URLs:
#             For steps whose PR targets a variable repo (e.g.
#             onboarder_workflow's Tekton PR goes to the component repo).
#             Any unclaimed URL is assigned if the step's label is present.
#
# All patterns: (step_key, url_field, url_regex).
STEP_URL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("quay",           "mr_url",  re.compile(r"app-interface/-/merge_requests/", re.I)),
    ("krd",            "mr_url",  re.compile(r"konflux-release-data/-/merge_requests/", re.I)),
    ("okc",            "pr_url",  re.compile(r"(?:odh|rhoai)-konflux-central/pull/", re.I)),
    ("operator",       "pr_url",  re.compile(r"(?:opendatahub-operator|rhods-operator)/pull/", re.I)),
    ("bundle",         "pr_url",  re.compile(r"(?:ODH|RHOAI)-Build-Config/pull/", re.I)),
    ("auto_merge",     "pr_url",  re.compile(r"rhods-devops-infra/pull/", re.I)),
]

# Shared URL patterns — labels disambiguate which step gets which URL.
SHARED_URL_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("delivery_repo",      "mr_url",  re.compile(r"pyxis-repo-configs/-/merge_requests/", re.I)),
    ("product_listing",    "mr_url",  re.compile(r"pyxis-repo-configs/-/merge_requests/", re.I)),
    ("pull_pipelines",     "pr_url",  re.compile(r"konflux-central/pull/", re.I)),
    ("renovate",           "pr_url",  re.compile(r"konflux-central/pull/", re.I)),
]

# Steps whose PR targets a variable repo (no URL pattern possible).
# Labels confirm the step ran; first unclaimed URL is assigned.
UNCLAIMED_URL_STEPS: list[tuple[str, str]] = [
    ("onboarder_workflow", "pr_url"),
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


def sync_urls_from_comments(state: dict, comments: list[dict], labels: list[str]) -> list[str]:
    changes = []
    # Reverse so the most recent comment wins when multiple comments
    # mention the same step (e.g. old PR closed, new PR raised).
    all_comment_bodies = [(c.get("body") or "") for c in reversed(comments)]

    # Collect every PR/MR URL across all comments (newest first).
    all_urls: list[str] = []
    for body in all_comment_bodies:
        all_urls.extend(extract_urls_from_comment(body))
    # Deduplicate while preserving order (newest first).
    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in all_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)
    all_urls = unique_urls

    # Track which URLs have been claimed to avoid double-assignment.
    claimed_urls: set[str] = set()

    # Build label→step lookup for disambiguation.
    label_to_steps: dict[str, set] = {}
    for label, (step_key, _status) in LABEL_MAP.items():
        label_to_steps.setdefault(step_key, set()).add(label)
    label_set = set(labels)

    def _step_has_label(step_key: str) -> bool:
        return bool(label_to_steps.get(step_key, set()) & label_set)

    # Phase 1: Unique URL patterns — repo name in URL identifies the step.
    for step_key, url_field, url_re in STEP_URL_PATTERNS:
        step = state.get("steps", {}).get(step_key)
        if step is None or step.get(url_field, ""):
            continue
        for url in all_urls:
            if url in claimed_urls:
                continue
            if url_re.search(url):
                step[url_field] = url
                claimed_urls.add(url)
                changes.append(f"{step_key}.{url_field} = {url} (from comment)")
                break

    # Phase 2: Shared URL patterns — URL matches, label disambiguates.
    for step_key, url_field, url_re in SHARED_URL_PATTERNS:
        step = state.get("steps", {}).get(step_key)
        if step is None or step.get(url_field, ""):
            continue
        if not _step_has_label(step_key):
            continue
        for url in all_urls:
            if url in claimed_urls:
                continue
            if url_re.search(url):
                step[url_field] = url
                claimed_urls.add(url)
                changes.append(f"{step_key}.{url_field} = {url} (from comment)")
                break

    # Phase 3: Unclaimed URLs — for steps whose PR targets a variable repo.
    # Label confirms the step ran; first unclaimed PR/MR URL is assigned.
    for step_key, url_field in UNCLAIMED_URL_STEPS:
        step = state.get("steps", {}).get(step_key)
        if step is None or step.get(url_field, ""):
            continue
        if not _step_has_label(step_key):
            continue
        for url in all_urls:
            if url in claimed_urls:
                continue
            step[url_field] = url
            claimed_urls.add(url)
            changes.append(f"{step_key}.{url_field} = {url} (from comment, unclaimed)")
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

    url_changes = sync_urls_from_comments(state, comments_raw, labels)
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
