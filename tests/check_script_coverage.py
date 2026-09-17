#!/usr/bin/env python3
"""Pre-commit hook: enforce per-script >97% line coverage on plan-touched scripts.

Runs the unit test suite under `coverage`, parses the JSON report, and verifies
that every script in PLAN_COVERAGE_TARGETS meets the minimum coverage threshold.
Exits 0 if all targets pass, 1 otherwise.

Usage:
    python tests/check_script_coverage.py [--min 97.0]

Manual / CI:
    python tests/check_script_coverage.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Scripts touched by the conforma-analyze Jira coverage plan.
# A script that does not yet exist (e.g. before Phase 3 lands) is skipped with a
# "skip" status, not treated as a failure.
PLAN_COVERAGE_TARGETS: list[str] = [
    "scripts/jira_ops.py",
    "scripts/conforma_constants.py",
    "scripts/conforma_jira_ops.py",
    "scripts/conforma_jira_ticket_ops.py",
]


def find_file_in_report(report: dict, target: str) -> tuple[str, dict] | None:
    """Find a target file in the coverage JSON report by relative path suffix.

    Returns (matched_path, file_entry) or None if not found.
    """
    for path, entry in report.get("files", {}).items():
        if path.replace("\\", "/").endswith(target):
            return path, entry
    return None


def coverage_pct(entry: dict) -> float | None:
    """Return percent_covered from a coverage file entry, or None if absent."""
    summary = entry.get("summary", {})
    pct = summary.get("percent_covered")
    return float(pct) if pct is not None else None


def check_targets(report: dict, targets: list[str], min_pct: float) -> list[dict]:
    """Check each target against min_pct. Returns list of per-target result dicts.

    Result dict keys: target, status ("PASS" | "FAIL" | "skip"), pct (float|None),
    covered, total.
    """
    results = []
    for target in targets:
        match = find_file_in_report(report, target)
        if match is None:
            results.append({"target": target, "status": "skip", "pct": None, "covered": 0, "total": 0})
            continue
        _, entry = match
        pct = coverage_pct(entry)
        summary = entry.get("summary", {})
        covered = summary.get("covered_lines", 0)
        total = summary.get("num_statements", 0)
        if pct is None or total == 0:
            results.append({"target": target, "status": "skip", "pct": pct, "covered": covered, "total": total})
        elif pct > min_pct:
            results.append({"target": target, "status": "PASS", "pct": pct, "covered": covered, "total": total})
        else:
            results.append({"target": target, "status": "FAIL", "pct": pct, "covered": covered, "total": total})
    return results


def format_report(results: list[dict], min_pct: float) -> str:
    """Format the results table for display."""
    lines = [f"Per-script coverage gate (threshold: > {min_pct}%)", ""]
    lines.append(f"{'Script':<50s} {'Coverage':>10s}  Status")
    lines.append("-" * 74)
    for r in results:
        pct_str = f"{r['pct']:.1f}%" if r["pct"] is not None else "  skip"
        lines.append(f"{r['target']:<50s} {pct_str:>10s}  {r['status']}")
    lines.append("")
    return "\n".join(lines)


def run_coverage(coverage_data_file: Path) -> int:
    """Run pytest under coverage (no --source filter, so root scripts/ are captured).

    Returns 0 on success, non-zero on failure.
    """
    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--data-file={coverage_data_file}",
        "-m",
        "pytest",
        "tests/unit/",
        "-q",
    ]
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-script coverage gate")
    parser.add_argument("--min", type=float, default=97.0, help="Minimum per-script coverage %%")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        cov_data = Path(tmpdir) / ".coverage"
        cov_json = Path(tmpdir) / "coverage.json"

        rc = run_coverage(cov_data)
        if rc != 0:
            print("ERROR: coverage run failed (test suite may have failed)", file=sys.stderr)
            return 1

        # Generate JSON report
        json_cmd = [sys.executable, "-m", "coverage", "json", "-o", str(cov_json)]
        env = {**os.environ, "COVERAGE_FILE": str(cov_data)}
        json_result = subprocess.run(json_cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        if json_result.returncode != 0:
            print("ERROR: coverage json generation failed", file=sys.stderr)
            sys.stderr.write(json_result.stderr)
            return 1

        report = json.loads(cov_json.read_text())
        results = check_targets(report, PLAN_COVERAGE_TARGETS, args.min)

        print(format_report(results, args.min))

        failures = [r for r in results if r["status"] == "FAIL"]
        if failures:
            for f in failures:
                print(
                    f"  {f['target']}: {f['pct']:.1f}% < {args.min}% — add tests to cover the missing lines.",
                    file=sys.stderr,
                )
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
