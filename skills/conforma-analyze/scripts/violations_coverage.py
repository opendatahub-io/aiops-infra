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
from pathlib import Path

import component_alias_ops
import conforma_jira_ops
import conforma_mr_ops
import conforma_policy_ops
import conforma_slack_ops
import jira_ops
import slack_ops


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


def _summarize_next_steps(
    coverage: str,
    open_mrs: list[dict],
    jira_tickets: list[dict],
    uncovered_count: int,
) -> str:
    """Build a context-sensitive Next Steps hint for the coverage table."""
    suffix = " — see resolution guide"

    if coverage == "fully_covered":
        return f"covered by existing exceptions{suffix}"

    has_exception_mr = any(
        mr.get("suggestion") in ("fully_covered", "extend_mr")
        and mr.get("mr_type", "exception") == "exception"
        for mr in open_mrs
    )
    has_remedy_mr = any(mr.get("mr_type") == "remedy" for mr in open_mrs)
    has_jira = bool(jira_tickets)

    parts: list[str] = []
    if has_exception_mr and has_remedy_mr:
        parts.append("exception + remedy Merge Requests open")
    elif has_exception_mr:
        parts.append("exception Merge Request open")
    elif has_remedy_mr:
        parts.append("remedy Merge Request open")

    if coverage == "partially_covered":
        parts.append(f"{uncovered_count} component(s) still uncovered")
    elif not parts:
        if has_jira:
            parts.append("Jira tracked, needs fix or exception")
        else:
            parts.append("untracked, needs fix or exception")

    return ", ".join(parts) + suffix


def check_violations_coverage(
    violations_yaml_path: str,
    clone_dir: str | None = None,
    environment: str = "prod",
    require_jira: bool = True,
    require_slack: bool = True,
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

        if gate["status"] == "blocked":
            coverage = "fully_covered"
            coverage_label = "already covered"
        elif gate["status"] == "partial":
            coverage = "partially_covered"
            coverage_label = f"{len(uncovered)} of {len(all_components)} uncovered"
        else:
            coverage = "not_covered"
            coverage_label = "not covered — resolve in code first, exception as last resort"

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

        next_steps = _summarize_next_steps(coverage, open_mrs, jira_tickets, len(uncovered))

        uncov_labels = []
        for c in uncovered:
            jc = component_owners.get(c)
            uncov_labels.append(f"{c} ({jc})" if jc else c)

        if len(uncov_labels) <= 3:
            display_components = ", ".join(uncov_labels)
        else:
            display_components = ", ".join(uncov_labels[:3]) + f" ... +{len(uncovered) - 3} more"

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
            "open_merge_requests": open_mrs,
            "open_mr_label": mr_label,
            "open_mr_search_url": search_urls["mr"],
            "open_jira_tickets": jira_tickets,
            "open_jira_label": jira_label,
            "open_jira_search_url": search_urls["jira"],
            "next_steps": next_steps,
            "coverage": coverage,
            "coverage_label": coverage_label,
            "status": gate["status"],
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

    md_table = _render_violations_markdown_table(results, summary, include_slack=require_slack)

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


def _render_violations_markdown_table(results: list[dict], summary: dict, include_slack: bool = False) -> str:
    """Pre-render a markdown table from violations coverage results.

    Columns: #, Rule, Violations, Components, Open Merge Requests, Open Jira, [Slack,] Next Steps.
    Each Merge Request entry is annotated with its type (exception/remedy).
    """
    lines = [
        f"**Summary**: {summary['total_violations']} unique rules — "
        f"{summary['fully_covered']} fully covered, "
        f"{summary['partially_covered']} partially covered, "
        f"{summary['not_covered']} not covered.",
        "",
    ]
    if include_slack:
        lines.append("| # | Rule | Violations | Components | Open Merge Requests | Open Jira | Slack | Next Steps |")
        lines.append("|---|------|------------|-----------|---------------------|-----------|-------|------------|")
    else:
        lines.append("| # | Rule | Violations | Components | Open Merge Requests | Open Jira | Next Steps |")
        lines.append("|---|------|------------|-----------|---------------------|-----------|------------|")

    for i, v in enumerate(results, 1):
        rule = f"`{v['rule']}`"
        viol_count = v.get("violation_count", "—")
        comps = v["display_components"]
        mr = v["open_mr_label"] or "—"
        jira = v["open_jira_label"] or "—"
        ns = v["next_steps"]
        if include_slack:
            slack = v.get("open_slack_label") or "—"
            lines.append(f"| {i} | {rule} | {viol_count} | {comps} | {mr} | {jira} | {slack} | {ns} |")
        else:
            lines.append(f"| {i} | {rule} | {viol_count} | {comps} | {mr} | {jira} | {ns} |")

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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = check_violations_coverage(
        violations_yaml_path=args.violations_yaml,
        clone_dir=args.clone_dir,
        environment=args.environment,
        require_jira=args.require_jira,
        require_slack=args.require_slack,
    )
    print(json.dumps(result, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
