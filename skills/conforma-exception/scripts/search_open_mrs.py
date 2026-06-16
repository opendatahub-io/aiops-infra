#!/usr/bin/env python3
"""Search for open conforma exception Merge Requests in konflux-release-data.

Usage:
    # All open conforma exception MRs (broad search):
    python3 skills/conforma-exception/scripts/search_open_mrs.py

    # Filter by rule code (prefix or full):
    python3 skills/conforma-exception/scripts/search_open_mrs.py --rule rpm_signature
    python3 skills/conforma-exception/scripts/search_open_mrs.py --rule rpm_signature.allowed:9386b48a

    # Filter by RHOAI version:
    python3 skills/conforma-exception/scripts/search_open_mrs.py --version rhoai-3.4

    # Combine filters:
    python3 skills/conforma-exception/scripts/search_open_mrs.py --rule rpm_signature --version 3.4

    # Output formats:
    python3 skills/conforma-exception/scripts/search_open_mrs.py --format json
    python3 skills/conforma-exception/scripts/search_open_mrs.py --format markdown
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import sys
from pathlib import Path

# Skill-local cli_runner must shadow repo-root cli_runner (different module,
# same name).  _setup_env inserts repo-root scripts/ at sys.path[0]; move the
# skill scripts dir ahead so the lazy ``from cli_runner import _resolve_env``
# inside preflight_check resolves to the skill-local version.
_SKILL_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SKILL_SCRIPTS_DIR in sys.path:
    sys.path.remove(_SKILL_SCRIPTS_DIR)
sys.path.insert(0, _SKILL_SCRIPTS_DIR)

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from typing import Optional  # noqa: E402

from conforma_mr_ops import _glab_get_mrs  # noqa: E402

_TITLE_RE = re.compile(
    r"^\[(?P<vendor>[^\]]*)\]\s*\[RHOAI\]\s*Conforma exception:\s*"
    r"(?P<rule>\S+)\s+for\s+(?P<versions>.+)$"
)

_BROAD_SEARCH_TERMS = ["Conforma exception", "conforma exception"]


def _normalize_author(author_field) -> str:
    if isinstance(author_field, dict):
        return author_field.get("username", "")
    if isinstance(author_field, str):
        return author_field
    return ""


def _normalize_mr(mr: dict) -> dict:
    """Normalize MR dict from either python-gitlab or raw API format."""
    return {
        "iid": mr.get("iid"),
        "title": mr.get("title", ""),
        "url": mr.get("web_url", mr.get("url", "")),
        "author": _normalize_author(mr.get("author", "")),
        "created_at": mr.get("created_at", ""),
        "labels": mr.get("labels", []),
        "source_branch": mr.get("source_branch", ""),
        "target_branch": mr.get("target_branch", ""),
    }


def _parse_title(title: str) -> dict:
    """Extract structured fields from a standard conforma exception MR title.

    Standard format:
        [Vendor] [RHOAI] Conforma exception: rule.code for rhoai-X.Y, rhoai-A.B
    """
    m = _TITLE_RE.match(title)
    if m:
        return {
            "vendor": m.group("vendor"),
            "rule": m.group("rule"),
            "versions": [v.strip() for v in m.group("versions").split(",")],
        }
    return {}


def _fetch_mrs(
    rule: Optional[str] = None,
) -> list[dict]:
    """Fetch open MRs from GitLab, optionally scoped to a rule."""
    raw: list[dict] = []
    seen: set[int] = set()

    def _collect(search_term: str) -> None:
        for mr in _glab_get_mrs(search_term):
            iid = mr.get("iid")
            if iid and iid not in seen:
                seen.add(iid)
                raw.append(mr)

    if rule:
        term = rule[:60] if len(rule) > 60 else rule
        _collect(term)
        if ":" in rule:
            suffix = rule.rsplit(":", 1)[1]
            if suffix and suffix != term:
                _collect(suffix)
        base = rule.split(":")[0]
        if "." in base:
            prefix = base.split(".")[0]
            if prefix != term:
                _collect(prefix)
    else:
        for term in _BROAD_SEARCH_TERMS:
            _collect(term)

    return raw


def search(
    rule: Optional[str] = None,
    version: Optional[str] = None,
    author: Optional[str] = None,
) -> list[dict]:
    """Search and filter open conforma exception MRs."""
    raw = _fetch_mrs(rule=rule)
    mrs = [_normalize_mr(mr) for mr in raw]

    for mr in mrs:
        mr["parsed"] = _parse_title(mr["title"])

    if version:
        v = version if version.startswith("rhoai-") else f"rhoai-{version}"
        mrs = [mr for mr in mrs if v in mr["title"] or v in mr.get("parsed", {}).get("versions", [])]

    if author:
        mrs = [mr for mr in mrs if mr["author"] == author]

    mrs.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return mrs


def format_text(
    mrs: list[dict],
    rule: Optional[str],
    version: Optional[str],
    author: Optional[str],
) -> str:
    filters = []
    if rule:
        filters.append(f"rule={rule}")
    if version:
        filters.append(f"version={version}")
    if author:
        filters.append(f"author={author}")
    suffix = f" ({', '.join(filters)})" if filters else ""

    if not mrs:
        return f"No open conforma exception MRs found{suffix}."

    lines = [f"Found {len(mrs)} open conforma exception MR(s){suffix}:", ""]
    for mr in mrs:
        p = mr.get("parsed", {})
        lines.append(f"  !{mr['iid']}  {mr['author']}  {mr['created_at'][:10]}")
        lines.append(f"    {mr['title']}")
        lines.append(f"    {mr['url']}")
        if p.get("vendor"):
            lines.append(f"    Vendor: {p['vendor']}")
        if p.get("rule"):
            lines.append(f"    Rule:   {p['rule']}")
        if p.get("versions"):
            lines.append(f"    Versions: {', '.join(p['versions'])}")
        lines.append("")

    return "\n".join(lines)


def format_markdown(mrs: list[dict]) -> str:
    if not mrs:
        return "No open conforma exception MRs found."

    lines = [
        "| MR | Rule | Vendor | Versions | Author | Created |",
        "|---|---|---|---|---|---|",
    ]
    for mr in mrs:
        p = mr.get("parsed", {})
        rule = f"`{p['rule']}`" if p.get("rule") else mr["title"][:60]
        vendor = p.get("vendor", "\u2014")
        versions = ", ".join(p.get("versions", ["\u2014"]))
        lines.append(
            f"| [!{mr['iid']}]({mr['url']}) "
            f"| {rule} | {vendor} | {versions} "
            f"| {mr['author']} | {mr['created_at'][:10]} |"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Search for open conforma exception MRs in konflux-release-data (GitLab)")
    )
    parser.add_argument(
        "--rule",
        default=None,
        help=(
            "Filter by rule code or prefix "
            "(e.g. 'rpm_signature', 'hermetic_task.hermetic', "
            "'rpm_signature.allowed:9386b48a')"
        ),
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Filter by RHOAI version (e.g. 'rhoai-3.4' or '3.4')",
    )
    parser.add_argument(
        "--author",
        default=None,
        help="Filter by MR author GitLab username",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        dest="fmt",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    mrs = search(rule=args.rule, version=args.version, author=args.author)

    if args.fmt == "json":
        print(
            json.dumps(
                {
                    "filters": {
                        "rule": args.rule,
                        "version": args.version,
                        "author": args.author,
                    },
                    "count": len(mrs),
                    "merge_requests": mrs,
                },
                indent=2,
            )
        )
    elif args.fmt == "markdown":
        print(format_markdown(mrs))
    else:
        print(format_text(mrs, args.rule, args.version, args.author))

    return 0


if __name__ == "__main__":
    sys.exit(main())
