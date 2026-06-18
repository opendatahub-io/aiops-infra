#!/usr/bin/env python3
"""Batch violations coverage check with cross-referencing.

Reads a violations YAML (from parse_violations.py) and cross-references each
violation against existing policy exceptions, open GitLab Merge Requests, open
Jira tickets, and Slack threads.  Produces a per-violation summary with a
pre-rendered markdown table.

Usage:
    python3 skills/conforma-analyze/scripts/violations_coverage.py \\
      --violations-yaml .work/20260610-103554/violations.yaml \\
      --clone-dir .work/konflux-release-data \\
      --environment prod
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import component_alias_ops
import conforma_jira_ops
import conforma_mr_ops
import conforma_policy_ops
import conforma_slack_ops
import jira_ops
import slack_ops


_GATE_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "permanent": ("fully_covered", "permanently excluded"),
    "blocked": ("fully_covered", "already covered"),
    "partial": ("partially_covered", None),
    "passed": ("not_covered", "not covered — resolve in code first, exception as last resort"),
    "skipped": ("not_covered", "not covered — resolve in code first, exception as last resort"),
    "error": ("not_covered", "not covered — exception check failed, manual review needed"),
}


def _map_gate_status(
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
        coverage_label = f"{len(uncovered)} of {len(all_components)} uncovered"
    return coverage, coverage_label


def _extract_exception_expiry(gate: dict) -> dict:
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


def _log(msg: str) -> None:
    """Progress message to stderr (never mixed with JSON stdout)."""
    print(msg, file=sys.stderr, flush=True)


def _build_search_urls(
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


def _determine_status_and_next_steps(
    coverage: str,
    open_mrs: list[dict],
    jira_tickets: list[dict],
    uncovered_count: int,
) -> tuple[str, str]:
    """Determine the Status and Next Steps for a violation row.

    Returns (status_label, next_steps_label).
    """
    has_exception_mr = any(
        mr.get("suggestion") in ("fully_covered", "extend_mr")
        and mr.get("mr_type", "exception") == "exception"
        for mr in open_mrs
    )
    has_remedy_mr = any(mr.get("mr_type") == "remedy" for mr in open_mrs)

    if coverage == "fully_covered":
        return "Exception granted, violation should disappear on next Conforma run", "Use `conforma-violations-scan` AI skill or [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter/actions/workflows/conforma-reporter.yaml) to rerun validation and verify the violation is gone"

    if coverage == "partially_covered":
        if has_exception_mr:
            return (
                "Partially covered, exception Merge Request pending",
                f"Work with ProdSec to get Merge Request merged ({uncovered_count} component(s) uncovered)",
            )
        return (
            f"Partially covered ({uncovered_count} uncovered)",
            "Fix in code or request exception — see resolution guide",
        )

    if has_exception_mr and has_remedy_mr:
        return "Exception + remedy Merge Requests pending", "Work with ProdSec to get Merge Requests merged"
    if has_exception_mr:
        return "Exception Merge Request pending", "Work with ProdSec to get Merge Request merged"
    if has_remedy_mr:
        return "Remedy Merge Request pending", "Merge fix, rebuild, and verify compliance"

    if jira_tickets:
        return "Tracked in Jira, no exception", "Fix in code or request exception — see resolution guide"

    return "No coverage", "Fix in code or request exception — see resolution guide"


_CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"


def _load_report_metadata(release: str | None, metadata_file: str | None) -> dict:
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
                f"https://github.com/{_CONFORMA_REPORTER_REPO}/blob/{ref}/{source_path}"
            )
            meta["source_path"] = source_path
        if created_at:
            meta["created_at"] = created_at
    except (json.JSONDecodeError, KeyError):
        pass

    return meta


def check_violations_coverage(
    violations_yaml_path: str,
    clone_dir: str | None = None,
    environment: str = "prod",
    require_jira: bool = True,
    require_slack: bool = True,
    metadata_file: str | None = None,
) -> dict:
    """Batch coverage check: read a violations YAML and check each violation's components
    against existing exceptions in the policy file.

    Returns a per-violation summary with coverage status so the agent can present
    an informed violation list (covered vs uncovered) without per-violation round trips.
    """
    import yaml

    path = Path(violations_yaml_path)
    if not path.exists():
        return {"error": f"Violations file not found: {violations_yaml_path}"}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_rule = data.get("violation_data", {}).get("violations_by_rule", {})

    if not by_rule:
        return {"error": "No violations_by_rule found in input YAML"}

    all_rules = list(by_rule.keys())
    releases = data.get("violation_data", {}).get("releases", [])

    aliases = component_alias_ops.load_aliases()
    if aliases:
        _log(f"Loaded {len(all_rules)} rules across {len(releases)} release(s) ({len(set().union(*aliases.values()))} component aliases)")
    else:
        _log(f"Loaded {len(all_rules)} rules across {len(releases)} release(s)")

    by_component_data = data.get("violation_data", {}).get("violations_by_component", {})
    component_owners: dict[str, str | None] = {}
    for comp, info in by_component_data.items():
        jc = info.get("jira_component")
        if jc is not None:
            component_owners[comp] = jc

    rule_to_components: dict[str, list[str]] = {}
    for rule, info in by_rule.items():
        comps: list[str] = []
        for _release, release_comps in info.get("releases", {}).items():
            comps.extend(release_comps)
        rule_to_components[rule] = sorted(set(comps))

    # Verify auth for enabled sources before starting parallel work.
    if require_jira:
        jira_auth = jira_ops.verify_auth()
        if not jira_auth["ok"]:
            return {"error": f"Jira auth failed: {jira_auth['error']}"}

    slack_team_url = ""
    if require_slack:
        slack_auth = slack_ops.verify_auth()
        if not slack_auth["ok"]:
            return {"error": f"Slack auth failed: {slack_auth['error']}"}
        slack_team_url = slack_auth.get("team_url", "")

    # Run MR, Jira, and Slack prefetches in parallel — they are independent.
    prefetched_mrs: dict = {}
    prefetched_jira: dict = {}
    prefetched_slack: dict = {}

    def _fetch_mrs():
        t0 = time.monotonic()
        _log(f"  [Merge Requests] Searching GitLab for {len(all_rules)} rules...")
        result = conforma_mr_ops.prefetch_open_mrs(all_rules)
        total_mrs = sum(len(v) for v in result.values())
        _log(f"  [Merge Requests] Done — {total_mrs} open Merge Request(s) found ({time.monotonic() - t0:.1f}s)")
        return "mrs", result

    def _fetch_jira():
        t0 = time.monotonic()
        _log(f"  [Jira] Searching Jira tickets for {len(all_rules)} rules...")
        result = conforma_jira_ops.prefetch_open_jira_tickets(
            all_rules,
            releases=releases,
            rule_to_components=rule_to_components,
            aliases=aliases,
        )
        total_tickets = sum(len(v) for v in result.values())
        _log(f"  [Jira] Done — {total_tickets} open ticket(s) found ({time.monotonic() - t0:.1f}s)")
        return "jira", result

    def _fetch_slack():
        t0 = time.monotonic()
        _log(f"  [Slack] Searching Slack threads for {len(all_rules)} rules...")
        result = conforma_slack_ops.prefetch_open_slack_threads(
            all_rules, rule_to_components=rule_to_components
        )
        total_threads = sum(len(v) for v in result.values())
        _log(f"  [Slack] Done — {total_threads} thread(s) found ({time.monotonic() - t0:.1f}s)")
        return "slack", result

    tasks = [_fetch_mrs]
    if require_jira:
        tasks.append(_fetch_jira)
    if require_slack:
        tasks.append(_fetch_slack)

    _log(f"Cross-referencing {len(all_rules)} rules ({len(tasks)} source(s) in parallel)...")
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {pool.submit(fn): fn.__name__ for fn in tasks}
        for future in as_completed(futures):
            key, result = future.result()
            if key == "mrs":
                prefetched_mrs = result
            elif key == "jira":
                prefetched_jira = result
            elif key == "slack":
                prefetched_slack = result
    _log(f"All prefetches complete ({time.monotonic() - t_start:.1f}s)")

    analyzed_release = releases[0] if releases else None

    # Refresh the policy clone once (not per rule).
    if clone_dir:
        t0 = time.monotonic()
        _log("Refreshing policy clone...")
        conforma_policy_ops.refresh_clone(clone_dir)
        _log(f"Policy clone refreshed ({time.monotonic() - t0:.1f}s)")

    _log(f"Checking exception coverage for {len(by_rule)} rules...")
    results = []
    for i, (rule, info) in enumerate(sorted(by_rule.items()), 1):
        all_components = []
        for release, comps in info.get("releases", {}).items():
            all_components.extend(comps)
        all_components = sorted(set(all_components))

        _log(f"  [{i}/{len(by_rule)}] {rule}")

        if not all_components:
            results.append(
                {
                    "rule": rule,
                    "title": info.get("title", ""),
                    "total_components": 0,
                    "covered_components": [],
                    "uncovered_components": [],
                    "coverage": "no_components",
                    "status": "skipped",
                }
            )
            continue

        gate = conforma_policy_ops.check_existing_exception_gate(
            rule=rule,
            components=all_components,
            clone_dir=clone_dir,
            environment=environment,
            prefetched_mrs=prefetched_mrs.get(rule),
            skip_refresh=True,
            aliases=aliases or None,
        )

        covered = gate.get("covered_components", [])
        uncovered = gate.get("uncovered_components", [])

        coverage, coverage_label = _map_gate_status(gate, rule, all_components, uncovered)
        exception_expiry = _extract_exception_expiry(gate)

        open_mrs = gate.get("open_merge_requests", [])

        mr_label = ""
        for mr in open_mrs:
            sug = mr.get("suggestion", "")
            mr_url = mr.get("url", "")
            mr_type = mr.get("mr_type", "exception")
            type_tag = f"({mr_type}) " if mr_type else ""
            if sug == "fully_covered":
                mr_label = f"{type_tag}fully covered by [!{mr['iid']}]({mr_url})"
                break
            if sug == "extend_mr":
                n_cov = len(mr.get("covered", []))
                mr_label = f"{type_tag}[!{mr['iid']}]({mr_url}) covers {n_cov}/{len(all_components)}"

        jira_tickets = prefetched_jira.get(rule, [])
        if analyzed_release:
            for t in jira_tickets:
                t["version_relevance"] = conforma_jira_ops.classify_ticket_version_relevance(
                    t, analyzed_release
                )
        jira_label = ""
        if jira_tickets:
            labels = []
            for t in jira_tickets:
                version_tag = ""
                # Only annotate fixVersion relevance for RHOAIENG tickets;
                # PSX, OCPEXCEPT, and PRODSECRM don't use the fixVersion field.
                project = t["key"].split("-", 1)[0]
                if analyzed_release and project == "RHOAIENG":
                    relevance = t.get("version_relevance", "no_target_version")
                    if relevance == "targets_future":
                        fv_str = ", ".join(t.get("fix_versions", []))
                        version_tag = f" ⚠️ targets {fv_str}"
                    elif relevance == "no_target_version":
                        version_tag = " ⚠️ no fixVersion"
                match_tag = ""
                if t.get("match_source") == "component_inference":
                    confidence = t.get("inference_confidence", "unconfirmed")
                    match_tag = " \U0001f50d" if confidence == "confirmed" else " \U0001f50d?"
                labels.append(f"[{t['key']}]({t['url']}) ({t['status']}{version_tag}{match_tag})")
            jira_label = ", ".join(labels)

        slack_threads = prefetched_slack.get(rule, [])
        slack_label = ""
        if slack_threads:
            labels = []
            for t in slack_threads:
                reply_info = f", {t['thread_reply_count']} replies" if t.get("thread_reply_count") else ""
                labels.append(f"[#{t['channel']}]({t['permalink']}) ({t['date']}{reply_info})")
            slack_label = ", ".join(labels)

        search_urls = _build_search_urls(rule, slack_team_url)
        if search_urls["mr"]:
            mr_label = (
                (mr_label + f" ([manual search]({search_urls['mr']}))") if mr_label else f"[manual search]({search_urls['mr']})"
            )
        if search_urls["jira"]:
            jira_label = (
                (jira_label + f" ([manual search]({search_urls['jira']}))")
                if jira_label
                else f"[manual search]({search_urls['jira']})"
            )
        if search_urls["slack"]:
            slack_label = (
                (slack_label + f" ([manual search]({search_urls['slack']}))")
                if slack_label
                else f"[manual search]({search_urls['slack']})"
            )

        status_label, next_steps = _determine_status_and_next_steps(
            coverage, open_mrs, jira_tickets, len(uncovered)
        )

        uncov_labels = []
        for c in uncovered:
            jc = component_owners.get(c)
            uncov_labels.append(f"{c} ({jc})" if jc else c)

        all_labels = []
        for c in all_components:
            jc = component_owners.get(c)
            all_labels.append(f"{c} ({jc})" if jc else c)

        if len(all_labels) <= 3:
            display_components = ", ".join(all_labels)
        else:
            display_components = ", ".join(all_labels[:3]) + f" ... +{len(all_components) - 3} more"

        entry = {
            "rule": rule,
            "title": info.get("title", ""),
            "violation_count": info.get("count", len(all_components)),
            "total_components": len(all_components),
            "covered_components": covered,
            "uncovered_components": uncovered,
            "covered_count": len(covered),
            "uncovered_count": len(uncovered),
            "display_components": display_components,
            "exception_expiry": exception_expiry,
            "open_merge_requests": open_mrs,
            "open_mr_label": mr_label,
            "open_mr_search_url": search_urls["mr"],
            "open_jira_tickets": jira_tickets,
            "open_jira_label": jira_label,
            "open_jira_search_url": search_urls["jira"],
            "next_steps": next_steps,
            "status_label": status_label,
            "coverage": coverage,
            "coverage_label": coverage_label,
            "gate_status": gate["status"],
            "analyzed_release": analyzed_release,
        }
        if require_slack:
            entry["open_slack_threads"] = slack_threads
            entry["open_slack_label"] = slack_label
            entry["open_slack_search_url"] = search_urls["slack"]
        results.append(entry)

    summary = {
        "fully_covered": sum(1 for r in results if r["coverage"] == "fully_covered"),
        "partially_covered": sum(1 for r in results if r["coverage"] == "partially_covered"),
        "not_covered": sum(1 for r in results if r["coverage"] == "not_covered"),
        "total_violations": len(results),
    }

    _log(
        f"Coverage complete: {summary['fully_covered']} covered, "
        f"{summary['partially_covered']} partial, {summary['not_covered']} uncovered"
    )

    report_meta = _load_report_metadata(analyzed_release, metadata_file)

    md_table = _render_violations_markdown_table(
        results, summary, include_slack=require_slack, report_meta=report_meta,
    )

    output = {
        "violations_source": violations_yaml_path,
        "environment": environment,
        "summary": summary,
        "violations": results,
        "markdown_table": md_table,
    }
    if component_owners:
        output["component_owners"] = component_owners
    return output


def _render_violations_markdown_table(
    results: list[dict],
    summary: dict,
    include_slack: bool = False,
    report_meta: dict | None = None,
) -> str:
    """Pre-render a markdown table from violations coverage results.

    Columns: #, Rule, Violations, Components, Open Merge Requests, Open Jira,
    [Slack,] Status, Next Steps.
    """
    meta = report_meta or {}
    lines: list[str] = []

    # Report header
    header_parts = [f"**Release**: `{meta.get('release', 'unknown')}`"]
    source_path = meta.get("source_path")
    source_url = meta.get("source_url")
    if source_path and source_url:
        header_parts.append(f"**Source**: [{source_path}]({source_url})")
    elif source_path:
        header_parts.append(f"**Source**: {source_path}")
    created_at = meta.get("created_at")
    if created_at:
        header_parts.append(f"**Report date**: {created_at}")
    lines.append(" | ".join(header_parts))
    lines.append("")

    lines.append(
        f"**Summary**: {summary['total_violations']} unique rules — "
        f"{summary['fully_covered']} fully covered, "
        f"{summary['partially_covered']} partially covered, "
        f"{summary['not_covered']} not covered."
    )
    lines.append("")

    if include_slack:
        lines.append("| # | Rule | Violations | Components | Open Merge Requests | Open Jira | Slack | Status | Next Steps |")
        lines.append("|---|------|------------|-----------|---------------------|-----------|-------|--------|------------|")
    else:
        lines.append("| # | Rule | Violations | Components | Open Merge Requests | Open Jira | Status | Next Steps |")
        lines.append("|---|------|------------|-----------|---------------------|-----------|--------|------------|")

    for i, v in enumerate(results, 1):
        rule = f"`{v['rule']}`"
        viol_count = v.get("violation_count", "—")
        comps = v["display_components"]
        mr = v["open_mr_label"] or "—"
        jira = v["open_jira_label"] or "—"
        status = v["status_label"]
        expiry = v.get("exception_expiry", {})
        expiry_display = expiry.get("display_expiry", "")
        if expiry_display:
            status = f"Exception granted ({expiry_display}), violation should disappear on next Conforma run"
        ns = v["next_steps"]
        if include_slack:
            slack = v.get("open_slack_label") or "—"
            lines.append(f"| {i} | {rule} | {viol_count} | {comps} | {mr} | {jira} | {slack} | {status} | {ns} |")
        else:
            lines.append(f"| {i} | {rule} | {viol_count} | {comps} | {mr} | {jira} | {status} | {ns} |")

    lines.append("")
    lines.append("*See the **Violation Resolution Guide** section below for full resolution details per violation.*")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch violations coverage check")
    parser.add_argument("--violations-yaml", required=True)
    parser.add_argument("--clone-dir", default=None)
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--require-jira", type=lambda v: v.lower() in ("true", "1", "yes"), default=True)
    parser.add_argument("--require-slack", type=lambda v: v.lower() in ("true", "1", "yes"), default=True)
    parser.add_argument("--metadata-file", default=None, help="Path to fetch-metadata.json for report header")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = check_violations_coverage(
        violations_yaml_path=args.violations_yaml,
        clone_dir=args.clone_dir,
        environment=args.environment,
        require_jira=args.require_jira,
        require_slack=args.require_slack,
        metadata_file=args.metadata_file,
    )
    print(json.dumps(result, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
