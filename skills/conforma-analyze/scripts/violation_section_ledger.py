"""Deterministic ownership ledger for Conforma resolution sections.

The renderer has several overlapping views of the same source violation.  This
module gives each atomic source identity one owner and records the other views
as secondary references.  It deliberately fails closed: incomplete coverage
evidence is classified as TODO rather than being treated as covered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable


SECTION_TOOLING = "tooling"
SECTION_NO_EXCEPTION = "violations-without-exception-or-merge-request"
SECTION_EXPIRING_SOON = "exceptions-expiring-within-14-days"
SECTION_EXPIRING_NO_MR = "expiring-exceptions-without-merge-request"
SECTION_EXPIRING_MR_BEFORE_RELEASE = "expiring-exceptions-merge-request-before-release"
SECTION_EXPIRING_MR_AFTER_RELEASE = "expiring-exceptions-merge-request-after-release"
SECTION_MR_BEFORE_RELEASE = "merge-request-expiring-before-release"
SECTION_OPEN_MR = "open-merge-requests-not-merged"
SECTION_WARNINGS_BEFORE_RELEASE = "warnings-before-release"
SECTION_WARNINGS_AFTER_RELEASE = "warnings-after-release"
SECTION_COVERED = "covered-violations"

VIOLATION_SECTION_IDS = (
    SECTION_TOOLING,
    SECTION_NO_EXCEPTION,
    SECTION_EXPIRING_NO_MR,
    SECTION_EXPIRING_MR_BEFORE_RELEASE,
    SECTION_EXPIRING_MR_AFTER_RELEASE,
    SECTION_MR_BEFORE_RELEASE,
    SECTION_OPEN_MR,
    SECTION_WARNINGS_BEFORE_RELEASE,
    SECTION_WARNINGS_AFTER_RELEASE,
)


def _value(record: Any, name: str, default: Any = "") -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


@dataclass(frozen=True, order=True)
class AtomicViolationIdentity:
    """The source identity used by the ownership gate."""

    base_code: str
    full_code: str
    component: str
    semantic_detail: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.base_code, self.full_code, self.component, self.semantic_detail)


@dataclass
class LedgerEntry:
    identity: AtomicViolationIdentity
    owner: str
    status: str
    coverage: str
    evidence: tuple[str, ...] = ()
    secondary_references: set[str] = field(default_factory=set)


@dataclass
class ViolationSectionLedger:
    entries: dict[AtomicViolationIdentity, LedgerEntry]
    source_identities: frozenset[AtomicViolationIdentity]

    @property
    def owned_identities(self) -> frozenset[AtomicViolationIdentity]:
        return frozenset(self.entries)

    def entries_for(self, section_id: str) -> list[LedgerEntry]:
        return sorted((entry for entry in self.entries.values() if entry.owner == section_id), key=lambda e: e.identity)

    def validate(self) -> None:
        """Raise when ownership is not an exact, one-owner partition."""
        if self.owned_identities != self.source_identities:
            missing = sorted(self.source_identities - self.owned_identities)
            unexpected = sorted(self.owned_identities - self.source_identities)
            raise ValueError(f"violation ownership gate failed: missing={missing!r}, unexpected={unexpected!r}")
        owners: dict[AtomicViolationIdentity, list[str]] = {}
        for entry in self.entries.values():
            owners.setdefault(entry.identity, []).append(entry.owner)
        duplicates = {identity: sections for identity, sections in owners.items() if len(sections) != 1}
        if duplicates:
            raise ValueError(f"violation ownership gate failed: duplicate owners={duplicates!r}")


def atomic_identity(record: Any) -> AtomicViolationIdentity:
    """Normalize a CSV-like record without inventing missing evidence."""
    base_code = str(_value(record, "base_code") or _value(record, "code") or _value(record, "rule") or "")
    full_code = str(_value(record, "full_code") or _value(record, "full_violation_code") or base_code)
    component = str(_value(record, "component") or _value(record, "component_name") or "")
    detail = str(_value(record, "semantic_detail") or _value(record, "detail") or "")
    return AtomicViolationIdentity(base_code, full_code, component, detail)


def _coverage_for(identity: AtomicViolationIdentity, coverage_data: dict) -> dict | None:
    for item in coverage_data.get("violations", []):
        rule = str(item.get("rule") or item.get("base_code") or "")
        if rule not in (identity.base_code, identity.full_code, identity.full_code.split(":", 1)[0]):
            continue
        components = set(item.get("all_components", []))
        components.update(item.get("covered_components", []))
        components.update(item.get("uncovered_components", []))
        if identity.component in components:
            return item
    return None


def _merge_request_for(component: str, item: dict) -> dict | None:
    for merge_request in item.get("open_merge_requests", []) or []:
        components = merge_request.get("mr_components", []) or []
        if "*" in components or component in components:
            return merge_request
    return None


def _secondary_references(item: dict, upcoming_release_date: str) -> set[str]:
    """Return non-owning views that may also display the identity."""
    references = set(item.get("secondary_sections", []) or [])
    expiry = item.get("exception_expiry") or {}
    if expiry.get("expiring_within_14_days") or item.get("expiring_within_14_days"):
        references.add(SECTION_EXPIRING_SOON)
    expiry_date = str(expiry.get("earliest_expiry") or "")[:10]
    if expiry_date and upcoming_release_date:
        try:
            if date.fromisoformat(expiry_date) < date.fromisoformat(upcoming_release_date):
                references.add(SECTION_EXPIRING_NO_MR)
        except ValueError:
            references.add(SECTION_EXPIRING_NO_MR)
    references.update(item.get("warning_sections", []) or [])
    return references


def _owner_for(identity: AtomicViolationIdentity, item: dict | None, upcoming_release_date: str) -> tuple[str, str, tuple[str, ...], set[str]]:
    if item is None:
        return SECTION_NO_EXCEPTION, "TODO", ("coverage input is missing",), set()

    covered = set(item.get("covered_components", []))
    uncovered = set(item.get("uncovered_components", []))
    coverage = item.get("coverage")
    if coverage not in {"fully_covered", "partially_covered", "not_covered"}:
        return SECTION_NO_EXCEPTION, "TODO", ("coverage status is unknown",), set()
    if identity.component not in covered and identity.component not in uncovered:
        return SECTION_NO_EXCEPTION, "TODO", ("component coverage is unknown",), set()

    merge_request = _merge_request_for(identity.component, item)
    if identity.component in covered:
        return SECTION_COVERED, "DONE", ("covered by existing policy",), set()

    if identity.component in uncovered and merge_request:
        owner = SECTION_OPEN_MR
        if not upcoming_release_date:
            evidence = ("upcoming release date is missing", "open Merge Request is not merged")
            return owner, "TODO", evidence, set()
        return owner, "TODO", ("open Merge Request is not merged",), set()

    if identity.component in uncovered:
        return SECTION_NO_EXCEPTION, "TODO", ("no policy exception covers this identity",), set()
    return SECTION_NO_EXCEPTION, "TODO", ("coverage could not be proven",), set()


def build_violation_section_ledger(
    source_records: Iterable[Any],
    coverage_data: dict | None = None,
    *,
    upcoming_release_date: str = "",
) -> ViolationSectionLedger:
    """Build and validate a one-owner ledger from source records.

    Duplicate source rows collapse only when their complete four-field atomic
    identity is identical.  Expiry and warning memberships are intentionally
    secondary metadata and therefore cannot create another owner.
    """
    source_identities = frozenset(atomic_identity(record) for record in source_records)
    entries: dict[AtomicViolationIdentity, LedgerEntry] = {}
    coverage_data = coverage_data or {}
    for identity in sorted(source_identities):
        item = _coverage_for(identity, coverage_data)
        owner, status, evidence, _ = _owner_for(identity, item, upcoming_release_date)
        references = _secondary_references(item, upcoming_release_date) if item else set()
        references.discard(owner)
        entries[identity] = LedgerEntry(
            identity,
            owner,
            status,
            item.get("coverage", "unknown") if item else "unknown",
            evidence,
            references,
        )
    ledger = ViolationSectionLedger(entries, source_identities)
    ledger.validate()
    return ledger


def section_marker(section_id: str) -> str:
    """Return the stable marker placed immediately before a section heading."""
    return f"<!-- conforma-section: {section_id} -->"
