"""Exception scanner — policy file scanning and component name matching."""

from __future__ import annotations

from __future__ import annotations
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


_VERSION_SUFFIX_RE = re.compile(r"-v\d+-\d+(?:-[a-z]+-\d+)?$")


def strip_version_suffix(name: str) -> str:
    """Strip Konflux version suffix from a component name.

    odh-dashboard-v3-4       -> odh-dashboard
    odh-mlflow-v3-3          -> odh-mlflow
    odh-vllm-cpu-v3-5-ea-1   -> odh-vllm-cpu
    """
    return _VERSION_SUFFIX_RE.sub("", name)


def extract_image_base(image_url: str) -> str:
    """Extract the base name from an image URL (strip registry path and -rhel9/-ubi9).

    quay.io/rhoai/odh-dashboard-rhel9       -> odh-dashboard
    quay.io/rhoai/odh-mlmd-grpc-server-rhel9 -> odh-mlmd-grpc-server
    """
    name = image_url.rsplit("/", 1)[-1]
    name = re.sub(r"-rhel\d+$", "", name)
    name = re.sub(r"-ubi\d+$", "", name)
    return name


def normalize_name(name: str) -> str:
    """Normalize a name for fuzzy comparison by stripping hyphens/underscores and lowercasing."""
    return re.sub(r"[-_]", "", name).lower()


def fuzzy_component_match(search_term: str, component_name: str) -> bool:
    """Check if search_term fuzzy-matches component_name.

    Handles underscore vs hyphen, missing separators, version suffixes,
    and odh-/rhoai- prefixes.

    >>> fuzzy_component_match("mlflow", "odh-mlflow-v3-3")
    True
    >>> fuzzy_component_match("nemo-guardrails", "odh-nemo_guardrails-v3-5-ea-1")
    True
    >>> fuzzy_component_match("nemoguardrails", "odh-nemo-guardrails-v3-4")
    True
    """
    base = strip_version_suffix(component_name)
    norm_search = normalize_name(strip_version_suffix(search_term))
    norm_base = normalize_name(base)

    if norm_search == norm_base or norm_search in norm_base:
        return True

    for prefix in ("odh", "rhoai"):
        if norm_base.startswith(prefix):
            stripped = norm_base[len(prefix) :]
            if norm_search == stripped or norm_search in stripped:
                return True

    return False


def fuzzy_image_match(search_term: str, image_url: str) -> bool:
    """Check if search_term fuzzy-matches an imageUrl/imageRef base name."""
    base = extract_image_base(image_url)
    return fuzzy_component_match(search_term, base)


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
                matched_terms = [t for t in search_terms if any(fuzzy_component_match(t, c) for c in comp_names)]
                if matched_terms:
                    matches.append(
                        {
                            **_volatile_to_result(exc),
                            "scope": "component",
                            "matched_search_terms": matched_terms,
                        }
                    )
            elif image_url:
                matched_terms = [t for t in search_terms if fuzzy_image_match(t, image_url)]
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
                matched_terms = [t for t in search_terms if any(fuzzy_component_match(t, c) for c in comp_names)]
                if matched_terms:
                    matches.append({**exc, "matched_search_terms": matched_terms})
            elif scope == "image" and image_url:
                matched_terms = [t for t in search_terms if fuzzy_image_match(t, image_url)]
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

