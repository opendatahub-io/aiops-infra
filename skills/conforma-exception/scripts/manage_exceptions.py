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


def _strip_version_suffix(name: str) -> str:
    """Strip Konflux version suffix from a component name.

    odh-dashboard-v3-4       -> odh-dashboard
    odh-mlflow-v3-3          -> odh-mlflow
    odh-vllm-cpu-v3-5-ea-1   -> odh-vllm-cpu
    """
    return _VERSION_SUFFIX_RE.sub("", name)


def _extract_image_base(image_url: str) -> str:
    """Extract the base name from an image URL (strip registry path and -rhel9/-ubi9).

    quay.io/rhoai/odh-dashboard-rhel9       -> odh-dashboard
    quay.io/rhoai/odh-mlmd-grpc-server-rhel9 -> odh-mlmd-grpc-server
    """
    name = image_url.rsplit("/", 1)[-1]
    name = re.sub(r"-rhel\d+$", "", name)
    name = re.sub(r"-ubi\d+$", "", name)
    return name


def _normalize_name(name: str) -> str:
    """Normalize a name for fuzzy comparison by stripping hyphens/underscores and lowercasing."""
    return re.sub(r"[-_]", "", name).lower()


def _fuzzy_component_match(search_term: str, component_name: str) -> bool:
    """Check if search_term fuzzy-matches component_name.

    Handles underscore vs hyphen, missing separators, version suffixes,
    and odh-/rhoai- prefixes.

    >>> _fuzzy_component_match("mlflow", "odh-mlflow-v3-3")
    True
    >>> _fuzzy_component_match("nemo-guardrails", "odh-nemo_guardrails-v3-5-ea-1")
    True
    >>> _fuzzy_component_match("nemoguardrails", "odh-nemo-guardrails-v3-4")
    True
    """
    base = _strip_version_suffix(component_name)
    norm_search = _normalize_name(_strip_version_suffix(search_term))
    norm_base = _normalize_name(base)

    if norm_search == norm_base or norm_search in norm_base:
        return True

    for prefix in ("odh", "rhoai"):
        if norm_base.startswith(prefix):
            stripped = norm_base[len(prefix) :]
            if norm_search == stripped or norm_search in stripped:
                return True

    return False


def _fuzzy_image_match(search_term: str, image_url: str) -> bool:
    """Check if search_term fuzzy-matches an imageUrl/imageRef base name."""
    base = _extract_image_base(image_url)
    return _fuzzy_component_match(search_term, base)


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


def scan_all_exceptions(clone_dir: Path, environment: str) -> list[dict]:
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


