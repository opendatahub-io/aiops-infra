"""conforma_jira_ops.py -- Conforma Jira ticket discovery primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import re

# Terminal/closed status names (case-insensitive). Anything else counts as open.
# Mirrors conforma_jira_ticket_ops.CLOSED_STATUS_NAMES (kept local because this
# module is the primitive layer and must not import the ticket-ops layer).
CLOSED_STATUS_NAMES = {"done", "closed", "canceled", "cancelled"}

_VERSION_SUFFIX_RE = re.compile(r"-v\d+-\d+(-ea-\d+)?$")

_TICKET_SUMMARY_PREFIX = "Conforma violation: "

# Deterministic ticket description produced by create_jira_ticket.py.
_DESCRIPTION_COMPONENTS_HEADER = "Components:"

_RULE_FAMILY_KEYWORDS: dict[str, list[str]] = {
    "hermetic_task": ["hermetic", "prefetch-dependencies", "network isolation"],
    "rpm_signature": ["signing key", "rpm signature", "unsigned", "allowed keys"],
    "test.no_failed_tests": ["failed test", "test failure"],
}


def _extract_ticket_key(url: str) -> str | None:
    match = re.search(r"([A-Z]+-\d+)", url)
    return match.group(1) if match else None


def _extract_rule_from_summary(summary: str) -> str | None:
    """Extract conforma rule from ticket summary."""
    match = re.search(r"(rpm_signature\.allowed:[0-9a-fA-F]+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"signed with ([0-9a-fA-F]{16})(?![0-9a-fA-F])", summary)
    if match:
        return f"rpm_signature.allowed:{match.group(1)}"
    match = re.search(r"signing key ([0-9a-fA-F]{16})(?![0-9a-fA-F])", summary)
    if match:
        return f"rpm_signature.allowed:{match.group(1)}"
    match = re.search(r"(hermetic_task\.\w+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"(schedule\.\w+)", summary)
    if match:
        return match.group(1)
    match = re.search(r"(test\.\w+:\S+)", summary)
    if match:
        return match.group(1)
    return None


def _strip_version_suffix(name: str) -> str:
    """Strip Konflux version suffix: -v3-5, -v3-5-ea-1, -v2-25, etc."""
    return _VERSION_SUFFIX_RE.sub("", name)


_PLUS_N_MORE_RE = re.compile(r"\s*\(\+\d+\s+more\)\s*$")


def _extract_components_from_summary(summary: str) -> list[str]:
    """Extract component stems from a deterministic Jira summary.

    Expected format (with optional vendor tag and summary context):
        [vendor_tag] [purpose_tag] {rule} - {comp1}, {comp2} (+N more) - rhoai-X.Y
        [vendor_tag] [purpose_tag] {rule} - {comp1} - rhoai-X.Y - {context}
    """
    parts = summary.split(" - ")
    if len(parts) < 3:
        return []
    comp_segment = parts[-2] if len(parts) == 3 else parts[1]
    comp_segment = _PLUS_N_MORE_RE.sub("", comp_segment).strip()
    if not comp_segment:
        return []
    raw_names = [n.strip() for n in comp_segment.split(", ") if n.strip()]
    return [_strip_version_suffix(n) for n in raw_names if n]


def _extract_components_from_description(description: str) -> list[str]:
    """Extract the full component list from a Jira description.

    Looks for the deterministic ``Components: comp1, comp2, ...`` line
    produced by ``create_jira_ticket.py``.
    """
    if not description:
        return []
    for line in description.splitlines():
        line = line.strip()
        if line.startswith("Components:"):
            raw = line[len("Components:"):].strip()
            if not raw:
                return []
            return [_strip_version_suffix(n.strip()) for n in raw.split(", ") if n.strip()]
    return []


def _extract_component_stems(summary: str, description: str | None = None) -> list[str]:
    """Extract component stems from summary and/or description.

    Prefers description (full list, no truncation) over summary.
    """
    if description:
        stems = _extract_components_from_description(description)
        if stems:
            return stems
    return _extract_components_from_summary(summary)


def _infer_rule_from_text(text: str, rule: str) -> str:
    """Infer whether *text* (summary + description) is about *rule*.

    Returns "confirmed" if the rule code or rule-family keywords are found,
    "unconfirmed" otherwise.
    """
    if not text:
        return "unconfirmed"

    extracted = _extract_rule_from_summary(text)
    if extracted and extracted == rule:
        return "confirmed"
    if extracted and ":" in rule and extracted.startswith(rule.split(":")[0]):
        if rule.split(":", 1)[1].lower() in text.lower():
            return "confirmed"

    text_lower = text.lower()

    rule_family = rule.split(".")[0] if "." in rule else rule
    if ":" in rule_family:
        rule_family = rule_family.split(":")[0]

    for family_prefix, keywords in _RULE_FAMILY_KEYWORDS.items():
        if rule.startswith(family_prefix):
            for kw in keywords:
                if kw in text_lower:
                    return "confirmed"
            break

    if ":" in rule:
        suffix = rule.split(":", 1)[1].lower()
        if suffix in text_lower:
            return "confirmed"

    return "unconfirmed"


def is_open(status: str | None) -> bool:
    """True if a Jira status name is not a terminal/closed state.

    Unknown/empty status is treated as open (do not silently drop a ticket).
    Mirrors conforma_jira_ticket_ops.is_open.
    """
    if not status:
        return True
    return status.strip().lower() not in CLOSED_STATUS_NAMES


def _summary_component_names(summary: str) -> list[str]:
    """Parse component names out of a deterministic ticket summary.

    Expected format (component version suffixes optional):
        Conform a violation: {rule} in {comp1}, {comp2} - rhoai-X.Y
    Returns [] for non-conforma (manually created) tickets.
    """
    if not summary.startswith(_TICKET_SUMMARY_PREFIX):
        return []
    body = summary[len(_TICKET_SUMMARY_PREFIX):]
    body = body.split(" - ", 1)[0]
    in_part = body.split(" in ", 1)
    if len(in_part) < 2:
        return []
    return [n.strip() for n in in_part[1].split(",") if n.strip()]


def _description_component_names(description: str) -> list[str]:
    """Extract the full component list from a deterministic ticket description.

    Looks for the ``Components: comp1, comp2, ...`` line produced by
    ``create_jira_ticket.py``.
    """
    if not description:
        return []
    for line in description.splitlines():
        line = line.strip()
        if line.startswith(_DESCRIPTION_COMPONENTS_HEADER):
            raw = line[len(_DESCRIPTION_COMPONENTS_HEADER):].strip()
            if not raw:
                return []
            return [n.strip() for n in raw.split(",") if n.strip()]
    return []


def _normalize_component_name(name: str) -> str:
    """Version-suffix-stripped component name, lowercased, for cross-ticket matching."""
    return _strip_version_suffix(name).lower()


def _ticket_component_names(ticket: dict) -> list[str]:
    """Ticket component names (version-suffixed) from the deterministic fields.

    Prefers the description ``Components:`` line (full list, no truncation), then
    the deterministic summary (``Conforma violation: rule in comps``), and finally
    the legacy summary (``[Conforma Violation] rule - comps``) for tickets created
    before the deterministic format.
    """
    names = _description_component_names(ticket.get("description") or "")
    if not names:
        names = _summary_component_names(ticket.get("summary") or "")
    if not names:
        names = _extract_components_from_summary(ticket.get("summary") or "")
    return names


def _matched_component_stems(ticket: dict) -> list[str]:
    """Version-stripped component stems the ticket names (summary/description)."""
    names = _ticket_component_names(ticket)
    return sorted({_strip_version_suffix(n).lower() for n in names if n})


def _normalize_ticket(
    ticket: dict,
    *,
    components: list[str] | None = None,
    match_source: str | None = None,
    inference_confidence: str | None = None,
) -> dict:
    """Build the coverage-table ticket entry consumed by violations_coverage.

    The base fields (``key``, ``summary``, ``status``, ``url``, ``fix_versions``,
    ``components``, ``matched_component_stems``) are always present. ``components``
    defaults to the ticket's konflux components (summary/description-derived).
    ``match_source`` and ``inference_confidence`` are set only for weak
    component-inference matches (alias-only); strong matches (exact rule, direct
    component) carry no tag.
    """
    if components is None:
        components = _ticket_component_names(ticket)
    normalized = {
        "key": ticket.get("key", ""),
        "type": ticket.get("type", "") or "",
        "status": ticket.get("status", "") or "",
        "summary": ticket.get("summary", "") or "",
        "url": ticket.get("url", ""),
        "fix_versions": ticket.get("fix_versions", []) or [],
        "components": components,
        "matched_component_stems": _matched_component_stems(ticket),
    }
    if match_source is not None:
        normalized["match_source"] = match_source
        normalized["inference_confidence"] = inference_confidence
    return normalized


def rule_matches(ticket: dict, rule: str) -> bool:
    """True if the ticket's summary/description is about *rule*."""
    extracted = _extract_rule_from_summary(ticket.get("summary", "") or "")
    if extracted == rule:
        return True
    text = (ticket.get("summary", "") or "") + " " + (ticket.get("description", "") or "")
    return _infer_rule_from_text(text, rule) == "confirmed"


