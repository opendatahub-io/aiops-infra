#!/usr/bin/env python3
"""Generate a unified Conforma Resolution Guide.

Combines outputs from the conforma-analyze workflow into a single markdown
document suitable for submission to the conforma-reporter repository.

Inputs:
  - violations.yaml (from parse_violations.py)
  - coverage.json (from violations_coverage.py)
  - CSV reports directory (for statistical analysis)
  - violation-catalog.yaml (for resolution guidance + fallback references)

Output: A unified markdown file with:
  1. Metadata header (generation date, source CSV link, etc.)
  2. Summary metrics
  3. Coverage table (verbatim from violations_coverage.py)
  4. Per-violation resolution guide (from catalog + fallbacks)
  5. Warnings becoming violations (if any)
  6. Statistical breakdown (from analyze_csv_report.py)

Usage:
    python3 skills/conforma-analyze/scripts/generate_resolution_guide.py \\
      --violations-yaml .work/20260610-143449/violations.yaml \\
      --coverage-json .work/20260610-143449/coverage.json \\
      --reports-dir .work/20260610-143449 \\
      --release rhoai-3.5-ea.2 \\
      --source-path "prod/release_day/conforma-violations-report.csv" \\
      --source-created-at "2026-06-10T05:19:05Z" \\
      --output .work/20260610-143449/conforma-resolution-guide.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _setup_env  # noqa: F401, E402

import conforma_counting  # noqa: E402
import yaml  # noqa: E402
from parse_violations import build_semantic_detail_lookup  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import analyze_csv_report as analysis  # noqa: E402

CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"
_CONFORMA_REPORTER_WORKFLOW_URL = (
    "https://github.com/red-hat-data-services/conforma-reporter"
    "/actions/workflows/conforma-reporter.yaml"
)
_VERIFY_NEXT_STEP = (
    f"Run [conforma-reporter]({_CONFORMA_REPORTER_WORKFLOW_URL})"
    " or `conforma-violations-scan` AI skill"
    " to verify the violation is no longer reported"
)


def _load_catalog(catalog_path: Path) -> dict:
    """Load the violation catalog YAML."""
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    return data


def _match_catalog_entry(rule_code: str, catalog: dict) -> dict | None:
    """Find a catalog violation entry matching the given rule code.

    Tries exact match on conforma_rule_codes first, then base_code prefix match.
    """
    base_code = rule_code.split(":")[0]
    violations = catalog.get("violations", [])

    for entry in violations:
        codes = entry.get("conforma_rule_codes", [])
        if rule_code in codes or base_code in codes:
            return entry

    for entry in violations:
        codes = entry.get("conforma_rule_codes", [])
        for code in codes:
            if base_code.startswith(code) or code.startswith(base_code):
                return entry

    return None


def _match_fallback_reference(rule_code: str, catalog: dict) -> dict | None:
    """Find the longest-matching fallback reference for a rule code."""
    base_code = rule_code.split(":")[0]
    fallbacks = catalog.get("fallback_references", [])

    best_match = None
    best_len = 0

    for fb in fallbacks:
        prefix = fb.get("code_prefix", "")
        if base_code.startswith(prefix) or base_code == prefix:
            if len(prefix) > best_len:
                best_match = fb
                best_len = len(prefix)

    return best_match


def _match_known_false_alert(rule_code: str, component: str, catalog: dict) -> dict | None:
    """Check if a violation matches a known false alert."""
    base_code = rule_code.split(":")[0]
    alerts = catalog.get("known_false_alerts", [])

    for alert in alerts:
        alert_codes = alert.get("conforma_rule_codes", [])
        if not alert_codes or base_code in alert_codes or rule_code in alert_codes:
            applies_to = alert.get("applies_to", "")
            if applies_to:
                import fnmatch

                if fnmatch.fnmatch(component, applies_to):
                    return alert
    return None


def _render_metadata_header(
    release: str,
    source_path: str,
    source_created_at: str,
    source_sha: str = "",
    policy_dir_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
    end_of_support: str = "",
) -> str:
    """Render the document metadata header."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ref = source_sha or release
    source_url = f"https://github.com/{CONFORMA_REPORTER_REPO}/blob/{ref}/{source_path}"

    lines = [
        f"# Conforma Resolution Guide: {release}",
        "",
        f"**Generated**: {now}\\",
    ]
    if end_of_support:
        version_label = release.replace("rhoai-", "RHOAI ").replace("-ea.", " EA")
        product_pages_url = "https://productpages.redhat.com/"
        lines.append(
            f"**End of support for {version_label}**: {end_of_support}"
            f" (see [Product Pages]({product_pages_url}))\\"
        )
    lines.append(f"**Source CSV**: [{source_path}]({source_url})\\")
    if source_created_at:
        lines.append(f"**Source CSV generated**: {source_created_at}\\")
    if policy_files:
        file_links = ", ".join(f"[{f['name']}]({f['url']})" for f in policy_files)
        lines.append(f"**Conforma policy config**: {file_links}\\")
    elif policy_dir_url:
        lines.append(f"**Conforma policy config**: [policy directory]({policy_dir_url})\\")
    lines += [
        "**Generated by**: aiops-infra conforma-analyze skill",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)