def scan_permanent_exclusions(clone_dir: Path, environment: str) -> list[dict]:
    """Scan policy files for permanent exclusions under config.exclude.

    These are simple rule-name strings (no componentNames, no effectiveUntil)
    that apply to ALL components permanently.
    """
    policy_files = _get_policy_files(clone_dir, environment)
    results: list[dict] = []

    for policy_file in policy_files:
        content = policy_file.read_text(encoding="utf-8")
        rel_path = str(policy_file.relative_to(clone_dir))
        lines = content.split("\n")

        in_config_exclude = False
        in_config_section = False
        config_indent = ""
        preceding_comments: list[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()

            if re.match(r"^\s+volatileConfig:\s*$", line):
                in_config_section = False
                in_config_exclude = False
                config_indent = ""
                continue

            if re.match(r"^\s+config:\s*$", line):
                config_indent = line[: len(line) - len(line.lstrip())]
                in_config_section = True
                continue

            exclude_match = re.match(r"^(\s+)exclude:\s*$", line)
            if exclude_match and in_config_section and config_indent:
                indent_depth = len(exclude_match.group(1))
                config_depth = len(config_indent)
                if indent_depth > config_depth:
                    in_config_exclude = True
                    preceding_comments = []
                    continue

            if in_config_exclude:
                if not stripped or (not stripped.startswith("-") and not stripped.startswith("#")):
                    in_config_exclude = False
                    preceding_comments = []
                    continue
                if stripped.startswith("#"):
                    preceding_comments.append(stripped)
                    continue
                if stripped.startswith("- "):
                    rule = stripped[2:].strip().strip('"').strip("'")
                    reference = None
                    for comment in preceding_comments:
                        url_match = re.search(r"https?://\S+", comment)
                        if url_match:
                            reference = url_match.group(0)
                    results.append(
                        {
                            "file": rel_path,
                            "rule": rule,
                            "type": "permanent",
                            "scope": "permanent",
                            "component_names": [],
                            "effective_until": None,
                            "reference": reference,
                            "comment_header_lines": list(preceding_comments),
                            "line": i + 1,
                        }
                    )
                    preceding_comments = []

    return results


def scan_self_service_exceptions(clone_dir: Path, environment: str) -> list[dict]:
    """Scan the self-service exceptions/ directory for RHOAI exception entries.

    These files use a flat YAML list format and may use either imageUrl or imageRef.
    """
    exceptions_dir = clone_dir / "exceptions"
    if not exceptions_dir.is_dir():
        return []

    results: list[dict] = []
    app_slug = _get_application_slug()
    for yaml_file in sorted(exceptions_dir.glob(f"*{app_slug}*{environment}*.yaml")):
        if not yaml_file.is_file():
            continue
        rel_path = str(yaml_file.relative_to(clone_dir))
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if not isinstance(data, list):
            continue

        for entry in data:
            if not isinstance(entry, dict):
                continue
            rule = entry.get("value", "")
            if not rule:
                continue

            component_names = entry.get("componentNames", [])
            image_url = entry.get("imageUrl") or entry.get("imageRef") or ""
            effective_until = entry.get("effectiveUntil")
            reference = entry.get("reference")

            if isinstance(effective_until, str):
                effective_until = effective_until.strip('"').strip("'")

            has_components = bool(component_names)
            has_image = bool(image_url) and not image_url.startswith("sha256:")

            if has_components:
                scope = "component"
            elif has_image:
                scope = "image"
            else:
                scope = "unscoped"

            results.append(
                {
                    "file": rel_path,
                    "rule": rule,
                    "type": "self-service",
                    "scope": scope,
                    "has_component_names": has_components,
                    "component_names": component_names if has_components else [],
                    "image_url": image_url if has_image else "",
                    "effective_until": effective_until,
                    "reference": reference,
                }
            )

    return results


# ---------------------------------------------------------------------------
# Search exceptions by component name
# ---------------------------------------------------------------------------


def search_exceptions_for_components(
    search_terms: list[str],
    environment: str,
    clone_dir: Path | None = None,
    refresh: bool = True,
) -> dict:
    """Search all exception sources for entries covering the given component(s).

    Scans three sources (prod-only by default):
      1. volatileConfig.exclude (time-limited) from policy files
      2. config.exclude (permanent) from policy files
      3. Self-service exceptions from exceptions/ directory

    Uses fuzzy matching: underscores/hyphens are interchangeable, version
    suffixes and odh-/rhoai- prefixes are stripped for comparison.

    Args:
        search_terms: Component names or partial names to search for.
        clone_dir: Path to existing konflux-release-data clone.
                   If None, clones into a temp directory.
        environment: Target environment filter (default: "prod").
        refresh: If True and clone_dir exists, git fetch + reset before scanning.

    Returns:
        dict with "matches" list and "summary" metadata.
    """
    is_temp = False
    try:
        if clone_dir and clone_dir.is_dir():
            repo_dir = clone_dir
            conforma_dir = _get_conforma_policy_dir()
            if conforma_dir and not (clone_dir / conforma_dir).is_dir():
                alt = clone_dir / "repo"
                if conforma_dir and (alt / conforma_dir).is_dir():
                    repo_dir = alt
            if refresh:
                _refresh_clone(repo_dir)
        else:
            repo_dir, is_temp = _clone_repo(clone_dir)

        volatile = scan_all_exceptions(repo_dir, environment)
        permanent = scan_permanent_exclusions(repo_dir, environment)
        self_service = scan_self_service_exceptions(repo_dir, environment)

        matches: list[dict] = []

        for exc in volatile:
            comp_names = exc.get("component_names", [])
            image_url = exc.get("image_url", "")
            has_components = exc.get("has_component_names", False)

            if has_components and comp_names:
                matched_terms = [t for t in search_terms if any(_fuzzy_component_match(t, c) for c in comp_names)]
                if matched_terms:
                    matches.append(
                        {
                            **_volatile_to_result(exc),
                            "scope": "component",
                            "matched_search_terms": matched_terms,
                        }
                    )
            elif image_url:
                matched_terms = [t for t in search_terms if _fuzzy_image_match(t, image_url)]
                if matched_terms:
                    matches.append(
                        {
                            **_volatile_to_result(exc),
                            "scope": "image",
                            "matched_search_terms": matched_terms,
                        }
                    )
            else:
                matches.append(
                    {
                        **_volatile_to_result(exc),
                        "scope": "unscoped",
                        "matched_search_terms": list(search_terms),
                    }
                )

        for exc in permanent:
            matches.append(
                {
                    **exc,
                    "matched_search_terms": list(search_terms),
                }
            )

        for exc in self_service:
            scope = exc.get("scope", "unscoped")
            comp_names = exc.get("component_names", [])
            image_url = exc.get("image_url", "")

            if scope == "component" and comp_names:
                matched_terms = [t for t in search_terms if any(_fuzzy_component_match(t, c) for c in comp_names)]
                if matched_terms:
                    matches.append({**exc, "matched_search_terms": matched_terms})
            elif scope == "image" and image_url:
                matched_terms = [t for t in search_terms if _fuzzy_image_match(t, image_url)]
                if matched_terms:
                    matches.append({**exc, "matched_search_terms": matched_terms})
            else:
                matches.append(
                    {
                        **exc,
                        "matched_search_terms": list(search_terms),
                    }
                )

        return {
            "search_terms": search_terms,
            "environment": environment,
            "matches": matches,
            "summary": {
                "total_matches": len(matches),
                "volatile": sum(1 for m in matches if m.get("type") == "volatile"),
                "permanent": sum(1 for m in matches if m.get("type") == "permanent"),
                "self_service": sum(1 for m in matches if m.get("type") == "self-service"),
                "by_scope": {
                    "component": sum(1 for m in matches if m.get("scope") == "component"),
                    "image": sum(1 for m in matches if m.get("scope") == "image"),
                    "unscoped": sum(1 for m in matches if m.get("scope") == "unscoped"),
                    "permanent": sum(1 for m in matches if m.get("scope") == "permanent"),
                },
            },
        }
    finally:
        if is_temp and clone_dir:
            shutil.rmtree(clone_dir, ignore_errors=True)


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