def _konflux_stems_in_text(
    ticket: dict,
    konflux_components: list[str],
    aliases: dict[str, set[str]] | None,
) -> list[str]:
    """Version-stripped konflux/alias component stems present in the ticket text.

    A ticket references a rule's component when a version-stripped konflux
    component name (or one of its aliases) appears in the ticket's summary or
    description. Substring matching (case-insensitive) keeps this robust for
    manually-created tickets with freeform summaries. Returns the sorted stems,
    or an empty list when the ticket names none of the rule's components.
    """
    if not konflux_components:
        return []
    text_lower = ((ticket.get("summary") or "") + " " + (ticket.get("description") or "")).lower()
    comp_set = set(konflux_components)
    if aliases:
        import component_alias_ops

        comp_set = component_alias_ops.expand_component_set(comp_set, aliases)
    return sorted({_normalize_component_name(c) for c in comp_set if _normalize_component_name(c) in text_lower})


def _build_release_version_patterns(releases: list[str]) -> list[str]:
    """Build a list of version patterns to match against Jira ticket text.

    From "rhoai-3.5-ea.1" generates patterns like:
    - "rhoai-3.5-ea.1" (full branch name)
    - "3.5-ea.1" (version without prefix)
    - "v3-5-ea-1" (component suffix form, dots→dashes)
    - "3.5-ea" (without patch for broader match)
    - "v3.5" (short version form)
    """
    patterns: list[str] = []
    for release in releases:
        patterns.append(release.lower())
        version = release.lower().removeprefix("rhoai-")
        patterns.append(version)
        patterns.append("v" + version.replace(".", "-"))
        base_version = re.sub(r"\.\d+$", "", version) if version.count(".") > 1 else version
        if base_version != version:
            patterns.append(base_version)
        short_ver = version.split("-")[0]
        if short_ver != version:
            patterns.append(f"v{short_ver}")
    return list(dict.fromkeys(patterns))


