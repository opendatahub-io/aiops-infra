"""conforma_policy_ops.py -- Conforma policy exception search and coverage gate (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import conforma_mr_ops

_REPO_ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = _REPO_ROOT / "skills" / "conforma-exception" / ".work"


def search_existing_exceptions(rule: str, clone_dir: str | None = None) -> dict:
    """Check if exception for this rule already exists in konflux-release-data.

    Searches two locations:
    1. The `exclude:` section — simple list items (permanent global exclusions)
    2. The `volatileCriteria:` section — structured blocks with componentNames/effectiveUntil
    """
    if clone_dir:
        search_dir = Path(clone_dir)
    else:
        search_dir = WORK_DIR

    if not search_dir.exists():
        return {"checked": False, "reason": "No local clone available"}

    _krd_domain = os.environ.get("KRD_CLUSTER_DOMAIN", "")
    _ec_dir = (
        f"config/{_krd_domain}/product/EnterpriseContractPolicy"
        if _krd_domain
        else os.environ.get("KRD_EC_POLICY_DIR", "")
    )
    if not _ec_dir:
        return {"checked": False, "reason": "KRD_CLUSTER_DOMAIN or KRD_EC_POLICY_DIR env var not set"}
    policy_dir = search_dir / _ec_dir
    if not policy_dir.exists():
        return {"checked": False, "reason": f"Policy dir not found: {policy_dir}"}

    found_in = []
    permanent_exclusions = []

    try:
        from create_gitlab_mr import _find_existing_exceptions
    except ImportError:
        _find_existing_exceptions = None

    for yaml_file in policy_dir.glob("*rhoai*.yaml"):
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
    clone_dir: str | None = None,
    environment: str = "prod",
    prefetched_mrs: list[dict] | None = None,
) -> dict:
    """Hard gate: check if active exceptions already cover the requested components.

    Clones konflux-release-data (if needed), searches for existing exceptions
    matching the rule, and determines whether any active (non-expired) exception
    already covers the requested components.

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
    base_result = {
        "gate": "existing_exception_check",
        "rule": rule,
        "requested_components": components,
        "active_exceptions": [],
        "permanent_exclusions": [],
        "covered_components": [],
        "uncovered_components": list(components),
    }

    # Ensure clone exists
    repo_dir = None
    if clone_dir:
        candidate = Path(clone_dir)
        _krd_dom = os.environ.get("KRD_CLUSTER_DOMAIN", "")
        policy_sub = (
            f"config/{_krd_dom}/product/EnterpriseContractPolicy"
            if _krd_dom
            else os.environ.get("KRD_EC_POLICY_DIR", "")
        )
        if (candidate / policy_sub).is_dir():
            repo_dir = candidate
        elif (candidate / "repo" / policy_sub).is_dir():
            repo_dir = candidate / "repo"

    if not repo_dir:
        try:
            from manage_exceptions import _clone_repo

            repo_dir, _ = _clone_repo(Path(clone_dir) if clone_dir else None)
        except Exception as exc:
            return {
                **base_result,
                "status": "passed",
                "reason": (
                    f"Could not clone konflux-release-data ({exc}). Gate check skipped — proceeding with caution."
                ),
            }

    existing = search_existing_exceptions(rule, str(repo_dir))

    open_mrs = prefetched_mrs if prefetched_mrs is not None else conforma_mr_ops.search_open_exception_mrs(rule)
    enriched_mrs: list[dict] = []
    for mr_info in open_mrs:
        coverage = conforma_mr_ops.analyze_mr_component_coverage(
            mr_iid=mr_info["iid"],
            rule=rule,
            requested_components=components,
            mr_description=mr_info.get("description", ""),
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

    # Check permanent exclusions first
    permanent = existing.get("permanent_exclusions", [])
    env_permanent = [p for p in permanent if f"-{environment}." in Path(p["file"]).name]
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

        exc_comps = set(exc.get("componentNames", []))
        dedup_key = f"{exc.get('file')}|{eu}|{sorted(exc_comps)}"
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        if exc.get("has_componentNames") and exc_comps:
            overlap = requested & exc_comps
            if overlap:
                covered |= overlap
                active_exceptions.append(
                    {
                        "file": exc["file"],
                        "componentNames": sorted(exc_comps),
                        "effectiveUntil": eu,
                        "covers_components": sorted(overlap),
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
                            "componentNames": [],
                            "imageUrl": image_url,
                            "effectiveUntil": eu,
                            "covers_components": sorted(matched),
                            "note": f"imageUrl-scoped exception ({image_url} covers base name '{conforma_mr_ops._extract_image_base(image_url)}')",
                        }
                    )
            else:
                covered = requested.copy()
                active_exceptions.append(
                    {
                        "file": exc["file"],
                        "componentNames": [],
                        "effectiveUntil": eu,
                        "covers_components": sorted(requested),
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
    p_search.add_argument("--clone-dir", default=None)

    p_gate = sub.add_parser("check-gate")
    p_gate.add_argument("--rule", required=True)
    p_gate.add_argument("--components", required=True)
    p_gate.add_argument("--clone-dir", default=None)
    p_gate.add_argument("--environment", default="prod")

    args = parser.parse_args()

    if args.command == "search-exceptions":
        result = search_existing_exceptions(args.rule, args.clone_dir)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "check-gate":
        components = [c.strip() for c in args.components.split(",")]
        result = check_existing_exception_gate(
            rule=args.rule,
            components=components,
            clone_dir=args.clone_dir,
            environment=args.environment,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] != "blocked" else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
