#!/usr/bin/env python3
"""Check the health of conforma infrastructure tools.

Queries the GitHub Actions API for workflow run status of conforma tooling
(starting with conforma-reporter), classifies health, and matches failure
logs against known failure modes from the tooling-health-catalog.yaml.

Usage:
    python3 check_tooling_health.py --release rhoai-3.5-ea.1 --output health.json
    python3 check_tooling_health.py --release rhoai-3.5-ea.1  # stdout

Exit code is always 0 -- all states are encoded in the JSON output.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _setup_env  # noqa: F401, E402

import requests  # noqa: E402
import yaml  # noqa: E402

import github_ops  # noqa: E402

GITHUB_API = "https://api.github.com"
CATALOG_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "references"
    / "tooling-health-catalog.yaml"
)


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------


def load_catalog(catalog_path: Path | None = None) -> dict:
    """Load the tooling-health-catalog.yaml."""
    path = catalog_path or CATALOG_PATH
    if not path.exists():
        return {"tools": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"tools": []}


def _get_tool_config(catalog: dict, tool_id: str) -> dict | None:
    """Get tool configuration from the catalog."""
    for tool in catalog.get("tools", []):
        if tool.get("id") == tool_id:
            return tool
    return None


# ---------------------------------------------------------------------------
# GitHub Actions API
# ---------------------------------------------------------------------------


def _fetch_workflow_runs(
    repo: str,
    workflow_file: str,
    release: str,
    max_runs: int,
    token: str,
    environment: str,
) -> dict:
    """Fetch recent workflow runs from GitHub Actions API, filtered by release and environment.

    The conforma-reporter workflow runs on ``main`` via workflow_dispatch and
    encodes the target release and environment in the run's ``display_title`` (e.g.
    ``"Conforma Reporter (target env: prod): rhoai-3.5-ea.2 (nightly)"``).
    We fetch a larger page of runs without a branch filter and then filter
    client-side to those whose display_title contains both the release name
    and the target environment.

    Returns dict with either 'runs' key (list) or 'error' key (str).
    """
    url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{workflow_file}/runs"
    fetch_size = max(max_runs * 5, 30)
    params = {"per_page": fetch_size}
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        return {"error": f"GitHub API request failed: {exc}"}

    if resp.status_code == 404:
        return {"error": f"Workflow not found (HTTP 404): {repo}/{workflow_file}"}
    if resp.status_code == 401:
        return {"error": "GitHub authentication failed (HTTP 401). Check GITHUB_TOKEN."}
    if resp.status_code == 403:
        text = resp.text[:200]
        if "rate limit" in text.lower():
            return {"error": f"GitHub API rate limit exceeded: {text}"}
        return {"error": f"GitHub API access denied (HTTP 403): {text}"}
    if resp.status_code != 200:
        return {"error": f"GitHub API error (HTTP {resp.status_code}): {resp.text[:300]}"}

    try:
        data = resp.json()
    except (ValueError, KeyError) as exc:
        return {"error": f"Failed to parse GitHub API response: {exc}"}

    all_runs = data.get("workflow_runs", [])
    env_marker = f"target env: {environment}"
    matched = [
        r for r in all_runs
        if release in (r.get("display_title") or "")
        and env_marker in (r.get("display_title") or "")
    ]

    return {"runs": matched[:max_runs]}


def _parse_run(run: dict) -> dict:
    """Extract relevant fields from a workflow run object."""
    return {
        "id": run.get("id"),
        "status": run.get("status", ""),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at", ""),
        "updated_at": run.get("updated_at", ""),
        "url": run.get("html_url", ""),
        "head_sha": run.get("head_sha", "")[:12],
        "run_attempt": run.get("run_attempt", 1),
    }


# ---------------------------------------------------------------------------
# Health classification
# ---------------------------------------------------------------------------

HEALTH_PRIORITY = {
    "error": 0,
    "unhealthy": 1,
    "in_progress": 2,
    "no_runs": 3,
    "healthy": 4,
}


def _classify_health(runs: list[dict]) -> dict:
    """Classify health status from a list of parsed runs.

    Returns a health dict with status, reason, consecutive_failures, last_success.
    """
    if not runs:
        return {
            "status": "no_runs",
            "reason": "No workflow runs found for this branch",
            "consecutive_failures": 0,
            "last_success": None,
        }

    latest = runs[0]

    if latest["status"] != "completed":
        return {
            "status": "in_progress",
            "reason": f"Run #{latest['id']} is {latest['status']} (started {latest['created_at'][:10]})",
            "consecutive_failures": 0,
            "last_success": _find_last_success(runs[1:]),
            "in_progress_run": {
                "id": latest["id"],
                "status": latest["status"],
                "created_at": latest["created_at"],
                "url": latest["url"],
            },
        }

    if latest["conclusion"] == "success":
        return {
            "status": "healthy",
            "reason": f"Latest run #{latest['id']} succeeded ({latest['updated_at'][:10]})",
            "consecutive_failures": 0,
            "last_success": {
                "id": latest["id"],
                "completed_at": latest["updated_at"],
                "url": latest["url"],
            },
        }

    consecutive = _count_consecutive_failures(runs)
    last_success = _find_last_success(runs)

    reason = f"Latest run failed ({latest['updated_at'][:10]})"
    if latest["conclusion"] == "cancelled":
        reason = f"Latest run was cancelled ({latest['updated_at'][:10]})"

    return {
        "status": "unhealthy",
        "reason": reason,
        "consecutive_failures": consecutive,
        "last_success": last_success,
    }


def _count_consecutive_failures(runs: list[dict]) -> int:
    """Count consecutive non-success completed runs from the start."""
    count = 0
    for run in runs:
        if run["status"] != "completed":
            continue
        if run["conclusion"] == "success":
            break
        count += 1
    return count


def _find_last_success(runs: list[dict]) -> dict | None:
    """Find the most recent successful run in the list."""
    for run in runs:
        if run["status"] == "completed" and run["conclusion"] == "success":
            return {
                "id": run["id"],
                "completed_at": run["updated_at"],
                "url": run["url"],
            }
    return None


# ---------------------------------------------------------------------------
# Symptom matching
# ---------------------------------------------------------------------------


def classify_failure(log_text: str, tool_config: dict) -> dict | None:
    """Match log text against known failure mode symptoms.

    Returns the matching failure_mode dict or None (falls back to unknown_failure).
    """
    failure_modes = tool_config.get("failure_modes", [])
    unknown = None

    for mode in failure_modes:
        if mode.get("id") == "unknown_failure":
            unknown = mode
            continue
        symptoms = mode.get("symptoms", [])
        if not symptoms:
            continue
        for symptom in symptoms:
            if symptom.lower() in log_text.lower():
                return mode

    return unknown


# ---------------------------------------------------------------------------
# Main check logic
# ---------------------------------------------------------------------------


def check_tool_health(
    tool_id: str,
    repo: str,
    workflow_file: str,
    release: str,
    max_runs: int,
    token: str,
    catalog: dict,
    environment: str,
) -> dict:
    """Check health for a single tool. Returns a tool status dict."""
    tool_config = _get_tool_config(catalog, tool_id) or {}
    workflow_url = f"https://github.com/{repo}/actions/workflows/{workflow_file}"

    result = _fetch_workflow_runs(repo, workflow_file, release, max_runs, token, environment=environment)

    if "error" in result:
        failure_info = classify_failure(result["error"], tool_config)
        return {
            "name": tool_id,
            "type": "github_actions_workflow",
            "workflow_url": workflow_url,
            "total_runs_checked": 0,
            "latest_run": None,
            "recent_runs": [],
            "health": {
                "status": "error",
                "reason": result["error"],
                "consecutive_failures": 0,
                "last_success": None,
            },
            "failure_classification": failure_info,
        }

    raw_runs = result["runs"]
    parsed_runs = [_parse_run(r) for r in raw_runs]
    health = _classify_health(parsed_runs)

    tool_result = {
        "name": tool_id,
        "type": "github_actions_workflow",
        "workflow_url": workflow_url,
        "total_runs_checked": len(parsed_runs),
        "latest_run": parsed_runs[0] if parsed_runs else None,
        "recent_runs": parsed_runs,
        "health": health,
    }

    if health["status"] == "unhealthy":
        tool_result["failure_classification"] = classify_failure(
            health.get("reason", ""), tool_config
        )

    return tool_result


def check_all_tools(release: str, environment: str, max_runs: int = 5, catalog_path: Path | None = None) -> dict:
    """Check health for all tools defined in the catalog.

    Returns the full tooling-health JSON structure.
    """
    token = github_ops.get_token()
    if not token:
        return {
            "release": release,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": [],
            "overall_health": "error",
            "error": "No GitHub token found (set GITHUB_TOKEN in .work/.env)",
        }

    catalog = load_catalog(catalog_path)
    tools_results = []

    for tool_def in catalog.get("tools", []):
        tool_result = check_tool_health(
            tool_id=tool_def["id"],
            repo=tool_def["repo"],
            workflow_file=tool_def["workflow_file"],
            release=release,
            max_runs=max_runs,
            token=token,
            catalog=catalog,
            environment=environment,
        )
        tools_results.append(tool_result)

    overall = _compute_overall_health(tools_results)

    result: dict = {
        "release": release,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tools": tools_results,
        "overall_health": overall,
    }

    if overall in ("unhealthy", "error"):
        unhealthy = [t for t in tools_results if t.get("health", {}).get("status") in ("unhealthy", "error")]
        parts = []
        for t in unhealthy:
            health = t.get("health", {})
            n = health.get("consecutive_failures", 0)
            ls = health.get("last_success") or {}
            ls_date = ls.get("completed_at", "")[:10] if ls else "unknown"
            ls_url = ls.get("url", "")
            ls_info = f"last success {ls_date} ({ls_url})" if ls_url else f"last success {ls_date}"
            parts.append(f"{t['name']}: {n} consecutive failure(s), {ls_info}")
        result["question_text"] = (
            f"Conforma reporter is UNHEALTHY for {release}: {'; '.join(parts)}. "
            "The violation report may be stale or incomplete. Proceed with analysis anyway?"
        )
        result["question_options"] = ["Yes, continue", "No, stop here"]
    elif overall == "in_progress":
        in_progress = [t for t in tools_results if t.get("health", {}).get("status") == "in_progress"]
        parts = []
        for t in in_progress:
            latest = t.get("latest_run", {})
            run_id = latest.get("id", "unknown")
            started = latest.get("created_at", "")[:16].replace("T", " ") if latest.get("created_at") else "unknown"
            health = t.get("health", {})
            ls = health.get("last_success") or {}
            ls_date = ls.get("completed_at", "")[:10] if ls else "unknown"
            parts.append(f"{t['name']}: run #{run_id} started {started}")
        result["question_text"] = (
            f"A conforma-reporter run is in progress for {release} ({'; '.join(parts)}). Choose:"
        )
        result["question_options"] = [
            f"Use last completed report ({ls_date})",
            "Wait for current run to finish (up to 60 min)",
        ]

    return result


def _compute_overall_health(tools: list[dict]) -> str:
    """Compute worst health status across all tools."""
    if not tools:
        return "error"

    worst_priority = max(HEALTH_PRIORITY.values())
    for tool in tools:
        status = tool.get("health", {}).get("status", "error")
        priority = HEALTH_PRIORITY.get(status, 0)
        worst_priority = min(worst_priority, priority)

    for status, priority in HEALTH_PRIORITY.items():
        if priority == worst_priority:
            return status
    return "error"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check health of conforma infrastructure tools"
    )
    parser.add_argument(
        "--release",
        required=True,
        help="Release branch name (e.g. rhoai-3.5-ea.1)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: stdout)",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=5,
        help="Maximum number of recent runs to check per tool (default: 5)",
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["prod", "stage"],
        help="Target environment to filter workflow runs",
    )
    parser.add_argument(
        "--catalog",
        default=None,
        help="Path to tooling-health-catalog.yaml (default: auto-detect)",
    )
    args = parser.parse_args()

    catalog_path = Path(args.catalog) if args.catalog else None
    result = check_all_tools(args.release, environment=args.environment, max_runs=args.max_runs, catalog_path=catalog_path)

    output_json = json.dumps(result, indent=2)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json, encoding="utf-8")
        print(f"Tooling health written to {output_path}", file=sys.stderr)
    else:
        print(output_json)

    return 0


if __name__ == "__main__":
    sys.exit(main())