def _normalize_version(version: str) -> str:
    """Normalize a version string for comparison (lowercase, strip whitespace)."""
    return version.strip().lower()


def classify_ticket_version_relevance(
    ticket: dict, analyzed_release: str
) -> str:
    """Classify whether a ticket's fixVersion targets the analyzed release.

    Returns one of:
    - "targets_current" — fixVersion matches the analyzed release
    - "targets_future" — fixVersion is set but doesn't match the analyzed release
    - "no_target_version" — no fixVersion set
    """
    fix_versions = ticket.get("fix_versions", [])
    if not fix_versions:
        return "no_target_version"

    release_patterns = _build_release_version_patterns([analyzed_release])
    for fv in fix_versions:
        fv_norm = _normalize_version(fv)
        for pattern in release_patterns:
            if pattern in fv_norm or fv_norm in pattern:
                return "targets_current"
    return "targets_future"


def prefetch_open_jira_tickets(
    rules: list[str],
    rule_to_components: dict[str, list[str]] | None = None,
    aliases: dict[str, set[str]] | None = None,
) -> dict[str, list[dict]]:
    """Discover open conforma-violation tickets and match them to the given rules.

    Runs one label-first discovery across the conforma projects
    (``conforma_jira_ticket_ops.discover_conforma_tickets``, all statuses), drops
    closed tickets, and matches each open ticket to a rule in two passes:

      1. **Exact rule code** -- the rule appears verbatim in the ticket summary
         (the deterministic ``Conforma violation: {rule} in ...`` format always
         carries the rule code). Strong deterministic signal, no inference tag.
      2. **Component overlap** for rules still unmatched -- a ticket that names one
         of the rule's konflux components (or an alias) in its text. These are
         weaker, inferred matches: they are tagged ``match_source =
         "component_inference"`` with an ``inference_confidence`` (``confirmed``
         when the ticket text also references the rule, else ``unconfirmed``).

    Release relevance is not filtered here; the coverage workflow annotates each
    ticket with ``classify_ticket_version_relevance`` downstream. Returns a
    mapping of ``rule -> list[ticket]`` in the coverage-table ticket shape.
    """
    import conforma_jira_ticket_ops

    discovered = conforma_jira_ticket_ops.discover_conforma_tickets()
    open_tickets = [t for t in discovered if is_open(t.get("status"))]
    base_by_key = {t.get("key", ""): _normalize_ticket(t) for t in open_tickets}

    rule_to_tickets: dict[str, list[dict]] = {r: [] for r in rules}
    assigned_keys: set[str] = set()

    # Pass 1: exact rule code in the summary (strong deterministic signal -- the
    # deterministic ``Conforma violation: {rule} in ...`` format always carries the
    # rule code). No inference tag. Each ticket is assigned to at most one rule
    # (the first rule whose code appears in its summary).
    for ticket in open_tickets:
        key = ticket.get("key", "")
        extracted = _extract_rule_from_summary(ticket.get("summary", "") or "")
        for rule in rules:
            if extracted == rule:
                rule_to_tickets[rule].append(base_by_key[key])
                assigned_keys.add(key)
                break

    # Pass 2: component overlap for rules still without a ticket. A ticket that
    # names one of the rule's konflux components (or an alias) in its text is an
    # inferred match -- tagged match_source="component_inference" with a
    # confidence based on whether the text also references the rule.
    component_map = rule_to_components or {}
    if component_map:
        for rule in rules:
            if rule_to_tickets[rule]:
                continue
            konflux_components = component_map.get(rule) or []
            if not konflux_components:
                continue
            for ticket in open_tickets:
                key = ticket.get("key", "")
                if key in assigned_keys:
                    continue
                if not _konflux_stems_in_text(ticket, konflux_components, aliases):
                    continue
                tagged = _normalize_ticket(
                    ticket,
                    match_source="component_inference",
                    inference_confidence="confirmed" if rule_matches(ticket, rule) else "unconfirmed",
                )
                rule_to_tickets[rule].append(tagged)
                assigned_keys.add(key)
                break

    return rule_to_tickets


def main() -> None:
    parser = argparse.ArgumentParser(description="Conforma Jira ticket discovery primitives")
    sub = parser.add_subparsers(dest="command")

    search_parser = sub.add_parser("search-tickets")
    search_parser.add_argument("--rules", required=True, help="Comma-separated conforma rules")

    args = parser.parse_args()

    if args.command == "search-tickets":
        rules = [r.strip() for r in args.rules.split(",")]
        result = prefetch_open_jira_tickets(rules)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
