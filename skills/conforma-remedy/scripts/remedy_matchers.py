"""remedy_matchers — Pure matching functions composed via Chain of Responsibility.

Each factory returns a Matcher (str -> MatchResult | None). The chain()
function composes them: first match wins, rest are skipped.

Adding a new matching strategy = writing a new factory + appending to the chain.
No existing code needs to change (Open/Closed Principle).
"""

from __future__ import annotations

import re
from typing import Callable

from remedy_result import MatchResult

Matcher = Callable[[str], MatchResult | None]

_MIN_SYMPTOM_LENGTH = 10
_CONFORMA_PREFIX = re.compile(r"^(deny|warn|failure|violation|warning):\s*", re.IGNORECASE)
_SURROUNDING_QUOTES = re.compile(r'^["\'](.+)["\']$')


def sanitize_query(raw: str) -> str:
    """Normalize raw user input before matching."""
    cleaned = raw.strip()
    cleaned = _SURROUNDING_QUOTES.sub(r"\1", cleaned)
    cleaned = _CONFORMA_PREFIX.sub("", cleaned)
    cleaned = _SURROUNDING_QUOTES.sub(r"\1", cleaned.strip())
    cleaned = cleaned.replace("\r", "").replace("\n", " ")
    cleaned = " ".join(cleaned.split())
    return cleaned.lower().strip()


def make_rule_code_matcher(violations: list[dict]) -> Matcher:
    """Match by exact rule code or conforma_rule_codes field."""

    def match(query: str) -> MatchResult | None:
        for v in violations:
            if v["id"].lower() == query:
                return MatchResult.from_catalog(v)
            if query in (c.lower() for c in v.get("conforma_rule_codes", [])):
                return MatchResult.from_catalog(v)
        return None

    return match


def make_alias_matcher(violations: list[dict]) -> Matcher:
    """Match by full alias (case-insensitive, no substrings)."""

    def match(query: str) -> MatchResult | None:
        for v in violations:
            if query in (a.lower() for a in v.get("aliases", [])):
                return MatchResult.from_catalog(v)
        return None

    return match


def make_symptom_matcher(violations: list[dict]) -> Matcher:
    """Match by symptom substring (bidirectional containment)."""

    def match(query: str) -> MatchResult | None:
        if len(query) < _MIN_SYMPTOM_LENGTH:
            return None
        for v in violations:
            for symptom in v.get("symptoms", []):
                symptom_lower = symptom.lower()
                if query in symptom_lower or symptom_lower in query:
                    return MatchResult.from_catalog(v)
        return None

    return match


def make_fallback_matcher(entries: list[dict]) -> Matcher:
    """Match against the full JSON rule catalog (basic info, no fix_steps)."""

    def match(query: str) -> MatchResult | None:
        normalized = query.replace(".", "__")
        for entry in entries:
            rule_id = entry["rule_id"].lower()
            if rule_id == normalized or rule_id == query:
                return MatchResult.from_fallback(entry)
        return None

    return match


def chain(matchers: list[Matcher]) -> Matcher:
    """Compose matchers — first non-None result wins."""

    def match(query: str) -> MatchResult | None:
        return next((r for m in matchers if (r := m(query)) is not None), None)

    return match


def find_false_alerts(
    alerts: list[dict], rule_code: str, component: str | None = None
) -> list[dict]:
    """Filter known false alerts by rule code, optionally scoped to a component."""
    return [
        alert
        for alert in alerts
        if rule_code in alert.get("conforma_rule_codes", [])
        and (not component or not alert.get("applies_to") or alert["applies_to"] == component)
    ]
