#!/usr/bin/env python3
"""List current RHOAI Conforma exceptions as formatted Markdown.

Scans policy files from a konflux-release-data clone and renders a
deterministic Markdown report grouped by expiry status.  The output is
designed to be printed verbatim by the AI agent — no reformatting needed.

Only analyzes prod policy files by default.  Use ``--environment stage``
to analyze stage files instead.

Usage:
  python3 scripts/list_exceptions.py --clone-dir .work/konflux-release-data
  python3 scripts/list_exceptions.py --clone-dir .work/konflux-release-data --environment stage
  python3 scripts/list_exceptions.py --clone-dir .work/konflux-release-data --soon-days 30
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from manage_exceptions import (
    _clone_repo,
    _get_policy_files,
    annotate_expiry,
    scan_all_exceptions,
)

_DEFAULT_SOON_DAYS = 14

_JIRA_HOSTS = {
    "issues.redhat.com": True,
    "redhat.atlassian.net": True,
}

_JIRA_KEY_RE = re.compile(r"((?:RHOAIENG|PSX|OCPEXCEPT|PRODSECRM|RHAIENG|RHAISTRAT|KONFLUX)-\d+)")
_GITHUB_ISSUE_RE = re.compile(r"github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)")


def _strip_quotes(s: str) -> str:
    if s and len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


# ── Rule formatting ──────────────────────────────────────────────────


def _format_rule(rule: str) -> str:
    """Format a rule for table display.

    Short rules are shown as-is.  Long rules with embedded package
    references are truncated to the base rule code (the package detail
    goes into the Component / Image column via ``_format_component``).
    """
    rule = _strip_quotes(rule)
    if len(rule) <= 80:
        return rule
    base = rule.split(":", 1)[0] if ":" in rule else rule
    return base


def _extract_package_from_rule(rule: str) -> str | None:
    """Extract a human-readable package/artifact name from long rules."""
    rule = _strip_quotes(rule)
    m = re.search(r"pkg:generic/([^?&]+)", rule)
    if m:
        return m.group(1)
    m = re.search(r"pkg:rpm/[^/]+/([^?&]+)", rule)
    if m:
        return m.group(1)
    return None


# ── Component / Image formatting ─────────────────────────────────────


def _format_component(exc: dict) -> str:
    """Format the 'Component / Image' column.

    Shows what the exception applies to:
      - Konflux componentNames when present
      - Container image base name when scoped by imageUrl
      - Package/artifact name extracted from long rule strings
      - ``(all)`` for truly unscoped exceptions

    When both an imageUrl *and* a long-rule package reference exist
    (e.g. autorag sbom entries), the package name is appended to
    differentiate otherwise-identical rows.
    """
    if exc.get("has_component_names") and exc.get("component_names"):
        names = exc["component_names"]
        if len(names) == 1:
            return names[0]
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} +{len(names) - 2} more"

    image_url = exc.get("image_url", "")
    pkg = _extract_package_from_rule(exc.get("rule", ""))

    if image_url:
        name = image_url.rsplit("/", 1)[-1]
        name = re.sub(r"-rhel\d+$", "", name)
        name = re.sub(r"-ubi\d+$", "", name)
        if pkg:
            return f"{name}: {pkg}"
        return name

    if pkg:
        return pkg

    return "(all)"


# ── Version extraction ───────────────────────────────────────────────


_VERSION_SUFFIX_RE = re.compile(r"-v(\d+)-(\d+)(?:-[a-z]+-\d+)?$")


def _extract_rhoai_version(exc: dict) -> str:
    """Derive RHOAI version(s) from componentNames or imageUrl.

    - **componentNames present**: extract version suffixes (e.g.
      ``odh-model-server-v3-4`` → ``3.4``).  Deduplicate and sort.
    - **imageUrl only** (no componentNames): the exception applies to
      every version shipping that image → ``all``.
    - **Neither**: truly unscoped → ``all``.
    """
    has_components = exc.get("has_component_names") and exc.get("component_names")

    if has_components:
        versions: set[str] = set()
        for name in exc["component_names"]:
            m = _VERSION_SUFFIX_RE.search(name)
            if m:
                versions.add(f"{m.group(1)}.{m.group(2)}")
        if versions:
            return ", ".join(sorted(versions, key=lambda v: tuple(int(p) for p in v.split("."))))
        return "—"

    return "all"


# ── Reference formatting ────────────────────────────────────────────


def _format_reference(ref_url: str | None) -> str:
    """Format a reference URL as a clickable Markdown link."""
    if not ref_url:
        return "—"
    ref_url = _strip_quotes(ref_url)

    m = _JIRA_KEY_RE.search(ref_url)
    if m:
        return f"[{m.group(1)}]({ref_url})"

    m = _GITHUB_ISSUE_RE.search(ref_url)
    if m:
        return f"[{m.group(1)}#{m.group(2)}]({ref_url})"

    if len(ref_url) > 60:
        return f"[link]({ref_url})"
    return ref_url


def _format_date(effective_until: str | None) -> str:
    """Extract the date portion from an effectiveUntil timestamp."""
    if not effective_until:
        return "—"
    eu = _strip_quotes(effective_until)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", eu)
    return m.group(1) if m else eu


# ── Table rendering ──────────────────────────────────────────────────


def _render_table(exceptions: list[dict]) -> str:
    """Render a Markdown table with the standard column layout."""
    lines = [
        "| Rule | Component / Image | RHOAI Version | Effective Until | Reference |",
        "|------|-------------------|---------------|-----------------|-----------|",
    ]
    for exc in exceptions:
        rule = f"`{_format_rule(exc['rule'])}`"
        component = _format_component(exc)
        version = _extract_rhoai_version(exc)
        date = _format_date(exc.get("effective_until"))
        ref = _format_reference(exc.get("reference"))
        lines.append(f"| {rule} | {component} | {version} | {date} | {ref} |")
    return "\n".join(lines)


# ── Report rendering ─────────────────────────────────────────────────


_GITLAB_HOST = os.environ.get("GITLAB_HOST", "")
_GITLAB_PROJECT = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")
_GITLAB_REPO_URL = f"https://{_GITLAB_HOST}/{_GITLAB_PROJECT}" if _GITLAB_HOST else ""


def _policy_file_link(rel_path: str) -> str:
    """Return a clickable Markdown link to a policy file on GitLab."""
    name = Path(rel_path).name
    if not _GITLAB_REPO_URL:
        return f"`{name}`"
    url = f"{_GITLAB_REPO_URL}/-/blob/main/{rel_path}"
    return f"[`{name}`]({url})"


def _render_report(
    exceptions: list[dict],
    environment: str,
    policy_files: list[str],
    soon_days: int,
) -> str:
    """Render the full Markdown report grouped by expiry status.

    Sections:
      1. Expired (effectiveUntil < now)
      2. Expiring within *soon_days* days
      3. One section per remaining effectiveUntil date

    Every section uses the identical table column layout.
    """
    now = datetime.now(timezone.utc)
    soon_cutoff = now + timedelta(days=soon_days)

    expired: list[dict] = []
    expiring_soon: list[dict] = []
    by_date: dict[str, list[dict]] = defaultdict(list)

    for exc in exceptions:
        eu_raw = exc.get("effective_until", "")
        eu_clean = _strip_quotes(eu_raw) if eu_raw else ""
        try:
            eu_dt = datetime.fromisoformat(eu_clean.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        if eu_dt < now:
            expired.append(exc)
        elif eu_dt < soon_cutoff:
            expiring_soon.append(exc)
        else:
            date_key = _format_date(eu_raw)
            by_date[date_key].append(exc)

    def _sort_key(e: dict) -> tuple:
        return (_format_rule(e.get("rule", "")), _format_component(e))

    expired.sort(key=_sort_key)
    expiring_soon.sort(key=_sort_key)

    total = len(exceptions)
    active_count = total - len(expired) - len(expiring_soon)

    parts: list[str] = []
    env_label = environment.capitalize()
    parts.append(f"# RHOAI Conforma Exceptions — {env_label}")
    parts.append("")
    gen_time = now.strftime("%Y-%m-%d %H:%M UTC")
    files = ", ".join(_policy_file_link(f) for f in sorted(policy_files))
    parts.append(f"> Generated: {gen_time} | Policy files: {files}")
    parts.append("")
    parts.append(
        f"**Summary**: {total} total volatile exceptions — "
        f"{len(expired)} expired, "
        f"{len(expiring_soon)} expiring within {soon_days} days, "
        f"{active_count} active"
    )

    if expired:
        parts.append("")
        parts.append(f"## Expired ({len(expired)} — need cleanup or extension)")
        parts.append("")
        parts.append(_render_table(expired))

    if expiring_soon:
        parts.append("")
        parts.append(f"## Expiring within {soon_days} days ({len(expiring_soon)})")
        parts.append("")
        parts.append(_render_table(expiring_soon))

    for date_key in sorted(by_date.keys()):
        group = by_date[date_key]
        group.sort(key=_sort_key)
        parts.append("")
        parts.append(f"## Expiring {date_key} ({len(group)})")
        parts.append("")
        parts.append(_render_table(group))

    parts.append("")
    return "\n".join(parts)


# ── CLI ──────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=("List current RHOAI Conforma exceptions as formatted Markdown"))
    parser.add_argument(
        "--environment",
        default="prod",
        choices=["prod", "stage"],
        help="Target environment (default: prod)",
    )
    parser.add_argument(
        "--clone-dir",
        default=None,
        help="Path to existing konflux-release-data clone",
    )
    parser.add_argument(
        "--soon-days",
        type=int,
        default=_DEFAULT_SOON_DAYS,
        help=(f"Days threshold for the 'expiring soon' section (default: {_DEFAULT_SOON_DAYS})"),
    )
    args = parser.parse_args()

    clone_dir_arg = Path(args.clone_dir) if args.clone_dir else None

    try:
        repo_dir, is_temp = _clone_repo(clone_dir_arg)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        all_exceptions = scan_all_exceptions(repo_dir, args.environment)
        annotated = annotate_expiry(all_exceptions)
        policy_files = [str(p.relative_to(repo_dir)) for p in _get_policy_files(repo_dir, args.environment)]
        report = _render_report(annotated, args.environment, policy_files, args.soon_days)
        print(report)
        return 0
    finally:
        if is_temp:
            shutil.rmtree(repo_dir.parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
