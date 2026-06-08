#!/usr/bin/env python3
"""Manage conforma exceptions: find and assess exceptions.

Four modes:
  --find-expired    List expired exceptions from policy files (stdout)
  --find-all        List all exceptions (expired + active) from policy files
  --assess-expired  Cross-reference expired exceptions against violations
  --assess-all      Cross-reference all exceptions against violations

Usage:
  # List expired exceptions (stdout)
  python3 scripts/manage_exceptions.py --find-expired --environment prod

  # List all exceptions (expired + active)
  python3 scripts/manage_exceptions.py --find-all --environment prod

  # Assess expired exceptions against violations data
  python3 scripts/manage_exceptions.py --assess-expired \\
    --violations-input .work/conforma-violations.yaml \\
    --environment prod \\
    --output .work/assessed-exceptions.yaml

  # Assess all exceptions (expired + active)
  python3 scripts/manage_exceptions.py --assess-all \\
    --violations-input .work/conforma-violations.yaml \\
    --environment prod \\
    --output .work/assessed-exceptions.yaml
"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

from create_gitlab_mr import (
    DEFAULT_BRANCH,
    POLICY_PATHS,
    WORK_DIR,
    _find_existing_exceptions,
    _get_authenticated_repo_url,
    _run_git,
)


# ---------------------------------------------------------------------------
# Defensive YAML serialization (self-contained copy, no cross-skill imports)
# ---------------------------------------------------------------------------

class _QuotedStr(str):
    """String subclass that forces YAML double-quoting."""


def _quoted_str_representer(dumper: yaml.Dumper, data: _QuotedStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def _safe_yaml_dump(data: dict, comment_header: str = "") -> str:
    """Dump data to YAML with defensive quoting."""
    safe_data = _quote_strings_recursively(data)

    dumper = yaml.Dumper
    dumper.add_representer(_QuotedStr, _quoted_str_representer)

    body = yaml.dump(
        safe_data,
        Dumper=dumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=200,
    )

    if comment_header:
        return comment_header.rstrip("\n") + "\n\n" + body
    return body


def _needs_quoting(value: str) -> bool:
    if not value:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return True
    if ":" in value:
        return True
    if value.startswith("http://") or value.startswith("https://"):
        return True
    if value.startswith("#"):
        return True
    if value.lower() in ("true", "false", "yes", "no", "null", "on", "off"):
        return True
    return False


def _quote_strings_recursively(obj):
    if isinstance(obj, str):
        if _needs_quoting(obj):
            return _QuotedStr(obj)
        return obj
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            safe_key = _QuotedStr(k) if isinstance(k, str) and _needs_quoting(k) else k
            result[safe_key] = _quote_strings_recursively(v)
        return result
    if isinstance(obj, list):
        return [_quote_strings_recursively(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Policy file scanning: wraps _find_existing_exceptions with extra fields
# ---------------------------------------------------------------------------

_EC_POLICY_DIR = "config/stone-prod-p02.hjvn.p1/product/EnterpriseContractPolicy"


def _get_policy_files(clone_dir: Path, environment: str) -> list[Path]:
    """Get all RHOAI policy files for the given environment."""
    policy_dir = clone_dir / _EC_POLICY_DIR
    if not policy_dir.is_dir():
        return []
    return sorted(
        p for p in policy_dir.glob(f"*rhoai*{environment}*.yaml")
        if p.is_file()
    )


def _extract_comment_header(lines: list[str], block_start: int, indent: str) -> list[str]:
    """Scan backwards from block_start to find the preceding comment header."""
    header_lines: list[str] = []
    i = block_start - 1
    while i >= 0:
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("#") and line.startswith(indent):
            header_lines.insert(0, stripped)
            i -= 1
        else:
            break
    return header_lines


def _extract_reference(lines: list[str], block_start: int, block_end: int) -> str | None:
    """Extract the reference URL from within the exception block."""
    for i in range(block_start, block_end):
        line = lines[i]
        ref_match = re.search(r"reference:\s*(\S+)", line)
        if ref_match:
            return ref_match.group(1)
    return None


def scan_all_exceptions(
    clone_dir: Path, environment: str
) -> list[dict]:
    """Scan all policy files for exception blocks, returning enriched metadata."""
    policy_files = _get_policy_files(clone_dir, environment)
    all_exceptions: list[dict] = []
    indent = "          "

    for policy_file in policy_files:
        content = policy_file.read_text(encoding="utf-8")
        lines = content.split("\n")
        rel_path = str(policy_file.relative_to(clone_dir))

        all_rules = set()
        for line in lines:
            m = re.match(rf"^{re.escape(indent)}- value:\s*(.+)$", line)
            if m:
                all_rules.add(m.group(1).strip())

        for rule in all_rules:
            blocks = _find_existing_exceptions(content, rule, indent)
            for block in blocks:
                comment_header = _extract_comment_header(lines, block["start"], indent)
                reference = _extract_reference(lines, block["start"], block["end"])

                exc_entry: dict = {
                    "file": rel_path,
                    "rule": rule,
                    "has_component_names": block["has_component_names"],
                    "component_names": block["component_names"],
                    "effective_until": block["effective_until_value"],
                    "reference": reference,
                    "comment_header_lines": comment_header,
                    "block_start_line": block["start"],
                    "block_end_line": block["end"],
                    "is_unscoped": not block["has_component_names"],
                }
                if block.get("image_url"):
                    exc_entry["image_url"] = block["image_url"]
                all_exceptions.append(exc_entry)

    return all_exceptions


def _parse_effective_until(exc: dict) -> datetime | None:
    """Parse the effectiveUntil field into a timezone-aware datetime."""
    eu = exc.get("effective_until")
    if not eu:
        return None
    try:
        return datetime.fromisoformat(eu.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def filter_expired(exceptions: list[dict]) -> list[dict]:
    """Filter to only expired exceptions (effectiveUntil < now)."""
    now = datetime.now(timezone.utc)
    expired = []

    for exc in exceptions:
        eu_dt = _parse_effective_until(exc)
        if eu_dt is None:
            continue

        if eu_dt < now:
            exc_copy = dict(exc)
            exc_copy["is_expired"] = True
            exc_copy["expired_days_ago"] = (now - eu_dt).days
            expired.append(exc_copy)

    expired.sort(key=lambda e: e.get("effective_until", ""))
    return expired


def annotate_expiry(exceptions: list[dict]) -> list[dict]:
    """Add expiry metadata to all exceptions without filtering."""
    now = datetime.now(timezone.utc)
    annotated = []

    for exc in exceptions:
        eu_dt = _parse_effective_until(exc)
        if eu_dt is None:
            continue

        exc_copy = dict(exc)
        if eu_dt < now:
            exc_copy["is_expired"] = True
            exc_copy["expired_days_ago"] = (now - eu_dt).days
        else:
            exc_copy["is_expired"] = False
            exc_copy["expires_in_days"] = (eu_dt - now).days

        annotated.append(exc_copy)

    annotated.sort(key=lambda e: e.get("effective_until", ""))
    return annotated


# ---------------------------------------------------------------------------
# Clone handling
# ---------------------------------------------------------------------------

def _clone_repo(clone_dir: Path | None) -> tuple[Path, bool]:
    """Clone konflux-release-data or use existing clone.

    Returns (repo_dir, is_temp) where is_temp indicates whether caller
    should clean up.
    """
    if clone_dir and clone_dir.is_dir():
        ec_dir = clone_dir / _EC_POLICY_DIR
        if ec_dir.is_dir():
            return clone_dir, False
        alt = clone_dir / "repo"
        if (alt / _EC_POLICY_DIR).is_dir():
            return alt, False

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="conforma-exception-manage-", dir=WORK_DIR))
    dest = workdir / "repo"
    repo_url = _get_authenticated_repo_url()

    policy_dir = str(Path(_EC_POLICY_DIR).parent)
    _run_git(
        ["git", "clone", "--depth=1", "--branch", DEFAULT_BRANCH,
         "--filter=blob:none", "--sparse", repo_url, str(dest)],
        timeout=300,
    )
    _run_git(["git", "sparse-checkout", "set", policy_dir], cwd=dest)

    return dest, True


# ---------------------------------------------------------------------------
# Assessment logic
# ---------------------------------------------------------------------------

def _load_violations(violations_path: Path) -> dict:
    """Load the violations YAML produced by conforma-analyze."""
    with open(violations_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and "violation_data" in data:
        return data["violation_data"]
    return data


def _match_rule_in_violations(
    rule: str, violations_by_rule: dict
) -> tuple[str, dict | None]:
    """Match an exception rule against the violations index.

    Returns (match_type, violations_entry) where match_type is
    "exact", "prefix", or "none".
    """
    if rule in violations_by_rule:
        return "exact", violations_by_rule[rule]

    base = rule.split(":")[0] if ":" in rule else rule
    for viol_rule, entry in violations_by_rule.items():
        if entry.get("base_code") == base or viol_rule.startswith(base + ":"):
            return "prefix", entry

    return "none", None


def assess_exception(
    exc: dict,
    violations_by_rule: dict,
    releases_checked: list[str],
    report_urls: dict[str, str] | None = None,
) -> dict:
    """Classify a single exception against violations data."""
    result = dict(exc)
    rule = exc["rule"]
    is_expired = exc.get("is_expired", True)

    match_type, viol_entry = _match_rule_in_violations(rule, violations_by_rule)
    result["match_type"] = match_type

    urls = report_urls or {}

    if match_type == "none" or viol_entry is None:
        result["classification"] = "no_longer_needed"
        result["evidence"] = {
            "still_violating_releases": [],
            "still_violating_components": [],
            "resolved_in_releases": list(releases_checked),
            "report_urls": {r: urls.get(r, "") for r in releases_checked if urls.get(r)},
        }
        result["recommended_action"] = "remove"
        return result

    viol_releases = viol_entry.get("releases", {})
    still_violating_releases = []
    still_violating_components: set[str] = set()
    resolved_releases = []

    if exc["has_component_names"]:
        exc_components = set(exc["component_names"])
        for release in releases_checked:
            release_components = set(viol_releases.get(release, []))
            overlap = exc_components & release_components
            if overlap:
                still_violating_releases.append(release)
                still_violating_components.update(overlap)
            else:
                resolved_releases.append(release)

        if still_violating_components == exc_components:
            classification = "still_needed"
        elif still_violating_components:
            classification = "partially_needed"
        else:
            classification = "no_longer_needed"
    else:
        for release in releases_checked:
            release_components = viol_releases.get(release, [])
            if release_components:
                still_violating_releases.append(release)
                still_violating_components.update(release_components)
            else:
                resolved_releases.append(release)

        classification = "still_needed" if still_violating_components else "no_longer_needed"

    result["classification"] = classification
    result["evidence"] = {
        "still_violating_releases": still_violating_releases,
        "still_violating_components": sorted(still_violating_components),
        "resolved_in_releases": resolved_releases,
        "report_urls": {r: urls.get(r, "") for r in still_violating_releases if urls.get(r)},
    }
    result["recommended_action"] = _recommend_action(
        classification, exc["is_unscoped"], is_expired
    )

    return result


def _recommend_action(classification: str, is_unscoped: bool, is_expired: bool = True) -> str:
    """Deterministic recommendation based on classification, scoping (componentNames vs not), and expiry."""
    if classification == "no_longer_needed":
        return "remove"
    if classification == "still_needed":
        if not is_expired:
            return "keep"
        return "extend_and_modernize" if is_unscoped else "extend"
    if classification == "partially_needed":
        if not is_expired:
            return "modernize_and_narrow" if is_unscoped else "narrow"
        return "modernize_and_narrow" if is_unscoped else "narrow_and_extend"
    return "review"


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

def cmd_find_expired(args: argparse.Namespace) -> int:
    """List all expired exceptions to stdout."""
    clone_dir_arg = Path(args.clone_dir) if args.clone_dir else None

    try:
        repo_dir, is_temp = _clone_repo(clone_dir_arg)
    except subprocess.CalledProcessError as exc:
        print(f"Error cloning repo: {exc.stderr or exc.stdout}", file=sys.stderr)
        return 1

    try:
        all_exceptions = scan_all_exceptions(repo_dir, args.environment)
        expired = filter_expired(all_exceptions)

        output = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expired_exceptions": expired,
            "summary": {
                "total_expired": len(expired),
                "total_with_component_names": sum(
                    1 for e in expired if e["has_component_names"]
                ),
                "total_unscoped": sum(1 for e in expired if e["is_unscoped"]),
            },
        }

        now_str = output["generated_at"]
        comment = (
            f"# Expired exceptions report\n"
            f"# Generated: {now_str}\n"
            f"# Environment: {args.environment}"
        )
        print(_safe_yaml_dump(output, comment))
        return 0

    finally:
        if is_temp:
            shutil.rmtree(repo_dir.parent, ignore_errors=True)


def _cmd_assess(args: argparse.Namespace, *, expired_only: bool) -> int:
    """Shared implementation for --assess-expired and --assess-all."""
    violations_path = Path(args.violations_input)
    if not violations_path.is_file():
        print(
            f"Error: violations file not found: {violations_path}",
            file=sys.stderr,
        )
        return 1

    violations = _load_violations(violations_path)
    violations_by_rule = violations.get("violations_by_rule", {})
    releases_checked = violations.get("releases", [])
    report_urls = violations.get("report_urls", {})
    report_created_at = violations.get("report_created_at", {})
    failed_releases = violations.get("failed_releases", [])

    clone_dir_arg = Path(args.clone_dir) if args.clone_dir else None

    try:
        repo_dir, is_temp = _clone_repo(clone_dir_arg)
    except subprocess.CalledProcessError as exc:
        print(f"Error cloning repo: {exc.stderr or exc.stdout}", file=sys.stderr)
        return 1

    try:
        all_exceptions = scan_all_exceptions(repo_dir, args.environment)
        if expired_only:
            target = filter_expired(all_exceptions)
        else:
            target = annotate_expiry(all_exceptions)

        assessed = []
        for exc in target:
            assessed.append(
                assess_exception(exc, violations_by_rule, releases_checked, report_urls)
            )

        total_expired = sum(1 for a in assessed if a.get("is_expired", True))
        total_active = sum(1 for a in assessed if not a.get("is_expired", True))
        still_needed = sum(1 for a in assessed if a["classification"] == "still_needed")
        no_longer = sum(1 for a in assessed if a["classification"] == "no_longer_needed")
        partial = sum(1 for a in assessed if a["classification"] == "partially_needed")

        summary: dict = {
            "total": len(assessed),
            "total_expired": total_expired,
            "still_needed": still_needed,
            "no_longer_needed": no_longer,
            "partially_needed": partial,
        }
        if not expired_only:
            summary["total_active"] = total_active

        scope = "expired" if expired_only else "all"
        output: dict = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": scope,
            "violations_source": str(violations_path),
            "releases_checked": releases_checked,
            "releases_not_checked": failed_releases,
            "assessed_exceptions": assessed,
            "summary": summary,
        }
        if report_created_at:
            output["report_created_at"] = report_created_at

        now_str = output["generated_at"]
        label = "Assessed expired exceptions" if expired_only else "Assessed all exceptions"
        comment = (
            f"# {label} report\n"
            f"# Generated: {now_str}\n"
            f"# Violations source: {violations_path}\n"
            f"# Releases checked: {', '.join(releases_checked)}"
        )
        yaml_output = _safe_yaml_dump(output, comment)

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(yaml_output, encoding="utf-8")
            print(f"Wrote assessed exceptions to {out_path}", file=sys.stderr)
        else:
            print(yaml_output)

        scope_label = "expired exceptions" if expired_only else "exceptions (expired + active)"
        print(
            f"\nSummary: {len(assessed)} {scope_label} — "
            f"{still_needed} still needed, {no_longer} no longer needed, "
            f"{partial} partially needed",
            file=sys.stderr,
        )
        return 0

    finally:
        if is_temp:
            shutil.rmtree(repo_dir.parent, ignore_errors=True)


def cmd_assess_expired(args: argparse.Namespace) -> int:
    """Assess expired exceptions against violations data."""
    return _cmd_assess(args, expired_only=True)


def cmd_find_all(args: argparse.Namespace) -> int:
    """List all exceptions (expired + active) to stdout."""
    clone_dir_arg = Path(args.clone_dir) if args.clone_dir else None

    try:
        repo_dir, is_temp = _clone_repo(clone_dir_arg)
    except subprocess.CalledProcessError as exc:
        print(f"Error cloning repo: {exc.stderr or exc.stdout}", file=sys.stderr)
        return 1

    try:
        all_exceptions = scan_all_exceptions(repo_dir, args.environment)
        annotated = annotate_expiry(all_exceptions)

        total_expired = sum(1 for e in annotated if e.get("is_expired"))
        total_active = sum(1 for e in annotated if not e.get("is_expired"))

        output = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scope": "all",
            "exceptions": annotated,
            "summary": {
                "total": len(annotated),
                "total_expired": total_expired,
                "total_active": total_active,
                "total_with_component_names": sum(
                    1 for e in annotated if e["has_component_names"]
                ),
                "total_unscoped": sum(1 for e in annotated if e["is_unscoped"]),
            },
        }

        now_str = output["generated_at"]
        comment = (
            f"# All exceptions report (expired + active)\n"
            f"# Generated: {now_str}\n"
            f"# Environment: {args.environment}"
        )
        print(_safe_yaml_dump(output, comment))
        return 0

    finally:
        if is_temp:
            shutil.rmtree(repo_dir.parent, ignore_errors=True)


def cmd_assess_all(args: argparse.Namespace) -> int:
    """Assess all exceptions (expired + active) against violations data."""
    return _cmd_assess(args, expired_only=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage conforma exceptions: find and assess"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--find-expired",
        action="store_true",
        help="List expired exceptions from policy files (stdout)",
    )
    group.add_argument(
        "--find-all",
        action="store_true",
        help="List all exceptions (expired + active) from policy files (stdout)",
    )
    group.add_argument(
        "--assess-expired",
        action="store_true",
        help="Assess expired exceptions against violations data",
    )
    group.add_argument(
        "--assess-all",
        action="store_true",
        help="Assess all exceptions (expired + active) against violations data",
    )

    parser.add_argument(
        "--violations-input",
        default=None,
        help="Path to violations YAML from conforma-analyze (required for --assess-*)",
    )
    parser.add_argument(
        "--environment",
        default="prod",
        choices=["prod", "stage"],
        help="Target environment (default: prod)",
    )
    parser.add_argument(
        "--clone-dir",
        default=None,
        help="Path to existing konflux-release-data clone (clones internally if omitted)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write assessed output to file (--assess-* only; default: stdout)",
    )

    args = parser.parse_args()

    if (args.assess_expired or args.assess_all) and not args.violations_input:
        parser.error("--violations-input is required when using --assess-expired or --assess-all")

    if args.find_expired:
        return cmd_find_expired(args)
    elif args.find_all:
        return cmd_find_all(args)
    elif args.assess_expired:
        return cmd_assess_expired(args)
    else:
        return cmd_assess_all(args)


if __name__ == "__main__":
    sys.exit(main())
