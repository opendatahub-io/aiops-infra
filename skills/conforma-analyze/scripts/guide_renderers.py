"""Resolution guide renderers — pure functions that take data and return markdown."""

from __future__ import annotations

from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import conforma_context_ops  # noqa: E402
import conforma_counting  # noqa: E402
import release_dates  # noqa: E402
import yaml  # noqa: E402
from parse_violations import build_semantic_detail_lookup  # noqa: E402
import analyze_csv_report as analysis  # noqa: E402
from conforma_constants import (  # noqa: E402
    CONFORMA_REPORTER_URL,
    VERIFY_NEXT_STEP,
)


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


def render_metadata_header(
    release: str,
    source_path: str,
    source_created_at: str,
    source_sha: str = "",
    policy_dir_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
    end_of_support: str = "",
    confirmation_display: str = "",
    title_prefix: str = "Conforma Status and Resolution Guide",
    code_freeze_date: str = "",
    upcoming_release_date: str = "",
    total_violations: int | None = None,
) -> str:
    """Render the document metadata header."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ref = source_sha or release
    source_url = f"{CONFORMA_REPORTER_URL}/blob/{ref}/{source_path}"

    lines = [f"# {title_prefix}: {release}", ""]

    if confirmation_display:
        display = confirmation_display.rstrip()
        display_lines = display.split("\n")
        while display_lines and (not display_lines[-1].strip() or display_lines[-1].strip().startswith("*Source:")):
            display_lines.pop()
        lines.append("\n".join(display_lines))
    else:
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| **Release branch** | {release} |")
        if end_of_support:
            version_label = release_dates.format_version_label(release)
            _, eos_source = release_dates.get_eos_date_with_source(release)
            eos_source_text = f" based on {eos_source}," if eos_source else ""
            lines.append(
                f"| **End of support for {version_label}** | {end_of_support}"
                f" —{eos_source_text}"
                f" verify on [Product Pages]({release_dates.PRODUCT_PAGES_URL}) |"
            )
        if code_freeze_date and upcoming_release_date and code_freeze_date > upcoming_release_date:
            version_label = release_dates.format_version_label(release)
            lines.append(
                f"| **Code freeze ({version_label})** | Already passed"
                f" (next code freeze {code_freeze_date} is for a future release) |"
            )
        elif code_freeze_date:
            version_label = release_dates.format_version_label(release)
            _, cf_source = release_dates.get_code_freeze_date_with_source(release)
            cf_source_text = f" based on {cf_source}," if cf_source else ""
            lines.append(
                f"| **Code freeze ({version_label})** | {code_freeze_date}"
                f" —{cf_source_text}"
                f" verify on [Product Pages]({release_dates.PRODUCT_PAGES_URL}) |"
            )
        elif not code_freeze_date and upcoming_release_date:
            version_label = release_dates.format_version_label(release)
            lines.append(
                f"| **Code freeze ({version_label})** | Already passed"
                f" (not found in rhai-release-data.yaml) |"
            )
        if upcoming_release_date:
            version_label = release_dates.format_version_label(release)
            _, upcoming_source = release_dates.get_upcoming_release_date_with_source(release)
            upcoming_source_text = f" based on {upcoming_source}," if upcoming_source else ""
            lines.append(
                f"| **Upcoming release date ({version_label})** | {upcoming_release_date}"
                f" —{upcoming_source_text}"
                f" verify on [Product Pages]({release_dates.PRODUCT_PAGES_URL}) |"
            )
        if policy_files:
            file_links = ", ".join(f"[{f['name']}]({f['url']})" for f in policy_files)
            lines.append(f"| **Conforma policy config** | {file_links} |")
        elif policy_dir_url:
            lines.append(f"| **Conforma policy config** | [policy directory]({policy_dir_url}) |")

    lines.append(f"| **Generated** | {now} |")
    lines.append(f"| **Source CSV** | [{source_path}]({source_url}) |")
    if source_created_at:
        lines.append(f"| **Source CSV generated** | {source_created_at} |")
    if total_violations is not None:
        lines.append(f"| **Total violations** | {total_violations} |")

    import getpass
    import socket
    user_host = f"{getpass.getuser()}@{socket.gethostname()}"

    lines += [
        "",
        "*Generated by: aiops-infra conforma-analyze skill*",
        "",
        f"*Run by: {user_host}*",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def render_key_takeaways(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
    tooling_health_data: dict | None = None,
    violations_yaml_data: dict | None = None,
    upcoming_release_date: str = "",
    policy_files: list[dict[str, str]] | None = None,
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
        unhealthy_tools = [t for t in tooling_health_data.get("tools", []) if t.get("health", {}).get("status") in ("unhealthy", "error")]
        if unhealthy_tools:
            names = ", ".join(t.get("name", "unknown") for t in unhealthy_tools)
            lines.append(f"- **⚠ WARNING: The violation data in this report may be stale because the {names} workflow is failing.**")

    detail_lookup, detail_labels = build_semantic_detail_lookup(violations_yaml_data) if violations_yaml_data else ({}, {})

    def _format_violation_cell(rule: str, comp: str) -> str:
        base_rule = rule.split(":")[0]
        details = detail_lookup.get((base_rule, comp), [])
        anchor = _violation_anchor(rule)
        rule_link = f"[`{rule}`](#{anchor})"
        if len(details) == 0:
            return rule_link
        if len(details) == 1:
            return f"{rule_link} ({details[0]})"
        if len(details) <= 20:
            return f"{rule_link} ({', '.join(details)})"
        label = detail_labels.get(base_rule, "items")
        return f"{rule_link} ({', '.join(details[:10])} ... +{len(details) - 10} more {label}s)"

    def _find_covering_mr(mrs: list[dict], component: str) -> dict | None:
        for mr in mrs:
            if component in mr.get("mr_components", []):
                return mr
        return None

    def _violation_count(rule: str, component: str) -> int:
        return (
            by_component_rule.get((rule, component), 0)
            or by_component_rule.get((rule.split(":")[0], component), 0)
            or 1
        )

    # 1) Collect ALL components without an exception (from not_covered AND partially_covered codes)
    uncovered_entries: list[dict] = []
    for v in violations:
        coverage = v.get("coverage", "not_covered")
        if coverage == "fully_covered":
            continue
        rule = v["rule"]
        uncovered_comps = v.get("uncovered_components", [])
        mrs = v.get("open_merge_requests", [])
        for comp in uncovered_comps:
            uncovered_entries.append({
                "rule": rule,
                "component": comp,
                "violation_count": _violation_count(rule, comp),
                "mr": _find_covering_mr(mrs, comp),
            })

    no_mr_entries = [e for e in uncovered_entries if not e["mr"]]
    has_mr_entries = [e for e in uncovered_entries if e["mr"]]
    no_mr_violation_count = sum(e["violation_count"] for e in no_mr_entries)
    has_mr_violation_count = sum(e["violation_count"] for e in has_mr_entries)

    table_num = 0

    # 1a) Violations with no exception and no open Merge Request (highest risk)
    table_num += 1
    lines.append(
        f"- **Table {table_num}.** — **{no_mr_violation_count:,} violations without exception or open Merge Request**:"
    )
    lines.append("")
    lines.append("| # | Violation | Component | Violations |")
    lines.append("|--:|-----------|-----------|:----------:|")
    if no_mr_entries:
        for row_num, entry in enumerate(no_mr_entries, 1):
            violation_cell = _format_violation_cell(entry["rule"], entry["component"])
            lines.append(f"| {row_num} | {violation_cell} | `{entry['component']}` | {entry['violation_count']} |")
    else:
        lines.append("| | No violations | | |")
    lines.append("")
    lines.append("&nbsp;")

    # 2) Exceptions expiring before the upcoming release date — split into 3 risk tiers
    if upcoming_release_date:
        try:
            upcoming_dt = datetime.strptime(upcoming_release_date, "%Y-%m-%d").date()
        except ValueError:
            upcoming_dt = None

        if upcoming_dt:
            expiring_no_mr: list[dict] = []
            expiring_mr_insufficient: list[dict] = []
            expiring_mr_sufficient: list[dict] = []
            for v in violations:
                if v.get("coverage") != "fully_covered":
                    continue
                expiry = v.get("exception_expiry", {})
                if expiry.get("is_permanent"):
                    continue
                rule = v["rule"]
                details = v.get("exception_details_by_component", [])
                mrs = v.get("open_merge_requests", [])
                for d in details:
                    eu = d.get("effective_until")
                    if not eu:
                        continue
                    try:
                        eu_date = datetime.strptime(eu[:10], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if eu_date < upcoming_dt:
                        comp = d.get("component", "")
                        entry = {
                            "rule": rule,
                            "component": comp,
                            "violation_count": _violation_count(rule, comp),
                            "effective_until": eu[:10],
                        }
                        covering_mr = _find_covering_mr(mrs, comp)
                        if not covering_mr:
                            expiring_no_mr.append(entry)
                        else:
                            mr_eu = covering_mr.get("effective_until")
                            mr_eu_ok = False
                            if mr_eu:
                                try:
                                    mr_eu_date = datetime.strptime(mr_eu[:10], "%Y-%m-%d").date()
                                    mr_eu_ok = mr_eu_date >= upcoming_dt
                                except ValueError:
                                    pass
                            entry["mr"] = covering_mr
                            entry["mr_effective_until"] = mr_eu
                            if mr_eu_ok:
                                expiring_mr_sufficient.append(entry)
                            else:
                                expiring_mr_insufficient.append(entry)

            # 2a) Expiring exceptions with no open Merge Request
            expiring_no_mr_count = sum(e["violation_count"] for e in expiring_no_mr)
            table_num += 1
            lines.append(
                f"- **Table {table_num}.** — **{expiring_no_mr_count:,} violations covered by currently active exceptions "
                f"that expire before the upcoming release date ({upcoming_release_date}) "
                f"and not addressed by any open Merge Request**:"
            )
            lines.append("")
            lines.append("| # | Violation | Component | Violations | Effective Until in Existing Exception |")
            lines.append("|--:|-----------|-----------|:----------:|-----------------|")
            if expiring_no_mr:
                for row_num, entry in enumerate(expiring_no_mr, 1):
                    violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                    lines.append(
                        f"| {row_num} | {violation_cell} | `{entry['component']}` "
                        f"| {entry['violation_count']} | {entry['effective_until']} |"
                    )
            else:
                lines.append("| | No violations | | | |")
            lines.append("")
            lines.append("&nbsp;")

            # 2b) Expiring exceptions with open Merge Request but MR expiry also before release
            expiring_mr_insuf_count = sum(e["violation_count"] for e in expiring_mr_insufficient)
            table_num += 1
            lines.append(
                f"- **Table {table_num}.** — **{expiring_mr_insuf_count:,} violations covered by currently active exceptions "
                f"that expire before the upcoming release date ({upcoming_release_date}) "
                f"— open Merge Request exists but its proposed exception also expires before the release date**:"
            )
            lines.append("")
            lines.append("| # | Violation | Component | Violations | Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request |")
            lines.append("|--:|-----------|-----------|:----------:|--------------------------------------|------------------------------------------------|---------------|")
            if expiring_mr_insufficient:
                for row_num, entry in enumerate(expiring_mr_insufficient, 1):
                    violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                    mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
                    mr_eu_display = entry.get("mr_effective_until") or "unknown"
                    lines.append(
                        f"| {row_num} | {violation_cell} | `{entry['component']}` "
                        f"| {entry['violation_count']} | {entry['effective_until']} | {mr_eu_display} | {mr_link} |"
                    )
            else:
                lines.append("| | No violations | | | | | |")
            lines.append("")
            lines.append("&nbsp;")

            # 2c) Expiring exceptions with open Merge Request extending past release (lower risk)
            expiring_mr_suf_count = sum(e["violation_count"] for e in expiring_mr_sufficient)
            table_num += 1
            lines.append(
                f"- **Table {table_num}.** — **{expiring_mr_suf_count:,} violations covered by currently active exceptions "
                f"that expire before the upcoming release date ({upcoming_release_date}) "
                f"— addressed by open Merge Requests extending past the release date**:"
            )
            lines.append("")
            lines.append("| # | Violation | Component | Violations | Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request |")
            lines.append("|--:|-----------|-----------|:----------:|--------------------------------------|------------------------------------------------|---------------|")
            if expiring_mr_sufficient:
                for row_num, entry in enumerate(expiring_mr_sufficient, 1):
                    violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                    mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
                    mr_eu_display = entry.get("mr_effective_until") or "unknown"
                    lines.append(
                        f"| {row_num} | {violation_cell} | `{entry['component']}` "
                        f"| {entry['violation_count']} | {entry['effective_until']} | {mr_eu_display} | {mr_link} |"
                    )
            else:
                lines.append("| | No violations | | | | | |")
            lines.append("")
            lines.append("&nbsp;")

    # 3) Violations with no exception but having an open Merge Request
    table_num += 1
    lines.append(
        f"- **Table {table_num}.** — **{has_mr_violation_count:,} violations addressed** by open Merge Requests (not yet merged):"
    )
    lines.append("")
    lines.append("| # | Violation | Component | Violations | Merge Request |")
    lines.append("|--:|-----------|-----------|:----------:|---------------|")
    if has_mr_entries:
        for row_num, entry in enumerate(has_mr_entries, 1):
            violation_cell = _format_violation_cell(entry["rule"], entry["component"])
            mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
            lines.append(f"| {row_num} | {violation_cell} | `{entry['component']}` | {entry['violation_count']} | {mr_link} |")
    else:
        lines.append("| | No violations | | | |")
    lines.append("")
    lines.append("&nbsp;")

    # 5) Violations covered by exceptions
    coverage_line = f"- **{covered_violations:,} of {total_violations:,} violations ({coverage_pct:.1f}%) covered** by exceptions"
    if policy_files:
        file_links = " · ".join(f"[{f['name']}]({f['url']})" for f in policy_files)
        coverage_line += f" in {file_links}"
    lines.append(coverage_line)

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
                rule = v["rule"]
                exception_details = v.get("exception_details_by_component", [])
                exception_values: set[str] = set()
                for ed in exception_details:
                    ev = ed.get("exception_value", "")
                    if ev and ev != rule:
                        exception_values.add(ev)
                detail_suffix = f" ({', '.join(sorted(exception_values))})" if exception_values else ""
                expiring_soon.append((rule, expiry_date.strftime("%Y-%m-%d"), days_left, detail_suffix))
        except (ValueError, TypeError):
            continue

    if expiring_soon:
        expiring_soon.sort(key=lambda x: x[2])
        parts = [f"`{rule}`{detail} (expires {date}, {days}d)" for rule, date, days, detail in expiring_soon]
        lines.append(f"- **Exceptions expiring in next {expiry_threshold_days} days**: {', '.join(parts)}")

    if analysis_result.upcoming_violations:
        lines.append(
            f"- **{len(analysis_result.upcoming_violations)} warnings becoming violations** "
            "within 21 days"
        )

    ec_validation = coverage_data.get("ec_validation", {})
    divergence_count = ec_validation.get("divergence_count", 0)
    if divergence_count > 0:
        lines.append(
            f"- **⚠ {divergence_count} violation{'s' if divergence_count != 1 else ''} "
            f"in the source report not evaluated by Conforma now** — the Conforma policy "
            f"has changed since the report was generated. Coverage for these violations "
            f"could not be verified automatically. See the Resolution Guide for details."
        )

    lines.append("")
    return "\n".join(lines)


def render_summary(
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


def render_coverage_table(coverage_data: dict) -> str:
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


def render_work_scope(
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


def render_resolution_guide(
    coverage_data: dict, catalog: dict,
    work_scope_by_rule: dict[str, dict] | None = None,
    source_csv_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
    detail_lookup: dict[tuple[str, str], list[str]] | None = None,
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

        base_rule = rule.split(":")[0]
        all_comps = v.get("all_components", [])
        unique_details: list[str] = []
        if detail_lookup:
            seen: set[str] = set()
            for comp in all_comps:
                for d in detail_lookup.get((base_rule, comp), []):
                    if d not in seen:
                        seen.add(d)
                        unique_details.append(d)
        detail_suffix = f" ({', '.join(unique_details)})" if unique_details else ""

        anchor = _violation_anchor(rule)
        lines.append(
            f'### {i}. `{rule}`{detail_suffix} — {total_components} components '
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

        render_divergence_warning(lines, v)

        if coverage == "fully_covered":
            render_excepted_violation(lines, v)
        else:
            if coverage == "partially_covered":
                render_partial_coverage_header(lines, v)

            catalog_entry = _match_catalog_entry(rule, catalog)
            if catalog_entry:
                render_cataloged_violation(lines, catalog_entry, v)
            else:
                fallback = _match_fallback_reference(rule, catalog)
                render_uncataloged_violation(lines, v, fallback)

        render_known_false_alerts(lines, rule, v, catalog)
        render_work_scope(lines, rule, work_scope_by_rule or {}, source_csv_url)
        render_components_table(
            lines, v, component_owners,
            policy_files=policy_files,
            slack_threads=v.get("open_slack_threads"),
            slack_search_url=v.get("open_slack_search_url", ""),
        )

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_divergence_warning(lines: list[str], violation: dict) -> None:
    """Render a warning when ec does not evaluate some violations from the source report."""
    divergences = violation.get("ec_divergences", [])
    if not divergences:
        return

    affected = sorted(set(d["component"] for d in divergences))
    lines.append(
        f"> **⚠ Policy divergence** ({len(divergences)} component{'s' if len(divergences) != 1 else ''}): "
        f"The source CSV report lists `{violation['rule']}` as a violation for "
        f"{', '.join(f'`{c}`' for c in affected)}, but running Conforma now does not "
        f"evaluate this rule for {'these components' if len(affected) != 1 else 'this component'}. "
        f"This means the Conforma policy has changed since the report was generated — "
        f"the rule may have been renamed, removed from the policy bundle, or encountered "
        f"an evaluation error. Exception coverage for the affected components could not be "
        f"verified automatically and should be checked manually."
    )
    lines.append("")


def render_excepted_violation(lines: list[str], violation: dict) -> None:
    """Render a compact block for a fully-excepted violation.

    Exception status is already in the property table above; this adds
    the next-step instruction and remedy hint.
    """
    next_steps = violation.get("next_steps") or VERIFY_NEXT_STEP
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


def render_components_table(
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


def render_partial_coverage_header(lines: list[str], violation: dict) -> None:
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


def render_known_false_alerts(
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


def render_cataloged_violation(lines: list[str], entry: dict, violation: dict) -> None:
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


def render_uncataloged_violation(lines: list[str], violation: dict, fallback: dict | None) -> None:
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


def render_warnings_section(analysis_result: analysis.AnalysisResult, component_owners: dict) -> str:
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


def render_statistical_breakdown(
    analysis_result: analysis.AnalysisResult,
    component_owners: dict[str, str | None],
) -> str:
    """Render the statistical breakdown section using analyze_csv_report's format_markdown."""
    md = analysis.format_markdown(analysis_result, component_owners)
    md = md.replace("# Conforma Violations Analysis", "## Statistical Breakdown", 1)
    return md


