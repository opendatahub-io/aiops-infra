#!/usr/bin/env python3
"""manage_exceptions — Manage conforma exceptions: find, assess, and search exceptions.

PUBLIC API:
    scan_all_exceptions(clone_dir, environment) -> list[dict]  [line 253]
    scan_permanent_exclusions(clone_dir, environment) -> list[dict]  [line 295]
    scan_self_service_exceptions(clone_dir, environment) -> list[dict]  [line 369]
    search_exceptions_for_components(search_terms, environment, clone_dir, refresh) -> dict  [line 438]
    filter_expired(exceptions) -> list[dict]  [line 594]
    annotate_expiry(exceptions) -> list[dict]  [line 614]
    assess_exception(exc, violations_by_rule, releases_checked, report_urls) -> dict  [line 731]
    cmd_find_expired(args) -> int  [line 823]
    cmd_assess_expired(args) -> int  [line 954]
    cmd_find_all(args) -> int  [line 959]
    cmd_assess_all(args) -> int  [line 1001]
    cmd_search_by_component(args) -> int  [line 1006]
    main() -> int  [line 1036]

INTERNAL SECTIONS:
    _QuotedStr: _quoted_str_representer, _safe_yaml_dump, _needs_quoting, _quote_strings_recursively, _strip_version_suffix, ... (+17 more)

DEPENDENCIES: argparse, conforma_context_ops, create_gitlab_mr, datetime, os, pathlib, re, shutil, subprocess, sys

"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import conforma_context_ops  # noqa: E402

import argparse
import os
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
    WORK_DIR,
    _find_existing_exceptions,
    _get_authenticated_repo_url,
    _run_git,
)

from exception_scanner import strip_version_suffix as _strip_version_suffix  # noqa: F401 — backward compat re-export
from exception_scanner import extract_image_base as _extract_image_base  # noqa: F401 — backward compat re-export
from exception_scanner import normalize_name as _normalize_name  # noqa: F401 — backward compat re-export
from exception_scanner import fuzzy_component_match as _fuzzy_component_match  # noqa: F401 — backward compat re-export
from exception_scanner import fuzzy_image_match as _fuzzy_image_match  # noqa: F401 — backward compat re-export
from exception_scanner import scan_all_exceptions  # noqa: F401 — backward compat re-export
from exception_scanner import scan_permanent_exclusions  # noqa: F401 — backward compat re-export
from exception_scanner import scan_self_service_exceptions  # noqa: F401 — backward compat re-export
from exception_scanner import search_exceptions_for_components  # noqa: F401 — backward compat re-export
from exception_scanner import filter_expired  # noqa: F401 — backward compat re-export
from exception_scanner import annotate_expiry  # noqa: F401 — backward compat re-export


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
# Fuzzy component name matching
# ---------------------------------------------------------------------------

_VERSION_SUFFIX_RE = re.compile(r"-v\d+-\d+(?:-[a-z]+-\d+)?$")


# ---------------------------------------------------------------------------
# Policy file scanning: wraps _find_existing_exceptions with extra fields
# ---------------------------------------------------------------------------


def _get_conforma_policy_dir() -> str:
    """Resolve the Conforma policy directory path at call time (not import time)."""
    domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    if domain:
        return f"config/{domain}/product/EnterpriseContractPolicy"
    return os.environ.get("KONFLUX_CONFORMA_POLICY_DIR", "")


def _get_application_slug() -> str:
    """Get the application slug from env, defaulting to 'rhoai'."""
    return os.environ.get("KONFLUX_APPLICATION_SLUG", "rhoai")


def _get_policy_files(clone_dir: Path, environment: str) -> list[Path]:
    """Get policy files for the configured product and environment."""
    conforma_dir = _get_conforma_policy_dir()
    if not conforma_dir:
        return []
    policy_dir = clone_dir / conforma_dir
    if not policy_dir.is_dir():
        return []
    app_slug = _get_application_slug()
    return sorted(p for p in policy_dir.glob(f"*{app_slug}*{environment}*.yaml") if p.is_file())


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


# ---------------------------------------------------------------------------
# Search exceptions by component name
# ---------------------------------------------------------------------------


def _volatile_to_result(exc: dict) -> dict:
    """Convert a volatile exception dict to a search result entry."""
    return {
        "file": exc["file"],
        "rule": exc["rule"],
        "type": "volatile",
        "component_names": exc.get("component_names", []),
        "image_url": exc.get("image_url", ""),
        "effective_until": exc.get("effective_until"),
        "reference": exc.get("reference"),
        "comment_header_lines": exc.get("comment_header_lines", []),
    }


def _parse_effective_until(exc: dict) -> datetime | None:
    """Parse the effectiveUntil field into a timezone-aware datetime."""
    eu = exc.get("effective_until")
    if not eu:
        return None
    try:
        return datetime.fromisoformat(eu.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Clone handling
# ---------------------------------------------------------------------------


def _clone_repo(clone_dir: Path | None) -> tuple[Path, bool]:
    """Clone konflux-release-data into ~/.conforma/, or fetch-and-reset an existing ~/.conforma/ clone.

    Policy: never silently reuse a stale clone.  If *clone_dir* points to an
    existing checkout we **always** ``git fetch`` first; if the fetch fails the
    remote is unreachable and we abort rather than use stale data.

    Returns (repo_dir, is_temp) where is_temp indicates whether caller
    should clean up.
    """
    conforma_policy_dir = _get_conforma_policy_dir()
    if clone_dir and clone_dir.is_dir():
        repo_dir = clone_dir
        if conforma_policy_dir and not (clone_dir / conforma_policy_dir).is_dir():
            alt = clone_dir / "repo"
            if conforma_policy_dir and (alt / conforma_policy_dir).is_dir():
                repo_dir = alt
            else:
                repo_dir = None

        if repo_dir is not None:
            _refresh_clone(repo_dir)
            return repo_dir, False

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="conforma-exception-manage-", dir=WORK_DIR))
    dest = workdir / "repo"
    repo_url = _get_authenticated_repo_url()

    policy_parent = str(Path(conforma_policy_dir).parent) if conforma_policy_dir else ""
    sparse_paths = [p for p in [policy_parent, "exceptions"] if p]
    _run_git(
        [
            "git",
            "clone",
            "--depth=1",
            "--branch",
            DEFAULT_BRANCH,
            "--filter=blob:none",
            "--sparse",
            repo_url,
            str(dest),
        ],
        timeout=300,
    )
    if sparse_paths:
        _run_git(["git", "sparse-checkout", "set", *sparse_paths], cwd=dest)

    return dest, True


def _refresh_clone(clone_dir: Path) -> None:
    """Fetch latest main and hard-reset an existing clone."""
    _run_git(["git", "fetch", "origin", DEFAULT_BRANCH], cwd=clone_dir, timeout=120)
    _run_git(["git", "reset", "--hard", f"origin/{DEFAULT_BRANCH}"], cwd=clone_dir, timeout=30)


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


def _match_rule_in_violations(rule: str, violations_by_rule: dict) -> tuple[str, dict | None]:
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
    result["recommended_action"] = _recommend_action(classification, exc["is_unscoped"], is_expired)

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
                "total_with_component_names": sum(1 for e in expired if e["has_component_names"]),
                "total_unscoped": sum(1 for e in expired if e["is_unscoped"]),
            },
        }

        now_str = output["generated_at"]
        comment = f"# Expired exceptions report\n# Generated: {now_str}\n# Environment: {args.environment}"
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
            assessed.append(assess_exception(exc, violations_by_rule, releases_checked, report_urls))

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
                "total_with_component_names": sum(1 for e in annotated if e["has_component_names"]),
                "total_unscoped": sum(1 for e in annotated if e["is_unscoped"]),
            },
        }

        now_str = output["generated_at"]
        comment = (
            f"# All exceptions report (expired + active)\n# Generated: {now_str}\n# Environment: {args.environment}"
        )
        print(_safe_yaml_dump(output, comment))
        return 0

    finally:
        if is_temp:
            shutil.rmtree(repo_dir.parent, ignore_errors=True)


def cmd_assess_all(args: argparse.Namespace) -> int:
    """Assess all exceptions (expired + active) against violations data."""
    return _cmd_assess(args, expired_only=False)


def cmd_search_by_component(args: argparse.Namespace) -> int:
    """Search for exceptions covering given component(s)."""
    import json as _json

    clone_dir_arg = Path(args.clone_dir) if args.clone_dir else None
    no_refresh = getattr(args, "no_refresh", False)

    try:
        result = search_exceptions_for_components(
            search_terms=args.components,
            clone_dir=clone_dir_arg,
            environment=args.environment,
            refresh=not no_refresh,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Error accessing repo: {exc.stderr or exc.stdout}", file=sys.stderr)
        return 1

    print(_json.dumps(result, indent=2, default=str))

    summary = result["summary"]
    print(
        f"\nFound {summary['total_matches']} exception(s) for {result['search_terms']}: "
        f"{summary['volatile']} volatile, {summary['permanent']} permanent, "
        f"{summary['self_service']} self-service",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage conforma exceptions: find, assess, and search")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
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
    group.add_argument(
        "--search-by-component",
        action="store_true",
        help="Search for exceptions covering given component name(s) (fuzzy matching)",
    )

    parser.add_argument(
        "--components",
        nargs="+",
        default=None,
        help="Component names to search for (required for --search-by-component)",
    )
    parser.add_argument(
        "--violations-input",
        default=None,
        help="Path to violations YAML from conforma-analyze (required for --assess-*)",
    )
    parser.add_argument(
        "--environment",
        default=None,
        choices=["prod", "stage"],
        help="Target environment (auto-discovered from run context if omitted)",
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
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        default=False,
        help="Skip git fetch+reset before searching (--search-by-component only)",
    )

    args = parser.parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    args.environment = conforma_context_ops.resolve_arg(args, "environment", context, "environment")

    if args.clone_dir is None and context:
        args.clone_dir = str(conforma_context_ops.discover_work_dir() / "konflux-release-data")

    if (args.assess_expired or args.assess_all) and not args.violations_input:
        parser.error("--violations-input is required when using --assess-expired or --assess-all")

    if args.search_by_component and not args.components:
        parser.error("--components is required when using --search-by-component")

    if args.find_expired:
        return cmd_find_expired(args)
    elif args.find_all:
        return cmd_find_all(args)
    elif args.assess_expired:
        return cmd_assess_expired(args)
    elif args.search_by_component:
        return cmd_search_by_component(args)
    else:
        return cmd_assess_all(args)


if __name__ == "__main__":
    sys.exit(main())
