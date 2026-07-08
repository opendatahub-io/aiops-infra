"""remedy_result — Structured result for violation lookups.

Normalizes results from different sources (YAML catalog, JSON fallback)
into a single immutable type with well-defined fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MatchResult:
    id: str
    title: str
    description: str
    source: str
    type: str = ""
    classification: dict | None = None
    fix_steps: tuple[dict, ...] = ()
    exception_context: dict | None = None
    aliases: tuple[str, ...] = ()
    symptoms: tuple[str, ...] = ()
    conforma_rule_codes: tuple[str, ...] = ()
    rule_name: str = ""
    policy_type: str = ""
    collections: tuple[str, ...] = ()

    @classmethod
    def from_catalog(cls, entry: dict) -> MatchResult:
        return cls(
            id=entry["id"],
            title=entry.get("title", ""),
            description=entry.get("description", ""),
            source="catalog",
            type=entry.get("type", ""),
            classification=entry.get("classification"),
            fix_steps=tuple(entry.get("fix_steps", [])),
            exception_context=entry.get("exception_context"),
            aliases=tuple(entry.get("aliases", [])),
            symptoms=tuple(entry.get("symptoms", [])),
            conforma_rule_codes=tuple(entry.get("conforma_rule_codes", [])),
        )

    @classmethod
    def from_fallback(cls, entry: dict) -> MatchResult:
        return cls(
            id=entry["rule_id"],
            title=entry.get("rule_name", ""),
            description=entry.get("description", ""),
            source="fallback",
            rule_name=entry.get("rule_name", ""),
            policy_type=entry.get("policy_type", ""),
            collections=tuple(entry.get("collections", [])),
        )
