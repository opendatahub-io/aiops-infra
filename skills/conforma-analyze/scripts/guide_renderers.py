"""Resolution guide renderers — pure functions that take data and return markdown."""

from __future__ import annotations

from __future__ import annotations
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
import conforma_counting  # noqa: E402
import release_dates  # noqa: E402
from parse_violations import build_semantic_detail_lookup  # noqa: E402
import analyze_csv_report as analysis  # noqa: E402
from conforma_constants import (  # noqa: E402
    CONFORMA_REPORTER_ACTIONS_URL,
    CONFORMA_REPORTER_URL,
    NOT_YET_AVAILABLE_SOURCE_CSV_GENERATED_NOTE,
    NOT_YET_AVAILABLE_SOURCE_CSV_ROWS_NOTE,
    NOT_YET_AVAILABLE_TOTAL_VIOLATIONS_NOTE,
    ROW_LABEL_GENERATED,
    ROW_LABEL_SOURCE_CSV_GENERATED,
    ROW_LABEL_SOURCE_CSV_ROWS,
    ROW_LABEL_TOTAL_VIOLATIONS,
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
    environment: str = "",
    title_prefix: str = "Conforma Status and Resolution Guide",
    code_freeze_date: str = "",
    upcoming_release_date: str = "",
    total_violations: int | None = None,
    source_csv_rows: int | None = None,
    ai_model: str = "",
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
        header_end = None
        source_csv_row = None
        for i, dl in enumerate(display_lines):
            stripped = dl.strip()
            if header_end is None and stripped.startswith("|---"):
                header_end = i + 1
            if stripped.startswith("| **Source CSV** |"):
                source_csv_row = i

        # The context confirmation table is reused verbatim across steps, so a
        # row whose value is not known yet already appears with a placeholder
        # note (see resolve_release_context._format_resolved). Set its real
        # value in place to keep the structure identical. A row is only
        # inserted when it is missing (e.g. a confirmation display generated
        # before the placeholder rows were introduced).
        def _ensure_row(label: str, value: str, insert_at: int) -> None:
            prefix = f"| **{label}** |"
            for line_index, line in enumerate(display_lines):
                if line.strip().startswith(prefix):
                    display_lines[line_index] = f"{prefix} {value} |"
                    return
            display_lines.insert(insert_at, f"{prefix} {value} |")

        # Generated is the first data row, right below the table separator.
        _ensure_row(ROW_LABEL_GENERATED, now, header_end if header_end is not None else 0)
        # Inserting Generated may have shifted the Source CSV row; recompute.
        for i, dl in enumerate(display_lines):
            if dl.strip().startswith("| **Source CSV** |"):
                source_csv_row = i
                break
        stat_insert_at = (
            (source_csv_row + 1)
            if source_csv_row is not None
            else (header_end if header_end is not None else len(display_lines))
        )
        # The source CSV generation timestamp sits directly under the Source
        # CSV row; the raw per-image row count and deduplicated total follow it.
        if source_created_at:
            _ensure_row(ROW_LABEL_SOURCE_CSV_GENERATED, source_created_at, stat_insert_at)
        if source_csv_rows is not None:
            _ensure_row(ROW_LABEL_SOURCE_CSV_ROWS, f"{source_csv_rows:,}", stat_insert_at + 1)
        if total_violations is not None:
            _ensure_row(ROW_LABEL_TOTAL_VIOLATIONS, f"{total_violations:,}", stat_insert_at + 2)
        lines.append("\n".join(display_lines))
    else:
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| **{ROW_LABEL_GENERATED}** | {now} |")
        lines.append(f"| **Release branch** | {release} |")
        if environment:
            lines.append(f"| **Environment** | {environment} |")
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
                f" (not found in {release_dates.RELEASE_DATA_LINK}) |"
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
        lines.append(
            "| **RHOAI Conforma doc** | [Conforma for RHOAI](https://docs.google.com/document/d/1LsHzcZ2TAIIc4slqAdMnDBovYa2EzgOD8bWx-QXR8kM/edit?tab=t.0#heading=h.5j6svfi94fr3)"
            " — reference only, superseded by conforma-* AI skills |"
        )

    if not confirmation_display:
        lines.append(f"| **Source CSV** | [{source_path}]({source_url}) |")
        # The source CSV generation timestamp sits directly under the Source
        # CSV row, matching the Step 2 context confirmation table.
        if source_created_at:
            lines.append(f"| **{ROW_LABEL_SOURCE_CSV_GENERATED}** | {source_created_at} |")
        else:
            lines.append(f"| **{ROW_LABEL_SOURCE_CSV_GENERATED}** | {NOT_YET_AVAILABLE_SOURCE_CSV_GENERATED_NOTE} |")
        # Keep the same structure as the Step 2 context confirmation table:
        # the raw (unfiltered) row count precedes the deduplicated total, and
        # a value that is not available yet carries a placeholder note.
        lines.append(
            f"| **{ROW_LABEL_SOURCE_CSV_ROWS}** | {source_csv_rows:,} |"
            if source_csv_rows is not None
            else f"| **{ROW_LABEL_SOURCE_CSV_ROWS}** | {NOT_YET_AVAILABLE_SOURCE_CSV_ROWS_NOTE} |"
        )
        lines.append(
            f"| **{ROW_LABEL_TOTAL_VIOLATIONS}** | {total_violations:,} |"
            if total_violations is not None
            else f"| **{ROW_LABEL_TOTAL_VIOLATIONS}** | {NOT_YET_AVAILABLE_TOTAL_VIOLATIONS_NOTE} |"
        )

    import getpass
    import socket

    user_host = f"{getpass.getuser()}@{socket.gethostname()}"

    model_suffix = f" (LLM: {ai_model})" if ai_model else ""
    lines += [
        "",
        f"*Generated by: aiops-infra conforma-analyze skill{model_suffix}*",
        "",
        f"*Run by: {user_host}*",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def _find_covering_mr(mrs: list[dict], component: str) -> dict | None:
    """Find the first MR in *mrs* whose components list includes *component*."""
    for mr in mrs:
        mr_comps = mr.get("mr_components", [])
        if "*" in mr_comps or component in mr_comps:
            return mr
    return None


def _jira_refs_from_merge_request(merge_request: dict | None) -> list[dict]:
    """Extract Jira issue references from a Merge Request's text.

    Merge Request titles and descriptions are an independent Jira discovery
    source. Keep those references visible in the guide even when Jira ticket
    creation is skipped for the run.
    """
    if not merge_request:
        return []
    text = " ".join(
        str(merge_request.get(field) or "")
        for field in ("title", "description")
    )
    keys = list(dict.fromkeys(match.upper() for match in re.findall(r"(?<![A-Z0-9])([A-Z][A-Z0-9]+-\d+)(?!\d)", text, re.IGNORECASE)))
    return [{"key": key, "url": f"https://redhat.atlassian.net/browse/{key}"} for key in keys]


def _violation_count(
    rule: str,
    component: str,
    by_component_rule: dict[tuple[str, str], int],
) -> int:
    """Return the exact violation count for a (rule, component) pair.

    Falls back to the base rule (without ``:``) suffix, then to 1.
    """
    return by_component_rule.get((rule, component), 0) or by_component_rule.get((rule.split(":")[0], component), 0) or 1


def _truncate_detail(detail: str, max_len: int = 60) -> str:
    """Truncate a semantic detail string for table display.

    For URLs, the truncated text links to the full URL so hovering
    reveals the complete value in the browser status bar.
    """
    if len(detail) <= max_len:
        return detail
    truncated = detail[:max_len] + "…"
    if detail.startswith(("http://", "https://")):
        return f"[{truncated}]({detail})"
    return truncated


def _compute_violation_buckets(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
    upcoming_release_date: str = "",
) -> dict:
    """Classify violations into action-priority buckets.

    Returns a dict with keys:
        no_mr_entries, has_mr_entries,
        expiring_no_mr, expiring_mr_insufficient, expiring_mr_sufficient,
        covered_violations, not_covered_violations, total_violations, coverage_pct,
        expiring_soon (list of tuples for 14-day window).
    """
    violations = coverage_data.get("violations", [])
    total_violations = analysis_result.total_violations

    covered_violations = 0
    not_covered_violations = 0
    for v in violations:
        rule = v["rule"]
        all_components = v.get("all_components", [])
        uncovered_comps = v.get("uncovered_components", [])
        covered_comps = [c for c in all_components if c not in uncovered_comps]
        covered_violations += conforma_counting.violations_for_components(
            rule,
            covered_comps,
            by_component_rule,
        )
        not_covered_violations += conforma_counting.violations_for_components(
            rule,
            uncovered_comps,
            by_component_rule,
        )

    coverage_pct = (covered_violations / total_violations * 100) if total_violations > 0 else 0

    uncovered_entries: list[dict] = []
    for v in violations:
        if v.get("coverage", "not_covered") == "fully_covered":
            continue
        rule = v["rule"]
        uncovered_comps = v.get("uncovered_components", [])
        mrs = v.get("open_merge_requests", [])
        for comp in uncovered_comps:
            uncovered_entries.append(
                {
                    "rule": rule,
                    "component": comp,
                    "violation_count": _violation_count(rule, comp, by_component_rule),
                    "mr": _find_covering_mr(mrs, comp),
                }
            )

    no_mr_entries = [e for e in uncovered_entries if not e["mr"]]
    has_mr_entries = [e for e in uncovered_entries if e["mr"]]

    has_mr_expires_before_release: list[dict] = []
    has_mr_ok: list[dict] = []

    if upcoming_release_date:
        try:
            _upcoming_dt_mr = datetime.strptime(upcoming_release_date, "%Y-%m-%d").date()
        except ValueError:
            _upcoming_dt_mr = None

        if _upcoming_dt_mr:
            for e in has_mr_entries:
                mr = e["mr"]
                comp = e.get("component")
                # Try per-component date first, fall back to global
                mr_eu = None
                if comp and mr.get("effective_until_by_component"):
                    mr_eu = mr["effective_until_by_component"].get(comp)
                if not mr_eu:
                    mr_eu = mr.get("effective_until")
                if mr_eu:
                    try:
                        mr_eu_date = datetime.strptime(mr_eu[:10], "%Y-%m-%d").date()
                        if mr_eu_date < _upcoming_dt_mr:
                            e["mr_effective_until"] = mr_eu[:10]
                            has_mr_expires_before_release.append(e)
                            continue
                    except ValueError:
                        pass
                has_mr_ok.append(e)
        else:
            has_mr_ok = list(has_mr_entries)
    else:
        has_mr_ok = list(has_mr_entries)

    expiring_no_mr: list[dict] = []
    expiring_mr_insufficient: list[dict] = []
    expiring_mr_sufficient: list[dict] = []

    if upcoming_release_date:
        try:
            upcoming_dt = datetime.strptime(upcoming_release_date, "%Y-%m-%d").date()
        except ValueError:
            upcoming_dt = None

        if upcoming_dt:
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
                            "violation_count": _violation_count(rule, comp, by_component_rule),
                            "effective_until": eu[:10],
                        }
                        covering_mr = _find_covering_mr(mrs, comp)
                        if not covering_mr:
                            expiring_no_mr.append(entry)
                        else:
                            # Try per-component date first, fall back to global
                            mr_eu = None
                            if covering_mr.get("effective_until_by_component"):
                                mr_eu = covering_mr["effective_until_by_component"].get(comp)
                            if not mr_eu:
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

    expiry_threshold_days = 14
    now = datetime.now(timezone.utc)
    expiring_soon: list[tuple] = []
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
    expiring_soon.sort(key=lambda x: x[2])

    table_num = 0
    table_map = {}
    table_num += 1
    table_map["no_mr"] = table_num
    if upcoming_release_date:
        table_num += 1
        table_map["expiring_no_mr"] = table_num
        table_num += 1
        table_map["expiring_mr_insufficient"] = table_num
        table_num += 1
        table_map["expiring_mr_sufficient"] = table_num
        table_num += 1
        table_map["has_mr_expires_before_release"] = table_num
    table_num += 1
    table_map["has_mr"] = table_num

    return {
        "no_mr_entries": no_mr_entries,
        "has_mr_entries": has_mr_entries,
        "has_mr_expires_before_release": has_mr_expires_before_release,
        "has_mr_ok": has_mr_ok,
        "expiring_no_mr": expiring_no_mr,
        "expiring_mr_insufficient": expiring_mr_insufficient,
        "expiring_mr_sufficient": expiring_mr_sufficient,
        "covered_violations": covered_violations,
        "not_covered_violations": not_covered_violations,
        "total_violations": total_violations,
        "coverage_pct": coverage_pct,
        "expiring_soon": expiring_soon,
        "table_map": table_map,
    }


def _append_tooling_health_detail(lines: list[str], tooling_health_data: dict) -> None:
    """Append a compact tooling health summary for the TODO #0 healthy case."""
    tools = tooling_health_data.get("tools", [])
    for tool in tools:
        name = tool.get("name", "unknown")
        health = tool.get("health", {})
        status = health.get("status", "unknown")
        in_progress = health.get("in_progress_run")
        last_success = health.get("last_success")

        if in_progress and last_success:
            success_url = last_success.get("url", "")
            success_date = last_success.get("completed_at", "")[:10]
            progress_url = in_progress.get("url", "")
            lines.append(
                f"The [{name} workflow]({CONFORMA_REPORTER_ACTIONS_URL}) "
                f"last succeeded on {success_date} "
                f"([run]({success_url})). "
                f"A [more recent run]({progress_url}) is currently **in progress** "
                f"— please monitor it for any errors."
            )
        elif tool.get("latest_run"):
            latest = tool["latest_run"]
            run_url = latest.get("url", "")
            run_date = latest.get("updated_at", "")[:10]
            lines.append(
                f"The [{name} workflow]({CONFORMA_REPORTER_ACTIONS_URL}) "
                f"is **{status}** — [latest run]({run_url}) succeeded on {run_date}."
            )
        else:
            lines.append(f"The [{name} workflow]({CONFORMA_REPORTER_ACTIONS_URL}) is **{status}**.")


def render_key_takeaways(
    coverage_data: dict,
    analysis_result: analysis.AnalysisResult,
    by_component_rule: dict[tuple[str, str], int],
    tooling_health_data: dict | None = None,
    violations_yaml_data: dict | None = None,
    upcoming_release_date: str = "",
    policy_files: list[dict[str, str]] | None = None,
    release: str = "",
    jira_sync: dict | None = None,
) -> str:
    """Render the violations breakdown — exact violation counts, no approximation.

    A violation = unique (code, component, message) triple. Coverage is binary:
    each violation either has an exception or does not.
    """
    buckets = _compute_violation_buckets(
        coverage_data,
        analysis_result,
        by_component_rule,
        upcoming_release_date,
    )

    no_mr_entries = buckets["no_mr_entries"]
    has_mr_entries = buckets["has_mr_entries"]
    has_mr_expires_before_release = buckets["has_mr_expires_before_release"]
    has_mr_ok = buckets["has_mr_ok"]
    no_mr_violation_count = sum(e["violation_count"] for e in no_mr_entries)
    has_mr_violation_count = sum(e["violation_count"] for e in has_mr_entries)
    has_mr_expires_count = sum(e["violation_count"] for e in has_mr_expires_before_release)
    has_mr_ok_count = sum(e["violation_count"] for e in has_mr_ok)
    covered_violations = buckets["covered_violations"]
    total_violations = buckets["total_violations"]
    coverage_pct = buckets["coverage_pct"]
    expiring_no_mr = buckets["expiring_no_mr"]
    expiring_mr_insufficient = buckets["expiring_mr_insufficient"]
    expiring_mr_sufficient = buckets["expiring_mr_sufficient"]
    expiring_soon = buckets["expiring_soon"]

    version_label = release_dates.format_version_label(release) if release else "the upcoming release"

    # Pre-compute warnings split for action counting
    _upcoming_pre_release: list = []
    _upcoming_post_release: list = []
    if analysis_result.upcoming_violations:
        for w in analysis_result.upcoming_violations:
            eff = getattr(w, "effective_on", "") or ""
            eff_date = eff[:10] if eff else ""
            if upcoming_release_date and eff_date and eff_date <= upcoming_release_date:
                _upcoming_pre_release.append(w)
            else:
                _upcoming_post_release.append(w)

    # Summary preamble — count non-empty action categories
    action_count = sum(
        [
            no_mr_violation_count > 0,
            sum(e["violation_count"] for e in expiring_no_mr) > 0,
            sum(e["violation_count"] for e in expiring_mr_insufficient) > 0,
            has_mr_expires_count > 0,
            has_mr_ok_count > 0,
            bool(
                tooling_health_data
                and any(
                    t.get("health", {}).get("status") in ("unhealthy", "error")
                    for t in tooling_health_data.get("tools", [])
                )
            ),
            bool(expiring_soon),
            bool(_upcoming_pre_release),
            bool(_upcoming_post_release),
        ]
    )
    lines = ["## TODO", ""]

    if action_count == 0:
        lines.append("> No TODOs — all violations are covered")

    lines.append("")

    detail_lookup, detail_labels = (
        build_semantic_detail_lookup(violations_yaml_data) if violations_yaml_data else ({}, {})
    )

    def _format_violation_cell(rule: str, comp: str) -> str:
        base_rule = rule.split(":")[0]
        details = detail_lookup.get((base_rule, comp), [])
        anchor = _violation_anchor(rule)
        rule_link = f"[`{rule}`](#{anchor})"
        if len(details) == 0:
            return rule_link
        if len(details) == 1:
            return f"{rule_link} ({_truncate_detail(details[0])})"
        return rule_link

    def _detail_continuation_rows(rule: str, comp: str, trailing_empty: int) -> list[str]:
        base_rule = rule.split(":")[0]
        details = detail_lookup.get((base_rule, comp), [])
        if len(details) <= 1:
            return []
        rows = []
        max_show = 15
        empty = " |" * trailing_empty
        for d in details[:max_show]:
            rows.append(f"|   | ↳ {_truncate_detail(d)}{empty}")
        if len(details) > max_show:
            label = detail_labels.get(base_rule, "items")
            rows.append(f"|   | +{len(details) - max_show} more {label}s{empty}")
        return rows

    # Per-row Jira column helpers. The Jira column is always rendered so TODO
    # tables retain a stable schema; an unavailable ticket or synchronization
    # entry is represented by an em dash in the cell.
    jira_cell_active = True

    def _jira_cell(rule: str, comp: str, covering_mr: dict | None = None) -> str:
        sync_entry = _jira_sync_entry(jira_sync, rule)
        refs, create_url, related_search_url, related_label = _sync_component_cells(sync_entry, comp)
        mr_refs = _jira_refs_from_merge_request(covering_mr)
        existing_keys = {ref.get("key") for ref in refs}
        refs.extend(ref for ref in mr_refs if ref.get("key") not in existing_keys)
        if not refs and not create_url:
            cell = "—"
        elif refs:
            cell = ", ".join(f"[{r['key']}]({r['url']})" if r.get("url") else r["key"] for r in refs)
        else:
            cell = f"[Create]({create_url})"
        if related_search_url:
            cell += f", [Search related Jira (label: `{related_label}`)]({related_search_url})"
        return cell

    def _detail_continuation_rows_jira(rule: str, comp: str, trailing_empty: int) -> list[str]:
        """Detail continuation rows with an empty Jira cell when the column is active."""
        return _detail_continuation_rows(rule, comp, trailing_empty + (1 if jira_cell_active else 0))

    # Collect all TODO sections as data structures for sorting
    todo_sections: list[dict] = []

    # TODO: Tooling health — always pinned first
    unhealthy_tools = [
        t
        for t in (tooling_health_data or {}).get("tools", [])
        if t.get("health", {}).get("status") in ("unhealthy", "error")
    ]
    tooling_body = []
    if unhealthy_tools:
        names = ", ".join(t.get("name", "unknown") for t in unhealthy_tools)
        title = f"{names} workflow is failing"
        tooling_body.append("")
        tooling_body.append(
            f"**The violation data in this report may be stale.** "
            f"The {names} workflow is failing — the CSV reports this analysis "
            f"depends on are not being refreshed."
        )
        tooling_body.append("")
        if tooling_health_data:
            tooling_body.extend(_render_tooling_health_table(tooling_health_data).splitlines())
            tooling_body.append("")
        tooling_body.append("**Next steps:**")
        tooling_body.append("")
        tooling_body.append(
            f"1. Go to the [conforma-reporter GitHub Actions workflow]({CONFORMA_REPORTER_ACTIONS_URL})"
        )
        tooling_body.append("2. Check the latest failed run for error details")
        tooling_body.append("3. Common failure causes: expired auth tokens, EC policy timeouts, branch not found")
        tooling_body.append("4. Fix the issue and re-run the workflow")
        tooling_body.append("5. Once the workflow succeeds, re-run this analysis to get fresh data")
        tooling_body.append("")
        tooling_line = _tooling_health_executive_line(tooling_health_data)
        if tooling_line:
            tooling_body.append(tooling_line)
        count = len(unhealthy_tools)
    else:
        title = "Tooling status: healthy"
        tooling_body.append("")
        if tooling_health_data:
            _append_tooling_health_detail(tooling_body, tooling_health_data)
            tooling_body.append("")
            tooling_body.extend(_render_tooling_health_table(tooling_health_data).splitlines())
        else:
            tooling_body.append(
                f"The [conforma-reporter workflow]({CONFORMA_REPORTER_ACTIONS_URL}) "
                f"status is unknown — no tooling health data was collected."
            )
        count = 0
    tooling_body.append("")
    tooling_body.append("---")

    todo_sections.append(
        {
            "title": title,
            "count": count,
            "body": tooling_body,
            "pinned": True,  # Always first
            "priority": 0,  # Tooling always #0
        }
    )

    # TODO: Violations with no exception and no open Merge Request (highest risk)
    no_mr_body = []
    no_mr_body.append("")
    no_mr_body.append("Review each violation — click the violation code to see details and next steps.")
    no_mr_body.append("")
    if jira_cell_active:
        no_mr_body.append("| # | Violation | Component | Violations | Jira |")
        no_mr_body.append("|--:|-----------|-----------|:----------:|------|")
        no_mr_empty = "| | No violations | | |  |"
    else:  # pragma: no cover - jira_cell_active is intentionally always enabled
        no_mr_body.append("| # | Violation | Component | Violations |")
        no_mr_body.append("|--:|-----------|-----------|:----------:|")
        no_mr_empty = "| | No violations | | |"
    if no_mr_entries:
        for row_num, entry in enumerate(no_mr_entries, 1):
            violation_cell = _format_violation_cell(entry["rule"], entry["component"])
            row = f"| {row_num} | {violation_cell} | `{entry['component']}` | {entry['violation_count']} |"
            row += f" {_jira_cell(entry['rule'], entry['component'], entry.get('mr'))} |" if jira_cell_active else " |"
            no_mr_body.append(row)
            no_mr_body.extend(_detail_continuation_rows_jira(entry["rule"], entry["component"], 2))
    else:
        no_mr_body.append(no_mr_empty)
    no_mr_body.append("")
    no_mr_body.append("---")

    todo_sections.append(
        {
            "title": f"{no_mr_violation_count:,} violations without exception or open Merge Request",
            "count": no_mr_violation_count,
            "body": no_mr_body,
            "pinned": False,
            "priority": 1,  # Highest priority: uncovered violations
        }
    )

    # TODOs: Exceptions expiring before the upcoming release date
    if upcoming_release_date:
        # TODO: Expiring exceptions with no open Merge Request
        expiring_no_mr_count = sum(e["violation_count"] for e in expiring_no_mr)
        expiring_no_mr_body = []
        expiring_no_mr_body.append("")
        expiring_no_mr_body.append(
            f"The exceptions below will expire before the planned release date for "
            f"{version_label} on {upcoming_release_date}. "
            f"Click each violation for details — try to resolve the underlying issue in code, "
            f"or create a Merge Request to extend the exception past the release date."
        )
        expiring_no_mr_body.append("")
        if jira_cell_active:
            expiring_no_mr_body.append(
                "| # | Violation | Component | Violations | Effective Until in Existing Exception | Jira |"
            )
            expiring_no_mr_body.append("|--:|-----------|-----------|:----------:|-----------------|------|")
            expiring_no_mr_empty = "| | No violations | | | |  |"
        else:  # pragma: no cover - jira_cell_active is intentionally always enabled
            expiring_no_mr_body.append(
                "| # | Violation | Component | Violations | Effective Until in Existing Exception |"
            )
            expiring_no_mr_body.append("|--:|-----------|-----------|:----------:|-----------------|")
            expiring_no_mr_empty = "| | No violations | | | |"
        if expiring_no_mr:
            for row_num, entry in enumerate(expiring_no_mr, 1):
                violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                row = (
                    f"| {row_num} | {violation_cell} | `{entry['component']}` "
                    f"| {entry['violation_count']} | {entry['effective_until']} |"
                )
                row += f" {_jira_cell(entry['rule'], entry['component'], entry.get('mr'))} |" if jira_cell_active else " |"
                expiring_no_mr_body.append(row)
                expiring_no_mr_body.extend(_detail_continuation_rows_jira(entry["rule"], entry["component"], 3))
        else:
            expiring_no_mr_body.append(expiring_no_mr_empty)
        expiring_no_mr_body.append("")
        expiring_no_mr_body.append("---")

        todo_sections.append(
            {
                "title": f"{expiring_no_mr_count:,} violations with expiring exceptions, no open Merge Request",
                "count": expiring_no_mr_count,
                "body": expiring_no_mr_body,
                "pinned": False,
                "priority": 2,
            }
        )

        # TODO: Expiring exceptions with MR but MR expiry also before release
        expiring_mr_insuf_count = sum(e["violation_count"] for e in expiring_mr_insufficient)
        expiring_mr_insuf_body = []
        expiring_mr_insuf_body.append("")
        expiring_mr_insuf_body.append(
            f"Open Merge Requests exist for these violations but their proposed effective-until dates "
            f"also expire before the release. Review and update the Merge Request to extend past "
            f"{upcoming_release_date}, or resolve the violation in code. Click each for details."
        )
        expiring_mr_insuf_body.append("")
        if jira_cell_active:
            expiring_mr_insuf_body.append(
                "| # | Violation | Component | Violations | Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request | Jira |"
            )
            expiring_mr_insuf_body.append(
                "|--:|-----------|-----------|:----------:|--------------------------------------|------------------------------------------------|---------------|------|"
            )
            expiring_mr_insuf_empty = "| | No violations | | | | | |  |"
        else:  # pragma: no cover - jira_cell_active is intentionally always enabled
            expiring_mr_insuf_body.append(
                "| # | Violation | Component | Violations | Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request |"
            )
            expiring_mr_insuf_body.append(
                "|--:|-----------|-----------|:----------:|--------------------------------------|------------------------------------------------|---------------|"
            )
            expiring_mr_insuf_empty = "| | No violations | | | | | |"
        if expiring_mr_insufficient:
            for row_num, entry in enumerate(expiring_mr_insufficient, 1):
                violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
                mr_eu_display = entry.get("mr_effective_until") or "unknown"
                row = (
                    f"| {row_num} | {violation_cell} | `{entry['component']}` "
                    f"| {entry['violation_count']} | {entry['effective_until']} | {mr_eu_display} | {mr_link} |"
                )
                row += f" {_jira_cell(entry['rule'], entry['component'], entry.get('mr'))} |" if jira_cell_active else " |"
                expiring_mr_insuf_body.append(row)
                expiring_mr_insuf_body.extend(_detail_continuation_rows_jira(entry["rule"], entry["component"], 5))
        else:
            expiring_mr_insuf_body.append(expiring_mr_insuf_empty)
        expiring_mr_insuf_body.append("")
        expiring_mr_insuf_body.append("---")

        todo_sections.append(
            {
                "title": f"{expiring_mr_insuf_count:,} violations with expiring exceptions, Merge Request also expires before release",
                "count": expiring_mr_insuf_count,
                "body": expiring_mr_insuf_body,
                "pinned": False,
                "priority": 3,
            }
        )

        # TODO: Expiring exceptions with MR extending past release (lower risk)
        expiring_mr_suf_count = sum(e["violation_count"] for e in expiring_mr_sufficient)
        expiring_mr_suf_body = []
        expiring_mr_suf_body.append("")
        expiring_mr_suf_body.append(
            "Open Merge Requests already extend these exceptions past the release date. "
            "Track and ensure they get merged before the release."
        )
        expiring_mr_suf_body.append("")
        if jira_cell_active:
            expiring_mr_suf_body.append(
                "| # | Violation | Component | Violations | Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request | Jira |"
            )
            expiring_mr_suf_body.append(
                "|--:|-----------|-----------|:----------:|--------------------------------------|------------------------------------------------|---------------|------|"
            )
            expiring_mr_suf_empty = "| | No violations | | | | | |  |"
        else:  # pragma: no cover - jira_cell_active is intentionally always enabled
            expiring_mr_suf_body.append(
                "| # | Violation | Component | Violations | Effective Until in Existing Exception | Exception Effective Until in Open Merge Request | Merge Request |"
            )
            expiring_mr_suf_body.append(
                "|--:|-----------|-----------|:----------:|--------------------------------------|------------------------------------------------|---------------|"
            )
            expiring_mr_suf_empty = "| | No violations | | | | | |"
        if expiring_mr_sufficient:
            for row_num, entry in enumerate(expiring_mr_sufficient, 1):
                violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
                mr_eu_display = entry.get("mr_effective_until") or "unknown"
                row = (
                    f"| {row_num} | {violation_cell} | `{entry['component']}` "
                    f"| {entry['violation_count']} | {entry['effective_until']} | {mr_eu_display} | {mr_link} |"
                )
                row += f" {_jira_cell(entry['rule'], entry['component'], entry.get('mr'))} |" if jira_cell_active else " |"
                expiring_mr_suf_body.append(row)
                expiring_mr_suf_body.extend(_detail_continuation_rows_jira(entry["rule"], entry["component"], 5))
        else:
            expiring_mr_suf_body.append(expiring_mr_suf_empty)
        expiring_mr_suf_body.append("")
        expiring_mr_suf_body.append("---")

        todo_sections.append(
            {
                "title": f"{expiring_mr_suf_count:,} violations with expiring exceptions, Merge Request extends past release",
                "count": expiring_mr_suf_count,
                "body": expiring_mr_suf_body,
                "pinned": False,
                "priority": 4,
            }
        )

    # TODO: Violations with no exception, open MR expires before release.
    # Always rendered (like the other expiring-exception sections) when a release
    # date is known: an empty bucket still shows "0 violations … ✓ (no action
    # needed)" so the check is visible in the report. Gating on a non-empty list
    # would silently drop the section and break the TODO numbering.
    if upcoming_release_date:
        has_mr_exp_body = []
        has_mr_exp_body.append("")
        if has_mr_expires_before_release:
            has_mr_exp_body.append(
                f"Open Merge Requests address these violations but their proposed exception "
                f"effective-until dates expire **before** the {version_label} release on "
                f"{upcoming_release_date}. Even if merged, the exception will not cover the "
                f"release. Update the Merge Request to extend past {upcoming_release_date}, "
                f"or resolve the violation in code."
            )
        has_mr_exp_body.append("")
        if jira_cell_active:
            has_mr_exp_body.append(
                "| # | Violation | Component | Violations | Exception Effective Until in Open Merge Request | Merge Request | Jira |"
            )
            has_mr_exp_body.append(
                "|--:|-----------|-----------|:----------:|------------------------------------------------|---------------|------|"
            )
            has_mr_exp_empty = "| | No violations | | | | |  |"
        else:  # pragma: no cover - jira_cell_active is intentionally always enabled
            has_mr_exp_body.append(
                "| # | Violation | Component | Violations | Exception Effective Until in Open Merge Request | Merge Request |"
            )
            has_mr_exp_body.append(
                "|--:|-----------|-----------|:----------:|------------------------------------------------|---------------|"
            )
            has_mr_exp_empty = "| | No violations | | | | |"
        if has_mr_expires_before_release:
            for row_num, entry in enumerate(has_mr_expires_before_release, 1):
                violation_cell = _format_violation_cell(entry["rule"], entry["component"])
                mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
                mr_eu_display = entry.get("mr_effective_until") or "unknown"
                row = (
                    f"| {row_num} | {violation_cell} | `{entry['component']}` "
                    f"| {entry['violation_count']} | {mr_eu_display} | {mr_link} |"
                )
                row += f" {_jira_cell(entry['rule'], entry['component'], entry.get('mr'))} |" if jira_cell_active else " |"
                has_mr_exp_body.append(row)
                has_mr_exp_body.extend(_detail_continuation_rows_jira(entry["rule"], entry["component"], 4))
        else:
            has_mr_exp_body.append(has_mr_exp_empty)
        has_mr_exp_body.append("")
        has_mr_exp_body.append("---")

        todo_sections.append(
            {
                "title": f"{has_mr_expires_count:,} violations with open Merge Request expiring before release",
                "count": has_mr_expires_count,
                "body": has_mr_exp_body,
                "pinned": False,
                "priority": 5,
            }
        )

    # TODO: Violations with no exception but having an open Merge Request (OK expiry)
    has_mr_ok_body = []
    has_mr_ok_body.append("")
    has_mr_ok_body.append(
        "Open Merge Requests address the following violations. "
        "Track and ensure they get merged. Click each violation for details."
    )
    has_mr_ok_body.append("")
    if jira_cell_active:
        has_mr_ok_body.append("| # | Violation | Component | Violations | Merge Request | Jira |")
        has_mr_ok_body.append("|--:|-----------|-----------|:----------:|---------------|------|")
        has_mr_ok_empty = "| | No violations | | | |  |"
    else:  # pragma: no cover - jira_cell_active is intentionally always enabled
        has_mr_ok_body.append("| # | Violation | Component | Violations | Merge Request |")
        has_mr_ok_body.append("|--:|-----------|-----------|:----------:|---------------|")
        has_mr_ok_empty = "| | No violations | | | |"
    if has_mr_ok:
        for row_num, entry in enumerate(has_mr_ok, 1):
            violation_cell = _format_violation_cell(entry["rule"], entry["component"])
            mr_link = f"[!{entry['mr']['iid']}]({entry['mr']['url']})"
            row = f"| {row_num} | {violation_cell} | `{entry['component']}` | {entry['violation_count']} | {mr_link} |"
            row += f" {_jira_cell(entry['rule'], entry['component'], entry.get('mr'))} |" if jira_cell_active else ""
            has_mr_ok_body.append(row)
            has_mr_ok_body.extend(_detail_continuation_rows_jira(entry["rule"], entry["component"], 3))
    else:
        has_mr_ok_body.append(has_mr_ok_empty)
    has_mr_ok_body.append("")
    has_mr_ok_body.append("---")

    todo_sections.append(
        {
            "title": f"{has_mr_ok_count:,} violations addressed by open Merge Requests (not yet merged)",
            "count": has_mr_ok_count,
            "body": has_mr_ok_body,
            "pinned": False,
            "priority": 6,
        }
    )

    # Warnings becoming violations — split by release date
    if analysis_result.upcoming_violations:
        grouped: dict[tuple[str, str, str], dict] = {}
        for w in analysis_result.upcoming_violations:
            detail = getattr(w, "semantic_detail", "") or ""
            key = (w.code, detail, w.component_name)
            if key not in grouped:
                grouped[key] = {
                    "count": 0,
                    "effective_on": w.effective_on,
                    "days_until_effective": w.days_until_effective,
                }
            entry = grouped[key]
            entry["count"] += 1
            if w.days_until_effective < entry["days_until_effective"]:
                entry["days_until_effective"] = w.days_until_effective
                entry["effective_on"] = w.effective_on

        sorted_entries = sorted(
            grouped.items(),
            key=lambda x: (x[1]["days_until_effective"], x[0][0], x[0][1], x[0][2]),
        )

        pre_release: list[tuple] = []
        post_release: list[tuple] = []
        if upcoming_release_date:
            for item in sorted_entries:
                eff = item[1]["effective_on"]
                eff_date = eff[:10] if eff else ""
                if eff_date and eff_date <= upcoming_release_date:
                    pre_release.append(item)
                else:
                    post_release.append(item)
        else:
            post_release = sorted_entries

        # TODO: Warnings becoming violations before the release date
        pre_count = sum(1 for _ in pre_release)
        pre_warn_body = []
        pre_warn_body.append("")
        if upcoming_release_date:
            pre_warn_body.append(
                f"These warnings will become enforced violations **before** the "
                f"{version_label} release on {upcoming_release_date}. "
                f"They will block the release if not addressed."
            )
        else:
            pre_warn_body.append(
                "No upcoming release date is set — cannot determine which warnings "
                "will become violations before the release."
            )
        pre_warn_body.append("")
        pre_warn_body.append("| # | Warning | Component | Count | Deadline | Days Left |")
        pre_warn_body.append("|--:|---------|-----------|:-----:|----------|:---------:|")
        if pre_release:
            for row_num, ((code, detail, component), info) in enumerate(pre_release, 1):
                days = info["days_until_effective"]
                urgency = "**OVERDUE**" if days == 0 else str(days)
                warning_cell = f"`{code}`"
                if detail:
                    warning_cell += f" ({detail})"
                pre_warn_body.append(
                    f"| {row_num} | {warning_cell} | `{component}` | {info['count']} | {info['effective_on']} | {urgency} |"
                )
        else:
            pre_warn_body.append("| | No warnings | | | | |")
        pre_warn_body.append("")
        pre_warn_body.append("---")

        todo_sections.append(
            {
                "title": f"{pre_count:,} warnings becoming violations before release date",
                "count": pre_count,
                "body": pre_warn_body,
                "pinned": False,
                "priority": 7,
            }
        )

        # TODO: Warnings becoming violations after the release date (within 21 days)
        post_count = sum(1 for _ in post_release)
        post_warn_body = []
        post_warn_body.append("")
        if upcoming_release_date:
            post_warn_body.append(
                f"These warnings will become enforced violations **after** the "
                f"{version_label} release on {upcoming_release_date}. "
                f"They will not block this release but should be tracked for the next one."
            )
        else:
            post_warn_body.append("All warnings within the 21-day threshold are listed below.")
        post_warn_body.append("")
        post_warn_body.append("| # | Warning | Component | Count | Deadline | Days Left |")
        post_warn_body.append("|--:|---------|-----------|:-----:|----------|:---------:|")
        if post_release:
            for row_num, ((code, detail, component), info) in enumerate(post_release, 1):
                days = info["days_until_effective"]
                urgency = "**OVERDUE**" if days == 0 else str(days)
                warning_cell = f"`{code}`"
                if detail:
                    warning_cell += f" ({detail})"
                post_warn_body.append(
                    f"| {row_num} | {warning_cell} | `{component}` | {info['count']} | {info['effective_on']} | {urgency} |"
                )
        else:
            post_warn_body.append("| | No warnings | | | | |")
        post_warn_body.append("")

        todo_sections.append(
            {
                "title": f"{post_count:,} warnings becoming violations within 21 days (after release date)",
                "count": post_count,
                "body": post_warn_body,
                "pinned": False,
                "priority": 8,
            }
        )

    # Sort TODO sections: pinned first, then non-zero by priority, then zero-count by priority
    def _sort_key(section: dict) -> tuple:
        if section.get("pinned"):
            return (0, 0, "")  # Pinned sections always first
        count = section["count"]
        priority = section.get("priority", 999)
        if count > 0:
            return (1, priority, section["title"])  # Non-zero, sorted by priority (preserves semantic order)
        return (2, priority, section["title"])  # Zero-count sections last, sorted by priority

    sorted_sections = sorted(todo_sections, key=_sort_key)

    # Render sorted sections with sequential numbering
    for todo_num, section in enumerate(sorted_sections):
        count = section["count"]
        title = section["title"]

        # Add visual indicator for zero-count sections (no action needed)
        if count == 0:
            title_suffix = " ✓ (no action needed)"
        else:
            title_suffix = ""

        if todo_num > 0:
            # Blank line + rendered <br> after the preceding --- so the
            # next heading does not visually merge with the previous
            # section (a bare blank line before a heading is not rendered
            # as a gap by most Markdown renderers).
            lines.append("")
            lines.append("<br>")

        lines.append(f"### TODO #{todo_num} — {title}{title_suffix}")
        lines.extend(section["body"])

    # Each section body already ends with ---; avoid a doubled rule.
    if not (sorted_sections and sorted_sections[-1]["body"][-1] == "---"):
        lines.append("---")

    if expiring_soon:
        parts = [f"`{rule}`{detail} (expires {date}, {days}d)" for rule, date, days, detail in expiring_soon]
        lines.append(f"- **Exceptions expiring in next 14 days**: {', '.join(parts)}")

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
            rule,
            covered_comps,
            by_component_rule,
        )
        not_covered_violations += conforma_counting.violations_for_components(
            rule,
            uncovered_comps,
            by_component_rule,
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


def _jira_sync_entry(jira_sync: dict | None, rule: str) -> dict | None:
    """Find the jira_sync.json violations entry for a rule.

    An entry only qualifies if it still carries uncovered work (uncovered
    components, or groups with an existing/created ticket). Matching is by
    exact rule first, then by base code (``rule.split(':')[0]``).
    """
    if not jira_sync:
        return None
    violations = jira_sync.get("violations") or []
    base_rule = rule.split(":")[0]
    candidates = [v for v in violations if v.get("rule") == rule]
    if not candidates:
        candidates = [v for v in violations if (v.get("rule") or "").split(":")[0] == base_rule]
    for entry in candidates:
        groups = entry.get("groups") or []
        if entry.get("uncovered_components") or any(g.get("existing") or g.get("created") for g in groups):
            return entry
    return None


def _sync_component_cells(
    sync_entry: dict | None, component: str
) -> tuple[list[dict], str | None, str | None, str | None]:
    """Jira refs + pre-fill link for one component row, from a sync entry.

    Returns ``(ticket_refs, create_url, related_search_url, related_label)`` where ``ticket_refs`` is a list of
    ``{"key", "url"}`` (open-matched first, then created-this-run, deduped by
    key) and ``create_url`` is the pre-fill Create URL of the first component
    group that has neither an open nor a created ticket (None if none).
    """
    if not sync_entry:
        return [], None, None, None
    comp_stem = _component_stem(component)
    ticket_refs: list[dict] = []
    create_url = None
    related_search_url = None
    related_label = None
    for group in sync_entry.get("groups") or []:
        members = (
            [group] if any(comp_stem == _component_stem(kc) for kc in group.get("konflux_components") or []) else []
        )
        for g in members:
            for ref in (g.get("existing"), g.get("created")):
                if ref and ref.get("key") and all(t["key"] != ref["key"] for t in ticket_refs):
                    ticket_refs.append({"key": ref["key"], "url": ref.get("url") or ""})
        if members and not create_url:
            has_ticket = any(bool(g.get("existing") or g.get("created")) for g in members)
            if not has_ticket:
                create_url = members[0].get("create_url")
        if members and not related_search_url:
            related_search_url = members[0].get("related_search_url")
            labels = members[0].get("unique_labels") or []
            matching_index = next(
                (index for index, name in enumerate(members[0].get("konflux_components") or [])
                 if _component_stem(name) == comp_stem),
                0,
            )
            related_label = labels[matching_index] if matching_index < len(labels) else None
    return ticket_refs, create_url, related_search_url, related_label


def _build_jira_cell(
    scoped_jiras: list[dict],
    unscoped_jiras: list[dict],
    sync_refs: list[dict],
    sync_create_url: str | None,
    sync_related_search_url: str | None = None,
    sync_related_label: str | None = None,
) -> str:
    """Build the per-component **JIRAs** cell for the components table.

    Merges the coverage open tickets (scoped + unscoped "possibly related")
    with the jira_sync data (existing/created ticket refs + create pre-fill
    link), deduplicated by ticket key (first occurrence wins, so the coverage
    scoping/ordering is preserved). Ticket links take precedence; the create
    pre-fill link is shown only when no ticket exists; ``—`` when there is
    nothing to show.
    """
    entries: list[tuple[str, str, str]] = []
    seen_keys: set[str] = set()

    def _add(key: str, url: str, suffix: str = "") -> None:
        if not key or key in seen_keys:
            return
        seen_keys.add(key)
        entries.append((key, url, suffix))

    for j in scoped_jiras:
        _add(j.get("key", ""), j.get("url") or "", "")
    for j in unscoped_jiras:
        _add(j.get("key", ""), j.get("url") or "", " (possibly related)")
    for ref in sync_refs:
        _add(ref.get("key", ""), ref.get("url") or "", "")

    if entries:
        cell = ", ".join(f"[{key}]({url}){suffix}" if url else f"{key}{suffix}" for key, url, suffix in entries)
    elif sync_create_url:
        cell = f"[Create]({sync_create_url})"
    else:
        cell = "—"
    if sync_related_search_url:
        cell += f", [Search related Jira (label: `{sync_related_label}`)]({sync_related_search_url})"
    return cell


def render_jira_tickets(lines: list[str], violation: dict, jira_sync: dict | None) -> None:
    """Render the per-violation **Jira tickets** block from jira_sync data.

    Appends:
      - **Open tickets:** — matched open tickets with status + release relevance
      - **Prior issues:** — closed, non-blocking matches
      - **Created this run:** — tickets created by the Jira sync step
      - **Create Jira ticket:** — one pre-fill link per component group with no
        open or created ticket

    Appends nothing at all when there is no sync entry for this rule (the
    fallback behavior is byte-identical to the pre-Jira-sync guide).
    """
    sync_entry = _jira_sync_entry(jira_sync, violation.get("rule", ""))
    if not sync_entry:
        return

    open_tickets: list[dict] = []
    prior_issues: list[dict] = []
    created_tickets: list[dict] = []
    create_links: list[tuple[str, str]] = []  # (label, url)
    for group in sync_entry.get("groups") or []:
        existing = group.get("existing")
        if existing and existing.get("key") and not any(t["key"] == existing["key"] for t in open_tickets):
            open_tickets.append(existing)
        for p in group.get("prior_issues") or []:
            if p.get("key") and not any(t["key"] == p["key"] for t in prior_issues):
                prior_issues.append(p)
        created = group.get("created")
        if created and created.get("key") and not any(t["key"] == created["key"] for t in created_tickets):
            created_tickets.append(created)
        if not (existing or created):
            create_url = group.get("create_url")
            if create_url and create_url not in [u for _, u in create_links]:
                comps = ", ".join(f"`{kc}`" for kc in group.get("konflux_components") or [])
                create_links.append((comps or group.get("jira_component") or "violation", create_url))

    if not (open_tickets or prior_issues or created_tickets or create_links):
        return

    lines.append("")
    lines.append("**Jira tickets:**")
    lines.append("")
    if open_tickets:
        lines.append("- **Open tickets:**")
        for t in open_tickets:
            relevance = t.get("release_relevance") or ""
            status = f" ({t.get('status')})" if t.get("status") else ""
            rel_note = f" — {relevance}" if relevance and relevance != "unknown" else ""
            lines.append(f"  - [{t['key']}]({t.get('url') or ''}){status}{rel_note}")
    if prior_issues:
        lines.append("- **Prior issues:** (closed — no action required)")
        for p in prior_issues:
            status = f" ({p.get('status')})" if p.get("status") else ""
            lines.append(f"  - [{p['key']}]({p.get('url') or ''}){status}")
    if created_tickets:
        lines.append("- **Created this run:**")
        for c in created_tickets:
            lines.append(f"  - [{c['key']}]({c.get('url') or ''})")
    if create_links:
        for comps, url in create_links:
            lines.append(f"- **Create Jira ticket** ({comps}): [create pre-filled]({url})")
    lines.append("")


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


def render_work_scope(lines: list[str], rule: str, work_scope_by_rule: dict[str, dict], source_csv_url: str) -> None:
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
    coverage_data: dict,
    catalog: dict,
    work_scope_by_rule: dict[str, dict] | None = None,
    source_csv_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
    detail_lookup: dict[tuple[str, str], list[str]] | None = None,
    jira_sync: dict | None = None,
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
            f"### {i}. `{rule}`{detail_suffix} — {total_components} components "
            f"({covered_count}/{total_components} have exceptions) "
            f'<a id="{anchor}"></a>'
        )
        lines.append("")

        render_csv_source_fields(lines, v)
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
            lines,
            v,
            component_owners,
            policy_files=policy_files,
            slack_threads=v.get("open_slack_threads"),
            slack_search_url=v.get("open_slack_search_url", ""),
            jira_sync=jira_sync,
        )

        # Per-violation Jira tickets block (open / prior / created / pre-fill
        # links). No-op when jira_sync is absent or has no entry for this rule,
        # so the output stays byte-identical to the pre-sync guide.
        render_jira_tickets(lines, v, jira_sync)

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def render_csv_source_fields(lines: list[str], violation: dict) -> None:
    """Render description, message, and solution fields from the source CSV report."""
    descriptions = violation.get("descriptions", [])
    solution = violation.get("solution", "")
    messages = violation.get("messages", [])

    if not descriptions and not solution and not messages:
        return

    if descriptions:
        lines.append("**Description** (from source report):")
        for desc in descriptions:
            lines.append(f"- {desc}")
        lines.append("")

    if messages:
        lines.append("**Message** (from source report):")
        for msg in messages:
            lines.append(f"- {msg}")
        lines.append("")

    if solution:
        lines.append(f"**Solution** (from source report): {solution}")
        lines.append("")


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
        f'use the `conforma-remedy` skill: *"How to fix `{rule}`?"*'
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
    jira_sync: dict | None = None,
) -> None:
    """Render a per-component table with one row per component.

    Columns: Component | Team | Exception | Merge Requests | JIRAs | Slack (optional)

    When ``jira_sync`` is provided, the JIRAs cell additionally shows
    created-this-run tickets and the Create pre-fill link for component
    groups without an open ticket.
    """
    sync_entry = _jira_sync_entry(jira_sync, violation.get("rule", "")) if jira_sync else None
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
        sync_refs, sync_create_url, sync_related_search_url, sync_related_label = _sync_component_cells(sync_entry, comp)
        jira_cell = _build_jira_cell(
            comp_jiras, unscoped_jiras, sync_refs, sync_create_url, sync_related_search_url, sync_related_label
        )

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


