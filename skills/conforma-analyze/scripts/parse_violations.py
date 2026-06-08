#!/usr/bin/env python3
"""Parse conforma violation report CSVs into a structured YAML index.

Reads CSV files (one per release) from a directory, extracts full rule codes
deterministically from the message column, filters to type=violation only,
and outputs a structured YAML file.

The output is wrapped in a `violation_data` top-level key for future
handover document embedding.

Usage:
    python3 scripts/parse_violations.py \\
      --reports-dir /tmp/conforma-reports \\
      --output /tmp/conforma-violations.yaml
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Rule code extraction: deterministic regex patterns per rule family
# ---------------------------------------------------------------------------

_RULE_EXTRACTORS: list[tuple[str, re.Pattern]] = [
    # rpm_signature.allowed -> extract 16-char hex key ID from message
    ("rpm_signature.allowed", re.compile(r"([0-9a-fA-F]{16})(?![0-9a-fA-F])")),
    # test.no_failed_tests -> extract test/task name from message
    ("test.no_failed_tests", re.compile(r"(?:task|test)\s+['\"]?(\S+?)['\"]?\s+(?:failed|did not)")),
]


def extract_full_rule_code(code: str, message: str) -> str:
    """Extract the full rule code including suffix from the message.

    For rules with known suffix patterns (e.g. rpm_signature.allowed),
    parses the message to find the suffix and returns code:suffix.
    For rules without suffixes, returns the base code as-is.
    """
    for prefix, pattern in _RULE_EXTRACTORS:
        if code.startswith(prefix):
            match = pattern.search(message)
            if match:
                suffix = match.group(1)
                return f"{code}:{suffix}"
            return code

    if ":" in code:
        return code

    return code


# ---------------------------------------------------------------------------
# Defensive YAML serialization
# ---------------------------------------------------------------------------

class _QuotedStr(str):
    """String subclass that forces YAML double-quoting."""


def _quoted_str_representer(dumper: yaml.Dumper, data: _QuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def _safe_yaml_dump(data: dict, comment_header: str = "") -> str:
    """Dump data to YAML with defensive quoting for timestamps, rule codes, URLs.

    All string values that could be misinterpreted by YAML (timestamps,
    strings containing colons, URLs) are explicitly double-quoted.
    """
    safe_data = _quote_strings_recursively(data)

    dumper = yaml.Dumper
    dumper.add_representer(_QuotedStr, _quoted_str_representer)

    body = yaml.dump(
        safe_data,
        Dumper=dumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    if comment_header:
        return comment_header.rstrip("\n") + "\n\n" + body
    return body


def _needs_quoting(value: str) -> bool:
    """Determine if a string needs explicit quoting in YAML."""
    if not value:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return True
    if ":" in value:
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if value.startswith("#"):
        return True
    if value.lower() in ("true", "false", "yes", "no", "null", "on", "off"):
        return True
    return False


def _quote_strings_recursively(obj):
    """Walk a data structure and wrap strings that need quoting."""
    if isinstance(obj, str):
        if _needs_quoting(obj):
            return _QuotedStr(obj)
        return obj
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            safe_key = _QuotedStr(k) if isinstance(k, str) and _needs_quoting(k) else k
            result[safe_key] = _quote_strings_recursively(v)
        return result
    if isinstance(obj, list):
        return [_quote_strings_recursively(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_csv_file(csv_path: Path, release: str) -> list[dict]:
    """Parse a single CSV file, returning violation records."""
    records = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_type = (row.get("type") or "").strip().lower()
            if row_type != "violation":
                continue

            code = (row.get("code") or "").strip()
            message = (row.get("message") or "").strip()
            component = (row.get("component_name") or "").strip()
            title = (row.get("title") or "").strip()

            if not code or not component:
                continue

            full_rule = extract_full_rule_code(code, message)
            records.append({
                "release": release,
                "component_name": component,
                "rule": full_rule,
                "base_code": code,
                "title": title,
                "message": message,
            })

    return records


CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"


def _build_report_url(release: str, source_path: str = "") -> str:
    """Build a GitHub URL to the violations report for a release."""
    csv_path = source_path or "prod/release_day/conforma-violations-report.csv"
    return f"https://github.com/{CONFORMA_REPORTER_REPO}/blob/{release}/{csv_path}"


def build_violations_index(
    all_records: list[dict],
    releases: list[str],
    source_paths: dict[str, str] | None = None,
    failed_releases: list[dict] | None = None,
) -> dict:
    """Build the structured violations index from parsed records."""
    by_rule: dict[str, dict] = {}
    by_component: dict[str, dict] = defaultdict(lambda: {"rules": set(), "releases": set()})

    for rec in all_records:
        rule = rec["rule"]
        release = rec["release"]
        component = rec["component_name"]

        if rule not in by_rule:
            by_rule[rule] = {
                "title": rec["title"],
                "base_code": rec["base_code"],
                "releases": defaultdict(set),
            }
        by_rule[rule]["releases"][release].add(component)

        by_component[component]["rules"].add(rule)
        by_component[component]["releases"].add(release)

    violations_by_rule = {}
    for rule, info in sorted(by_rule.items()):
        rule_entry = {
            "title": info["title"],
            "base_code": info["base_code"],
            "releases": {},
        }
        for release in releases:
            components = info["releases"].get(release, set())
            if components:
                rule_entry["releases"][release] = sorted(components)
        violations_by_rule[rule] = rule_entry

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
        unique_rules = set(r["rule"] for r in release_records)
        unique_components = set(r["component_name"] for r in release_records)
        summary[release] = {
            "total_violations": len(release_records),
            "unique_rules": len(unique_rules),
            "unique_components": len(unique_components),
        }

    report_urls = {}
    for release in releases:
        src = (source_paths or {}).get(release, "")
        report_urls[release] = _build_report_url(release, src)

    result = {
        "violation_data": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "releases": releases,
            "report_urls": report_urls,
            "summary": summary,
            "violations_by_rule": violations_by_rule,
            "violations_by_component": violations_by_component,
        }
    }

    if failed_releases:
        result["violation_data"]["failed_releases"] = failed_releases

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse conforma violation CSVs into structured YAML"
    )
    parser.add_argument(
        "--reports-dir",
        required=True,
        help="Directory containing per-release CSV files (named <release>.csv)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output YAML file path",
    )
    parser.add_argument(
        "--source-paths-json",
        default=None,
        help='JSON mapping release->source_path (e.g. \'{"rhoai-3.4":"prod/release_day/conforma-violations-report.csv"}\')',
    )
    parser.add_argument(
        "--failed-releases-json",
        default=None,
        help='JSON array of releases that failed to fetch (e.g. \'[{"release":"rhoai-3.5","error":"branch not found"}]\')',
    )
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    if not reports_dir.is_dir():
        print(f"Error: reports directory not found: {reports_dir}", file=sys.stderr)
        return 1

    csv_files = sorted(reports_dir.glob("*.csv"))
    if not csv_files:
        print(f"Error: no CSV files found in {reports_dir}", file=sys.stderr)
        return 1

    all_records: list[dict] = []
    releases: list[str] = []

    for csv_path in csv_files:
        release = csv_path.stem
        releases.append(release)
        print(f"Parsing {csv_path.name}...", file=sys.stderr)
        records = parse_csv_file(csv_path, release)
        all_records.extend(records)
        print(f"  {len(records)} violations", file=sys.stderr)

    import json as _json

    source_paths = None
    if args.source_paths_json:
        source_paths = _json.loads(args.source_paths_json)

    failed_releases = None
    if args.failed_releases_json:
        failed_releases = _json.loads(args.failed_releases_json)

    index = build_violations_index(all_records, releases, source_paths, failed_releases)

    comment_header = (
        f"# conforma-analyze violations output\n"
        f"# Generated: {index['violation_data']['generated_at']}\n"
        f"# Releases checked: {', '.join(releases)}"
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_safe_yaml_dump(index, comment_header), encoding="utf-8")

    total = len(all_records)
    rules = len(index["violation_data"]["violations_by_rule"])
    print(
        f"\nDone. {total} violations, {rules} unique rules across "
        f"{len(releases)} releases -> {output_path}",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
