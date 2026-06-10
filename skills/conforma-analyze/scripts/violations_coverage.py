#!/usr/bin/env python3
"""Batch violations coverage check with cross-referencing.

Reads a violations YAML (from parse_violations.py) and cross-references each
violation against existing policy exceptions, open GitLab MRs, open Jira
tickets, and Slack threads.  Produces a per-violation summary with a
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
import urllib.parse
from pathlib import Path

import conforma_jira_ops
import conforma_mr_ops
import conforma_policy_ops
import conforma_slack_ops
import jira_ops
import slack_ops


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
        f"project in (RHOAIENG, PSX, OCPEXCEPT) "
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

    by_component_data = data.get("violation_data", {}).get("violations_by_component", {})
    component_owners: dict[str, str | None] = {}
    for comp, info in by_component_data.items():
        jc = info.get("jira_component")
        if jc is not None:
            component_owners[comp] = jc

    prefetched_mrs = conforma_mr_ops.prefetch_open_mrs(all_rules)

    if require_jira:
        jira_auth = jira_ops.verify_auth()
        if not jira_auth["ok"]:
            return {"error": f"Jira auth failed: {jira_auth['error']}"}
    prefetched_jira = conforma_jira_ops.prefetch_open_jira_tickets(all_rules, releases=releases) if require_jira else {}

    rule_to_components: dict[str, list[str]] = {}
    for rule, info in by_rule.items():
        comps: list[str] = []
        for _release, release_comps in info.get("releases", {}).items():
            comps.extend(release_comps)
        rule_to_components[rule] = sorted(set(comps))

    slack_team_url = ""
    if require_slack:
        slack_auth = slack_ops.verify_auth()
        if not slack_auth["ok"]:
            return {"error": f"Slack auth failed: {slack_auth['error']}"}
        slack_team_url = slack_auth.get("team_url", "")
        prefetched_slack = conforma_slack_ops.prefetch_open_slack_threads(
            all_rules, rule_to_components=rule_to_components
        )
    else:
        prefetched_slack = {}

    results = []
    for rule, info in sorted(by_rule.items()):
        all_components = []
        for release, comps in info.get("releases", {}).items():
            all_components.extend(comps)
        all_components = sorted(set(all_components))

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
            if sug == "fully_covered":
                mr_label = f"fully covered by open [MR !{mr['iid']}]({mr_url})"
                break
            if sug == "extend_mr":
                n_cov = len(mr.get("covered", []))
                mr_label = f"open [MR !{mr['iid']}]({mr_url}) covers {n_cov}/{len(all_components)}"

        jira_tickets = prefetched_jira.get(rule, [])
        jira_label = ""
        if jira_tickets:
            labels = []
            for t in jira_tickets:
                labels.append(f"[{t['key']}]({t['url']}) ({t['status']})")
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
                (mr_label + f" ([search]({search_urls['mr']}))") if mr_label else f"[search]({search_urls['mr']})"
            )
        if search_urls["jira"]:
            jira_label = (
                (jira_label + f" ([search]({search_urls['jira']}))")
                if jira_label
                else f"[search]({search_urls['jira']})"
            )
        if search_urls["slack"]:
            slack_label = (
                (slack_label + f" ([search]({search_urls['slack']}))")
                if slack_label
                else f"[search]({search_urls['slack']})"
            )

        next_steps = "see resolution guide below"

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

    Columns: #, Rule, Components, Open MRs, Open Jira, [Slack,] Next Steps.
    No Coverage column — next_steps is the single source of guidance.
    """
    lines = [
        f"**Summary**: {summary['total_violations']} unique rules — "
        f"{summary['fully_covered']} fully covered, "
        f"{summary['partially_covered']} partially covered, "
        f"{summary['not_covered']} not covered.",
        "",
    ]
    if include_slack:
        lines.append("| # | Rule | Components | Open MRs | Open Jira | Slack | Next Steps |")
        lines.append("|---|------|-----------|----------|-----------|-------|------------|")
    else:
        lines.append("| # | Rule | Components | Open MRs | Open Jira | Next Steps |")
        lines.append("|---|------|-----------|----------|-----------|------------|")

    for i, v in enumerate(results, 1):
        rule = f"`{v['rule']}`"
        comps = v["display_components"]
        mr = v["open_mr_label"] or "—"
        jira = v["open_jira_label"] or "—"
        ns = v["next_steps"]
        if include_slack:
            slack = v.get("open_slack_label") or "—"
            lines.append(f"| {i} | {rule} | {comps} | {mr} | {jira} | {slack} | {ns} |")
        else:
            lines.append(f"| {i} | {rule} | {comps} | {mr} | {jira} | {ns} |")

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