def _render_key_takeaways(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
    tooling_health_data: dict | None = None,
    violations_yaml_data: dict | None = None,
) -> str:
    """Render the executive summary — exact violation counts, no approximation.

    A violation = unique (code, component, message) triple. Coverage is binary:
    each violation either has an exception or does not.
    """
    violations = coverage_data.get("violations", [])

    total_violations = analysis_result.total_violations

    # Compute covered/uncovered using exact per-component-rule counts
    covered_violations = 0
    not_covered_violations = 0

    for v in violations:
        coverage = v.get("coverage", "not_covered")
        rule = v["rule"]
        all_components = v.get("all_components", [])
        uncovered_comps = v.get("uncovered_components", [])
        covered_comps = [c for c in all_components if c not in uncovered_comps]

        covered_count = conforma_counting.violations_for_components(
            rule, covered_comps, by_component_rule,
        )
        uncovered_count = conforma_counting.violations_for_components(
            rule, uncovered_comps, by_component_rule,
        )
        covered_violations += covered_count
        not_covered_violations += uncovered_count

    coverage_pct = (covered_violations / total_violations * 100) if total_violations > 0 else 0

    lines = ["## Executive Summary", ""]

    if tooling_health_data:
        tooling_line = _tooling_health_executive_line(tooling_health_data)
        if tooling_line:
            lines.append(tooling_line)

    lines.append(
        f"- **{covered_violations:,} of {total_violations:,} violations ({coverage_pct:.1f}%) covered** by exceptions"
    )

    detail_lookup, detail_labels = build_semantic_detail_lookup(violations_yaml_data) if violations_yaml_data else ({}, {})

    # Collect ALL components without an exception (from not_covered AND partially_covered codes)
    uncovered_entries: list[dict] = []
    for v in violations:
        coverage = v.get("coverage", "not_covered")
        if coverage == "fully_covered":
            continue
        rule = v["rule"]
        uncovered_comps = v.get("uncovered_components", [])
        mrs = v.get("open_merge_requests", [])
        for comp in uncovered_comps:
            covering_mr = None
            for mr in mrs:
                if comp in mr.get("mr_components", []):
                    covering_mr = mr
                    break
            uncovered_entries.append({
                "rule": rule,
                "component": comp,
                "violation_count": by_component_rule.get((rule, comp), 0) or by_component_rule.get((rule.split(":")[0], comp), 0) or 1,
                "mr": covering_mr,
            })

    if uncovered_entries:
        lines.append(
            f"- **{not_covered_violations:,} violations without exception coverage**:"
        )
        lines.append("")
        lines.append("| # | Violation | Component | Violations | Exception Request |")
        lines.append("|--:|-----------|-----------|:----------:|-------------------|")
        for row_num, entry in enumerate(uncovered_entries, 1):
            rule = entry["rule"]
            comp = entry["component"]
            viol_count = entry["violation_count"]
            mr = entry["mr"]
            base_rule = rule.split(":")[0]
            details = detail_lookup.get((base_rule, comp), [])
            if len(details) == 0:
                violation_cell = f"`{rule}`"
            elif len(details) == 1:
                violation_cell = f"`{rule}` ({details[0]})"
            elif len(details) <= 20:
                violation_cell = f"`{rule}` ({', '.join(details)})"
            else:
                label = detail_labels.get(base_rule, "items")
                violation_cell = f"`{rule}` ({', '.join(details[:10])} ... +{len(details) - 10} more {label}s)"
            if mr:
                mr_link = f"[!{mr['iid']}]({mr['url']})"
                lines.append(f"| {row_num} | {violation_cell} | `{comp}` | {viol_count} | {mr_link} |")
            else:
                lines.append(f"| {row_num} | {violation_cell} | `{comp}` | {viol_count} | No exception Merge Request open |")
        lines.append("")

    expiry_threshold_days = 14
    now = datetime.now(timezone.utc)
    expiring_soon = []
    for v in violations:
        if v.get("coverage") != "fully_covered":
            continue
        expiry = v.get("exception_expiry", {})
        if expiry.get("is_permanent"):
            continue
        expiry_date_str = expiry.get("earliest_expiry")
        if not expiry_date_str:
            continue
        try:
            expiry_date = datetime.fromisoformat(expiry_date_str.replace("Z", "+00:00"))
            days_left = (expiry_date.date() - now.date()).days
            if days_left <= expiry_threshold_days:
                expiring_soon.append((v["rule"], expiry_date.strftime("%Y-%m-%d"), days_left))
        except (ValueError, TypeError):
            continue

    if expiring_soon:
        expiring_soon.sort(key=lambda x: x[2])
        parts = [f"`{rule}` (expires {date}, {days}d)" for rule, date, days in expiring_soon]
        lines.append(f"- **Expiring soon**: {', '.join(parts)}")

    if analysis_result.upcoming_violations:
        lines.append(
            f"- **{len(analysis_result.upcoming_violations)} warnings becoming violations** "
            "within 21 days"
        )

    lines.append("")
    return "\n".join(lines)


