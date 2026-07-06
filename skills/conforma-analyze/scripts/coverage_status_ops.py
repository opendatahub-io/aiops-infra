"""Coverage status operations — pure status determination and classification logic."""

from __future__ import annotations

from __future__ import annotations
import argparse
import conforma_context_ops
import fnmatch
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import component_alias_ops
import conforma_ec_validate
import conforma_jira_ops
import conforma_mr_ops
import conforma_policy_ops
import conforma_slack_ops
import jira_ops
import slack_ops
from conforma_constants import (
    CONFORMA_REPORTER_URL,
    VERIFY_NEXT_STEP,
)


_GATE_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "permanent": ("fully_covered", "permanently excluded"),
    "blocked": ("fully_covered", "already covered"),
    "partial": ("partially_covered", None),
    "passed": ("not_covered", "not covered — resolve in code first, exception as last resort"),
    "skipped": ("not_covered", "not covered — resolve in code first, exception as last resort"),
    "error": ("not_covered", "not covered — exception check failed, manual review needed"),
}


def map_gate_status(
    gate: dict, rule: str, all_components: list, uncovered: list
) -> tuple[str, str]:
    """Map a gate check status to a coverage classification.

    Raises ValueError on unrecognised statuses so new gate statuses are never
    silently misclassified.
    """
    gate_status = gate["status"]
    if gate_status not in _GATE_STATUS_MAP:
        raise ValueError(
            f"Unknown gate status '{gate_status}' for rule '{rule}'. "
            f"Add it to _GATE_STATUS_MAP in violations_coverage.py."
        )
    coverage, coverage_label = _GATE_STATUS_MAP[gate_status]
    if coverage_label is None:
        coverage_label = f"{len(uncovered)} of {len(all_components)} without exception coverage"
    return coverage, coverage_label


def extract_exception_expiry(gate: dict) -> dict:
    """Extract effectiveUntil dates from active exceptions in a gate result.

    Returns:
        {
            "is_permanent": bool,
            "earliest_expiry": str | None,  # ISO date (YYYY-MM-DD) of soonest expiry
            "latest_expiry": str | None,     # ISO date (YYYY-MM-DD) of latest expiry
            "expiry_dates": list[str],       # all unique dates sorted ascending
            "display_expiry": str,           # human-readable label for the table
        }
    """
    permanent = gate.get("permanent_exclusions", [])
    if permanent or gate.get("status") == "permanent":
        return {
            "is_permanent": True,
            "earliest_expiry": None,
            "latest_expiry": None,
            "expiry_dates": [],
            "display_expiry": "permanent (no expiry)",
        }

    active = gate.get("active_exceptions", [])
    dates: list[datetime] = []
    for exc in active:
        eu = exc.get("effectiveUntil")
        if eu:
            try:
                eu_str = eu.strip('"').strip("'")
                eu_dt = datetime.fromisoformat(eu_str.replace("Z", "+00:00"))
                dates.append(eu_dt)
            except (ValueError, TypeError):
                pass

    if not dates:
        return {
            "is_permanent": False,
            "earliest_expiry": None,
            "latest_expiry": None,
            "expiry_dates": [],
            "display_expiry": "",
        }

    dates_sorted = sorted(set(dates))
    date_strs = [d.strftime("%Y-%m-%d") for d in dates_sorted]

    if len(dates_sorted) == 1:
        display = f"expires {date_strs[0]}"
    else:
        display = f"expires {date_strs[0]} — {date_strs[-1]}"

    return {
        "is_permanent": False,
        "earliest_expiry": date_strs[0],
        "latest_expiry": date_strs[-1],
        "expiry_dates": date_strs,
        "display_expiry": display,
    }