def render_known_false_alerts(lines: list[str], rule: str, violation: dict, catalog: dict) -> None:
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
    triage_note = entry.get("triage_note", "")
    if triage_note:
        lines.append(f"**Quick context**: {triage_note}")
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


def _render_tooling_health_table(tooling_health_data: dict) -> str:
    """Render the tooling-health table shared by TODO #0 and the full guide."""
    tools = tooling_health_data.get("tools", [])
    if not tools:
        return ""

    lines = [
        "| Tool | Status | Latest Run | Consecutive Failures | Last Success |",
        "|------|--------|------------|---------------------|--------------|",
    ]

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

    return "\n".join(lines)


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

    table = _render_tooling_health_table(tooling_health_data)
    if not table:
        return ""

    lines = ["## Tooling Health", "", table]

    tools = tooling_health_data.get("tools", [])
    unhealthy_tools = [t for t in tools if t.get("health", {}).get("status") in ("unhealthy", "error")]
    if unhealthy_tools:
        names = ", ".join(t.get("name", "unknown") for t in unhealthy_tools)
        lines.extend(
            [
                "",
                f"**⚠ WARNING: The violation data in this report may be stale because the {names} workflow is failing.**",
            ]
        )

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


def write_todo_preview(
    output_path: str,
    *,
    metadata_header: str,
    key_takeaways: str,
) -> None:
    """Write TODO preview file for chat display.

    Contains the metadata header (context confirmation) and the TODO section
    with summary preamble and all TODO #N subsections. This is the actionable
    subset shown in agent chat — the full resolution guide (submitted to
    GitHub) contains all sections including coverage, detailed resolution
    steps, and stats.
    """
    sections = [metadata_header, key_takeaways]
    content = "\n\n".join(s for s in sections if s)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"TODO preview written to {path}", file=sys.stderr)