def _render_summary(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
) -> str:
    """Render the summary metrics section — exact violation counts from counting module."""
    violations = coverage_data.get("violations", [])
    total_violations = analysis_result.total_violations
    total_rules = len(violations)

    covered_violations = 0
    not_covered_violations = 0
    for v in violations:
        rule = v["rule"]
        all_components = v.get("all_components", [])
        uncovered_comps = v.get("uncovered_components", [])
        covered_comps = [c for c in all_components if c not in uncovered_comps]

        covered_violations += conforma_counting.violations_for_components(
            rule, covered_comps, by_component_rule,
        )
        not_covered_violations += conforma_counting.violations_for_components(
            rule, uncovered_comps, by_component_rule,
        )

    coverage_pct = (covered_violations / total_violations * 100) if total_violations > 0 else 0

    lines = [
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total violations | {total_violations:,} |",
        f"| Violations covered by exceptions | {covered_violations:,} ({coverage_pct:.1f}%) |",
        f"| Violations not covered | {not_covered_violations:,} |",
        f"| Source CSV rows (per-image occurrences) | {analysis_result.total_csv_rows:,} |",
        f"| Components affected | {analysis_result.unique_components} |",
        f"| Unique violation codes | {total_rules} |",
    ]
    if analysis_result.upcoming_violations:
        lines.append(f"| Warnings becoming violations (21d) | {len(analysis_result.upcoming_violations)} |")
    lines.append("")
    lines.append(
        "> Each violation is a unique (violation code, component, semantic detail) triple "
        "representing one actionable work unit. The source CSV contains additional rows "
        "because each violation is checked against every container image build — the same "
        "violation appears once per image digest."
    )
    lines.append("")
    return "\n".join(lines)


def _violation_anchor(rule: str) -> str:
    """Return a stable HTML id for a violation section anchor.

    Replaces ``.`` and ``:`` with ``-`` so the anchor is safe in URI
    fragments (colons have special meaning; dots break CSS selectors).
    The ``violation-`` prefix scopes it away from any other document ids.

    Examples:
        hermetic_task.hermetic                        -> violation-hermetic_task-hermetic
        rpm_signature.allowed:9386b48a1a693c5c        -> violation-rpm_signature-allowed-9386b48a1a693c5c
    """
    safe = rule.replace(".", "-").replace(":", "-")
    return f"violation-{safe}"


def _render_coverage_table(coverage_data: dict) -> str:
    """Render the coverage table section.

    Violation names in the table are linked to their corresponding section
    in the Resolution Guide below using HTML id anchors.
    """
    md_table = coverage_data.get("markdown_table", "")

    # Replace each backtick-quoted rule name in the table with a link to its section.
    for v in coverage_data.get("violations", []):
        rule = v.get("rule", "")
        if not rule:
            continue
        anchor = _violation_anchor(rule)
        md_table = md_table.replace(
            f"`{rule}`",
            f"[`{rule}`](#{anchor})",
        )

    lines = [
        "## Violations Coverage",
        "",
        md_table,
        "",
    ]
    return "\n".join(lines)


def _render_work_scope(
    lines: list[str], rule: str, work_scope_by_rule: dict[str, dict], source_csv_url: str
) -> None:
    """Render a work-scope line showing unique items to fix and CSV link for details."""
    ws = work_scope_by_rule.get(rule)
    if not ws:
        return

    unique_items = ws.get("unique_items", 0)
    total_components = ws.get("total_components", 0)

    if unique_items <= 1 or total_components == 0:
        return

    avg = ws.get("per_component_avg", 0)

    if unique_items <= 2 * total_components:
        lines.append(
            f"**Scope of work**: {unique_items} unique work item{'s' if unique_items != 1 else ''} "
            f"across {total_components} component{'s' if total_components != 1 else ''}."
        )
    else:
        lines.append(
            f"**Scope of work**: {unique_items:,} unique work items across "
            f"{total_components} component{'s' if total_components != 1 else ''} "
            f"(avg ~{avg} per component). "
            f"For full per-item details, see the [source CSV]({source_csv_url})."
        )
    lines.append("")