def build_search_urls(
    rule: str,
    slack_team_url: str,
) -> dict[str, str]:
    """Build clickable search URLs for each data source."""
    encoded_rule = urllib.parse.quote(rule)

    mr_search_url = ""
    if conforma_mr_ops.GITLAB_HOST and conforma_mr_ops.GITLAB_PROJECT:
        mr_search_url = (
            f"https://{conforma_mr_ops.GITLAB_HOST}/{conforma_mr_ops.GITLAB_PROJECT}"
            f"/-/merge_requests?state=opened&search={encoded_rule}"
        )

    jql = (
        f"{conforma_jira_ops.SEARCH_PROJECTS_JQL} "
        f"AND labels = 'conforma-violation' "
        f"AND status not in (Closed, Resolved, Done) "
        f"AND summary ~ '{rule}'"
    )
    jira_search_url = f"https://redhat.atlassian.net/issues/?jql={urllib.parse.quote(jql)}"

    slack_search_url = ""
    if slack_team_url:
        slack_search_url = f"{slack_team_url}/search/{encoded_rule}"

    return {
        "mr": mr_search_url,
        "jira": jira_search_url,
        "slack": slack_search_url,
    }


def determine_status_and_next_steps(
    coverage: str,
    open_mrs: list[dict],
    jira_tickets: list[dict],
    uncovered_count: int,
) -> tuple[str, str, str]:
    """Determine the Status and Next Steps for a violation row.

    Returns (status_label, next_steps, next_steps_short).
    next_steps is the detailed version (used by the resolution guide).
    next_steps_short is the concise version (used by the summary table).
    """
    has_exception_mr = any(
        mr.get("suggestion") in ("fully_covered", "extend_mr")
        and mr.get("mr_type", "exception") == "exception"
        for mr in open_mrs
    )
    has_remedy_mr = any(mr.get("mr_type") == "remedy" for mr in open_mrs)

    if coverage == "fully_covered":
        return (
            "Exception granted, violation should disappear on next Conforma run",
            VERIFY_NEXT_STEP,
            VERIFY_NEXT_STEP,
        )

    if coverage == "partially_covered":
        if has_exception_mr:
            return (
                "Partially covered, exception Merge Request pending",
                f"Work with ProdSec to get Merge Request merged ({uncovered_count} component(s) without coverage)",
                f"Get Merge Request merged ({uncovered_count} without coverage)",
            )
        return (
            f"Partially covered ({uncovered_count} without coverage)",
            "Fix in code or request exception — see resolution guide",
            "Fix remaining — see guide below",
        )

    if has_exception_mr and has_remedy_mr:
        return (
            "Exception + remedy Merge Requests pending",
            "Work with ProdSec to get Merge Requests merged",
            "Get Merge Requests merged",
        )
    if has_exception_mr:
        return (
            "Exception Merge Request pending",
            "Work with ProdSec to get Merge Request merged",
            "Get Merge Request merged",
        )
    if has_remedy_mr:
        return (
            "Remedy Merge Request pending",
            "Merge fix, rebuild, and verify compliance",
            "Merge fix and rebuild",
        )

    if jira_tickets:
        return (
            "Tracked in Jira, no exception",
            "Fix in code or request exception — see resolution guide",
            "Fix in code or request exception — see guide below",
        )

    return (
        "No exception coverage",
        "Fix in code or request exception — see resolution guide",
        "Fix in code or request exception — see guide below",
    )


def load_report_metadata(release: str | None, metadata_file: str | None) -> dict:
    """Build report metadata dict for the table header.

    Reads from fetch-metadata.json when available, falls back to release name.
    """
    meta: dict = {"release": release or "unknown"}
    if not metadata_file:
        return meta

    path = Path(metadata_file)
    if not path.exists():
        return meta

    try:
        data = json.load(path.open(encoding="utf-8"))
        rel_data = data.get("releases", {}).get(release or "", {})
        source_path = rel_data.get("source_path", "")
        created_at = rel_data.get("created_at", "")
        source_sha = rel_data.get("source_sha", "")
        if source_path:
            ref = source_sha or release or ""
            meta["source_url"] = (
                f"{CONFORMA_REPORTER_URL}/blob/{ref}/{source_path}"
            )
            meta["source_path"] = source_path
        if created_at:
            meta["created_at"] = created_at
    except (json.JSONDecodeError, KeyError):
        pass

    return meta

