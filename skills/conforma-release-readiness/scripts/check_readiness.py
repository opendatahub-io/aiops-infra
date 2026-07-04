#!/usr/bin/env python3
"""Check release readiness: violations vs exception coverage.

Produces a ship/no-ship verdict with detailed breakdown.

Usage:
    python3 scripts/check_readiness.py \\
      --release rhoai-3.5 \\
      --violations-input ~/.conforma/conforma-analyze.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

_REPO_SCRIPTS = str(Path(__file__).resolve().parent.parent.parent.parent / "scripts")
if _REPO_SCRIPTS not in sys.path:
    sys.path.insert(0, _REPO_SCRIPTS)

import conforma_context_ops  # noqa: E402


def load_violations(violations_path: Path) -> dict:
    """Load violations data from conforma-analyze output."""
    data = yaml.safe_load(violations_path.read_text(encoding="utf-8"))
    return data.get("violation_data", data)


def load_exceptions(clone_dir: Path, environment: str) -> list[dict]:
    """Load active exceptions from a konflux-release-data clone."""
    # Reuse manage_exceptions scanning
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "conforma-exception" / "scripts"))
    try:
        from manage_exceptions import annotate_expiry, scan_all_exceptions

        exceptions = scan_all_exceptions(clone_dir, environment)
        return annotate_expiry(exceptions)
    except ImportError:
        return []


def check_readiness(
    release: str,
    violations_data: dict,
    exceptions: list[dict],
    soon_days: int = 14,
) -> dict:
    """Cross-reference violations against exceptions for a release.

    Returns a readiness verdict with detailed breakdown.
    """
    violations_by_rule = violations_data.get("violations_by_rule", {})

    release_violations: list[dict] = []
    for rule, info in violations_by_rule.items():
        releases = info.get("releases", {})
        components = releases.get(release, [])
        if components:
            release_violations.append(
                {
                    "rule": rule,
                    "base_code": info.get("base_code", rule.split(":")[0]),
                    "components": components,
                    "title": info.get("title", ""),
                }
            )

    active_exceptions = [e for e in exceptions if not e.get("is_expired", True)]
    expiring_soon = [e for e in active_exceptions if e.get("expires_in_days", 999) <= soon_days]

    covered: list[dict] = []
    blocking: list[dict] = []

    for violation in release_violations:
        rule = violation["rule"]
        base_code = violation["base_code"]
        components = set(violation["components"])

        covering_exception = None
        for exc in active_exceptions:
            exc_rule = exc.get("rule", "")
            if exc_rule == rule or exc_rule == base_code or rule.startswith(exc_rule.split(":")[0]):
                if exc.get("is_unscoped") or set(exc.get("component_names", [])) & components:
                    covering_exception = exc
                    break

        if covering_exception:
            covered.append({**violation, "exception": covering_exception.get("rule", "")})
        else:
            blocking.append(violation)

    total = len(release_violations)
    covered_count = len(covered)
    blocking_count = len(blocking)
    verdict = "SHIP" if blocking_count == 0 and total > 0 else "NO-SHIP" if blocking_count > 0 else "NO-DATA"

    return {
        "release": release,
        "verdict": verdict,
        "summary": f"{covered_count} of {total} violations covered, {blocking_count} blocking",
        "total_violations": total,
        "covered_count": covered_count,
        "blocking_count": blocking_count,
        "blocking_violations": blocking,
        "covered_violations": covered,
        "expiring_soon": [
            {
                "rule": e.get("rule"),
                "expires_in_days": e.get("expires_in_days"),
                "effective_until": e.get("effective_until"),
            }
            for e in expiring_soon
        ],
        "active_exceptions_count": len(active_exceptions),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check release readiness")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
    )
    parser.add_argument("--release", default=None, help="Release branch (e.g. rhoai-3.5)")
    parser.add_argument("--violations-input", default=None, help="Path to conforma-analyze violations YAML")
    parser.add_argument("--clone-dir", default=None, help="Path to konflux-release-data clone")
    parser.add_argument("--environment", default=None, choices=["prod", "stage"], help="Environment (prod/stage)")
    parser.add_argument("--soon-days", type=int, default=14, help="Warn if exception expires within N days")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    args = parser.parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    release = conforma_context_ops.resolve_arg(args, "release", context, "application.release")
    environment = conforma_context_ops.resolve_arg(args, "environment", context, "environment")

    violations_input = args.violations_input
    if violations_input is None and context:
        ctx_vy = conforma_context_ops.get(run_dir, "steps.parse.violations_yaml", None)
        if ctx_vy:
            violations_input = str(Path(run_dir) / ctx_vy)
    if violations_input is None:
        print("Error: --violations-input is required when no run context is available", file=sys.stderr)
        return 1

    violations_path = Path(violations_input)
    if not violations_path.is_file():
        print(f"Error: violations file not found: {violations_path}", file=sys.stderr)
        return 1

    violations_data = load_violations(violations_path)

    clone_dir = args.clone_dir
    if clone_dir is None and context:
        clone_dir = str(conforma_context_ops.discover_work_dir() / "konflux-release-data")
    exceptions = load_exceptions(Path(clone_dir), environment) if clone_dir else []

    result = check_readiness(release, violations_data, exceptions, args.soon_days)

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"\n{'=' * 60}")
        print(f"RELEASE READINESS: {result['release']}")
        print(f"{'=' * 60}")
        print(f"\n  VERDICT: {result['verdict']}")
        print(f"  {result['summary']}")
        if result["blocking_violations"]:
            print(f"\n  BLOCKING ({result['blocking_count']}):")
            for v in result["blocking_violations"]:
                print(f"    - {v['rule']}: {', '.join(v['components'][:5])}")
        if result["expiring_soon"]:
            print("\n  EXPIRING SOON:")
            for e in result["expiring_soon"]:
                print(f"    - {e['rule']}: {e['expires_in_days']}d remaining")
        print()

    return 0 if result["verdict"] == "SHIP" else 1


if __name__ == "__main__":
    sys.exit(main())