def _render_resolution_guide(
    coverage_data: dict, catalog: dict,
    work_scope_by_rule: dict[str, dict] | None = None,
    source_csv_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
) -> str:
    """Render the per-violation resolution guide section."""
    violations = coverage_data.get("violations", [])
    component_owners = coverage_data.get("component_owners", {})
    lines = ["## Resolution Guide", ""]

    for i, v in enumerate(violations, 1):
        rule = v["rule"]
        total_components = v["total_components"]
        covered_count = v.get("covered_count", 0)
        coverage = v.get("coverage", "not_covered")

        anchor = _violation_anchor(rule)
        lines.append(
            f'### {i}. `{rule}` — {total_components} components '
            f'({covered_count}/{total_components} have exceptions) '
            f'<a id="{anchor}"></a>'
        )
        lines.append("")

        search_parts = []
        search_url = v.get("open_mr_search_url", "")
        if search_url:
            search_parts.append(f"[search GitLab]({search_url})")
        jira_search = v.get("open_jira_search_url", "")
        if jira_search:
            search_parts.append(f"[search Jira]({jira_search})")
        if search_parts:
            lines.append(" | ".join(search_parts))
            lines.append("")

        if coverage == "fully_covered":
            _render_excepted_violation(lines, v)
        else:
            if coverage == "partially_covered":
                _render_partial_coverage_header(lines, v)

            catalog_entry = _match_catalog_entry(rule, catalog)
            if catalog_entry:
                _render_cataloged_violation(lines, catalog_entry, v)
            else:
                fallback = _match_fallback_reference(rule, catalog)
                _render_uncataloged_violation(lines, v, fallback)

        _render_known_false_alerts(lines, rule, v, catalog)
        _render_work_scope(lines, rule, work_scope_by_rule or {}, source_csv_url)
        _render_components_table(
            lines, v, component_owners,
            policy_files=policy_files,
            slack_threads=v.get("open_slack_threads"),
            slack_search_url=v.get("open_slack_search_url", ""),
        )

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _render_excepted_violation(lines: list[str], violation: dict) -> None:
    """Render a compact block for a fully-excepted violation.

    Exception status is already in the property table above; this adds
    the next-step instruction and remedy hint.
    """
    next_steps = violation.get("next_steps") or _VERIFY_NEXT_STEP
    lines.append(f"**Next step**: {next_steps}")
    lines.append("")

    rule = violation.get("rule", "")
    lines.append(
        f"> For the underlying remediation procedure (e.g. after the exception expires), "
        f"use the `conforma-remedy` skill: *\"How to fix `{rule}`?\"*"
    )
    lines.append("")


def _component_stem(name: str) -> str:
    """Strip the RHOAI version suffix from a Konflux component name.

    The suffix always starts with ``-v{major}-{minor}`` (e.g. ``-v3-5``,
    ``-v3-5-ea-2``, ``-v2-25``).  Requiring two hyphen-separated digit groups
    after ``v`` prevents false-stripping on mid-name segments such as
    ``-vllm`` (letter follows v) or ``-cuda121`` (c follows cuda).

    Examples:
        odh-vllm-cpu-v3-5-ea-2               -> odh-vllm-cpu
        odh-workbench-jupyter-minimal-v3-4    -> odh-workbench-jupyter-minimal
        odh-pipeline-runtime-py312-v2-25      -> odh-pipeline-runtime-py312
        odh-generic-tool (no suffix)          -> odh-generic-tool  (unchanged)
    """
    return re.sub(r"-v\d+-\d+.*$", "", name)


