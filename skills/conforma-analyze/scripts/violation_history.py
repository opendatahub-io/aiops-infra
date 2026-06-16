#!/usr/bin/env python3
"""Trace when a violation type last appeared (or disappeared) in the
conforma-reporter CSV git history for a given release branch.

Uses the GitHub API to walk commits that touched the CSV file and
downloads each version via raw.githubusercontent.com to check for the
presence of a specific violation code.

Output is JSON to stdout, progress to stderr.

Usage:
    # By exact violation code:
    python3 scripts/violation_history.py \
      --release rhoai-3.5-ea.1 \
      --code prefetch_dependencies.mode_not_permissive

    # Optionally filter by component:
    python3 scripts/violation_history.py \
      --release rhoai-3.5-ea.1 \
      --code rpm_signature.allowed \
      --component odh-vllm-cpu-v3-5-ea-1

    # Stop early once the violation is found (fastest for "when last seen"):
    python3 scripts/violation_history.py \
      --release rhoai-3.5-ea.1 \
      --code prefetch_dependencies.mode_not_permissive \
      --until-found

    # Override the CSV path within the repo:
    python3 scripts/violation_history.py \
      --release rhoai-3.5-ea.1 \
      --code hermetic_task.hermetic \
      --csv-path prod/future/build_type_latest/conforma-violations-report.csv

    # Limit history depth:
    python3 scripts/violation_history.py \
      --release rhoai-3.5-ea.1 \
      --code rpm_signature.allowed \
      --max-commits 50
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

import _setup_env  # noqa: F401 -- loads .work/.env and adds scripts/ to sys.path

CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"
RAW_DOWNLOAD_BASE = "https://raw.githubusercontent.com"
GITHUB_API = "https://api.github.com"

CSV_PATHS = [
    "prod/release_day/conforma-violations-report.csv",
    "prod/future/build_type_latest/conforma-violations-report.csv",
    "prod/future/build_type_nightly/conforma-violations-report.csv",
]

_github_token_cache: str | None = None


def _get_github_token() -> str:
    global _github_token_cache
    if _github_token_cache is not None:
        return _github_token_cache

    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(var, "").strip()
        if val:
            _github_token_cache = val
            return _github_token_cache

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _github_token_cache = result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _github_token_cache = ""
    return _github_token_cache


def _gh_headers() -> dict[str, str]:
    token = _get_github_token()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _find_csv_path(ref: str) -> str | None:
    """Probe CSV_PATHS in order and return the first that exists on *ref*."""
    token = _get_github_token()
    if not token:
        return None
    for csv_path in CSV_PATHS:
        url = f"{RAW_DOWNLOAD_BASE}/{CONFORMA_REPORTER_REPO}/{ref}/{csv_path}"
        try:
            resp = requests.head(url, headers={"Authorization": f"token {token}"}, timeout=30)
            if resp.status_code == 200:
                return csv_path
        except requests.RequestException:
            continue
    return None


def _fetch_commits(ref: str, csv_path: str, max_commits: int) -> list[dict]:
    """Return commits that touched *csv_path* on *ref*, newest-first."""
    all_commits: list[dict] = []
    page = 1
    per_page = min(max_commits, 100)

    while len(all_commits) < max_commits:
        url = (
            f"{GITHUB_API}/repos/{CONFORMA_REPORTER_REPO}/commits"
            f"?sha={ref}&path={csv_path}&per_page={per_page}&page={page}"
        )
        try:
            resp = requests.get(url, headers=_gh_headers(), timeout=30)
            if resp.status_code != 200:
                break
            commits = resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            break

        if not commits:
            break

        for c in commits:
            all_commits.append(
                {
                    "sha": c["sha"],
                    "date": c["commit"]["committer"]["date"],
                    "message": c["commit"]["message"].split("\n", 1)[0][:120],
                }
            )

        if len(commits) < per_page:
            break
        page += 1

    return all_commits[:max_commits]


def _fetch_csv_content(sha: str, csv_path: str) -> str | None:
    """Download CSV content at a specific commit SHA."""
    token = _get_github_token()
    if not token:
        return None
    url = f"{RAW_DOWNLOAD_BASE}/{CONFORMA_REPORTER_REPO}/{sha}/{csv_path}"
    try:
        resp = requests.get(url, headers={"Authorization": f"token {token}"}, timeout=120)
        if resp.status_code != 200:
            return None
        content = resp.text
        return content if content.strip() else None
    except requests.RequestException:
        return None


def _check_violation_in_csv(
    content: str,
    code: str,
    component: str | None = None,
) -> dict:
    """Check if violation *code* exists in CSV content.

    Returns ``{present, count, components}``.
    """
    reader = csv.DictReader(io.StringIO(content))
    matching_components: list[str] = []

    for row in reader:
        if (row.get("type") or "").strip().lower() != "violation":
            continue
        if (row.get("code") or "").strip() != code:
            continue

        row_component = (row.get("component_name") or "").strip()
        if component and row_component != component:
            continue

        matching_components.append(row_component)

    unique = sorted(set(matching_components))
    return {"present": bool(matching_components), "count": len(matching_components), "components": unique}


def trace_history(
    release: str,
    code: str,
    component: str | None = None,
    max_commits: int = 100,
    csv_path_override: str | None = None,
    until_found: bool = False,
) -> dict:
    """Walk the git history and check each commit for *code*."""

    # 1 — resolve CSV path
    if csv_path_override:
        csv_path = csv_path_override
        print(f"Using specified CSV path: {csv_path}", file=sys.stderr)
    else:
        print(f"Probing CSV path on {release}...", file=sys.stderr)
        csv_path = _find_csv_path(release)
        if not csv_path:
            return {"error": f"No violations CSV found on branch {release}", "release": release, "code": code}
        print(f"  Resolved: {csv_path}", file=sys.stderr)

    # 2 — fetch commit list
    print(f"Fetching commit history (max {max_commits})...", file=sys.stderr)
    commits = _fetch_commits(release, csv_path, max_commits)
    if not commits:
        return {
            "error": f"No commits found for {csv_path} on {release}",
            "release": release,
            "code": code,
            "csv_path": csv_path,
        }
    print(
        f"  {len(commits)} commits  ({commits[-1]['date'][:10]} → {commits[0]['date'][:10]})",
        file=sys.stderr,
    )

    # 3 — walk each commit
    timeline: list[dict] = []
    for i, commit in enumerate(commits):
        sha_short = commit["sha"][:12]
        print(
            f"  [{i + 1}/{len(commits)}] {sha_short} {commit['date'][:10]}",
            file=sys.stderr,
            end="",
        )

        content = _fetch_csv_content(commit["sha"], csv_path)
        if content is None:
            print("  FETCH_FAILED", file=sys.stderr)
            continue

        result = _check_violation_in_csv(content, code, component)
        entry = {
            "sha": sha_short,
            "date": commit["date"],
            "present": result["present"],
            "count": result["count"],
            "components": result["components"],
        }
        timeline.append(entry)

        if result["present"]:
            print(
                f"  PRESENT  {result['count']} rows  {len(result['components'])} components",
                file=sys.stderr,
            )
            if until_found:
                print("  (--until-found: stopping early)", file=sys.stderr)
                break
        else:
            print("  absent", file=sys.stderr)

    if not timeline:
        return {"error": "Could not fetch any commit content", "release": release, "code": code, "csv_path": csv_path}

    # 4 — derive summary fields
    currently_present = timeline[0]["present"]

    last_seen = None
    disappeared_on = None
    first_seen_in_history = None

    for entry in timeline:
        if entry["present"]:
            last_seen = entry
            break

    if last_seen and not currently_present:
        for idx, entry in enumerate(timeline):
            if entry["sha"] == last_seen["sha"] and idx > 0:
                disappeared_on = timeline[idx - 1]
                break

    for entry in reversed(timeline):
        if entry["present"]:
            first_seen_in_history = entry
            break

    present_count = sum(1 for e in timeline if e["present"])

    output: dict = {
        "release": release,
        "code": code,
        "component_filter": component,
        "csv_path": csv_path,
        "total_commits_checked": len(timeline),
        "history_range": {
            "oldest": timeline[-1]["date"],
            "newest": timeline[0]["date"],
        },
        "currently_present": currently_present,
    }

    if currently_present and timeline[0]["present"]:
        output["current_status"] = {
            "count": timeline[0]["count"],
            "components": timeline[0]["components"],
        }

    if last_seen:
        output["last_seen"] = {
            "date": last_seen["date"],
            "sha": last_seen["sha"],
            "count": last_seen["count"],
            "components": last_seen["components"],
        }

    if disappeared_on:
        output["disappeared_on"] = {
            "date": disappeared_on["date"],
            "sha": disappeared_on["sha"],
        }

    if first_seen_in_history:
        output["first_seen_in_history"] = {
            "date": first_seen_in_history["date"],
            "sha": first_seen_in_history["sha"],
        }

    output["presence_summary"] = {
        "present_in": present_count,
        "absent_in": len(timeline) - present_count,
        "total": len(timeline),
    }

    if not until_found:
        output["timeline"] = timeline

    return output


def format_text(data: dict) -> str:
    """Render a human-readable summary from the JSON result."""
    if "error" in data:
        return f"ERROR: {data['error']}"

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("VIOLATION HISTORY")
    lines.append("=" * 72)
    lines.append(f"  Release:    {data['release']}")
    lines.append(f"  Code:       {data['code']}")
    if data.get("component_filter"):
        lines.append(f"  Component:  {data['component_filter']}")
    lines.append(f"  CSV path:   {data['csv_path']}")
    lines.append(f"  Commits:    {data['total_commits_checked']}")
    hr = data["history_range"]
    lines.append(f"  Range:      {hr['oldest'][:10]} → {hr['newest'][:10]}")
    lines.append("")

    if data["currently_present"]:
        cs = data.get("current_status", {})
        lines.append(
            f"  STATUS: CURRENTLY PRESENT  ({cs.get('count', '?')} rows, {len(cs.get('components', []))} components)"
        )
        if cs.get("components"):
            for comp in cs["components"]:
                lines.append(f"    - {comp}")
    else:
        lines.append("  STATUS: NOT currently present")

    lines.append("")

    ls = data.get("last_seen")
    if ls:
        lines.append(f"  Last seen:  {ls['date'][:10]}  (commit {ls['sha']})")
        lines.append(f"              {ls['count']} rows, {len(ls['components'])} components")
    else:
        lines.append("  Last seen:  NEVER in checked history")

    do = data.get("disappeared_on")
    if do:
        lines.append(f"  Disappeared: {do['date'][:10]}  (commit {do['sha']})")

    fs = data.get("first_seen_in_history")
    if fs:
        lines.append(f"  First seen: {fs['date'][:10]}  (commit {fs['sha']})")

    ps = data.get("presence_summary", {})
    lines.append("")
    lines.append(f"  Present in {ps.get('present_in', 0)}/{ps.get('total', 0)} checked commits")

    tl = data.get("timeline")
    if tl:
        lines.append("")
        lines.append("-" * 72)
        lines.append("TIMELINE (newest → oldest)")
        lines.append("-" * 72)
        for entry in tl:
            marker = "██" if entry["present"] else "··"
            count_str = f"  {entry['count']} rows" if entry["present"] else ""
            lines.append(f"  {marker}  {entry['date'][:10]}  {entry['sha']}{count_str}")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace violation history in conforma-reporter CSV")
    parser.add_argument(
        "--release",
        required=True,
        help="Release branch (e.g. rhoai-3.5-ea.1)",
    )
    parser.add_argument(
        "--code",
        required=True,
        help="Exact violation code (e.g. prefetch_dependencies.mode_not_permissive)",
    )
    parser.add_argument(
        "--component",
        default=None,
        help="Optional component name filter",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=100,
        help="Max commits to check (default: 100)",
    )
    parser.add_argument(
        "--csv-path",
        default=None,
        help="Override CSV path within the repo (default: auto-detect)",
    )
    parser.add_argument(
        "--until-found",
        action="store_true",
        help="Stop after finding the first commit where the violation is present",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args()

    data = trace_history(
        release=args.release,
        code=args.code,
        component=args.component,
        max_commits=args.max_commits,
        csv_path_override=args.csv_path,
        until_found=args.until_found,
    )

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_text(data))

    return 1 if "error" in data else 0


if __name__ == "__main__":
    sys.exit(main())
