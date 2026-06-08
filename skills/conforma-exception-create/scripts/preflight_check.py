#!/usr/bin/env python3
"""Deterministic pre-flight check for conforma-exception-create.

Resolves ALL parameters from authoritative sources (Jira, GitLab, RPA files).
The agent MUST run this script FIRST and present its output to the user for
confirmation. The agent MUST NOT make decisions about any of these values.

Outputs a JSON with:
  - resolved values (rule, components, versions, dates, links)
  - existing state (duplicate tickets, existing exceptions, related PSX)
  - hard-rule defaults (link types, MR-per-version strategy)
  - items requiring user confirmation

Usage:
  python3 scripts/preflight_check.py --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38389
  python3 scripts/preflight_check.py --rhoaieng-url ... --rpa-dir /tmp/conforma-check/config/.../rhoai
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


# Hard rules — NOT configurable by the agent or user
HARD_RULES = {
    "mr_strategy": "always_one_mr_per_rhoai_version",
    "link_type_rhoaieng_to_psx": "Blocks",
    "link_type_related_psx": "Related",
    "link_type_tracking_ticket": "Related",
    "no_self_links": True,
    "remote_links_are_idempotent": True,
    "old_style_exception_handling": "leave_intact_append_new_with_componentNames",
    "matching_componentNames_exception_handling": "extend_effectiveUntil_in_place",
}

# Default end-of-support dates (effectiveUntil = EOS + 7 days)
DEFAULT_EOS_DATES: dict[str, str] = {
    "rhoai-2.25": "2027-04-26",
    "rhoai-3.3": "2026-10-05",
    "rhoai-3.4": "2026-08-12",
    "rhoai-3.5-ea.1": "2026-06-19",
}


def _run_acli(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    from cli_runner import run_acli
    return run_acli(args, timeout=timeout)


def _extract_ticket_key(url: str) -> str | None:
    match = re.search(r"([A-Z]+-\d+)", url)
    return match.group(1) if match else None


def fetch_rhoaieng_ticket(url: str) -> dict:
    """Fetch RHOAIENG ticket details and extract rule/version/component info."""
    ticket_key = _extract_ticket_key(url)
    if not ticket_key:
        return {"error": f"Cannot extract ticket key from: {url}"}

    result = _run_acli(["jira", "workitem", "view", ticket_key, "--json"], timeout=30)
    if result.returncode != 0:
        return {"error": f"Cannot fetch {ticket_key}: {result.stderr.strip()}"}

    data = json.loads(result.stdout)
    fields = data.get("fields", {})

    info = {
        "key": ticket_key,
        "url": url,
        "summary": fields.get("summary", ""),
        "type": fields.get("issuetype", {}).get("name", "Unknown"),
        "priority": fields.get("priority", {}).get("name", "Unknown"),
        "status": fields.get("status", {}).get("name", "Unknown"),
        "labels": fields.get("labels", []),
    }

    if info["type"] != "Bug" or info["priority"] != "Blocker":
        info["type_warning"] = (
            f"{ticket_key} is a '{info['type']}' (priority: {info['priority']}). "
            f"Exception process expects a Blocker Bug cloned from RHOAIENG-62569."
        )

    rule = _extract_rule_from_summary(info["summary"])
    if rule:
        info["detected_rule"] = rule

    return info


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


def search_related_psx(rule: str) -> list[dict]:
    """Search for existing PSX tickets related to this rule."""
    rule_fragment = rule
    if ":" in rule:
        rule_fragment = rule.split(":", 1)[1]

    result = _run_acli(
        ["jira", "workitem", "search", "--jql",
         f"project = PSX AND text ~ '{rule_fragment}'"],
        timeout=30,
    )
    if result.returncode != 0:
        return []

    tickets = []
    for line in result.stdout.splitlines():
        match = re.search(r"(PSX-\d+)", line)
        if match:
            key = match.group(1)
            if key not in [t["key"] for t in tickets]:
                summary_match = re.search(r"PSX-\d+\s*│\s*.*?│.*?│.*?│\s*(.*)", line)
                summary = summary_match.group(1).strip() if summary_match else ""
                tickets.append({"key": key, "summary_fragment": summary})
    return tickets


def search_existing_exceptions(rule: str, clone_dir: str | None = None) -> dict:
    """Check if exception for this rule already exists in konflux-release-data."""
    if clone_dir:
        search_dir = Path(clone_dir)
    else:
        search_dir = Path("/tmp/conforma-check")

    if not search_dir.exists():
        return {"checked": False, "reason": "No local clone available"}

    policy_dir = search_dir / "config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy"
    if not policy_dir.exists():
        return {"checked": False, "reason": f"Policy dir not found: {policy_dir}"}

    found_in = []
    for yaml_file in policy_dir.glob("*rhoai*.yaml"):
        content = yaml_file.read_text(encoding="utf-8")
        if f"value: {rule}" in content:
            from create_gitlab_mr import _find_existing_exceptions
            exceptions = _find_existing_exceptions(content, rule)
            for exc in exceptions:
                found_in.append({
                    "file": str(yaml_file.relative_to(search_dir)),
                    "has_componentNames": exc["has_component_names"],
                    "componentNames": exc["component_names"],
                    "effectiveUntil": exc["effective_until_value"],
                })

    return {
        "checked": True,
        "rule": rule,
        "existing_exceptions": found_in,
        "count": len(found_in),
    }


def check_duplicate_psx_tickets(rule: str, rhoai_versions: list[str]) -> list[dict]:
    """Check if PSX tickets already exist for this exact rule+versions combo."""
    search_term = rule.split(":", 1)[1] if ":" in rule else rule
    result = _run_acli(
        ["jira", "workitem", "search", "--jql",
         f"project = PSX AND summary ~ '{search_term}' AND "
         f"labels = 'conforma-exception-create-ai-skill'"],
        timeout=30,
    )
    if result.returncode != 0:
        return []

    tickets = []
    for line in result.stdout.splitlines():
        match = re.search(r"(PSX-\d+)", line)
        if match:
            key = match.group(1)
            if key not in [t["key"] for t in tickets]:
                tickets.append({"key": key})
    return tickets


def lookup_components_from_rpa(
    image_bases: list[str], rhoai_versions: list[str], rpa_dir: str | None = None
) -> dict[str, list[str]]:
    """Look up Konflux component names from ReleasePlanAdmission files."""
    from validate_inputs import lookup_component_names, parse_rhoai_version

    results: dict[str, list[str]] = {}
    for ver in rhoai_versions:
        all_matches = []
        for img in image_bases:
            found = lookup_component_names(img, [ver], rpa_dir)
            all_matches.extend(found.get(ver, []))
        results[ver] = sorted(set(all_matches))
    return results


def resolve_effective_until_dates(rhoai_versions: list[str]) -> dict[str, dict]:
    """Resolve effectiveUntil dates from defaults (end-of-support + 7 days)."""
    results = {}
    for ver in rhoai_versions:
        if ver in DEFAULT_EOS_DATES:
            results[ver] = {
                "effectiveUntil": f"{DEFAULT_EOS_DATES[ver]}T00:00:00Z",
                "source": "default_eos_table",
                "note": "End-of-support + 7 days buffer (pre-calculated)",
            }
        else:
            results[ver] = {
                "effectiveUntil": None,
                "source": "unknown",
                "note": f"No default EOS date for {ver}. User must provide.",
            }
    return results


def run_preflight(
    rhoaieng_url: str,
    rule_override: str | None = None,
    versions_override: list[str] | None = None,
    image_bases: list[str] | None = None,
    rpa_dir: str | None = None,
    clone_dir: str | None = None,
) -> dict:
    """Run all pre-flight checks and return structured result."""
    output: dict = {
        "hard_rules": HARD_RULES,
        "rhoaieng": {},
        "rule": {},
        "versions": {},
        "components": {},
        "effective_until": {},
        "related_psx": {},
        "existing_exceptions": {},
        "duplicate_check": {},
        "user_confirmation_required": [],
    }

    # 1. Fetch RHOAIENG ticket
    rhoaieng = fetch_rhoaieng_ticket(rhoaieng_url)
    output["rhoaieng"] = rhoaieng
    if "error" in rhoaieng:
        output["user_confirmation_required"].append(
            f"Cannot fetch RHOAIENG ticket: {rhoaieng['error']}"
        )
        return output

    # 2. Resolve rule
    if rule_override:
        resolved_rule = rule_override
        output["rule"] = {"value": resolved_rule, "source": "user_override"}
    elif rhoaieng.get("detected_rule"):
        resolved_rule = rhoaieng["detected_rule"]
        output["rule"] = {"value": resolved_rule, "source": "extracted_from_summary"}
        output["user_confirmation_required"].append(
            f"Confirm rule: {resolved_rule} (extracted from ticket summary)"
        )
    else:
        resolved_rule = ""
        output["rule"] = {"value": None, "source": "not_found"}
        output["user_confirmation_required"].append(
            "Could not extract rule from ticket. User must provide --rule."
        )

    # 3. Resolve versions
    if versions_override:
        versions = versions_override
        output["versions"] = {"values": versions, "source": "user_override"}
    else:
        output["versions"] = {"values": [], "source": "not_provided"}
        output["user_confirmation_required"].append(
            "RHOAI versions not provided. User must specify."
        )
        versions = []

    # 4. Look up components
    if image_bases and versions:
        components = lookup_components_from_rpa(image_bases, versions, rpa_dir)
        output["components"] = {"per_version": components, "source": "rpa_lookup"}
        output["user_confirmation_required"].append(
            f"Confirm component names per version: {json.dumps(components)}"
        )
    else:
        output["components"] = {"per_version": {}, "source": "not_resolved"}
        if not image_bases:
            output["user_confirmation_required"].append(
                "Image base names not provided. Cannot look up components."
            )

    # 5. Resolve effectiveUntil dates
    if versions:
        dates = resolve_effective_until_dates(versions)
        output["effective_until"] = dates
        missing_dates = [v for v, d in dates.items() if d["effectiveUntil"] is None]
        if missing_dates:
            output["user_confirmation_required"].append(
                f"No default EOS dates for: {missing_dates}. User must provide."
            )
        else:
            output["user_confirmation_required"].append(
                "Confirm effectiveUntil dates (end-of-support + 7 days): "
                + ", ".join(f"{v}={d['effectiveUntil']}" for v, d in dates.items())
            )

    # 6. Search related PSX
    if resolved_rule:
        related = search_related_psx(resolved_rule)
        output["related_psx"] = {"found": related, "count": len(related)}
    else:
        output["related_psx"] = {"found": [], "count": 0}

    # 7. Check existing exceptions in GitLab
    if resolved_rule:
        existing = search_existing_exceptions(resolved_rule, clone_dir)
        output["existing_exceptions"] = existing

    # 8. Check for duplicate PSX tickets
    if resolved_rule and versions:
        dupes = check_duplicate_psx_tickets(resolved_rule, versions)
        output["duplicate_check"] = {
            "existing_skill_created_psx": dupes,
            "count": len(dupes),
        }
        if dupes:
            output["user_confirmation_required"].append(
                f"WARNING: Found {len(dupes)} existing PSX ticket(s) created by this "
                f"skill for the same rule: {[d['key'] for d in dupes]}. "
                f"Confirm whether to reuse or create new."
            )

    # 9. RHOAIENG type warning
    if rhoaieng.get("type_warning"):
        output["user_confirmation_required"].append(rhoaieng["type_warning"])

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deterministic pre-flight check for conforma-exception-create"
    )
    parser.add_argument("--rhoaieng-url", required=True, help="RHOAIENG Jira ticket URL")
    parser.add_argument("--rule", default=None, help="Override rule (skip extraction)")
    parser.add_argument(
        "--versions", default=None,
        help="Comma-separated RHOAI versions (e.g. rhoai-2.25,rhoai-3.3)"
    )
    parser.add_argument(
        "--image-bases", default=None,
        help="Comma-separated image base names for RPA lookup (e.g. odh-vllm-cpu,odh-vllm-gaudi)"
    )
    parser.add_argument("--rpa-dir", default=None, help="Path to RPA directory")
    parser.add_argument("--clone-dir", default=None, help="Path to konflux-release-data clone")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    versions = [v.strip() for v in args.versions.split(",")] if args.versions else None
    image_bases = [i.strip() for i in args.image_bases.split(",")] if args.image_bases else None

    result = run_preflight(
        rhoaieng_url=args.rhoaieng_url,
        rule_override=args.rule,
        versions_override=versions,
        image_bases=image_bases,
        rpa_dir=args.rpa_dir,
        clone_dir=args.clone_dir,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