def _render_components_table(
    lines: list[str],
    violation: dict,
    component_owners: dict,
    policy_files: list[dict[str, str]] | None = None,
    slack_threads: list[dict] | None = None,
    slack_search_url: str = "",
) -> None:
    """Render a per-component table with one row per component.

    Columns: Component | Team | Exception | Merge Requests | JIRAs | Slack (optional)
    """
    all_comps = violation.get("uncovered_components", []) + violation.get("covered_components", [])
    all_comps = sorted(set(all_comps))
    if not all_comps:
        return

    details_by_comp = {}
    for d in violation.get("exception_details_by_component", []):
        details_by_comp[d["component"]] = d

    # Build stem -> MR list mapping for fast per-component lookup (deduplicated by mr_iid).
    # Skip exception MRs with no_overlap — they are text-search false positives whose diff
    # covers a different rule.  Remedy MRs (mr_type="remedy") have empty mr_components by
    # design (they change source code, not policy files) and are intentionally excluded from
    # the per-component MR column (they have no component-level policy file association).
    mr_by_stem: dict[str, list[dict]] = {}
    for mr in violation.get("open_merge_requests", []):
        if mr.get("mr_type", "exception") == "exception" and mr.get("suggestion", "") == "no_overlap":
            continue
        for mr_comp in mr.get("mr_components", []):
            stem = _component_stem(mr_comp)
            existing = mr_by_stem.setdefault(stem, [])
            mr_id = mr.get("mr_iid") or mr.get("iid")
            if not any((e.get("mr_iid") or e.get("iid")) == mr_id for e in existing):
                existing.append(mr)

    jira_by_stem: dict[str, list[dict]] = {}
    unscoped_jiras: list[dict] = []
    for jira in violation.get("open_jira_tickets", []):
        stems = jira.get("matched_component_stems", [])
        if not stems:
            legacy = jira.get("matched_component_stem") or ""
            stems = [legacy] if legacy else []
        if stems:
            for stem in stems:
                jira_by_stem.setdefault(stem, []).append(jira)
        else:
            unscoped_jiras.append(jira)

    include_slack = slack_threads is not None
    if include_slack:
        if slack_threads:
            slack_parts = []
            for t in slack_threads[:3]:
                channel = t.get("channel", t.get("channel_name", ""))
                permalink = t.get("permalink", "")
                date = t.get("date", "")
                reply_info = f", {t['thread_reply_count']} replies" if t.get("thread_reply_count") else ""
                slack_parts.append(f"[#{channel}]({permalink}) ({date}{reply_info})")
            if len(slack_threads) > 3:
                slack_parts.append(f"+{len(slack_threads) - 3} more")
            slack_cell = ", ".join(slack_parts)
            if slack_search_url:
                slack_cell += f" ([search]({slack_search_url}))"
        elif slack_search_url:
            slack_cell = f"[search Slack]({slack_search_url})"
        else:
            slack_cell = "—"

    lines.append("")
    lines.append("**Components:**")
    lines.append("")
    if include_slack:
        lines.append("| Component | Team | Exception | Merge Requests | JIRAs | Slack |")
        lines.append("|-----------|------|-----------|----------------|-------|-------|")
    else:
        lines.append("| Component | Team | Exception | Merge Requests | JIRAs |")
        lines.append("|-----------|------|-----------|----------------|-------|")
    for comp in all_comps:
        team = component_owners.get(comp, "—")
        d = details_by_comp.get(comp)

        if d and d.get("url"):
            file_name = d.get("file", "")
            line_num = d.get("line")
            anchor = f"{file_name}#L{line_num}" if line_num else file_name
            expires = d.get("effective_until") or "permanent"
            exc_cell = (
                f"[{anchor}]({d['url']}) (expires {expires})"
                if expires != "permanent"
                else f"[{anchor}]({d['url']}) (permanent)"
            )
        elif d and d.get("effective_until"):
            exc_cell = f"covered (expires {d['effective_until']})"
        elif d and not d.get("url"):
            if policy_files:
                file_links = ", ".join(f"[{f['name']}]({f['url']})" for f in policy_files)
                exc_cell = f"not in {file_links}"
            else:
                exc_cell = "not in policy files"
        else:
            exc_cell = "not covered"

        comp_stem = _component_stem(comp)

        comp_mrs = mr_by_stem.get(comp_stem, [])
        if comp_mrs:
            mr_parts = []
            for mr in comp_mrs:
                link = f"[!{mr.get('mr_iid') or mr.get('iid', '?')}]({mr['url']})"
                if mr.get("discrepancy") == "code_only":
                    link += " ⚠️"
                mr_parts.append(link)
            mr_cell = ", ".join(mr_parts)
        else:
            mr_cell = "—"

        comp_jiras = jira_by_stem.get(comp_stem, [])
        jira_parts = [f"[{j['key']}]({j['url']})" for j in comp_jiras]
        if unscoped_jiras:
            jira_parts += [f"[{j['key']}]({j['url']}) (possibly related)" for j in unscoped_jiras]
        jira_cell = ", ".join(jira_parts) if jira_parts else "—"

        row = f"| `{comp}` | {team} | {exc_cell} | {mr_cell} | {jira_cell} |"
        if include_slack:
            row = f"| `{comp}` | {team} | {exc_cell} | {mr_cell} | {jira_cell} | {slack_cell} |"
        lines.append(row)
    lines.append("")


def _render_partial_coverage_header(lines: list[str], violation: dict) -> None:
    """Render a brief partial-coverage note before full remediation steps.

    Component list and exception details are already in the property table above.
    """
    covered = violation.get("covered_count", 0)
    total = violation.get("total_components", 0)
    uncovered = violation.get("uncovered_components", [])

    lines.append(
        f"**Partially covered**: {covered}/{total} components have exceptions. "
        f"{len(uncovered)} component(s) still need resolution."
    )
    lines.append("")


def _render_known_false_alerts(
    lines: list[str], rule: str, violation: dict, catalog: dict
) -> None:
    """Render known false alerts for a violation's components."""
    all_comps = violation.get("uncovered_components", []) + violation.get("covered_components", [])
    false_alert_comps = []
    for comp in all_comps:
        alert = _match_known_false_alert(rule, comp, catalog)
        if alert:
            false_alert_comps.append((comp, alert))

    if false_alert_comps:
        lines.append("**Known false alerts:**")
        for comp, alert in false_alert_comps:
            lines.append(f"- `{comp}`: {alert['title']} — {alert.get('condition', '')}")
        lines.append("")


def _render_cataloged_violation(lines: list[str], entry: dict, violation: dict) -> None:
    """Render resolution details for a violation with a catalog match."""
    classification = entry.get("classification", {})
    resolution_path = classification.get("resolution_path", "unknown")
    typical_owner = classification.get("typical_owner", "unknown")
    effort = classification.get("estimated_effort", "unknown")
    requires_rebuild = classification.get("requires_rebuild", False)

    lines.append(
        f"**Classification**: {resolution_path} | "
        f"Owner: {typical_owner} | "
        f"Effort: {effort} | "
        f"Requires rebuild: {'yes' if requires_rebuild else 'no'}"
    )
    lines.append("")

    fix_steps = entry.get("fix_steps", [])
    if fix_steps:
        lines.append("**Resolution:**")
        for j, step in enumerate(fix_steps, 1):
            action = step.get("action", "")
            ref = step.get("reference", "")
            where = step.get("where", "")
            line = f"{j}. {action}"
            if ref:
                line += f" — [docs]({ref})"
            if where:
                line += f" (in: {where})"
            lines.append(line)
        lines.append("")

    exception_ctx = entry.get("exception_context", {})
    when_to_exception = exception_ctx.get("when_to_exception", "")
    if when_to_exception:
        lines.append(f"**Exception only if**: {when_to_exception}")
        lines.append("")


