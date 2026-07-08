#!/usr/bin/env python3
"""match_violation — Look up conforma violations and return remediation guidance.

Composes data sources (Repository Pattern) with matching strategies
(Chain of Responsibility) to find the best match for a user query.

Usage:
    python3 match_violation.py "hermetic_task.hermetic"
    python3 match_violation.py "hermetic build"
    python3 match_violation.py "Build task was not invoked with the hermetic parameter"
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

# Load _setup_env from THIS skill's directory to avoid sys.path shadowing
# when multiple skills have their own _setup_env.py (e.g., in test conftest).
_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_setup_env", _HERE / "_setup_env.py")
_setup_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_setup_env)
_setup_env.bootstrap_env()

import yaml

from remedy_matchers import (
    chain,
    find_false_alerts,
    make_alias_matcher,
    make_fallback_matcher,
    make_rule_code_matcher,
    make_symptom_matcher,
    sanitize_query,
)
from remedy_result import MatchResult

_REFERENCES = Path(__file__).resolve().parent.parent.parent / "references"
_DEFAULT_CATALOG = _REFERENCES / "violation-catalog.yaml"
_DEFAULT_FALLBACK = _REFERENCES / "conforma-rule-catalog-full.json"


# ── Data loading (Repository Pattern) ───────────────────────────────


def load_catalog(path: Path) -> tuple[list[dict], list[dict]]:
    """Load YAML catalog. Returns (violations, false_alerts)."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("violations", []), data.get("known_false_alerts", [])


def load_fallback(path: Path) -> list[dict]:
    """Load JSON fallback catalog. Returns empty list if file is missing."""
    if not path.is_file():
        return []
    with open(path) as f:
        return json.load(f)


# ── Orchestrator ─────────────────────────────────────────────────────


class ViolationMatcher:
    """Compose data sources and matchers into a single lookup API."""

    def __init__(
        self,
        catalog_path: str | None = None,
        fallback_path: str | None = None,
    ) -> None:
        violations, self._false_alerts = load_catalog(
            Path(catalog_path) if catalog_path else _DEFAULT_CATALOG
        )
        fallback = load_fallback(
            Path(fallback_path) if fallback_path else _DEFAULT_FALLBACK
        )

        self._match_chain = chain([
            make_rule_code_matcher(violations),
            make_alias_matcher(violations),
            make_symptom_matcher(violations),
            make_fallback_matcher(fallback),
        ])

    def match(self, query: str | None) -> MatchResult | None:
        if not query or not query.strip():
            return None
        return self._match_chain(sanitize_query(query))

    def check_false_alerts(
        self, rule_code: str, component: str | None = None
    ) -> list[dict]:
        return find_false_alerts(self._false_alerts, rule_code, component)


# ── CLI entry point ──────────────────────────────────────────────────


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: match_violation.py <query>", file=sys.stderr)
        return 1

    query = " ".join(sys.argv[1:])
    matcher = ViolationMatcher()
    result = matcher.match(query)

    if result is None:
        print(f"No match found for: {query}")
        return 1

    print(f"ID:       {result.id}")
    print(f"Title:    {result.title}")
    print(f"Source:   {result.source}")
    if result.fix_steps:
        print("Fix steps:")
        for i, step in enumerate(result.fix_steps, 1):
            print(f"  {i}. {step['action']}")
            if step.get("reference"):
                print(f"     → {step['reference']}")
    if result.classification:
        c = result.classification
        print(f"Owner:    {c.get('typical_owner', 'unknown')}")
        print(f"Effort:   {c.get('estimated_effort', 'unknown')}")
        print(f"Rebuild:  {c.get('requires_rebuild', False)}")

    alerts = matcher.check_false_alerts(result.id)
    if alerts:
        print(f"\n⚠ Known false alert: {alerts[0]['title']}")
        print(f"  Condition: {alerts[0].get('condition', 'N/A')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
