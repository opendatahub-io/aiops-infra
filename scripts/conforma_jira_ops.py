"""conforma_jira_ops.py -- Conforma Jira ticket discovery primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import re

import jira_ops


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


def _ticket_matches_release(ticket: dict, version_patterns: list[str]) -> bool:
    """Check if a Jira ticket's summary references one of the target release versions."""
    summary_lower = re.sub(r"\s+", "", ticket["summary"].lower())
    for pattern in version_patterns:
        pattern_nospace = re.sub(r"\s+", "", pattern)
        if pattern_nospace in summary_lower:
            return True
    return False




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


def prefetch_open_jira_tickets(rules: list[str], releases: list[str] | None = None) -> dict[str, list[dict]]:
    """Batch search for open Jira tickets (RHOAIENG, PSX, OCPEXCEPT) matching violations.

    Does one broad JQL query to find all open conforma-violation tickets,
    then matches them to rules by summary text. When ``releases`` is provided,
    further filters to only tickets whose summary references one of the target
    RHOAI versions (checked via target_versions/affected_versions text patterns
    in the ticket summary).

    Returns a mapping of ``rule -> list[ticket_info]``.
    """
    all_tickets: list[dict] = []

    jql = (
        "project in (RHOAIENG, PSX, OCPEXCEPT) "
        "AND labels = 'conforma-violation' "
        "AND status not in (Closed, Resolved, Done)"
    )
    result = jira_ops.search_issues(jql, max_results=200, fields=["key", "summary", "status", "issuetype", "fixVersions"])
    if result.get("issues"):
        all_tickets = [
            {
                "key": t["key"],
                "type": t.get("type", ""),
                "status": t.get("status", ""),
                "summary": t.get("summary", ""),
                "url": t["url"],
                "fix_versions": t.get("fix_versions", []),
            }
            for t in result["issues"]
        ]

    version_patterns = _build_release_version_patterns(releases) if releases else []

    rule_to_tickets: dict[str, list[dict]] = {r: [] for r in rules}
    for ticket in all_tickets:
        summary_nospace = re.sub(r"\s+", "", ticket["summary"].lower())
        for rule in rules:
            rule_nospace = re.sub(r"\s+", "", rule.lower())
            matched = rule_nospace in summary_nospace
            if not matched and ":" in rule:
                suffix_nospace = re.sub(r"\s+", "", rule.split(":", 1)[1].lower())
                matched = suffix_nospace in summary_nospace
            if matched:
                if not version_patterns or _ticket_matches_release(ticket, version_patterns):
                    rule_to_tickets[rule].append(ticket)
                break

    unmatched = [r for r, tickets in rule_to_tickets.items() if not tickets]
    for rule in unmatched:
        label_jql = (
            f"project in (RHOAIENG, PSX, OCPEXCEPT) AND labels = '{rule}' "
            f"AND status not in (Closed, Resolved, Done)"
        )
        label_result = jira_ops.search_issues(label_jql, max_results=50, fields=["key", "summary", "status", "issuetype", "fixVersions"])
        if label_result.get("issues"):
            for ticket in label_result["issues"]:
                normalized = {
                    "key": ticket["key"],
                    "type": ticket.get("type", ""),
                    "status": ticket.get("status", ""),
                    "summary": ticket.get("summary", ""),
                    "url": ticket["url"],
                    "fix_versions": ticket.get("fix_versions", []),
                }
                existing_keys = {t["key"] for t in rule_to_tickets[rule]}
                if normalized["key"] not in existing_keys:
                    if not version_patterns or _ticket_matches_release(normalized, version_patterns):
                        rule_to_tickets[rule].append(normalized)

    return rule_to_tickets


def main() -> None:
    parser = argparse.ArgumentParser(description="Conforma Jira ticket discovery primitives")
    sub = parser.add_subparsers(dest="command")

    search_parser = sub.add_parser("search-tickets")
    search_parser.add_argument("--rules", required=True, help="Comma-separated conforma rules")
    search_parser.add_argument("--releases", default=None, help="Comma-separated RHOAI release names")

    args = parser.parse_args()

    if args.command == "search-tickets":
        rules = [r.strip() for r in args.rules.split(",")]
        releases = [r.strip() for r in args.releases.split(",")] if args.releases else None
        result = prefetch_open_jira_tickets(rules, releases=releases)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