def _render_uncataloged_violation(lines: list[str], violation: dict, fallback: dict | None) -> None:
    """Render resolution details for a violation without a catalog match."""
    title = violation.get("title", "")

    lines.append("**Note**: Not in violation catalog — using fallback references.")
    lines.append("")

    if title:
        lines.append(f"**From report**: {title}")
        lines.append("")

    if fallback:
        doc_urls = fallback.get("doc_urls", [])
        guidance = fallback.get("guidance", "")

        if doc_urls:
            lines.append("**References:**")
            for url in doc_urls:
                lines.append(f"- [{url}]({url})")
            lines.append("")

        if guidance:
            lines.append(f"**Guidance**: {guidance}")
            lines.append("")
    else:
        lines.append(
            "**Guidance**: No resolution guidance available. Investigate the build logs and Konflux documentation."
        )
        lines.append("")


def _render_warnings_section(analysis_result: analysis.AnalysisResult, component_owners: dict) -> str:
    """Render warnings becoming violations section."""
    if not analysis_result.upcoming_violations:
        return ""

    lines = [
        "## Warnings Becoming Violations",
        "",
        f"**{len(analysis_result.upcoming_violations)}** current warnings will become "
        "enforced violations once their enforcement date passes.",
        "",
        "| Code | Count | Deadline | Days Left | Components |",
        "|------|-------|----------|-----------|------------|",
    ]

    for code, info in sorted(
        analysis_result.upcoming_by_code.items(),
        key=lambda x: x[1]["min_days_remaining"],
    ):
        days = info["min_days_remaining"]
        urgency = "**OVERDUE**" if days == 0 else str(days)
        comps = ", ".join(f"`{c}`" for c in info["affected_components"][:5])
        if len(info["affected_components"]) > 5:
            comps += f" +{len(info['affected_components']) - 5} more"
        lines.append(f"| `{code}` | {info['count']} | {info['earliest_effective_on']} | {urgency} | {comps} |")

    lines.append("")
    return "\n".join(lines)


def _render_statistical_breakdown(
    analysis_result: analysis.AnalysisResult,
    component_owners: dict[str, str | None],
) -> str:
    """Render the statistical breakdown section using analyze_csv_report's format_markdown."""
    md = analysis.format_markdown(analysis_result, component_owners)
    md = md.replace("# Conforma Violations Analysis", "## Statistical Breakdown", 1)
    return md


def _render_tooling_health(tooling_health_data: dict) -> str:
    """Render the Tooling Health section from tooling-health.json data."""
    tools = tooling_health_data.get("tools", [])
    if not tools:
        return ""

    lines = ["## Tooling Health", ""]
    lines.append("| Tool | Status | Latest Run | Consecutive Failures | Last Success |")
    lines.append("|------|--------|------------|---------------------|--------------|")

    for tool in tools:
        name = tool.get("name", "unknown")
        health = tool.get("health", {})
        status = health.get("status", "unknown").upper()
        consecutive = health.get("consecutive_failures", 0)

        latest_run = tool.get("latest_run")
        if latest_run:
            run_id = latest_run.get("id", "")
            run_url = latest_run.get("url", "")
            conclusion = latest_run.get("conclusion") or latest_run.get("status", "")
            run_date = latest_run.get("updated_at", "")[:10]
            latest_cell = f"[#{run_id}]({run_url}) -- {conclusion} ({run_date})"
        else:
            latest_cell = "N/A"

        last_success = health.get("last_success")
        if last_success:
            ls_id = last_success.get("id", "")
            ls_url = last_success.get("url", "")
            ls_date = last_success.get("completed_at", "")[:10]
            success_cell = f"[#{ls_id}]({ls_url}) ({ls_date})"
        else:
            success_cell = "None found"

        lines.append(f"| {name} | {status} | {latest_cell} | {consecutive} | {success_cell} |")

    unhealthy_tools = [t for t in tools if t.get("health", {}).get("status") in ("unhealthy", "error")]
    if unhealthy_tools:
        names = ", ".join(t.get("name", "unknown") for t in unhealthy_tools)
        lines.extend([
            "",
            f"> The violation data in this report may be stale because the {names} workflow is failing.",
        ])

    lines.append("")
    return "\n".join(lines)


_EXTERNAL_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^)]+)\)")


def _open_links_in_new_tab(content: str) -> str:
    """Convert external markdown links to HTML <a> tags with target="_blank".

    Internal anchor links (``#section``) are left as markdown.
    """
    def _replace(m: re.Match) -> str:
        label = m.group(1)
        url = m.group(2)
        return f'<a href="{url}" target="_blank">{label}</a>'

    return _EXTERNAL_MD_LINK_RE.sub(_replace, content)


