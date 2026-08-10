"""conforma_policy_ops.py -- Conforma policy exception search and coverage gate (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import conforma_mr_ops

from _repo_root import REPO_ROOT as _REPO_ROOT
WORK_DIR = (
    Path(os.environ.get("CONFORMA_WORKDIR", ""))
    if os.environ.get("CONFORMA_WORKDIR")
    else Path.home() / ".conforma"
)


def _refresh_workdir_clone(clone_dir: Path) -> None:
    """Fetch latest main and hard-reset an existing clone.

    Raises subprocess.CalledProcessError if fetch fails (e.g. VPN down,
    host unreachable).  Callers must not silently fall back to stale data.
    Uses gitlab_ops.run_git() to respect GITLAB_SSL_VERIFY settings.
    """
    import gitlab_ops

    gitlab_ops.run_git(
        ["git", "fetch", "origin", "main"],
        cwd=clone_dir,
        timeout=120,
    )
    gitlab_ops.run_git(
        ["git", "reset", "--hard", "origin/main"],
        cwd=clone_dir,
        timeout=30,
    )


def _resolve_repo_dir(clone_dir: str | Path) -> Path | None:
    """Resolve a clone_dir to the actual repo root containing the policy subdir."""
    candidate = Path(clone_dir)
    _krd_dom = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    policy_sub = (
        f"config/{_krd_dom}/product/EnterpriseContractPolicy"
        if _krd_dom
        else os.environ.get("KONFLUX_CONFORMA_POLICY_DIR", "")
    )
    if not policy_sub:
        return None
    if (candidate / policy_sub).is_dir():
        return candidate
    if (candidate / "repo" / policy_sub).is_dir():
        return candidate / "repo"
    return None


def refresh_clone(clone_dir: str | Path) -> Path | None:
    """Ensure clone exists, fetch + hard-reset once.

    If the clone directory does not exist, performs a shallow clone from
    GitLab.  If it already exists, fetches latest main and hard-resets.

    Call this once before a batch of ``check_existing_exception_gate()``
    calls, then pass ``skip_refresh=True`` to each gate call.

    Returns the resolved repo_dir, or None if the clone could not be located.
    """
    target = Path(clone_dir)
    if not (target / ".git").is_dir():
        import gitlab_ops

        krd_project = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")
        clone_url = gitlab_ops.authenticated_clone_url(krd_project)
        if target.exists():
            import shutil
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        gitlab_ops.run_git(
            ["git", "clone", "--depth=1", "--branch", "main", clone_url, str(target)],
            timeout=120,
        )
    else:
        _refresh_workdir_clone(target)
    return _resolve_repo_dir(clone_dir)


def search_existing_exceptions(rule: str, policy_files: list[str], clone_dir: str | None = None) -> dict:
    """Check if exception for this rule already exists in konflux-release-data.

    Searches two locations:
    1. The `exclude:` section — simple list items (permanent global exclusions)
    2. The `volatileCriteria:` section — structured blocks with componentNames/effectiveUntil

    Only policy files whose basename appears in *policy_files* are searched.
    This prevents cross-product contamination (e.g. an unscoped exception in
    a desktop-extensions policy file incorrectly covering RHOAI components).
    """
    allowed_basenames = {Path(f).name for f in policy_files}
    if clone_dir:
        search_dir = Path(clone_dir)
    else:
        search_dir = WORK_DIR

    if not search_dir.exists():
        return {"checked": False, "reason": "No local clone available"}

    _krd_domain = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    _ec_dir = (
        f"config/{_krd_domain}/product/EnterpriseContractPolicy"
        if _krd_domain
        else os.environ.get("KONFLUX_CONFORMA_POLICY_DIR", "")
    )
    if not _ec_dir:
        return {"checked": False, "reason": "KONFLUX_CLUSTER_DOMAIN or KONFLUX_CONFORMA_POLICY_DIR env var not set"}
    policy_dir = search_dir / _ec_dir
    if not policy_dir.exists():
        return {"checked": False, "reason": f"Policy dir not found: {policy_dir}"}

    found_in = []
    permanent_exclusions = []

    _find_existing_exceptions = None
    try:
        from create_gitlab_mr import _find_existing_exceptions
    except ImportError:
        _exception_scripts = Path(__file__).resolve().parent.parent / "skills" / "conforma-exception" / "scripts"
        if _exception_scripts.is_dir():
            sys.path.insert(0, str(_exception_scripts))
            try:
                from create_gitlab_mr import _find_existing_exceptions
            except ImportError:
                pass
            finally:
                sys.path.pop(0)

    for yaml_file in policy_dir.glob("*.yaml"):
        if yaml_file.name not in allowed_basenames:
            continue
        content = yaml_file.read_text(encoding="utf-8")
        rel_path = str(yaml_file.relative_to(search_dir))

        if rule in content:
            _check_permanent_exclusions(content, rule, rel_path, permanent_exclusions)

        if f"value: {rule}" in content and _find_existing_exceptions is not None:
            exceptions = _find_existing_exceptions(content, rule)
            for exc in exceptions:
                found_in.append(
                    {
                        "file": rel_path,
                        "has_componentNames": exc["has_component_names"],
                        "componentNames": exc["component_names"],
                        "imageUrl": exc.get("image_url", ""),
                        "effectiveUntil": exc["effective_until_value"],
                        "block_start_line": exc["start"] + 1,
                        "exception_value": exc.get("value", rule),
                    }
                )

    return {
        "checked": True,
        "rule": rule,
        "existing_exceptions": found_in,
        "permanent_exclusions": permanent_exclusions,
        "count": len(found_in),
        "permanent_count": len(permanent_exclusions),
    }


def _build_digest_to_component_map(csv_path: str) -> dict[str, str]:
    """Build a mapping from image digest → component name from the source CSV.

    Reads the same ``image`` column that ``build_snapshot_from_csv()`` uses.
    Each ``image`` value is ``quay.io/repo/name@sha256:abcdef...``; we extract
    the ``sha256:abcdef...`` portion and map it to the ``component_name``.
    """
    import csv as csv_mod

    digest_map: dict[str, str] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv_mod.DictReader(f):
            image = (row.get("image") or "").strip()
            component = (row.get("component_name") or "").strip()
            if not image or not component:
                continue
            if "@" in image:
                digest = image.split("@", 1)[1]
                digest_map[digest] = component
    return digest_map


def _self_service_rule_matches(entry_value: str, target_rule: str) -> bool:
    """Check if a self-service entry's ``value`` matches a target violation rule.

    Matching rules:
    - Exact match: ``entry == rule``
    - Entry is a subcode of the rule's base: ``entry == "base:subcode"`` and
      ``rule == "base"`` or ``rule == "base:subcode"``
    - Rule is a subcode of the entry's base: ``rule == "base:sub"`` and
      ``entry == "base:sub"``

    Examples:
        ``("test.no_failed_tests:fbc-target-index-pruning-check",
          "test.no_failed_tests:fbc-target-index-pruning-check")`` → True
        ``("test.no_failed_tests:fbc-target-index-pruning-check",
          "test.no_failed_tests")`` → True (entry is subcode of rule's base)
        ``("schedule.weekday_restriction",
          "schedule.weekday_restriction")`` → True
    """
    if entry_value == target_rule:
        return True
    entry_base = entry_value.split(":")[0]
    rule_base = target_rule.split(":")[0]
    if entry_base == rule_base:
        return True
    return False


def search_self_service_exceptions(
    rule: str,
    self_service_files: list[str],
    clone_dir: str | None = None,
    csv_path: str | None = None,
) -> dict:
    """Search self-service exception files for coverage of a violation rule.

    Self-service files live in ``exceptions/`` in the konflux-release-data
    clone.  They are flat YAML lists of ``- value: rule.code`` entries with
    optional ``imageRef``, ``componentNames``, and ``effectiveUntil``.

    Unlike EC policy files, these are NOT processed by ``ec validate image``.
    Coverage is determined by YAML parsing and digest cross-referencing.

    *self_service_files* are basenames (e.g. ``["fbc-rhoai-stage.yaml"]``).
    *csv_path* is needed to cross-reference ``imageRef`` digests to components.
    """
    import yaml

    search_dir = Path(clone_dir) if clone_dir else WORK_DIR
    exceptions_dir = search_dir / "exceptions"

    if not exceptions_dir.exists():
        return {"checked": False, "reason": f"exceptions/ directory not found in {search_dir}"}

    digest_map: dict[str, str] | None = None
    if csv_path and Path(csv_path).exists():
        digest_map = _build_digest_to_component_map(csv_path)

    now = datetime.now(timezone.utc)
    matching_entries: list[dict] = []
    covered_components: set[str] = set()
    source_files: list[str] = []

    for basename in self_service_files:
        filepath = exceptions_dir / basename
        if not filepath.exists():
            continue

        try:
            data = yaml.safe_load(filepath.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(data, list):
            continue

        rel_path = f"exceptions/{basename}"
        file_had_match = False

        for entry in data:
            if not isinstance(entry, dict):
                continue

            value = entry.get("value", "")
            if not _self_service_rule_matches(value, rule):
                continue

            effective_until = entry.get("effectiveUntil")
            if effective_until:
                try:
                    eu_str = str(effective_until).strip('"').strip("'")
                    eu_dt = datetime.fromisoformat(eu_str.replace("Z", "+00:00"))
                    if eu_dt <= now:
                        continue
                except (ValueError, TypeError):
                    pass

            file_had_match = True
            entry_info: dict = {
                "file": rel_path,
                "value": value,
                "imageRef": entry.get("imageRef", ""),
                "effectiveUntil": str(effective_until) if effective_until else None,
                "componentNames": entry.get("componentNames", []),
                "has_componentNames": bool(entry.get("componentNames")),
            }
            matching_entries.append(entry_info)

            comp_names = entry.get("componentNames", [])
            image_ref = entry.get("imageRef", "")

            if comp_names:
                covered_components.update(comp_names)
            elif image_ref and digest_map is not None:
                component = digest_map.get(image_ref)
                if component:
                    covered_components.add(component)
            elif not image_ref and not comp_names:
                entry_info["unscoped"] = True

        if file_had_match:
            source_files.append(rel_path)

    return {
        "checked": True,
        "rule": rule,
        "matching_entries": matching_entries,
        "covered_components": covered_components,
        "source_files": source_files,
        "has_unscoped": any(e.get("unscoped") for e in matching_entries),
    }


def _check_permanent_exclusions(content: str, rule: str, file_path: str, results: list[dict]) -> None:
    """Check if the rule appears in the `exclude:` section as a permanent global exclusion.

    These are simple list items under `exclude:` with no componentNames or effectiveUntil,
    meaning the rule is permanently excluded for ALL components.
    """
    lines = content.split("\n")
    in_exclude_section = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "exclude:":
            in_exclude_section = True
            continue
        if in_exclude_section:
            if not stripped or (not stripped.startswith("-") and not stripped.startswith("#")):
                in_exclude_section = False
                continue
            if stripped.startswith("#"):
                continue
            if stripped == f"- {rule}":
                results.append(
                    {
                        "file": file_path,
                        "line": i + 1,
                        "type": "permanent_global_exclusion",
                        "detail": (
                            f"Rule '{rule}' is permanently excluded globally "
                            f"(no componentNames, no effectiveUntil). "
                            f"All components are covered forever."
                        ),
                    }
                )


def check_existing_exception_gate(
    rule: str,
    components: list[str],
    policy_files: list[str],
    environment: str,
    clone_dir: str | None = None,
    prefetched_mrs: list[dict] | None = None,
    skip_refresh: bool = False,
    aliases: dict[str, set[str]] | None = None,
) -> dict:
    """Hard gate: check if active exceptions already cover the requested components.

    Clones konflux-release-data (if needed), searches for existing exceptions
    matching the rule, and determines whether any active (non-expired) exception
    already covers the requested components.

    *policy_files* restricts both the upstream search and the gate evaluation
    to the specified policy file basenames (defense-in-depth — the search
    function also filters, but the gate double-checks).

    When *aliases* is provided, component sets are expanded before intersection
    so that renamed components (e.g. llama -> ogx) are recognised as equivalent.

    Returns:
        {
            "gate": "existing_exception_check",
            "status": "blocked" | "partial" | "passed" | "permanent",
            "reason": str,
            "rule": str,
            "requested_components": list[str],
            "active_exceptions": list[dict],
            "permanent_exclusions": list[dict],
            "covered_components": list[str],
            "uncovered_components": list[str],
        }
    """
    allowed_basenames = {Path(f).name for f in policy_files}
    base_result = {
        "gate": "existing_exception_check",
        "rule": rule,
        "requested_components": components,
        "active_exceptions": [],
        "permanent_exclusions": [],
        "covered_components": [],
        "uncovered_components": list(components),
    }

    # Ensure clone exists and is fresh (fetch from remote).
    # Policy: never use a stale clone — always fetch, abort if unreachable.
    # When skip_refresh=True, the caller has already called refresh_clone().
    repo_dir = None
    if clone_dir:
        repo_dir = _resolve_repo_dir(clone_dir)

        if repo_dir is not None and not skip_refresh:
            try:
                _refresh_workdir_clone(repo_dir)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                return {
                    **base_result,
                    "status": "error",
                    "reason": (
                        f"git fetch failed for {repo_dir} — remote unreachable (VPN down?). "
                        f"Refusing to use stale data. Error: {exc}"
                    ),
                }

    if not repo_dir:
        try:
            import gitlab_ops

            target_dir = Path(clone_dir) if clone_dir else (WORK_DIR / "konflux-release-data")
            krd_project = os.environ.get("GITLAB_PROJECT", "releng/konflux-release-data")
            clone_url = gitlab_ops.authenticated_clone_url(krd_project)
            if (target_dir / ".git").is_dir():
                _refresh_workdir_clone(target_dir)
            else:
                import shutil

                if target_dir.exists():
                    shutil.rmtree(target_dir)
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                gitlab_ops.run_git(
                    ["git", "clone", "--depth=1", "--branch", "main", clone_url, str(target_dir)],
                    timeout=120,
                )
            repo_dir = target_dir
        except Exception as exc:
            return {
                **base_result,
                "status": "error",
                "reason": (
                    f"Could not clone konflux-release-data ({exc}). "
                    f"Ensure VPN is connected, GitLab is reachable, and GITLAB_TOKEN is set."
                ),
            }

    existing = search_existing_exceptions(rule, policy_files, str(repo_dir))

    open_mrs = prefetched_mrs if prefetched_mrs is not None else conforma_mr_ops.search_open_exception_mrs(rule)
    enriched_mrs: list[dict] = []
    for mr_info in open_mrs:
        coverage = conforma_mr_ops.analyze_mr_component_coverage(
            mr_iid=mr_info["iid"],
            rule=rule,
            requested_components=components,
            mr_description=mr_info.get("description", ""),
            aliases=aliases,
            relevant_policy_files=policy_files,
        )
        merged = {**mr_info, **coverage}
        merged.pop("description", None)
        enriched_mrs.append(merged)
    base_result["open_merge_requests"] = enriched_mrs

    if not existing.get("checked"):
        return {
            **base_result,
            "status": "passed",
            "reason": (
                f"Could not check existing exceptions: "
                f"{existing.get('reason', 'unknown')}. "
                "Gate check skipped — proceeding with caution."
            ),
        }

    # Check permanent exclusions first (defense-in-depth: re-filter by policy_files)
    permanent = existing.get("permanent_exclusions", [])
    env_permanent = [
        p for p in permanent
        if f"-{environment}." in Path(p["file"]).name
        and Path(p["file"]).name in allowed_basenames
    ]
    if env_permanent:
        return {
            **base_result,
            "status": "permanent",
            "permanent_exclusions": env_permanent,
            "covered_components": list(components),
            "uncovered_components": [],
            "reason": (
                f"Rule '{rule}' is permanently excluded globally in "
                f"{env_permanent[0]['file']} (line {env_permanent[0]['line']}). "
                f"All components are covered forever in {environment}. "
                f"No exception needed."
            ),
        }

    # Check volatile exceptions for active coverage
    volatile = existing.get("existing_exceptions", [])
    if not volatile:
        return {
            **base_result,
            "status": "passed",
            "reason": f"No existing exceptions found for rule '{rule}'. Proceed with creation.",
        }

    now = datetime.now(timezone.utc)
    requested = set(components)
    _aliases = aliases or {}

    if _aliases:
        import component_alias_ops
        requested_expanded = component_alias_ops.expand_component_set(requested, _aliases)
    else:
        requested_expanded = requested

    covered = set()
    active_exceptions = []
    seen_keys: set[str] = set()

    for exc in volatile:
        eu = exc.get("effectiveUntil")
        is_active = True
        if eu:
            try:
                eu_str = eu.strip('"').strip("'")
                eu_dt = datetime.fromisoformat(eu_str.replace("Z", "+00:00"))
                is_active = eu_dt > now
            except (ValueError, TypeError):
                is_active = True  # can't parse → assume active

        if not is_active:
            continue

        env_file = Path(exc.get("file", "")).name
        if f"-{environment}" not in env_file and environment != "":
            continue
        if env_file not in allowed_basenames:
            continue

        exc_comps = set(exc.get("componentNames", []))
        dedup_key = f"{exc.get('file')}|{eu}|{sorted(exc_comps)}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        if exc.get("has_componentNames") and exc_comps:
            if _aliases:
                exc_comps_expanded = component_alias_ops.expand_component_set(exc_comps, _aliases)
                expanded_overlap = requested_expanded & exc_comps_expanded
                overlap = expanded_overlap & requested
            else:
                overlap = requested & exc_comps
            if overlap:
                covered |= overlap
                active_exceptions.append(
                    {
                        "file": exc["file"],
                        "line": exc.get("block_start_line"),
                        "componentNames": sorted(exc_comps),
                        "effectiveUntil": eu,
                        "covers_components": sorted(overlap),
                        "exception_value": exc.get("exception_value", rule),
                    }
                )
        elif not exc.get("has_componentNames"):
            image_url = exc.get("imageUrl", "")
            if image_url:
                matched = {c for c in requested if conforma_mr_ops.image_url_covers_component(image_url, c)}
                if matched:
                    covered |= matched
                    active_exceptions.append(
                        {
                            "file": exc["file"],
                            "line": exc.get("block_start_line"),
                            "componentNames": [],
                            "imageUrl": image_url,
                            "effectiveUntil": eu,
                            "covers_components": sorted(matched),
                            "exception_value": exc.get("exception_value", rule),
                            "note": f"imageUrl-scoped exception ({image_url} covers base name '{conforma_mr_ops._extract_image_base(image_url)}')",
                        }
                    )
            else:
                covered = requested.copy()
                active_exceptions.append(
                    {
                        "file": exc["file"],
                        "line": exc.get("block_start_line"),
                        "componentNames": [],
                        "effectiveUntil": eu,
                        "covers_components": sorted(requested),
                        "exception_value": exc.get("exception_value", rule),
                        "note": "Unscoped exception (no componentNames, no imageUrl) — covers all components for this rule",
                    }
                )

    uncovered = sorted(requested - covered)
    covered_list = sorted(covered)

    if not active_exceptions:
        return {
            **base_result,
            "status": "passed",
            "reason": (f"Existing exceptions found for rule '{rule}' but all are expired. Proceed with creation."),
        }

    if not uncovered:
        return {
            **base_result,
            "status": "blocked",
            "active_exceptions": active_exceptions,
            "covered_components": covered_list,
            "uncovered_components": [],
            "reason": (
                f"All {len(requested)} requested component(s) are already covered by "
                f"active exception(s) in {active_exceptions[0]['file']} "
                f"(effectiveUntil: {active_exceptions[0]['effectiveUntil']}). "
                f"No new exception needed."
            ),
        }

    return {
        **base_result,
        "status": "partial",
        "active_exceptions": active_exceptions,
        "covered_components": covered_list,
        "uncovered_components": uncovered,
        "reason": (
            f"{len(covered_list)} of {len(requested)} component(s) already covered "
            f"by active exception(s). {len(uncovered)} component(s) still need "
            f"exceptions: {', '.join(uncovered[:5])}"
            + (f"... (+{len(uncovered) - 5} more)" if len(uncovered) > 5 else "")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Conforma policy exception search and coverage gate")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search-exceptions")
    p_search.add_argument("--rule", required=True)
    p_search.add_argument("--policy-files", required=True,
                          help="Comma-separated list of policy file basenames to search")
    p_search.add_argument("--clone-dir", default=None)

    p_gate = sub.add_parser("check-gate")
    p_gate.add_argument("--rule", required=True)
    p_gate.add_argument("--components", required=True)
    p_gate.add_argument("--policy-files", required=True,
                        help="Comma-separated list of policy file basenames to scope the gate check")
    p_gate.add_argument("--clone-dir", default=None)
    p_gate.add_argument("--environment", required=True, choices=["prod", "stage"])

    args = parser.parse_args()

    if args.command == "search-exceptions":
        pf = [f.strip() for f in args.policy_files.split(",")]
        if args.clone_dir and Path(args.clone_dir).is_dir():
            try:
                _refresh_workdir_clone(Path(args.clone_dir))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                print(json.dumps({"checked": False, "reason": f"git fetch failed — remote unreachable: {exc}"}))
                return 1
        result = search_existing_exceptions(args.rule, pf, args.clone_dir)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "check-gate":
        components = [c.strip() for c in args.components.split(",")]
        pf = [f.strip() for f in args.policy_files.split(",")]
        result = check_existing_exception_gate(
            rule=args.rule,
            components=components,
            policy_files=pf,
            clone_dir=args.clone_dir,
            environment=args.environment,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] != "blocked" else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
