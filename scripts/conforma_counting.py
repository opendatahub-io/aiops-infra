"""Conforma Violation Counting Model — single source of truth.

Violation = violation_code + component + semantic_detail.

- violation_code: the base Conforma violation code (e.g. rpm_repos.ids_known)
- component: the Konflux component name
- semantic_detail: the actionable root cause extracted by the semantic detail
  catalog (e.g. a repo ID, attribute name, package name)

The dedup key is (violation_code, component, semantic_detail). Multiple CSV
rows with the same triple but different image digests or different per-package
PURLs sharing the same root cause are the SAME violation — they collapse to
one violation.

Each violation represents one actionable unit of work that needs its own
resolution or exception entry.

All conforma scripts MUST use this module for counting.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ViolationCounts:
    """Deterministic counts at both levels."""

    violations: int
    """Unique (violation_code, component, semantic_detail) triples — the primary metric."""

    image_occurrences: int
    """Total CSV rows — raw source data (context only)."""

    full_violation_code_count: int = 0
    """Unique (full_violation_code, component) pairs — policy-matching granularity (context only)."""

    by_component_rule: dict[tuple[str, str], int] = field(default_factory=dict)
    """(violation_code, component) -> semantic violation count for that group.
    Sum of all values == self.violations."""


def count_from_records(
    records,
    *,
    code_field: str = "code",
    component_field: str = "component_name",
    detail_field: str = "semantic_detail",
    full_code_field: str = "full_violation_code",
) -> ViolationCounts:
    """Count violations from raw CSV records.

    A violation = unique (violation_code, component, semantic_detail) triple.
    Image digest duplication is removed; rows sharing the same root cause
    are the same violation.

    Args:
        records: list of dicts or dataclass instances (CSV rows)
        code_field: attribute/key name for the base violation code
        component_field: attribute/key name for the component
        detail_field: attribute/key name for the semantic detail
        full_code_field: attribute/key name for the full violation code
            (used only for full_violation_code_count context metric)

    Returns:
        ViolationCounts with deterministic totals and per-group breakdown.
    """
    seen_violations: set[tuple[str, str, str]] = set()
    seen_full_codes: set[tuple[str, str]] = set()
    by_group: Counter[tuple[str, str]] = Counter()
    total_rows = 0

    for rec in records:
        code = _get_field(rec, code_field)
        comp = _get_field(rec, component_field)
        detail = _get_field(rec, detail_field)
        full_code = _get_field(rec, full_code_field)

        total_rows += 1

        if full_code:
            seen_full_codes.add((full_code, comp))

        violation_key = (code, comp, detail)
        if violation_key not in seen_violations:
            seen_violations.add(violation_key)
            by_group[(code, comp)] += 1

    return ViolationCounts(
        violations=len(seen_violations),
        image_occurrences=total_rows,
        full_violation_code_count=len(seen_full_codes),
        by_component_rule=dict(by_group),
    )


def _get_field(rec, field_name: str) -> str:
    """Extract a field value from a dict or dataclass record."""
    if isinstance(rec, dict):
        return rec.get(field_name, "")
    val = getattr(rec, field_name, None)
    if val is None:
        return ""
    return val


def violations_for_components(
    rule: str,
    components: list[str],
    by_component_rule: dict[tuple[str, str], int],
) -> int:
    """Total violations across given components for a rule.

    Uses by_component_rule from count_from_records() for exact per-component counts.
    Falls back to 1 per component if counts not available.
    """
    base_code = rule.split(":")[0]
    total = 0
    for comp in components:
        count = by_component_rule.get((rule, comp), 0) or by_component_rule.get((base_code, comp), 0) or 1
        total += count
    return total