def _tooling_health_executive_line(tooling_health_data: dict) -> str | None:
    """Generate a one-liner for the Executive Summary when tooling is unhealthy."""
    tools = tooling_health_data.get("tools", [])
    unhealthy = [t for t in tools if t.get("health", {}).get("status") in ("unhealthy", "error")]
    if not unhealthy:
        return None

    parts = []
    for tool in unhealthy:
        name = tool.get("name", "unknown")
        health = tool.get("health", {})
        last_success = health.get("last_success")
        latest_run = tool.get("latest_run")

        ls_info = ""
        if last_success:
            ls_date = last_success.get("completed_at", "")[:10]
            ls_info = f", last success: {ls_date}"

        run_link = ""
        if latest_run and latest_run.get("url"):
            run_link = f" [view run]({latest_run['url']})"

        parts.append(f"{name} workflow failing{ls_info}{run_link}")

    return f"- **Tooling unhealthy** -- {'; '.join(parts)}"


def _write_executive_summary(
    output_path: str,
    *,
    metadata_header: str,
    tooling_health: str,
    key_takeaways: str,
    summary_metrics: str,
    guide_path: str | None,
    analysis_path: str | None,
) -> None:
    """Write a compact executive summary suitable for chat display.

    Contains the metadata header, tooling health warning (if any), the
    executive summary bullets, the summary metrics table, and links to
    the detailed documents.  The guide_path is filled in by main() after
    the guide file is written (it's not known inside generate_resolution_guide).
    """
    sections = [metadata_header, tooling_health, key_takeaways, summary_metrics]
    content = "\n".join(s for s in sections if s)

    doc_lines = ["## Detailed Documents", ""]
    if guide_path:
        doc_lines.append(f"- **Resolution Guide**: `{guide_path}`")
    if analysis_path:
        doc_lines.append(f"- **Analysis Output**: `{analysis_path}`")
    if guide_path or analysis_path:
        doc_lines.append("")

    content = content.rstrip("\n") + "\n\n" + "\n".join(doc_lines)
    content = _open_links_in_new_tab(content)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Executive summary written to {path}", file=sys.stderr)