def render_tooling_health(tooling_health_data: dict) -> str:
    """Render the Tooling Health section from tooling-health.json data.

    Prefers the pre-rendered ``display`` field produced by
    ``check_tooling_health._render_display()`` so the table format is
    consistent across interactive prompts and the resolution guide.
    Falls back to inline rendering for older JSON files that lack the field.
    """
    display = tooling_health_data.get("display", "")
    if display:
        return f"## Tooling Health\n\n{display}"

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
            f"**⚠ WARNING: The violation data in this report may be stale because the {names} workflow is failing.**",
        ])

    lines.append("")
    return "\n".join(lines)


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

        if last_success:
            ls_timestamp = last_success.get("completed_at", "")[:16].replace("T", " ")
            ls_url = last_success.get("url")
            ls_label = f"[{ls_timestamp}]({ls_url})" if ls_url else ls_timestamp
        else:
            ls_label = "unknown"
        ls_info = f", last success: {ls_label}"

        fail_info = ""
        if latest_run:
            fail_timestamp = latest_run.get("updated_at", latest_run.get("created_at", ""))[:16].replace("T", " ")
            fail_url = latest_run.get("url")
            fail_label = f"[{fail_timestamp}]({fail_url})" if fail_url else fail_timestamp
            fail_info = f", latest failure: {fail_label}"

        parts.append(f"{name} workflow failing{ls_info}{fail_info}")

    return f"- **Tooling unhealthy** -- {'; '.join(parts)}"


def write_executive_summary(
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
    SECTION_SPACER = "\n&nbsp;\n"
    sections = [metadata_header, key_takeaways, summary_metrics, tooling_health]
    content = SECTION_SPACER.join(s for s in sections if s)

    doc_lines = [SECTION_SPACER, "## Detailed Documents", ""]
    if guide_path:
        doc_lines.append(f"- **Resolution Guide**: `{guide_path}`")
    if analysis_path:
        doc_lines.append(f"- **Analysis Output**: `{analysis_path}`")
    if guide_path or analysis_path:
        doc_lines.append("")

    content = content.rstrip("\n") + "\n\n" + "\n".join(doc_lines)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Executive summary written to {path}", file=sys.stderr)

