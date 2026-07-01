#!/usr/bin/env python3
"""Generate a markdown report from assessed exceptions.

Reads assessed-exceptions.yaml (output of manage_exceptions.py --assess-expired
or --assess-all) and produces a .md file with summary stats, an exception/release
matrix table, and per-exception detail sections.

Supports both expired-only and mixed (expired + active) input. The report format
adapts automatically based on the input scope.

Usage:
    python3 scripts/generate_report.py \\
      --assessed-input .work/assessed-exceptions.yaml \\
      --output .work/exceptions-report.md

    # Also write a machine-readable action plan for the agent:
    python3 scripts/generate_report.py \\
      --assessed-input .work/assessed-exceptions.yaml \\
      --output .work/exceptions-report.md \\
      --action-plan-output .work/action-plan.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import yaml


from conforma_constants import build_report_url as _build_report_url
KONFLUX_RELEASE_DATA_HOST = os.environ.get("GITLAB_HOST", "")
KONFLUX_RELEASE_DATA_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")

ACTION_LABELS = {
    "extend": "extend",
    "extend_and_modernize": "extend + modernize",
    "narrow_and_extend": "narrow + extend",
    "narrow": "narrow",
    "modernize_and_narrow": "modernize + narrow",
    "remove": "remove",
    "keep": "keep",
}

ACTION_DETAILS = {
    "extend": "extend effectiveUntil date",
    "extend_and_modernize": "remove unscoped block (no componentNames), create new per-componentName exceptions",
    "narrow_and_extend": "reduce scope to still-violating releases, extend date",
    "narrow": "active exception, remove components that no longer violate",
    "modernize_and_narrow": "remove unscoped block (no componentNames), create per-componentName exceptions for remaining violations only",
    "remove": "violation resolved, delete exception block",
    "keep": "still needed and not expired, no action required",
}


def _load_assessment(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_policy_file_url(file_path: str) -> str:
    return f"https://{KONFLUX_RELEASE_DATA_HOST}/{KONFLUX_RELEASE_DATA_PROJECT}/-/blob/main/{file_path}"


def _exception_label(exc: dict) -> str:
    """Derive a human-readable label from comment headers or rule."""
    headers = exc.get("comment_header_lines", [])
    for line in headers:
        cleaned = line.lstrip("# ").strip()
        if (
            cleaned
            and not cleaned.startswith("http")
            and not cleaned.startswith("impacted")
            and not cleaned.startswith("dates ")
        ):
            if len(cleaned) > 60:
                cleaned = cleaned[:57] + "..."
            return cleaned
    rule = exc.get("rule", "")
    base = rule.split(":")[0] if ":" in rule else rule
    return base


def _reference_label(exc: dict) -> tuple[str, str]:
    """Extract a short label and URL for the reference field."""
    ref = exc.get("reference", "")
    if not ref:
        return ("--", "")

    if "atlassian.net/browse/" in ref:
        key = ref.split("/browse/")[-1]
        return (key, ref)
    if "issues.redhat.com/browse/" in ref:
        key = ref.split("/browse/")[-1]
        return (key, ref)
    if "github.com/" in ref:
        parts = ref.rstrip("/").split("/")
        if len(parts) >= 2:
            return (f"{parts[-2]}#{parts[-1]}", ref)
        return (ref.split("github.com/")[-1][:30], ref)

    return (ref[:30], ref)


def _policy_label(file_path: str) -> str:
    """Derive a short label from the policy file path (e.g. 'registry' or 'fbc')."""
    name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    if name.startswith("fbc-"):
        return "fbc"
    if name.startswith("registry-"):
        return "registry"
    return name.replace(".yaml", "")


def _md_link(text: str, url: str) -> str:
    if url:
        return f"[{text}]({url})"
    return text


def _strip_version_suffix(name: str) -> str:
    """Strip the trailing release-version suffix from a Konflux component name.

    E.g. 'odh-mlflow-v3-3' -> 'odh-mlflow', 'odh-dashboard-v3-5-ea-1' -> 'odh-dashboard'.
    """
    import re

    return re.sub(r"-v\d+[-.\d]*(-(ea|rc|beta)[-.\d]*)?$", "", name)


def _component_cell(exc: dict) -> str:
    """Build a compact component-names or imageUrl cell for the matrix table.

    Shows what is declared in the policy file:
    - Scoped exceptions: componentNames list
    - Unscoped exceptions with imageUrl: the image URL
    - Unscoped exceptions without imageUrl: 'all' (blanket exception)
    """
    comp_names = exc.get("component_names", [])
    if comp_names:
        names = sorted(comp_names)
        if len(names) == 1:
            return f"`{names[0]}`"
        if len(names) <= 3:
            return ", ".join(f"`{c}`" for c in names)
        return f"{len(names)} components"

    image_url = exc.get("image_url", "")
    if image_url:
        return f"`{image_url}`"

    return "all"


def _components_by_release(exc: dict) -> dict[str, list[str]]:
    """Map components to their release based on version suffix in the name."""
    evidence = exc.get("evidence", {})
    still_violating = evidence.get("still_violating_releases", [])
    still_components = evidence.get("still_violating_components", [])

    result: dict[str, list[str]] = {}
    for comp in still_components:
        for rel in still_violating:
            suffix = rel.replace("rhoai-", "v").replace(".", "-")
            if suffix in comp or rel in comp:
                result.setdefault(rel, []).append(comp)
                break
        else:
            for rel in still_violating:
                result.setdefault(rel, [])
    return result


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------


def _effective_until_cell(exc: dict) -> str:
    """Format the effective-until column for the matrix row."""
    effective_until = exc.get("effective_until", "")
    date_str = effective_until[:10] if effective_until else "--"
    is_expired = exc.get("is_expired", True)

    if is_expired:
        days_ago = exc.get("expired_days_ago", 0)
        return f"{date_str} ({days_ago}d ago)"
    else:
        days_left = exc.get("expires_in_days", 0)
        return f"{date_str} (in {days_left}d)"


def _effective_until_detail(exc: dict) -> str:
    """Format the effective-until line for the detail section."""
    effective_until = exc.get("effective_until", "")
    date_str = effective_until[:10] if effective_until else "--"
    is_expired = exc.get("is_expired", True)

    if is_expired:
        days_ago = exc.get("expired_days_ago", 0)
        return f"**Expired**: {date_str} ({days_ago} days ago)"
    else:
        days_left = exc.get("expires_in_days", 0)
        return f"**Effective until**: {date_str} (in {days_left} days)"


def _append_matrix_table(
    lines: list[str],
    exceptions: list[dict],
    releases: list[str],
    is_all: bool,
    report_created_at: dict[str, str] | None = None,
    report_urls: dict[str, str] | None = None,
) -> None:
    """Append an exception/release matrix table to the lines list."""
    date_col = "Effective Until" if is_all else "Expired"
    dates = report_created_at or {}
    urls = report_urls or {}
    rel_headers = []
    for rel in releases:
        label = rel.replace("rhoai-", "")
        created = dates.get(rel, "")
        if created:
            label += f" ({created[:10]})"
        rel_headers.append(f"[{label}]({urls.get(rel, '')})")
    header = f"| Exception | Component(s) | Rule | {date_col} | Ref | " + " | ".join(rel_headers) + " | Action |"
    sep = "|:----------|:-------------|:-----|:--------|:----" + "|:------:" * len(releases) + "|:-------|"
    lines.append(header)
    lines.append(sep)

    for exc in exceptions:
        label = _exception_label(exc)
        rule = exc.get("rule", "")
        eu_cell = _effective_until_cell(exc)
        ref_label, ref_url = _reference_label(exc)
        action = exc.get("recommended_action", "review")
        is_unscoped = exc.get("is_unscoped", False)
        policy = _policy_label(exc.get("file", ""))
        comp_cell = _component_cell(exc)

        evidence = exc.get("evidence", {})
        resolved_in = evidence.get("resolved_in_releases", [])
        comps_by_rel = _components_by_release(exc)

        exc_label = label
        if policy == "fbc":
            exc_label += " `[fbc]`"

        ref_cell = _md_link(ref_label, ref_url) if ref_url else ref_label

        rel_cells = []
        for rel in releases:
            if rel in resolved_in:
                rel_cells.append("resolved")
            elif rel in comps_by_rel and comps_by_rel[rel]:
                count = len(comps_by_rel[rel])
                rel_cells.append(f"**{count}** comp{'s' if count > 1 else ''}")
            else:
                rel_cells.append("--")

        action_text = ACTION_LABELS.get(action, action)
        if is_unscoped and action not in ("keep", "remove") and "modernize" not in action:
            action_text += " (unscoped, no componentNames)"

        row = (
            f"| {exc_label} | {comp_cell} | `{rule}` | {eu_cell} | {ref_cell} | "
            + " | ".join(rel_cells)
            + f" | {action_text} |"
        )
        lines.append(row)


def generate_markdown(data: dict, environment: str) -> str:
    """Generate a markdown report from assessment data."""
    releases = data.get("releases_checked", [])
    not_checked = data.get("releases_not_checked", [])
    exceptions = data.get("assessed_exceptions", [])
    generated_at = data.get("generated_at", "unknown")
    scope = data.get("scope", "expired")
    is_all = scope == "all"

    report_urls: dict[str, str] = {}
    for exc in exceptions:
        for rel, url in exc.get("evidence", {}).get("report_urls", {}).items():
            if rel not in report_urls and url:
                report_urls[rel] = url
    for rel in releases:
        if rel not in report_urls:
            report_urls[rel] = _build_report_url(rel, environment)

    report_created_at: dict[str, str] = data.get("report_created_at", {})

    total = len(exceptions)
    total_expired = sum(1 for e in exceptions if e.get("is_expired", True))
    total_active = total - total_expired
    can_remove = sum(1 for e in exceptions if e.get("classification") == "no_longer_needed")
    need_action = sum(
        1
        for e in exceptions
        if e.get("is_expired", True) and e.get("classification") in ("still_needed", "partially_needed")
    )
    no_action = sum(1 for e in exceptions if e.get("recommended_action") == "keep")
    need_modernize = sum(1 for e in exceptions if "modernize" in e.get("recommended_action", ""))

    lines: list[str] = []

    if is_all:
        lines.append("# RHOAI Conforma Exception Assessment")
    else:
        lines.append("# RHOAI Conforma Expired Exceptions")
    lines.append("")
    lines.append(f"Assessment as of {generated_at[:10]}. Source: konflux-release-data policy files.")
    lines.append("")

    # --- Summary ---
    lines.append("## Summary")
    lines.append("")
    if is_all:
        lines.append("| Total | Expired | Active | Can remove | Need action | No action needed |")
        lines.append("|:-----:|:-------:|:------:|:----------:|:-----------:|:----------------:|")
        lines.append(f"| {total} | {total_expired} | {total_active} | {can_remove} | {need_action} | {no_action} |")
    else:
        still_needed = sum(1 for e in exceptions if e.get("classification") == "still_needed")
        lines.append("| Expired | Still needed | Can remove | Need modernizing |")
        lines.append("|:-------:|:------------:|:----------:|:----------------:|")
        lines.append(f"| {total} | {still_needed} | {can_remove} | {need_modernize} |")
    lines.append("")

    # --- Release report links ---
    lines.append("## Violation reports")
    lines.append("")
    for rel in releases:
        url = report_urls.get(rel, "")
        created = report_created_at.get(rel, "")
        date_suffix = f" (created {created[:10]})" if created else ""
        if url:
            lines.append(f"- {rel}: [conforma-violations-report.csv]({url}){date_suffix}")
        else:
            lines.append(f"- {rel}: *(no report)*")
    lines.append("")

    # --- Policy file links ---
    policy_files = sorted({exc.get("file", "") for exc in exceptions if exc.get("file")})
    if policy_files:
        lines.append("## Policy files")
        lines.append("")
        for pf in policy_files:
            name = pf.rsplit("/", 1)[-1] if "/" in pf else pf
            url = _build_policy_file_url(pf)
            lines.append(f"- [{name}]({url})")
        lines.append("")

    # --- Not checked ---
    if not_checked:
        lines.append("> **Not checked:** " + "; ".join(f"{nc['release']}: {nc['error']}" for nc in not_checked) + ".")
        lines.append("")

    # --- Removable exceptions table (shown first when present) ---
    removable = [e for e in exceptions if e.get("classification") == "no_longer_needed"]
    if removable:
        lines.append("## Can remove")
        lines.append("")
        lines.append("Violations resolved in all checked releases -- these exceptions can be deleted now.")
        lines.append("")
        _append_matrix_table(lines, removable, releases, is_all, report_created_at, report_urls)
        lines.append("")

    # --- Exception / Release Matrix ---
    lines.append("## Exception / Release Matrix")
    lines.append("")

    _append_matrix_table(lines, exceptions, releases, is_all, report_created_at, report_urls)
    lines.append("")

    # --- Detailed component lists ---
    lines.append("## Details per exception")
    lines.append("")

    for i, exc in enumerate(exceptions, 1):
        label = _exception_label(exc)
        rule = exc.get("rule", "")
        ref_label, ref_url = _reference_label(exc)
        action = exc.get("recommended_action", "review")
        is_unscoped = exc.get("is_unscoped", False)
        policy_file = exc.get("file", "")

        evidence = exc.get("evidence", {})
        resolved_in = evidence.get("resolved_in_releases", [])
        comps_by_rel = _components_by_release(exc)

        action_label = ACTION_LABELS.get(action, action)
        action_detail = ACTION_DETAILS.get(action, "")

        lines.append(f"### {i}. {label}")
        lines.append("")
        lines.append(f"- **Rule**: `{rule}`")
        lines.append(f"- {_effective_until_detail(exc)}")
        if ref_url:
            lines.append(f"- **Reference**: [{ref_label}]({ref_url})")
        elif ref_label != "--":
            lines.append(f"- **Reference**: {ref_label}")
        lines.append(f"- **Policy file**: `{policy_file}`")
        if is_unscoped:
            lines.append("- **Type**: unscoped (uses containerImage refs instead of componentNames)")
        lines.append(f"- **Action**: **{action_label}** -- {action_detail}")
        if resolved_in:
            lines.append(f"- **Resolved in**: {', '.join(resolved_in)}")
        lines.append("")

        if comps_by_rel:
            lines.append("| Release | Components |")
            lines.append("|:--------|:-----------|")
            for rel in releases:
                if rel in resolved_in:
                    lines.append(f"| {rel} | *resolved* |")
                elif rel in comps_by_rel and comps_by_rel[rel]:
                    comp_list = ", ".join(f"`{c}`" for c in comps_by_rel[rel])
                    lines.append(f"| {rel} | {comp_list} |")
                else:
                    lines.append(f"| {rel} | -- |")
            lines.append("")

    # --- Footer ---
    lines.append("---")
    lines.append("")
    import getpass
    import socket
    user_host = f"{getpass.getuser()}@{socket.gethostname()}"
    lines.append("*Generated by conforma-analyze + conforma-exception skills.*")
    lines.append(f"*Run by: {user_host}*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Action plan (JSON) -- machine-readable for the agent's action loop
# ---------------------------------------------------------------------------


def build_action_plan(data: dict) -> dict:
    """Build a machine-readable action plan from the assessment data.

    Returns a JSON-serializable dict with structured action items the
    agent can iterate over to create Merge Requests. Excludes "keep" actions since
    they require no Merge Request.
    """
    exceptions = data.get("assessed_exceptions", [])
    generated_at = data.get("generated_at", "unknown")

    ACTION_ORDER = {
        "remove": 0,
        "narrow": 1,
        "extend": 2,
        "narrow_and_extend": 3,
        "extend_and_modernize": 4,
        "modernize_and_narrow": 5,
    }

    actions = []
    skipped = 0
    for exc in exceptions:
        action = exc.get("recommended_action", "review")
        if action == "keep":
            skipped += 1
            continue

        versions = _components_by_release(exc)

        actions.append(
            {
                "rule": exc.get("rule", ""),
                "label": _exception_label(exc),
                "action": action,
                "classification": exc.get("classification", "unknown"),
                "is_expired": exc.get("is_expired", True),
                "policy_file": exc.get("file", ""),
                "old_effective_until": exc.get("effective_until", ""),
                "is_unscoped": exc.get("is_unscoped", False),
                "reference": exc.get("reference", ""),
                "versions": versions,
                "resolved_in": exc.get("evidence", {}).get("resolved_in_releases", []),
            }
        )

    actions.sort(key=lambda a: ACTION_ORDER.get(a["action"], 99))

    return {
        "generated_at": generated_at,
        "total_actions": len(actions),
        "total_skipped_keep": skipped,
        "actions": actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a markdown report from assessed exceptions")
    parser.add_argument(
        "--assessed-input",
        required=True,
        help="Path to assessed-exceptions.yaml",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the markdown report (.md)",
    )
    parser.add_argument(
        "--action-plan-output",
        default=None,
        help="Write a JSON action plan for the agent to iterate over",
    )
    parser.add_argument(
        "--environment",
        required=True,
        choices=["prod", "stage"],
        help="Target environment (prod or stage) — determines fallback report URLs",
    )
    args = parser.parse_args()

    input_path = Path(args.assessed_input)
    if not input_path.is_file():
        print(f"Error: assessment file not found: {input_path}", file=sys.stderr)
        return 1

    data = _load_assessment(input_path)
    report = generate_markdown(data, environment=args.environment)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")

    exc_count = len(data.get("assessed_exceptions", []))
    rel_count = len(data.get("releases_checked", []))
    print(
        f"Report: {exc_count} exceptions x {rel_count} releases -> {output_path}",
        file=sys.stderr,
    )

    if args.action_plan_output:
        plan = build_action_plan(data)
        plan_path = Path(args.action_plan_output)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(
            f"Action plan: {plan['total_actions']} actions -> {plan_path}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