def generate_resolution_guide(
    violations_yaml_path: str,
    coverage_json_path: str,
    reports_dir: str,
    catalog_path: str,
    release: str,
    source_path: str,
    source_created_at: str,
    source_sha: str = "",
    policy_dir_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
    tooling_health_path: str | None = None,
    executive_summary_file: str | None = None,
    analysis_output_file: str | None = None,
    end_of_support: str = "",
) -> str:
    """Generate the full resolution guide markdown content.

    When ``executive_summary_file`` is provided, also writes a compact
    executive summary (metadata header, tooling health warning, key
    takeaways, summary metrics, and links to the detailed documents) to
    that path.  The ``analysis_output_file`` path is embedded in the
    executive summary as a clickable link; pass the path where the
    analysis markdown was saved (step 6 output).
    """
    violations_yaml = Path(violations_yaml_path)
    coverage_json = Path(coverage_json_path)
    reports = Path(reports_dir)
    catalog_file = Path(catalog_path)

    if not violations_yaml.exists():
        raise FileNotFoundError(f"Violations YAML not found: {violations_yaml}")
    if not coverage_json.exists():
        raise FileNotFoundError(f"Coverage JSON not found: {coverage_json}")
    if not reports.is_dir():
        raise FileNotFoundError(f"Reports directory not found: {reports}")
    if not catalog_file.exists():
        raise FileNotFoundError(f"Violation catalog not found: {catalog_file}")

    coverage_data = json.loads(coverage_json.read_text(encoding="utf-8"))
    catalog = _load_catalog(catalog_file)

    # Load component ownership from violations YAML
    viol_data = yaml.safe_load(violations_yaml.read_text(encoding="utf-8"))
    component_owners: dict[str, str | None] = {}
    by_component = viol_data.get("violation_data", {}).get("violations_by_component", {})
    for comp, info in by_component.items():
        jc = info.get("jira_component")
        if jc is not None:
            component_owners[comp] = jc

    # Load tooling health data if provided
    tooling_health_data: dict | None = None
    if tooling_health_path:
        th_path = Path(tooling_health_path)
        if th_path.exists():
            try:
                tooling_health_data = json.loads(th_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    # Run statistical analysis
    records = analysis.load_reports_dir(reports)
    warnings = analysis.load_warnings_dir(reports)
    analysis_result = analysis.analyze(records, upcoming=warnings)

    # Assemble sections
    ref = source_sha or release
    source_csv_url = f"https://github.com/{CONFORMA_REPORTER_REPO}/blob/{ref}/{source_path}"

    # Extract work_scope per rule from violations YAML
    work_scope_by_rule: dict[str, dict] = {}
    by_rule_data = viol_data.get("violation_data", {}).get("violations_by_rule", {})
    for rule, rule_info in by_rule_data.items():
        ws = rule_info.get("work_scope")
        if ws:
            work_scope_by_rule[rule] = ws

    counts = conforma_counting.count_from_records(records, code_field="code")

    metadata_header = _render_metadata_header(release, source_path, source_created_at, source_sha, policy_dir_url, policy_files, end_of_support=end_of_support)
    tooling_health = _render_tooling_health(tooling_health_data) if tooling_health_data else ""
    key_takeaways = _render_key_takeaways(coverage_data, analysis_result, counts.by_component_rule, tooling_health_data, violations_yaml_data=viol_data)
    summary_metrics = _render_summary(coverage_data, analysis_result, counts.by_component_rule)

    sections = [
        metadata_header,
        tooling_health,
        key_takeaways,
        summary_metrics,
        _render_coverage_table(coverage_data),
        _render_resolution_guide(coverage_data, catalog, work_scope_by_rule, source_csv_url, policy_files=policy_files),
        _render_warnings_section(analysis_result, component_owners),
        _render_statistical_breakdown(analysis_result, component_owners),
    ]

    guide = "\n".join(s for s in sections if s)
    guide = _open_links_in_new_tab(guide)

    if executive_summary_file:
        _write_executive_summary(
            executive_summary_file,
            metadata_header=metadata_header,
            tooling_health=tooling_health,
            key_takeaways=key_takeaways,
            summary_metrics=summary_metrics,
            guide_path=None,
            analysis_path=analysis_output_file,
        )

    return guide


def _find_default_catalog() -> Path:
    """Find the default violation catalog relative to this script."""
    here = Path(__file__).resolve().parent
    # scripts/ -> conforma-analyze/ -> skills/ -> repo/skills/references/
    candidate = here.parent.parent / "references" / "violation-catalog.yaml"
    if candidate.exists():
        return candidate
    # Try from repo root
    repo_root = here.parent.parent.parent
    candidate2 = repo_root / "skills" / "references" / "violation-catalog.yaml"
    if candidate2.exists():
        return candidate2
    raise FileNotFoundError("Cannot find violation-catalog.yaml. Use --catalog to specify its path.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a unified Conforma Resolution Guide")
    parser.add_argument("--violations-yaml", required=True, help="Path to parsed violations YAML")
    parser.add_argument("--coverage-json", required=True, help="Path to coverage check JSON output")
    parser.add_argument("--reports-dir", required=True, help="Directory containing CSV reports")
    parser.add_argument(
        "--catalog",
        default=None,
        help="Path to violation-catalog.yaml (default: auto-detect)",
    )
    parser.add_argument("--release", required=True, help="Release name (e.g. rhoai-3.5-ea.2)")
    parser.add_argument(
        "--source-path",
        required=True,
        help="CSV source path in the repo (e.g. prod/release_day/conforma-violations-report.csv)",
    )
    parser.add_argument(
        "--source-created-at",
        required=True,
        help="When the source CSV was generated (ISO timestamp)",
    )
    parser.add_argument(
        "--source-sha",
        default="",
        help="Git commit SHA of the source CSV (for permalink URL)",
    )
    parser.add_argument(
        "--policy-dir-url",
        default="",
        help="URL to the conforma policy directory in konflux-release-data (from resolve_release_context.py)",
    )
    parser.add_argument(
        "--policy-files-json",
        default="",
        help='JSON array of {name, url} objects for policy config files (from resolve_release_context.py links.policy_files)',
    )
    parser.add_argument(
        "--end-of-support",
        default="",
        help="Release end-of-support date (YYYY-MM-DD) from resolve_release_context.py",
    )
    parser.add_argument(
        "--tooling-health-json",
        default=None,
        help="Path to tooling-health.json from check_tooling_health.py (optional)",
    )
    parser.add_argument("--output", required=True, help="Output file path")
    parser.add_argument(
        "--executive-summary-file",
        default=None,
        help="Path to write a compact executive summary (for chat display). "
        "Includes metadata, key takeaways, summary metrics, and links to detailed documents.",
    )
    parser.add_argument(
        "--analysis-output-file",
        default=None,
        help="Path to the analysis output markdown file (step 6 output). "
        "Embedded as a link in the executive summary.",
    )
    args = parser.parse_args()

    catalog_path = args.catalog or str(_find_default_catalog())

    policy_files = None
    if args.policy_files_json:
        try:
            policy_files = json.loads(args.policy_files_json)
        except json.JSONDecodeError:
            print("WARNING: --policy-files-json is not valid JSON, ignoring", file=sys.stderr)

    try:
        content = generate_resolution_guide(
            violations_yaml_path=args.violations_yaml,
            coverage_json_path=args.coverage_json,
            reports_dir=args.reports_dir,
            catalog_path=catalog_path,
            release=args.release,
            source_path=args.source_path,
            source_created_at=args.source_created_at,
            source_sha=args.source_sha,
            policy_dir_url=args.policy_dir_url,
            policy_files=policy_files,
            tooling_health_path=args.tooling_health_json,
            executive_summary_file=args.executive_summary_file,
            analysis_output_file=args.analysis_output_file,
            end_of_support=args.end_of_support,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Resolution guide written to {output_path}", file=sys.stderr)

    if args.executive_summary_file:
        es_path = Path(args.executive_summary_file)
        if es_path.exists():
            es_content = es_path.read_text(encoding="utf-8")
            guide_link = f"- **Resolution Guide**: `{output_path}`"
            if "## Detailed Documents" in es_content and guide_link not in es_content:
                es_content = es_content.replace(
                    "## Detailed Documents\n",
                    f"## Detailed Documents\n\n{guide_link}\n",
                    1,
                )
                es_path.write_text(es_content, encoding="utf-8")

    print(json.dumps({"output": str(output_path), "release": args.release}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
