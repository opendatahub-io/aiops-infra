#!/usr/bin/env python3
"""parse_violations — Parse conforma violation and warnings report CSVs into a structured YAML index.

PUBLIC API:
    extract_full_rule_code(code, message, description) -> str  [line 70]
    extract_full_violation_code(description, code, message) -> str  [line 105]
    get_semantic_catalog() -> dict  [line 147]
    extract_semantic_detail(code, message, full_violation_code, catalog) -> str  [line 155]
    parse_csv_file(csv_path, release) -> list[dict]  [line 292]
    parse_warnings_csv_file(csv_path, release, threshold_days, reference_date) -> list[dict]  [line 358]
    build_semantic_detail_lookup(violations_yaml_data) -> tuple[dict[tuple[str, str], list[str]], dict[str, str]]  [line 547]
    build_violations_index(all_records, releases, environment, failed_releases, report_dates, upcoming_records, upcoming_threshold_days) -> dict  [line 576]
    main() -> int  [line 730]

INTERNAL SECTIONS:
    Main: _load_semantic_catalog
    _QuotedStr: _quoted_str_representer, _safe_yaml_dump, _needs_quoting, _quote_strings_recursively, _parse_date, ... (+3 more)

DEPENDENCIES: argparse, collections, conforma_constants, conforma_context_ops, conforma_counting, csv, datetime, pathlib, re, sys

"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import conforma_context_ops
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import conforma_counting
import yaml


# ---------------------------------------------------------------------------
# Rule code extraction: deterministic regex patterns per rule family
# ---------------------------------------------------------------------------

# Each extractor is (rule_prefix, [(field, pattern), ...]).
# Fields are tried in order; first match wins.  Supported fields: "message", "description".
_RULE_EXTRACTORS: list[tuple[str, list[tuple[str, re.Pattern]]]] = [
    # rpm_signature.allowed -> extract 16-char hex key ID from message
    ("rpm_signature.allowed", [
        ("message", re.compile(r"([0-9a-fA-F]{16})(?![0-9a-fA-F])")),
    ]),
    # test.no_failed_tests -> extract task name from description (primary) or message (fallback)
    # Description contains the exact EC exclude entry: add "test.no_failed_tests:<task-name>"
    # Message contains: The Task "<task-name>" from the build Pipeline reports a failed test
    ("test.no_failed_tests", [
        ("description", re.compile(r'test\.no_failed_tests:([^"]+)')),
        ("message", re.compile(r'[Tt]ask\s+"([^"]+)"')),
    ]),
    # test.no_erred_tests -> extract task name (same message pattern as no_failed_tests)
    # Message contains: The Task "<task-name>" from the build Pipeline reports a test erred
    ("test.no_erred_tests", [
        ("description", re.compile(r'test\.no_erred_tests:([^"]+)')),
        ("message", re.compile(r'[Tt]ask\s+"([^"]+)"')),
    ]),
]


def extract_full_rule_code(code: str, message: str, description: str = "") -> str:
    """Extract the full rule code including suffix from CSV fields.

    For rules with known suffix patterns, parses the description and/or
    message to find the suffix and returns code:suffix.
    For rules without suffixes, returns the base code as-is.

    The description field is preferred when available because the EC engine
    embeds the exact exclude entry (e.g. "test.no_failed_tests:task-name")
    which matches the policy exclusion format directly.
    """
    fields = {"message": message, "description": description}
    for prefix, patterns in _RULE_EXTRACTORS:
        if code.startswith(prefix):
            for field_name, pattern in patterns:
                text = fields.get(field_name, "")
                if text:
                    match = pattern.search(text)
                    if match:
                        return f"{code}:{match.group(1)}"
            return code

    if ":" in code:
        return code

    return code


# ---------------------------------------------------------------------------
# Universal full violation code extraction
# ---------------------------------------------------------------------------

_FULL_VIOLATION_CODE_RE = re.compile(r'To exclude this rule add "([^"]+)"')


def extract_full_violation_code(description: str, code: str, message: str = "") -> str:
    """Extract the full violation code from the Conforma engine's exclusion hint.

    The Conforma engine embeds the exact policy-matching identifier in every
    violation's description field:

        To exclude this rule add "violation_code:suffix" to the `exclude` section...

    This is the canonical full violation code used for policy-matching and
    exception filing.

    Falls back to the legacy _RULE_EXTRACTORS if the description is missing
    or malformed.
    """
    if description:
        match = _FULL_VIOLATION_CODE_RE.search(description)
        if match:
            return match.group(1)

    return extract_full_rule_code(code, message, description)


# ---------------------------------------------------------------------------
# Semantic detail extraction
# ---------------------------------------------------------------------------


def _load_semantic_catalog() -> dict:
    """Load the violation-detail-extractors.yaml catalog."""
    catalog_path = (
        Path(__file__).resolve().parent.parent.parent
        / "references"
        / "violation-detail-extractors.yaml"
    )
    if not catalog_path.exists():
        return {}
    return yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}


_SEMANTIC_CATALOG: dict | None = None


def get_semantic_catalog() -> dict:
    """Return the cached semantic detail catalog (loaded once)."""
    global _SEMANTIC_CATALOG
    if _SEMANTIC_CATALOG is None:
        _SEMANTIC_CATALOG = _load_semantic_catalog()
    return _SEMANTIC_CATALOG


def _apply_extraction(
    extraction: dict, message: str, full_violation_code: str
) -> str:
    """Apply a single extraction config and return the extracted detail."""
    field = extraction.get("field", "")
    pattern_str = extraction.get("pattern", "")
    group = extraction.get("group", 1)
    fmt = extraction.get("format")

    if field == "message":
        text = message
    elif field == "full_violation_code_suffix":
        text = full_violation_code.split(":", 1)[1] if ":" in full_violation_code else ""
    else:
        text = ""

    if not text or not pattern_str:
        return ""

    match = re.search(pattern_str, text)
    if not match:
        return ""

    if fmt:
        result = fmt
        for i in range(1, match.lastindex + 1 if match.lastindex else 1):
            result = result.replace(f"{{{i}}}", match.group(i) or "")
        return result

    return match.group(group) if match.lastindex and group <= match.lastindex else match.group(0)


def extract_semantic_detail(
    code: str,
    message: str,
    full_violation_code: str,
    catalog: dict | None = None,
) -> str:
    """Extract the semantic detail that defines a unique violation.

    The semantic detail is the actionable root cause (e.g., a repo ID, an
    attribute name, a package name). It is extracted using the rule-specific
    config in the violation-detail-extractors.yaml catalog.

    For uncataloged codes (not in the catalog's ``rules`` section), the
    configured extraction is tried first (typically full_violation_code suffix
    via ``_default``).  When that yields nothing, the raw ``message`` is used
    as the semantic detail so that new violation codes surface their details
    automatically without manual catalog entries.

    A violation = (violation_code + component + semantic_detail).
    """
    if catalog is None:
        catalog = get_semantic_catalog()

    rules = catalog.get("rules", {})
    entry = rules.get(code)
    is_cataloged = entry is not None
    if not is_cataloged:
        entry = catalog.get("_default")
    if entry is None:
        suffix = full_violation_code.split(":", 1)[1] if ":" in full_violation_code else ""
        return suffix or message

    if entry.get("detail_label") is None:
        return ""

    extraction = entry.get("extraction")
    if extraction is None:
        return message if not is_cataloged else ""

    result = _apply_extraction(extraction, message, full_violation_code)

    if not result and not is_cataloged:
        return message

    return result


# ---------------------------------------------------------------------------
# Defensive YAML serialization
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def parse_csv_file(csv_path: Path, release: str) -> list[dict]:
    """Parse a single CSV file, returning violation records."""
    catalog = get_semantic_catalog()
    records = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_type = (row.get("type") or "").strip().lower()
            if row_type != "violation":
                continue

            code = (row.get("code") or "").strip()
            message = (row.get("message") or "").strip()
            description = (row.get("description") or "").strip()
            component = (row.get("component_name") or "").strip()
            title = (row.get("title") or "").strip()
            image = (row.get("image") or "").strip()
            effective_on = (row.get("effective_on") or "").strip()
            solution = (row.get("solution") or "").strip()

            if not code or not component:
                continue

            full_violation_code = extract_full_violation_code(description, code, message)
            semantic_detail = extract_semantic_detail(code, message, full_violation_code, catalog)
            records.append(
                {
                    "type": "violation",
                    "release": release,
                    "component_name": component,
                    "image": image,
                    "code": code,
                    "full_violation_code": full_violation_code,
                    "semantic_detail": semantic_detail,
                    "title": title,
                    "message": message,
                    "effective_on": effective_on,
                    "description": description,
                    "solution": solution,
                }
            )

    return records


DEFAULT_UPCOMING_THRESHOLD_DAYS = 21




def parse_warnings_csv_file(
    csv_path: Path,
    release: str,
    threshold_days: int = DEFAULT_UPCOMING_THRESHOLD_DAYS,
    reference_date: datetime | None = None,
) -> list[dict]:
    """Parse a warnings CSV file, returning records for warnings becoming violations.

    Warnings are policies not yet enforced.  A warning is included when its
    ``effective_on`` enforcement date is in the future but within
    ``threshold_days`` of the reference date (defaults to now) — meaning
    it will become an enforced violation soon.  Warnings with no parseable
    ``effective_on`` or with dates beyond the threshold are excluded.
    """
    now = reference_date or datetime.now(timezone.utc)
    cutoff = now + timedelta(days=threshold_days)
    catalog = get_semantic_catalog()
    records = []

    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_type = (row.get("type") or "").strip().lower()
            if row_type != "warning":
                continue

            code = (row.get("code") or "").strip()
            message = (row.get("message") or "").strip()
            description = (row.get("description") or "").strip()
            component = (row.get("component_name") or "").strip()
            title = (row.get("title") or "").strip()
            effective_on_str = (row.get("effective_on") or "").strip()

            if not code or not component:
                continue

            effective_dt = _parse_date(effective_on_str)
            if effective_dt is None:
                continue

            if effective_dt > cutoff:
                continue

            days_remaining = (effective_dt - now).days
            full_violation_code = extract_full_violation_code(description, code, message)
            semantic_detail = extract_semantic_detail(code, message, full_violation_code, catalog)
            records.append(
                {
                    "release": release,
                    "component_name": component,
                    "code": code,
                    "full_violation_code": full_violation_code,
                    "semantic_detail": semantic_detail,
                    "title": title,
                    "message": message,
                    "effective_on": effective_on_str,
                    "days_until_effective": max(days_remaining, 0),
                }
            )

    return records


from conforma_constants import (
    build_report_url as _build_report_url,
    build_warnings_report_url as _build_warnings_report_url,
)
from date_ops import parse_date as _parse_date  # noqa: F401
from conforma_yaml_ops import QuotedStr as _QuotedStr  # noqa: F401
from conforma_yaml_ops import quoted_str_representer as _quoted_str_representer  # noqa: F401
from conforma_yaml_ops import safe_yaml_dump as _safe_yaml_dump  # noqa: F401
from conforma_yaml_ops import needs_quoting as _needs_quoting  # noqa: F401
from conforma_yaml_ops import quote_strings_recursively as _quote_strings_recursively  # noqa: F401


def _build_upcoming_violations_section(
    upcoming_records: list[dict],
    releases: list[str],
    threshold_days: int,
    environment: str,
) -> dict:
    """Build the upcoming_violations section from warnings becoming violations."""
    if not upcoming_records:
        return {}

    by_rule: dict[str, dict] = {}
    by_component: dict[str, dict] = defaultdict(lambda: {"rules": set(), "releases": set()})

    for rec in upcoming_records:
        code = rec["code"]
        release = rec["release"]
        component = rec["component_name"]
        effective_on = rec["effective_on"]
        days_left = rec["days_until_effective"]

        if code not in by_rule:
            by_rule[code] = {
                "title": rec["title"],
                "violation_code": code,
                "releases": defaultdict(set),
                "effective_on": effective_on,
                "days_until_effective": days_left,
            }
        else:
            existing_dt = _parse_date(by_rule[code]["effective_on"])
            new_dt = _parse_date(effective_on)
            if existing_dt and new_dt and new_dt < existing_dt:
                by_rule[code]["effective_on"] = effective_on
                by_rule[code]["days_until_effective"] = days_left

        by_rule[code]["releases"][release].add(component)
        by_component[component]["rules"].add(code)
        by_component[component]["releases"].add(release)

    upcoming_by_rule = {}
    for code, info in sorted(by_rule.items()):
        rule_entry = {
            "title": info["title"],
            "violation_code": info["violation_code"],
            "effective_on": info["effective_on"],
            "days_until_effective": info["days_until_effective"],
            "releases": {},
        }
        for release in releases:
            components = info["releases"].get(release, set())
            if components:
                rule_entry["releases"][release] = sorted(components)
        upcoming_by_rule[code] = rule_entry

    upcoming_by_component = {}
    for comp, info in sorted(by_component.items()):
        comp_releases = sorted(info["releases"])
        upcoming_by_component[comp] = {
            "release": comp_releases[0] if len(comp_releases) == 1 else comp_releases,
            "rules": sorted(info["rules"]),
        }

    upcoming_summary = {}
    for release in releases:
        release_records = [r for r in upcoming_records if r["release"] == release]
        if not release_records:
            continue
        unique_codes = set(r["code"] for r in release_records)
        unique_components = set(r["component_name"] for r in release_records)
        dates = [r["effective_on"] for r in release_records if r["effective_on"]]
        earliest = min(dates) if dates else ""
        upcoming_summary[release] = {
            "total_upcoming": len(release_records),
            "unique_violation_codes": len(unique_codes),
            "unique_components": len(unique_components),
            "earliest_deadline": earliest,
        }

    warnings_report_urls = {release: _build_warnings_report_url(release, environment) for release in releases}

    return {
        "threshold_days": threshold_days,
        "warnings_report_urls": warnings_report_urls,
        "summary": upcoming_summary,
        "by_rule": upcoming_by_rule,
        "by_component": upcoming_by_component,
    }


def _build_semantic_violations(records_for_code: list[dict], catalog: dict) -> list[dict]:
    """Build the semantic_violations sub-structure for a violation code.

    Groups records by (semantic_detail, component) and collects the
    full_violation_codes for each group (for exception-filing scripts).
    """
    by_detail_comp: dict[tuple[str, str], set[str]] = defaultdict(set)

    for rec in records_for_code:
        detail = rec.get("semantic_detail", "")
        comp = rec["component_name"]
        full_code = rec.get("full_violation_code", "")
        by_detail_comp[(detail, comp)].add(full_code)

    by_detail: dict[str, dict] = {}
    for (detail, comp), full_codes in sorted(by_detail_comp.items()):
        if detail not in by_detail:
            by_detail[detail] = {"components": [], "full_violation_codes": set()}
        by_detail[detail]["components"].append(comp)
        by_detail[detail]["full_violation_codes"].update(full_codes)

    result = []
    for detail, info in sorted(by_detail.items()):
        entry: dict = {"detail": detail, "components": sorted(info["components"])}
        codes = sorted(info["full_violation_codes"] - {""})
        if codes:
            entry["full_violation_codes"] = codes
        result.append(entry)
    return result


def build_semantic_detail_lookup(
    violations_yaml_data: dict,
) -> tuple[dict[tuple[str, str], list[str]], dict[str, str]]:
    """Build semantic detail lookup from a loaded violations YAML.

    Returns:
        (detail_lookup, detail_labels) where:
        - detail_lookup: maps (base_violation_code, component) to a list of
          semantic detail strings for that combination
        - detail_labels: maps base_violation_code to its human-readable
          detail category label (e.g. "package name", "signing key")
    """
    detail_lookup: dict[tuple[str, str], list[str]] = {}
    detail_labels: dict[str, str] = {}
    by_rule_data = violations_yaml_data.get("violation_data", {}).get("violations_by_rule", {})
    for rule_key, rule_info in by_rule_data.items():
        base_code = rule_info.get("violation_code", rule_key.split(":")[0])
        dl = rule_info.get("detail_label", "")
        if dl:
            detail_labels[base_code] = dl
        for sv in rule_info.get("semantic_violations", []):
            detail = sv.get("detail", "")
            if not detail:
                continue
            for comp in sv.get("components", []):
                detail_lookup.setdefault((base_code, comp), []).append(detail)
    return detail_lookup, detail_labels


def build_violations_index(
    all_records: list[dict],
    releases: list[str],
    environment: str,
    failed_releases: list[dict] | None = None,
    report_dates: dict[str, str] | None = None,
    upcoming_records: list[dict] | None = None,
    upcoming_threshold_days: int = DEFAULT_UPCOMING_THRESHOLD_DAYS,
) -> dict:
    """Build the structured violations index from parsed records.

    Groups violations by base violation_code and deduplicates using the
    semantic model: (violation_code, component, semantic_detail).

    When ``upcoming_records`` is provided (from warnings CSV parsing), an
    ``upcoming_violations`` section is included — these are warnings that
    will become enforced violations once their ``effective_on`` date passes.
    """
    catalog = get_semantic_catalog()
    by_code: dict[str, dict] = {}
    by_component: dict[str, dict] = defaultdict(lambda: {"rules": set(), "releases": set()})
    records_by_code: dict[str, list[dict]] = defaultdict(list)

    for rec in all_records:
        code = rec["code"]
        release = rec["release"]
        component = rec["component_name"]

        if code not in by_code:
            by_code[code] = {
                "title": rec["title"],
                "releases": defaultdict(set),
                "seen_violations": set(),
                "csv_row_count": 0,
                "descriptions": set(),
                "solution": "",
                "messages": set(),
            }
        by_code[code]["csv_row_count"] += 1
        by_code[code]["seen_violations"].add((code, component, rec.get("semantic_detail", "")))
        by_code[code]["releases"][release].add(component)
        desc = rec.get("description", "")
        if desc:
            by_code[code]["descriptions"].add(desc)
        if not by_code[code]["solution"] and rec.get("solution"):
            by_code[code]["solution"] = rec["solution"]
        msg = rec.get("message", "")
        if msg:
            by_code[code]["messages"].add(msg)
        records_by_code[code].append(rec)

        by_component[component]["rules"].add(code)
        by_component[component]["releases"].add(release)

    rules_config = catalog.get("rules", {})
    default_detail_label = catalog.get("_default", {}).get("detail_label")

    # Auto-suppress uniform details for uncataloged codes: when every record
    # for a code has the same non-empty semantic_detail that came from the
    # message fallback, suppress it to avoid redundant display.  Details
    # derived from the full_violation_code suffix are always meaningful
    # (policy-matching identifiers) and must NOT be suppressed.
    for code, recs in records_by_code.items():
        if code in rules_config:
            continue
        unique_details = {r.get("semantic_detail", "") for r in recs}
        if len(unique_details) == 1 and unique_details != {""}:
            has_suffix = any(":" in r.get("full_violation_code", "") for r in recs)
            if has_suffix:
                continue
            for r in recs:
                r["semantic_detail"] = ""
            by_code[code]["seen_violations"] = {
                (code, r["component_name"], "") for r in recs
            }

    violations_by_rule = {}
    for code, info in sorted(by_code.items()):
        detail_label = None
        if code in rules_config:
            detail_label = rules_config[code].get("detail_label")
        else:
            has_details = any(r.get("semantic_detail", "") for r in records_by_code[code])
            if has_details and default_detail_label is not None:
                detail_label = default_detail_label

        rule_entry = {
            "title": info["title"],
            "violation_code": code,
            "count": len(info["seen_violations"]),
            "csv_row_count": info["csv_row_count"],
            "releases": {},
            "semantic_violations": _build_semantic_violations(records_by_code[code], catalog),
            "descriptions": sorted(info["descriptions"]),
            "solution": info["solution"],
            "messages": sorted(info["messages"]),
        }
        if detail_label is not None:
            rule_entry["detail_label"] = detail_label
        for release in releases:
            components = info["releases"].get(release, set())
            if components:
                rule_entry["releases"][release] = sorted(components)
        violations_by_rule[code] = rule_entry

    violations_by_component = {}
    for comp, info in sorted(by_component.items()):
        comp_releases = sorted(info["releases"])
        violations_by_component[comp] = {
            "release": comp_releases[0] if len(comp_releases) == 1 else comp_releases,
            "rules": sorted(info["rules"]),
        }

    summary = {}
    for release in releases:
        release_records = [r for r in all_records if r["release"] == release]
        counts = conforma_counting.count_from_records(
            release_records,
            component_field="component_name",
            detail_field="semantic_detail",
            full_code_field="full_violation_code",
        )
        unique_codes = set(r["code"] for r in release_records)
        unique_components = set(r["component_name"] for r in release_records)
        summary[release] = {
            "total_violations": counts.violations,
            "total_csv_rows": counts.image_occurrences,
            "full_violation_code_count": counts.full_violation_code_count,
            "unique_violation_codes": len(unique_codes),
            "unique_components": len(unique_components),
        }

    report_urls = {release: _build_report_url(release, environment) for release in releases}
    dates = report_dates or {}
    report_created_at = {rel: dates.get(rel, "") for rel in releases if dates.get(rel)}

    result = {
        "violation_data": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "releases": releases,
            "report_urls": report_urls,
            "report_created_at": report_created_at,
            "summary": summary,
            "violations_by_rule": violations_by_rule,
            "violations_by_component": violations_by_component,
        }
    }

    if failed_releases:
        result["violation_data"]["failed_releases"] = failed_releases

    if upcoming_records:
        upcoming_section = _build_upcoming_violations_section(upcoming_records, releases, upcoming_threshold_days, environment)
        if upcoming_section:
            result["violation_data"]["upcoming_violations"] = upcoming_section

    return result


def _enrich_with_catalog(index: dict) -> bool:
    """Add jira_component to each violations_by_component entry.

    Uses component_catalog_ops to resolve Konflux component names to Jira
    Components.  Returns True if enrichment succeeded.
    """
    import component_catalog_ops

    vdata = index.get("violation_data", {})
    by_component = vdata.get("violations_by_component", {})
    upcoming_by_comp = vdata.get("upcoming_violations", {}).get("by_component", {})

    all_names = sorted(set(list(by_component.keys()) + list(upcoming_by_comp.keys())))
    if not all_names:
        return True

    catalog = component_catalog_ops.load_catalog()
    mapping = component_catalog_ops.resolve_jira_components(all_names, catalog)

    for comp in by_component:
        by_component[comp]["jira_component"] = mapping.get(comp)
    for comp in upcoming_by_comp:
        upcoming_by_comp[comp]["jira_component"] = mapping.get(comp)

    unmapped = [n for n, v in mapping.items() if v is None]
    if unmapped:
        print(
            f"  {len(unmapped)} components could not be mapped to Jira Components: {', '.join(unmapped[:5])}",
            file=sys.stderr,
        )

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse conforma violation and warnings CSVs into structured YAML")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
    )
    parser.add_argument(
        "--reports-dir",
        default=None,
        help="Directory containing per-release CSV files ({release}.csv and {release}-warnings.csv)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output YAML file path",
    )
    parser.add_argument(
        "--failed-releases-json",
        default=None,
        help='JSON array of releases that failed to fetch (e.g. \'[{"release":"rhoai-3.5","error":"branch not found"}]\')',
    )
    parser.add_argument(
        "--report-dates-json",
        default=None,
        help="JSON mapping release->ISO-8601 date when the report was last committed",
    )
    parser.add_argument(
        "--upcoming-threshold-days",
        type=int,
        default=DEFAULT_UPCOMING_THRESHOLD_DAYS,
        help=f"Warnings enforced within this many days are flagged as becoming violations (default: {DEFAULT_UPCOMING_THRESHOLD_DAYS})",
    )
    parser.add_argument(
        "--no-warnings",
        action="store_true",
        default=False,
        help="Skip parsing warnings CSVs",
    )
    parser.add_argument(
        "--no-catalog",
        action="store_true",
        default=False,
        help="Skip Jira Component enrichment from component-maturity catalog (for CI/testing only)",
    )
    parser.add_argument(
        "--release",
        default=None,
        help="Only parse CSVs for this specific release (e.g. rhoai-3.5-ea.1). "
        "When set, only {release}.csv and {release}-warnings.csv are processed "
        "from the reports directory; other CSVs are ignored. "
        "This prevents accidentally analyzing all releases when only one was intended.",
    )
    parser.add_argument(
        "--environment",
        default=None,
        choices=["prod", "stage"],
        help="Target environment (prod or stage) — determines which CSV report URLs are generated",
    )
    args = parser.parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    environment = conforma_context_ops.resolve_arg(args, "environment", context, "environment")

    target_release = args.release
    if target_release is None and context:
        target_release = conforma_context_ops.get(run_dir, "application.release", None)

    if args.reports_dir:
        reports_dir_path = Path(args.reports_dir)
    elif run_dir:
        reports_dir_path = Path(run_dir)
    else:
        print("Error: --reports-dir is required when no run context is available", file=sys.stderr)
        return 1

    if args.output:
        output_path = Path(args.output)
    elif run_dir:
        output_path = Path(run_dir) / "violations.yaml"
    else:
        print("Error: --output is required when no run context is available", file=sys.stderr)
        return 1

    if not args.no_catalog:
        import component_catalog_ops

        print("Loading component-maturity catalog...", file=sys.stderr)
        cat_result = component_catalog_ops.ensure_catalog_repo()
        if not cat_result["ok"]:
            print(
                f"Error: component-maturity catalog unavailable: {cat_result['error']}\n"
                "VPN and GitLab auth are required. Use --no-catalog to skip (CI/testing only).",
                file=sys.stderr,
            )
            return 1
        print(f"  Catalog ready at {cat_result['path']}", file=sys.stderr)

    if not reports_dir_path.is_dir():
        print(f"Error: reports directory not found: {reports_dir_path}", file=sys.stderr)
        return 1

    if target_release:
        target_csv = reports_dir_path / f"{target_release}.csv"
        if not target_csv.exists():
            print(
                f"Error: no CSV found for release '{target_release}' "
                f"(expected {target_csv})",
                file=sys.stderr,
            )
            return 1
        violation_csv_files = [target_csv]
    else:
        violation_csv_files = sorted(f for f in reports_dir_path.glob("*.csv") if not f.name.endswith("-warnings.csv"))
    if not violation_csv_files:
        print(f"Error: no violation CSV files found in {reports_dir_path}", file=sys.stderr)
        return 1

    all_records: list[dict] = []
    releases: list[str] = []

    for csv_path in violation_csv_files:
        release = csv_path.stem
        releases.append(release)
        print(f"Parsing {csv_path.name}...", file=sys.stderr)
        records = parse_csv_file(csv_path, release)
        all_records.extend(records)
        print(f"  {len(records)} violations", file=sys.stderr)

    upcoming_records: list[dict] = []
    if not args.no_warnings:
        if target_release:
            target_warn = reports_dir_path / f"{target_release}-warnings.csv"
            warning_csv_files = [target_warn] if target_warn.exists() else []
        else:
            warning_csv_files = sorted(reports_dir_path.glob("*-warnings.csv"))
        for csv_path in warning_csv_files:
            release = csv_path.stem.removesuffix("-warnings")
            print(f"Parsing warnings {csv_path.name}...", file=sys.stderr)
            warnings = parse_warnings_csv_file(csv_path, release, threshold_days=args.upcoming_threshold_days)
            upcoming_records.extend(warnings)
            print(
                f"  {len(warnings)} warnings becoming violations within {args.upcoming_threshold_days} days",
                file=sys.stderr,
            )

    import json as _json

    failed_releases = None
    if args.failed_releases_json:
        failed_releases = _json.loads(args.failed_releases_json)

    report_dates = None
    if args.report_dates_json:
        report_dates = _json.loads(args.report_dates_json)

    index = build_violations_index(
        all_records,
        releases,
        environment,
        failed_releases,
        report_dates,
        upcoming_records=upcoming_records or None,
        upcoming_threshold_days=args.upcoming_threshold_days,
    )

    catalog_enriched = False
    if not args.no_catalog:
        print("Enriching with Jira Component ownership...", file=sys.stderr)
        catalog_enriched = _enrich_with_catalog(index)
    index["violation_data"]["catalog_enriched"] = catalog_enriched

    comment_parts = [
        "# conforma-analyze violations output",
        f"# Generated: {index['violation_data']['generated_at']}",
        f"# Releases checked: {', '.join(releases)}",
    ]
    if upcoming_records:
        comment_parts.append(
            f"# Warnings becoming violations within {args.upcoming_threshold_days} days: {len(upcoming_records)}"
        )
    comment_header = "\n".join(comment_parts)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_safe_yaml_dump(index, comment_header), encoding="utf-8")

    if run_dir:
        conforma_context_ops.update_step(
            run_dir, "parse", "completed",
            violations_yaml=output_path.name,
        )

    total_counts = conforma_counting.count_from_records(
        all_records,
        component_field="component_name",
        detail_field="semantic_detail",
        full_code_field="full_violation_code",
    )
    violation_codes = len(index["violation_data"]["violations_by_rule"])
    upcoming_count = len(upcoming_records)
    msg = f"\nDone. {total_counts.violations} violations, {violation_codes} unique violation codes across {len(releases)} releases"
    if upcoming_count:
        upcoming_codes = len(index["violation_data"].get("upcoming_violations", {}).get("by_rule", {}))
        msg += f", {upcoming_count} warnings becoming violations ({upcoming_codes} violation codes)"
    msg += f" -> {output_path}"
    print(msg, file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
