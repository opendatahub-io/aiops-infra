#!/usr/bin/env python3
"""Analyze conforma violation reports and produce a structured summary.

Reads a violations CSV (or multiple CSVs from a directory) and outputs a
human-readable analysis covering:
  - Totals and breakdown by violation code
  - Root cause extraction (untrusted task names, signing keys, etc.)
  - Per-component violation patterns
  - Effective date enforcement deadlines
  - Prioritized remediation recommendations

Usage:
    # Analyze a single CSV:
    python3 scripts/analyze_report.py --csv /path/to/report.csv

    # Analyze all CSVs in a directory (one per release):
    python3 scripts/analyze_report.py --reports-dir /tmp/conforma-reports

    # Output as markdown:
    python3 scripts/analyze_report.py --csv /path/to/report.csv --format markdown

    # Output as JSON (for programmatic consumption):
    python3 scripts/analyze_report.py --csv /path/to/report.csv --format json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ViolationRecord:
    type: str
    component_name: str
    image: str
    message: str
    effective_on: str
    code: str
    title: str
    description: str
    solution: str
    release: str = ""


@dataclass
class AnalysisResult:
    total_violations: int = 0
    unique_codes: int = 0
    unique_components: int = 0
    violations_by_code: dict = field(default_factory=dict)
    violations_by_component: dict = field(default_factory=dict)
    component_patterns: list = field(default_factory=list)
    untrusted_tasks: dict = field(default_factory=dict)
    rpm_signature_details: list = field(default_factory=list)
    effective_dates: dict = field(default_factory=dict)
    priority_recommendations: list = field(default_factory=list)


def load_csv(csv_path: Path, release: str = "") -> list[ViolationRecord]:
    """Load violation records from a CSV file."""
    records = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(ViolationRecord(
                type=row.get("type", "").strip(),
                component_name=row.get("component_name", "").strip(),
                image=row.get("image", "").strip(),
                message=row.get("message", "").strip(),
                effective_on=row.get("effective_on", "").strip(),
                code=row.get("code", "").strip(),
                title=row.get("title", "").strip(),
                description=row.get("description", "").strip(),
                solution=row.get("solution", "").strip(),
                release=release or csv_path.stem,
            ))
    return [r for r in records if r.type == "violation"]


def load_reports_dir(reports_dir: Path) -> list[ViolationRecord]:
    """Load all CSVs from a directory."""
    all_records = []
    for csv_path in sorted(reports_dir.glob("*.csv")):
        release = csv_path.stem
        records = load_csv(csv_path, release)
        all_records.extend(records)
    return all_records


def extract_untrusted_tasks(records: list[ViolationRecord]) -> dict[str, int]:
    """Extract untrusted task names from trusted_task.trusted violation messages."""
    task_counts: Counter = Counter()
    for r in records:
        if r.code == "trusted_task.trusted":
            match = re.search(r'Task "([^"]+)"', r.message)
            if match:
                task_counts[match.group(1)] += 1
    return dict(task_counts.most_common())


def extract_rpm_signature_details(records: list[ViolationRecord]) -> list[dict]:
    """Extract RPM signature key details from rpm_signature.allowed violations."""
    details = []
    seen = set()
    for r in records:
        if r.code == "rpm_signature.allowed":
            key = (r.component_name, r.message)
            if key not in seen:
                seen.add(key)
                details.append({
                    "component": r.component_name,
                    "message": r.message,
                })
    return details


def compute_component_patterns(records: list[ViolationRecord]) -> list[dict]:
    """Compute violation code combinations per component."""
    comp_codes: dict[str, set] = defaultdict(set)
    for r in records:
        comp_codes[r.component_name].add(r.code)

    combos: Counter = Counter()
    combo_components: dict[tuple, list] = defaultdict(list)
    for comp, codes in sorted(comp_codes.items()):
        combo = tuple(sorted(codes))
        combos[combo] += 1
        combo_components[combo].append(comp)

    patterns = []
    for combo, count in combos.most_common():
        patterns.append({
            "codes": list(combo),
            "count": count,
            "components": sorted(combo_components[combo]),
        })
    return patterns


def compute_effective_dates(records: list[ViolationRecord]) -> dict[str, int]:
    """Count violations by effective_on date."""
    dates: Counter = Counter()
    for r in records:
        date_key = r.effective_on if r.effective_on else "(not set)"
        dates[date_key] += 1
    return dict(sorted(dates.items()))


def generate_priority_recommendations(
    records: list[ViolationRecord],
    code_counts: Counter,
    untrusted_tasks: dict,
) -> list[dict]:
    """Generate prioritized remediation recommendations."""
    recommendations = []
    total = len(records)

    prefetch_codes = {
        "trusted_task.trusted",
        "prefetch_dependencies.package_registry_proxy_enabled",
        "tasks.required_untrusted_task_found",
    }
    prefetch_count = sum(1 for r in records if r.code in prefetch_codes)
    if prefetch_count > 0:
        task_names = ", ".join(untrusted_tasks.keys()) if untrusted_tasks else "unknown"
        trusted_records = [r for r in records if r.code == "trusted_task.trusted"]
        upgrade_sha = ""
        for tr in trusted_records:
            sha_match = re.search(r"sha256:([a-f0-9]{64})", tr.message)
            if sha_match:
                upgrade_sha = f"sha256:{sha_match.group(1)}"
                break

        solution = f"Upgrade task ({task_names}) to trusted version"
        if upgrade_sha:
            solution += f" ({upgrade_sha})"
        solution += " and set enable-package-registry-proxy=true"

        recommendations.append({
            "priority": 1,
            "action": "Upgrade prefetch-dependencies task",
            "violations_resolved": prefetch_count,
            "percent_of_total": round(prefetch_count / total * 100, 1),
            "solution": solution,
            "affected_components": len(set(
                r.component_name for r in records if r.code in prefetch_codes
            )),
        })

    rpm_count = code_counts.get("rpm_signature.allowed", 0)
    if rpm_count > 0:
        rpm_components = sorted(set(
            r.component_name for r in records if r.code == "rpm_signature.allowed"
        ))
        recommendations.append({
            "priority": 2,
            "action": "Fix RPM signing key compliance",
            "violations_resolved": rpm_count,
            "percent_of_total": round(rpm_count / total * 100, 1),
            "solution": "Ensure RPMs use the allowed signing key or get the additional key approved",
            "affected_components": len(rpm_components),
        })

    hermetic_count = code_counts.get("hermetic_task.hermetic", 0)
    if hermetic_count > 0:
        comps = sorted(set(
            r.component_name for r in records if r.code == "hermetic_task.hermetic"
        ))
        recommendations.append({
            "priority": 3,
            "action": "Enable hermetic builds",
            "violations_resolved": hermetic_count,
            "percent_of_total": round(hermetic_count / total * 100, 1),
            "solution": "Set HERMETIC=true on the task",
            "affected_components": len(comps),
            "components": comps,
        })

    permissive_count = code_counts.get("prefetch_dependencies.mode_not_permissive", 0)
    if permissive_count > 0:
        comps = sorted(set(
            r.component_name for r in records
            if r.code == "prefetch_dependencies.mode_not_permissive"
        ))
        recommendations.append({
            "priority": 4,
            "action": "Fix permissive prefetch mode",
            "violations_resolved": permissive_count,
            "percent_of_total": round(permissive_count / total * 100, 1),
            "solution": "Change prefetch-dependencies mode from 'permissive' to a secure value",
            "affected_components": len(comps),
            "components": comps,
        })

    return recommendations


def analyze(records: list[ViolationRecord]) -> AnalysisResult:
    """Run the full analysis pipeline on a set of violation records."""
    result = AnalysisResult()
    result.total_violations = len(records)

    code_counts = Counter(r.code for r in records)
    result.unique_codes = len(code_counts)

    component_counts = Counter(r.component_name for r in records)
    result.unique_components = len(component_counts)

    for code, count in code_counts.most_common():
        code_records = [r for r in records if r.code == code]
        components = sorted(set(r.component_name for r in code_records))
        result.violations_by_code[code] = {
            "count": count,
            "title": code_records[0].title,
            "solution": code_records[0].solution,
            "affected_components": len(components),
            "components": components,
        }

    for comp, count in component_counts.most_common():
        comp_records = [r for r in records if r.component_name == comp]
        result.violations_by_component[comp] = {
            "count": count,
            "codes": sorted(set(r.code for r in comp_records)),
        }

    result.untrusted_tasks = extract_untrusted_tasks(records)
    result.rpm_signature_details = extract_rpm_signature_details(records)
    result.component_patterns = compute_component_patterns(records)
    result.effective_dates = compute_effective_dates(records)
    result.priority_recommendations = generate_priority_recommendations(
        records, code_counts, result.untrusted_tasks
    )

    return result


def format_text(result: AnalysisResult) -> str:
    """Format analysis result as plain text."""
    lines = []

    lines.append("=" * 80)
    lines.append("CONFORMA VIOLATIONS ANALYSIS")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Total violations:       {result.total_violations}")
    lines.append(f"Unique violation codes:  {result.unique_codes}")
    lines.append(f"Components affected:     {result.unique_components}")
    lines.append("")

    lines.append("-" * 80)
    lines.append("VIOLATIONS BY CODE")
    lines.append("-" * 80)
    for code, info in result.violations_by_code.items():
        pct = info["count"] / result.total_violations * 100
        lines.append(f"\n  {code}: {info['count']} ({pct:.1f}%)")
        lines.append(f"    Title: {info['title']}")
        lines.append(f"    Solution: {info['solution'][:200]}")
        lines.append(f"    Affected components: {info['affected_components']}")
    lines.append("")

    if result.untrusted_tasks:
        lines.append("-" * 80)
        lines.append("UNTRUSTED TASKS (from trusted_task.trusted violations)")
        lines.append("-" * 80)
        for task, count in result.untrusted_tasks.items():
            lines.append(f"  {task}: {count} violations")
        lines.append("")

    if result.rpm_signature_details:
        lines.append("-" * 80)
        lines.append("RPM SIGNATURE VIOLATIONS")
        lines.append("-" * 80)
        for detail in result.rpm_signature_details[:20]:
            lines.append(f"  {detail['component']}: {detail['message']}")
        if len(result.rpm_signature_details) > 20:
            lines.append(f"  ... and {len(result.rpm_signature_details) - 20} more")
        lines.append("")

    lines.append("-" * 80)
    lines.append("EFFECTIVE DATES")
    lines.append("-" * 80)
    for date, count in result.effective_dates.items():
        lines.append(f"  {date}: {count} violations")
    lines.append("")

    lines.append("-" * 80)
    lines.append("COMPONENT VIOLATION PATTERNS")
    lines.append("-" * 80)
    for pattern in result.component_patterns:
        codes_str = " + ".join(pattern["codes"])
        lines.append(f"  {pattern['count']} components: {codes_str}")
    lines.append("")

    lines.append("-" * 80)
    lines.append("PRIORITY RECOMMENDATIONS")
    lines.append("-" * 80)
    for rec in result.priority_recommendations:
        lines.append(f"\n  #{rec['priority']}: {rec['action']}")
        lines.append(f"    Resolves: {rec['violations_resolved']} violations"
                     f" ({rec['percent_of_total']}% of total)")
        lines.append(f"    Components: {rec['affected_components']}")
        lines.append(f"    Solution: {rec['solution']}")
    lines.append("")

    return "\n".join(lines)


def format_markdown(result: AnalysisResult) -> str:
    """Format analysis result as markdown."""
    lines = []

    lines.append("# Conforma Violations Analysis")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total violations | {result.total_violations} |")
    lines.append(f"| Unique violation codes | {result.unique_codes} |")
    lines.append(f"| Components affected | {result.unique_components} |")
    lines.append("")

    lines.append("## Violations by Code")
    lines.append("")
    lines.append("| Code | Count | % | Components | Title |")
    lines.append("|------|-------|---|------------|-------|")
    for code, info in result.violations_by_code.items():
        pct = info["count"] / result.total_violations * 100
        lines.append(
            f"| `{code}` | {info['count']} | {pct:.1f}% "
            f"| {info['affected_components']} | {info['title']} |"
        )
    lines.append("")

    if result.untrusted_tasks:
        lines.append("## Untrusted Tasks")
        lines.append("")
        for task, count in result.untrusted_tasks.items():
            lines.append(f"- `{task}`: {count} violations")
        lines.append("")

    if result.rpm_signature_details:
        lines.append("## RPM Signature Violations")
        lines.append("")
        lines.append("| Component | Message |")
        lines.append("|-----------|---------|")
        for detail in result.rpm_signature_details[:30]:
            lines.append(f"| `{detail['component']}` | {detail['message']} |")
        if len(result.rpm_signature_details) > 30:
            lines.append(f"\n... and {len(result.rpm_signature_details) - 30} more")
        lines.append("")

    lines.append("## Effective Dates")
    lines.append("")
    lines.append("| Date | Violations |")
    lines.append("|------|------------|")
    for date, count in result.effective_dates.items():
        lines.append(f"| {date} | {count} |")
    lines.append("")

    lines.append("## Component Violation Patterns")
    lines.append("")
    lines.append("| # Components | Violation Codes |")
    lines.append("|--------------|-----------------|")
    for pattern in result.component_patterns:
        codes_str = " + ".join(f"`{c}`" for c in pattern["codes"])
        lines.append(f"| {pattern['count']} | {codes_str} |")
    lines.append("")

    lines.append("## Priority Recommendations")
    lines.append("")
    for rec in result.priority_recommendations:
        lines.append(f"### #{rec['priority']}: {rec['action']}")
        lines.append("")
        lines.append(f"- **Resolves:** {rec['violations_resolved']} violations"
                     f" ({rec['percent_of_total']}% of total)")
        lines.append(f"- **Components affected:** {rec['affected_components']}")
        lines.append(f"- **Solution:** {rec['solution']}")
        if "components" in rec:
            lines.append(f"- **Specific components:** "
                         + ", ".join(f"`{c}`" for c in rec["components"]))
        lines.append("")

    return "\n".join(lines)


def format_json(result: AnalysisResult) -> str:
    """Format analysis result as JSON."""
    data = {
        "summary": {
            "total_violations": result.total_violations,
            "unique_codes": result.unique_codes,
            "unique_components": result.unique_components,
        },
        "violations_by_code": result.violations_by_code,
        "violations_by_component": result.violations_by_component,
        "untrusted_tasks": result.untrusted_tasks,
        "rpm_signature_details": result.rpm_signature_details,
        "effective_dates": result.effective_dates,
        "component_patterns": result.component_patterns,
        "priority_recommendations": result.priority_recommendations,
    }
    return json.dumps(data, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze conforma violation reports"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--csv",
        help="Path to a single violations CSV file",
    )
    input_group.add_argument(
        "--reports-dir",
        help="Directory containing per-release CSV files",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: stdout)",
    )
    args = parser.parse_args()

    if args.csv:
        csv_path = Path(args.csv)
        if not csv_path.is_file():
            print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
            return 1
        records = load_csv(csv_path)
    else:
        reports_dir = Path(args.reports_dir)
        if not reports_dir.is_dir():
            print(f"Error: directory not found: {reports_dir}", file=sys.stderr)
            return 1
        records = load_reports_dir(reports_dir)

    if not records:
        print("Error: no violation records found", file=sys.stderr)
        return 1

    print(f"Loaded {len(records)} violations", file=sys.stderr)

    result = analyze(records)

    formatters = {
        "text": format_text,
        "markdown": format_markdown,
        "json": format_json,
    }
    output = formatters[args.format](result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
