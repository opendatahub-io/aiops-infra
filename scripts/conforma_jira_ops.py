"""conforma_jira_ops.py -- Conforma Jira ticket discovery primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess


def _run_acli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    from cli_runner import run_acli

    return run_acli(args, timeout=timeout)


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


def _parse_acli_table(stdout: str) -> list[dict]:
    """Parse acli table output with multi-line wrapped cells.

    The table has columns: Type | Key | Assignee | Priority | Status | Summary.
    Rows are separated by ``├──`` lines. Long cell values wrap across multiple
    lines within the same row.
    """
    tickets: list[dict] = []
    current_cells: dict[str, str] = {}
    col_indices: list[tuple[int, int]] = []

    for line in stdout.splitlines():
        if line.startswith("├") or line.startswith("└"):
            if current_cells.get("key"):
                tickets.append(
                    {
                        "key": current_cells["key"].strip(),
                        "type": current_cells.get("type", "").strip(),
                        "status": current_cells.get("status", "").strip(),
                        "summary": re.sub(r"\s+", " ", current_cells.get("summary", "")).strip(),
                        "url": f"https://redhat.atlassian.net/browse/{current_cells['key'].strip()}",
                    }
                )
            current_cells = {}
            continue

        if line.startswith("┌"):
            col_indices = []
            start = 0
            for m in re.finditer(r"[┬┐]", line):
                col_indices.append((start + 1, m.start()))
                start = m.start()
            continue

        if "│" not in line or not col_indices:
            continue

        if line.strip().startswith("│") and "Type" in line and "Key" in line:
            continue

        parts = []
        raw_parts = []
        for start, end in col_indices:
            if start < len(line) and end <= len(line):
                parts.append(line[start:end].strip())
                raw_parts.append(line[start:end].rstrip())
            else:
                parts.append("")
                raw_parts.append("")

        if len(parts) >= 6:
            key_candidate = parts[1]
            if re.match(r"(RHOAIENG|PSX|OCPEXCEPT)-\d+", key_candidate):
                current_cells = {
                    "type": parts[0],
                    "key": key_candidate,
                    "status": parts[4],
                    "summary": raw_parts[5],
                }
            elif current_cells:
                current_cells["summary"] = current_cells.get("summary", "") + raw_parts[5]

    if current_cells.get("key"):
        tickets.append(
            {
                "key": current_cells["key"].strip(),
                "type": current_cells.get("type", "").strip(),
                "status": current_cells.get("status", "").strip(),
                "summary": re.sub(r"\s+", " ", current_cells.get("summary", "")).strip(),
                "url": f"https://redhat.atlassian.net/browse/{current_cells['key'].strip()}",
            }
        )

    return tickets


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
    result = _run_acli(
        ["jira", "workitem", "search", "--jql", jql],
        timeout=45,
    )
    if result.returncode == 0:
        all_tickets = _parse_acli_table(result.stdout)

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
            f"project in (RHOAIENG, PSX, OCPEXCEPT) AND labels = '{rule}' AND status not in (Closed, Resolved, Done)"
        )
        label_result = _run_acli(
            ["jira", "workitem", "search", "--jql", label_jql],
            timeout=45,
        )
        if label_result.returncode == 0:
            for ticket in _parse_acli_table(label_result.stdout):
                if ticket not in rule_to_tickets[rule]:
                    if not version_patterns or _ticket_matches_release(ticket, version_patterns):
                        rule_to_tickets[rule].append(ticket)

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
