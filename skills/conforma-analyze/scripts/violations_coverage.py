#!/usr/bin/env python3
"""violations_coverage — Batch violations coverage check with cross-referencing.

PUBLIC API:
    check_violations_coverage(violations_yaml_path, policy_files, environment, clone_dir, require_jira, require_slack, metadata_file, release, csv_path, self_service_files) -> dict  [line 657]
    parse_args() -> argparse.Namespace  [line 1111]
    main() -> int  [line 1147]

INTERNAL SECTIONS:
    Main: _map_gate_status, _extract_exception_expiry, _build_component_exception_details, _log, _build_search_urls, ... (+9 more)

DEPENDENCIES: argparse, component_alias_ops, concurrent, conforma_constants, conforma_context_ops, conforma_ec_validate, conforma_jira_ops, conforma_mr_ops, conforma_policy_ops, conforma_slack_ops

"""

from __future__ import annotations

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import argparse
import conforma_context_ops
import fnmatch
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import component_alias_ops
import conforma_ec_validate
import conforma_jira_ops
import conforma_mr_ops
import conforma_policy_ops
import conforma_slack_ops
import jira_ops
import slack_ops


_GATE_STATUS_MAP: dict[str, tuple[str, str | None]] = {
    "permanent": ("fully_covered", "permanently excluded"),
    "blocked": ("fully_covered", "already covered"),
    "partial": ("partially_covered", None),
    "passed": ("not_covered", "not covered — resolve in code first, exception as last resort"),
    "skipped": ("not_covered", "not covered — resolve in code first, exception as last resort"),
    "error": ("not_covered", "not covered — exception check failed, manual review needed"),
}


def _build_component_exception_details(
    gate: dict,
    all_components: list[str],
    policy_files: list[str] | None = None,
) -> list[dict]:
    """Build per-component exception details from the gate result.

    Returns a list of dicts (one per component) with file, line, effective_until, and url.
    Components not covered by any exception in the user's policy files get null fields.
    """
    host = conforma_mr_ops.GITLAB_HOST
    project = conforma_mr_ops.GITLAB_PROJECT
    allowed = {Path(f).name for f in policy_files} if policy_files else None

    def _make_url(file_path: str | None, line: int | None) -> str | None:
        if not host or not project or not file_path:
            return None
        if line:
            return f"https://{host}/{project}/-/blob/main/{file_path}#L{line}"
        return f"https://{host}/{project}/-/blob/main/{file_path}"

    def _in_policy_files(file_path: str) -> bool:
        if allowed is None:
            return True
        return Path(file_path).name in allowed

    comp_details: dict[str, dict] = {}

    permanent = gate.get("permanent_exclusions", [])
    for exc in permanent:
        file_path = exc.get("file", "")
        if not _in_policy_files(file_path):
            continue
        line = exc.get("line")
        for comp in all_components:
            if comp not in comp_details:
                comp_details[comp] = {
                    "component": comp,
                    "file": Path(file_path).name,
                    "line": line,
                    "effective_until": None,
                    "url": _make_url(file_path, line),
                }

    active = gate.get("active_exceptions", [])
    for exc in active:
        file_path = exc.get("file", "")
        if not _in_policy_files(file_path):
            continue
        line = exc.get("line")
        effective_until = exc.get("effectiveUntil")
        if effective_until:
            effective_until = effective_until.strip('"').strip("'")[:10]
        exception_value = exc.get("exception_value", "")
        covered = exc.get("covers_components", [])
        for comp in covered:
            if comp not in comp_details:
                comp_details[comp] = {
                    "component": comp,
                    "file": Path(file_path).name,
                    "line": line,
                    "effective_until": effective_until,
                    "exception_value": exception_value,
                    "url": _make_url(file_path, line),
                }

    result = []
    for comp in all_components:
        if comp in comp_details:
            result.append(comp_details[comp])
        else:
            result.append({
                "component": comp,
                "file": None,
                "line": None,
                "effective_until": None,
                "url": None,
            })
    return result


def _log(msg: str) -> None:
    """Progress message to stderr (never mixed with JSON stdout)."""
    print(msg, file=sys.stderr, flush=True)


from conforma_constants import (
    CONFORMA_REPORTER_URL,
    VERIFY_NEXT_STEP,
)

from coverage_status_ops import map_gate_status as _map_gate_status  # noqa: F401 — backward compat re-export
from coverage_status_ops import extract_exception_expiry as _extract_exception_expiry  # noqa: F401 — backward compat re-export
from coverage_status_ops import build_search_urls as _build_search_urls  # noqa: F401 — backward compat re-export
from coverage_status_ops import determine_status_and_next_steps as _determine_status_and_next_steps  # noqa: F401 — backward compat re-export
from coverage_status_ops import load_report_metadata as _load_report_metadata  # noqa: F401 — backward compat re-export


def _find_all_policy_file_paths(
    clone_dir: str,
    policy_basenames: list[str],
    environment: str,
) -> list[Path]:
    """Locate ALL environment-specific policy YAMLs in the clone.

    Returns paths for all policy files matching the environment filter.
    Falls back to all existing files if no environment-specific files found.
    """
    import os as _os

    search_dir = Path(clone_dir)
    krd_domain = _os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
    ec_dir = (
        f"config/{krd_domain}/product/EnterpriseContractPolicy"
        if krd_domain
        else _os.environ.get("KONFLUX_CONFORMA_POLICY_DIR", "")
    )
    if not ec_dir:
        return []
    policy_dir = search_dir / ec_dir
    if not policy_dir.exists():
        return []

    env_matches = []
    for basename in policy_basenames:
        candidate = policy_dir / basename
        if candidate.exists() and f"-{environment}" in basename:
            env_matches.append(candidate)
    if env_matches:
        return env_matches

    all_existing = []
    for basename in policy_basenames:
        candidate = policy_dir / basename
        if candidate.exists():
            all_existing.append(candidate)
    return all_existing


_MAPPING_FILE = Path(__file__).resolve().parent.parent.parent / "references" / "component-policy-mapping.yaml"


def _load_component_policy_mapping(mapping_file: Path | None = None) -> list[dict]:
    """Load component-to-policy mapping rules from YAML reference file."""
    import yaml

    path = mapping_file or _MAPPING_FILE
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("rules", [])


def _map_component_to_policy(
    component_name: str,
    policy_paths: list[Path],
    mapping_rules: list[dict],
) -> Path | None:
    """Determine which policy file applies to a component.

    Evaluates mapping rules top-to-bottom; first match wins.
    Returns the matching policy Path, or None if no match.
    """
    for rule in mapping_rules:
        pattern = rule.get("pattern", "")
        if not fnmatch.fnmatch(component_name, pattern):
            continue
        prefix = rule.get("policy_prefix", "")
        must_contain = rule.get("policy_must_contain", "")
        must_not_contain = rule.get("policy_must_not_contain", "")
        for p in policy_paths:
            name = p.name
            if prefix and not name.startswith(prefix):
                continue
            if must_contain and must_contain not in name:
                continue
            if must_not_contain and must_not_contain in name:
                continue
            return p
        return None
    return None


def _group_components_by_policy(
    component_names: list[str],
    policy_paths: list[Path],
    mapping_rules: list[dict],
) -> dict[Path, list[str]]:
    """Group component names by their assigned policy file.

    Returns {policy_path: [component_names]}.
    Components that don't match any policy are logged and omitted.
    """
    groups: dict[Path, list[str]] = {p: [] for p in policy_paths}
    unmapped: list[str] = []

    for comp in component_names:
        policy = _map_component_to_policy(comp, policy_paths, mapping_rules)
        if policy is not None:
            groups[policy].append(comp)
        else:
            unmapped.append(comp)

    if unmapped:
        _log(f"  WARNING: {len(unmapped)} component(s) not mapped to any policy: {', '.join(unmapped[:5])}")

    return {p: comps for p, comps in groups.items() if comps}


def _run_ec_coverage(
    csv_path: str,
    clone_dir: str,
    policy_basenames: list[str],
    environment: str,
) -> dict:
    """Run ec validate image per policy file and merge results.

    Each component is evaluated against its assigned policy (determined
    by component-policy-mapping.yaml).  Results from other policies are
    discarded for that component.

    Returns dict with keys:
        violations: {component_name: {violation_code, ...}}
        successes:  {component_name: {violation_code, ...}}
        validation: validation result from validate_ec_against_csv()

    Raises EcValidateError on hard failures (no policies found, binary unavailable).
    """
    policy_paths = _find_all_policy_file_paths(clone_dir, policy_basenames, environment)
    if not policy_paths:
        raise conforma_ec_validate.EcValidateError(
            "Cannot find any policy files for ec validate. "
            f"Searched for {policy_basenames} in {clone_dir} (env={environment}). "
            "Ensure KONFLUX_CLUSTER_DOMAIN is set and the policy clone is fresh."
        )

    mapping_rules = _load_component_policy_mapping()

    work_dir = Path(csv_path).parent / "ec-validate"
    work_dir.mkdir(parents=True, exist_ok=True)

    _log(f"Running ec validate image against {len(policy_paths)} policy file(s)...")
    for p in policy_paths:
        _log(f"  - {p.name}")

    ec_binary = conforma_ec_validate.ensure_ec_binary()

    spec_path, all_entries = conforma_ec_validate.build_snapshot_from_csv(
        csv_path, str(work_dir / "spec.json")
    )
    all_component_names = [e["name"] for e in all_entries]
    _log(f"  Snapshot: {spec_path} ({len(all_entries)} image entries, {len(set(all_component_names))} unique components)")

    component_groups = _group_components_by_policy(
        list(dict.fromkeys(all_component_names)), policy_paths, mapping_rules,
    )

    merged_violations: dict[str, set[str]] = {}
    merged_successes: dict[str, set[str]] = {}

    for policy_path in policy_paths:
        assigned_components = set(component_groups.get(policy_path, []))
        if not assigned_components:
            _log(f"  Skipping {policy_path.name} — no components mapped to this policy")
            continue

        policy_work_dir = work_dir / policy_path.stem
        policy_work_dir.mkdir(parents=True, exist_ok=True)

        policy_entries = [e for e in all_entries if e["name"] in assigned_components]
        base_image_groups = conforma_ec_validate.group_entries_by_base_image(policy_entries)

        _log(f"  Validating against {policy_path.name} ({len(assigned_components)} components, {len(base_image_groups)} batches)...")

        local_policy = conforma_ec_validate.prepare_policy_for_local_use(
            str(policy_path), str(policy_work_dir / "policy-local.yaml")
        )

        batches_succeeded = 0
        batches_failed = 0
        for batch_idx, (base_url, entries) in enumerate(base_image_groups.items(), 1):
            batch_dir = policy_work_dir / f"batch-{batch_idx:03d}"
            batch_dir.mkdir(parents=True, exist_ok=True)

            batch_spec = conforma_ec_validate.build_snapshot_from_entries(
                entries, str(batch_dir / "spec.json")
            )
            _log(f"    Batch {batch_idx}/{len(base_image_groups)}: {base_url} ({len(entries)} digests)...")

            try:
                ec_output = conforma_ec_validate.run_ec_validate(
                    ec_binary, str(batch_spec), str(local_policy), str(batch_dir)
                )
            except conforma_ec_validate.EcValidateError as exc:
                batches_failed += 1
                _log(f"    Batch {batch_idx}/{len(base_image_groups)} FAILED: {base_url} — {str(exc)[:200]}")
                continue

            batches_succeeded += 1
            ec_violations = conforma_ec_validate.extract_ec_violations(ec_output)
            ec_successes_batch = conforma_ec_validate.extract_ec_successes(ec_output)

            for comp, codes in ec_violations.items():
                merged_violations.setdefault(comp, set()).update(codes)
            for comp, codes in ec_successes_batch.items():
                merged_successes.setdefault(comp, set()).update(codes)

        _log(f"    {policy_path.name}: {batches_succeeded}/{batches_succeeded + batches_failed} batches succeeded")

    total_viols = sum(len(v) for v in merged_violations.values())
    total_succ = sum(len(v) for v in merged_successes.values())
    _log(f"  Merged: {len(merged_violations)} components, {total_viols} violations, {total_succ} successes")

    csv_violations = conforma_ec_validate.extract_csv_violations(csv_path)
    validation = conforma_ec_validate.validate_ec_against_csv(
        csv_violations, merged_violations, merged_successes
    )

    if validation["validated"]:
        _log(f"  Baseline validation passed: {validation['confirmed_violations']} active, {validation['confirmed_covered']} covered by exception")
    else:
        _log(
            f"  WARNING: {validation['divergence_count']} violation(s) in the source CSV report "
            f"are not evaluated by Conforma now. The Conforma policy may have changed since "
            f"the report was generated. Coverage for these violations cannot be verified."
        )

    return {
        "violations": merged_violations,
        "successes": merged_successes,
        "validation": validation,
    }


def _ec_coverage_for_rule(
    rule: str,
    components: list[str],
    ec_violations: dict[str, set[str]],
    ec_successes: dict[str, set[str]] | None = None,
) -> tuple[list[str], list[str], str, str, list[dict]]:
    """Determine coverage for a rule using ec validate results.

    Three-way classification when ec_successes is provided:
      - In ec_violations → uncovered (confirmed active)
      - In ec_successes → covered (confirmed by Conforma engine)
      - In neither → uncovered + divergence flag (ec doesn't evaluate this rule)
      - Component not in ec output at all → uncovered

    Returns (covered, uncovered, coverage, coverage_label, divergences).
    """
    covered = []
    uncovered = []
    divergences: list[dict] = []

    for comp in components:
        ec_viols = ec_violations.get(comp, None)
        ec_succ = ec_successes.get(comp, set()) if ec_successes is not None else None

        if ec_viols is None:
            uncovered.append(comp)
        elif rule in ec_viols:
            uncovered.append(comp)
        elif ec_succ is not None and rule in ec_succ:
            covered.append(comp)
        elif ec_succ is not None:
            uncovered.append(comp)
            divergences.append({
                "component": comp,
                "violation_code": rule,
                "reason": (
                    "The source CSV report lists this as a violation, but "
                    "running Conforma now does not evaluate this rule for "
                    "this component. The Conforma policy may have changed "
                    "since the report was generated (rule renamed, removed "
                    "from the policy bundle, or evaluation error). Coverage "
                    "cannot be verified automatically."
                ),
            })
        else:
            covered.append(comp)

    if not uncovered:
        coverage = "fully_covered"
        coverage_label = "fully covered (verified by Conforma engine)"
    elif not covered:
        coverage = "not_covered"
        coverage_label = "not covered — resolve in code first, exception as last resort"
    else:
        coverage = "partially_covered"
        coverage_label = f"{len(uncovered)} of {len(components)} without exception coverage"

    return covered, uncovered, coverage, coverage_label, divergences


def check_violations_coverage(
    violations_yaml_path: str,
    policy_files: list[str],
    environment: str,
    clone_dir: str | None = None,
    require_jira: bool = True,
    require_slack: bool = True,
    metadata_file: str | None = None,
    release: str | None = None,
    csv_path: str | None = None,
    self_service_files: list[str] | None = None,
) -> dict:
    """Batch coverage check: read a violations YAML and check each violation's components
    against existing exceptions in the policy file.

    Returns a per-violation summary with coverage status so the agent can present
    an informed violation list (covered vs uncovered) without per-violation round trips.
    """
    import yaml

    path = Path(violations_yaml_path)
    if not path.exists():
        return {"error": f"Violations file not found: {violations_yaml_path}"}

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_rule = data.get("violation_data", {}).get("violations_by_rule", {})

    if not by_rule:
        return {"error": "No violations_by_rule found in input YAML"}

    all_rules = list(by_rule.keys())
    releases = data.get("violation_data", {}).get("releases", [])

    aliases = component_alias_ops.load_aliases()
    if aliases:
        _log(f"Loaded {len(all_rules)} rules across {len(releases)} release(s) ({len(set().union(*aliases.values()))} component aliases)")
    else:
        _log(f"Loaded {len(all_rules)} rules across {len(releases)} release(s)")

    by_component_data = data.get("violation_data", {}).get("violations_by_component", {})
    component_owners: dict[str, str | None] = {}
    for comp, info in by_component_data.items():
        jc = info.get("jira_component")
        if jc is not None:
            component_owners[comp] = jc

    rule_to_components: dict[str, list[str]] = {}
    for rule, info in by_rule.items():
        comps: list[str] = []
        for _release, release_comps in info.get("releases", {}).items():
            comps.extend(release_comps)
        rule_to_components[rule] = sorted(set(comps))

    # Verify auth for enabled sources before starting parallel work.
    if require_jira:
        jira_auth = jira_ops.verify_auth()
        if not jira_auth["ok"]:
            return {"error": f"Jira auth failed: {jira_auth['error']}"}

    slack_team_url = ""
    if require_slack:
        slack_auth = slack_ops.verify_auth()
        if not slack_auth["ok"]:
            return {"error": f"Slack auth failed: {slack_auth['error']}"}
        slack_team_url = slack_auth.get("team_url", "")

    # Run Merge Request, Jira, and Slack prefetches in parallel — they are independent.
    prefetched_mrs: dict = {}
    prefetched_jira: dict = {}
    prefetched_slack: dict = {}

    def _fetch_mrs():
        t0 = time.monotonic()
        _log(f"  [Merge Requests] Searching GitLab for {len(all_rules)} rules...")
        result = conforma_mr_ops.prefetch_open_mrs(all_rules)
        total_mrs = sum(len(v) for v in result.values())
        _log(f"  [Merge Requests] Done — {total_mrs} open Merge Request(s) found ({time.monotonic() - t0:.1f}s)")
        return "mrs", result

    def _fetch_jira():
        t0 = time.monotonic()
        _log(f"  [Jira] Searching Jira tickets for {len(all_rules)} rules...")
        result = conforma_jira_ops.prefetch_open_jira_tickets(
            all_rules,
            releases=releases,
            rule_to_components=rule_to_components,
            aliases=aliases,
        )
        total_tickets = sum(len(v) for v in result.values())
        _log(f"  [Jira] Done — {total_tickets} open ticket(s) found ({time.monotonic() - t0:.1f}s)")
        return "jira", result

    def _fetch_slack():
        t0 = time.monotonic()
        _log(f"  [Slack] Searching Slack threads for {len(all_rules)} rules...")
        result = conforma_slack_ops.prefetch_open_slack_threads(
            all_rules, rule_to_components=rule_to_components
        )
        total_threads = sum(len(v) for v in result.values())
        _log(f"  [Slack] Done — {total_threads} thread(s) found ({time.monotonic() - t0:.1f}s)")
        return "slack", result

    tasks = [_fetch_mrs]
    if require_jira:
        tasks.append(_fetch_jira)
    if require_slack:
        tasks.append(_fetch_slack)

    _log(f"Cross-referencing {len(all_rules)} rules ({len(tasks)} source(s) in parallel)...")
    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {pool.submit(fn): fn.__name__ for fn in tasks}
        for future in as_completed(futures):
            key, result = future.result()
            if key == "mrs":
                prefetched_mrs = result
            elif key == "jira":
                prefetched_jira = result
            elif key == "slack":
                prefetched_slack = result
    _log(f"All prefetches complete ({time.monotonic() - t_start:.1f}s)")

    analyzed_release = release or (releases[0] if releases else None)

    # Refresh the policy clone once (not per rule).
    if clone_dir:
        t0 = time.monotonic()
        _log("Refreshing policy clone...")
        conforma_policy_ops.refresh_clone(clone_dir)
        _log(f"Policy clone refreshed ({time.monotonic() - t0:.1f}s)")

    # Run ec validate image once for authoritative coverage.
    ec_violations: dict[str, set[str]] | None = None
    ec_successes: dict[str, set[str]] | None = None
    ec_validation: dict | None = None
    if csv_path and clone_dir:
        t0 = time.monotonic()
        ec_result = _run_ec_coverage(csv_path, clone_dir, policy_files, environment)
        ec_violations = ec_result["violations"]
        ec_successes = ec_result["successes"]
        ec_validation = ec_result["validation"]
        _log(f"ec validate coverage complete ({time.monotonic() - t0:.1f}s)")
    elif not csv_path:
        return {"error": "--csv is required for ec-based coverage checking"}

    _log(f"Checking exception coverage for {len(by_rule)} rules...")
    results = []
    for i, (rule, info) in enumerate(sorted(by_rule.items()), 1):
        all_components = []
        for release, comps in info.get("releases", {}).items():
            all_components.extend(comps)
        all_components = sorted(set(all_components))

        _log(f"  [{i}/{len(by_rule)}] {rule}")

        if not all_components:
            results.append(
                {
                    "rule": rule,
                    "title": info.get("title", ""),
                    "total_components": 0,
                    "covered_components": [],
                    "uncovered_components": [],
                    "coverage": "no_components",
                    "status": "skipped",
                }
            )
            continue

        # Coverage from ec validate (authoritative, catches all exception types).
        covered, uncovered, coverage, coverage_label, rule_divergences = _ec_coverage_for_rule(
            rule, all_components, ec_violations, ec_successes,
        )

        # Self-service exception coverage (supplements EC, which doesn't see exceptions/ files).
        if self_service_files and uncovered:
            ss_result = conforma_policy_ops.search_self_service_exceptions(
                rule=rule,
                self_service_files=self_service_files,
                clone_dir=clone_dir,
                csv_path=csv_path,
            )
            if ss_result.get("checked"):
                ss_covered = ss_result.get("covered_components", set())
                if ss_result.get("has_unscoped"):
                    ss_covered = set(all_components)
                rescued = [c for c in uncovered if c in ss_covered]
                if rescued:
                    covered = covered + rescued
                    uncovered = [c for c in uncovered if c not in ss_covered]
                    if not uncovered:
                        coverage = "fully_covered"
                        coverage_label = "fully covered (verified by self-service exception file)"
                    else:
                        coverage = "partially_covered"
                        coverage_label = f"{len(uncovered)} of {len(all_components)} without exception coverage"
                    _log(f"    Self-service exceptions rescued {len(rescued)} component(s) from {ss_result.get('source_files', [])}")

        # Gate check for enrichment metadata (expiry dates, policy file links).
        gate = conforma_policy_ops.check_existing_exception_gate(
            rule=rule,
            components=all_components,
            policy_files=policy_files,
            clone_dir=clone_dir,
            environment=environment,
            prefetched_mrs=prefetched_mrs.get(rule),
            skip_refresh=True,
            aliases=aliases or None,
        )

        exception_expiry = _extract_exception_expiry(gate)
        exception_details = _build_component_exception_details(gate, all_components, policy_files=policy_files)

        open_mrs = gate.get("open_merge_requests", [])

        # Compute discrepancy for each MR:
        # - "code_only": diff covers this rule but title/description doesn't mention it
        #   (description is outdated or MR was discovered purely by code cross-index)
        # - "title_only": title mentions this rule but diff doesn't cover it
        #   (text-search false positive; filtered from display by no_overlap, kept here for audit)
        for mr in open_mrs:
            rules_in_diff = mr.get("rules_in_diff", [])
            title_mentions = mr.get("title_mentions_rule", True)
            rule_base = rule.split(":")[0]
            diff_covers_rule = any(
                r == rule or r.split(":")[0] == rule_base
                for r in rules_in_diff
            )
            if diff_covers_rule and not title_mentions:
                mr["discrepancy"] = "code_only"
                mr["discrepancy_detail"] = (
                    f"Diff covers `{rule}` but MR title/description doesn't mention it "
                    f"(discovered via code scan — description may be outdated)"
                )
            elif not diff_covers_rule and title_mentions:
                mr["discrepancy"] = "title_only"
                mr["discrepancy_detail"] = (
                    f"MR title/description mentions `{rule}` but the diff doesn't add "
                    f"an exception for it — diff actually covers: {rules_in_diff or '(nothing)'}"
                )
            else:
                mr["discrepancy"] = None
                mr["discrepancy_detail"] = None

        mr_label = ""
        for mr in open_mrs:
            sug = mr.get("suggestion", "")
            mr_url = mr.get("url", "")
            mr_type = mr.get("mr_type", "exception")
            type_tag = f"({mr_type}) " if mr_type else ""
            if sug == "fully_covered":
                mr_label = f"{type_tag}fully covered by [!{mr['iid']}]({mr_url})"
                break
            if sug == "extend_mr":
                n_cov = len(mr.get("covered", []))
                mr_label = f"{type_tag}[!{mr['iid']}]({mr_url}) covers {n_cov}/{len(all_components)}"

        jira_tickets = prefetched_jira.get(rule, [])
        if analyzed_release:
            for t in jira_tickets:
                t["version_relevance"] = conforma_jira_ops.classify_ticket_version_relevance(
                    t, analyzed_release
                )
        jira_label = ""
        if jira_tickets:
            labels = []
            for t in jira_tickets:
                version_tag = ""
                # Only annotate fixVersion relevance for RHOAIENG tickets;
                # PSX, OCPEXCEPT, and PRODSECRM don't use the fixVersion field.
                project = t["key"].split("-", 1)[0]
                if analyzed_release and project == "RHOAIENG":
                    relevance = t.get("version_relevance", "no_target_version")
                    if relevance == "targets_future":
                        fv_str = ", ".join(t.get("fix_versions", []))
                        version_tag = f" ⚠️ targets {fv_str}"
                    elif relevance == "no_target_version":
                        version_tag = " ⚠️ no fixVersion"
                match_tag = ""
                if t.get("match_source") == "component_inference":
                    confidence = t.get("inference_confidence", "unconfirmed")
                    match_tag = " \U0001f50d" if confidence == "confirmed" else " \U0001f50d?"
                labels.append(f"[{t['key']}]({t['url']}) ({t['status']}{version_tag}{match_tag})")
            jira_label = ", ".join(labels)

        slack_threads = prefetched_slack.get(rule, [])
        slack_label = ""
        if slack_threads:
            labels = []
            for t in slack_threads:
                reply_info = f", {t['thread_reply_count']} replies" if t.get("thread_reply_count") else ""
                labels.append(f"[#{t['channel']}]({t['permalink']}) ({t['date']}{reply_info})")
            slack_label = ", ".join(labels)

        search_urls = _build_search_urls(rule, slack_team_url)
        if search_urls["mr"]:
            mr_label = (
                (mr_label + f" ([try manual search]({search_urls['mr']}))") if mr_label else f"[try manual search]({search_urls['mr']})"
            )
        if search_urls["jira"]:
            jira_label = (
                (jira_label + f" ([try manual search]({search_urls['jira']}))")
                if jira_label
                else f"[try manual search]({search_urls['jira']})"
            )
        if search_urls["slack"]:
            slack_label = (
                (slack_label + f" ([try manual search]({search_urls['slack']}))")
                if slack_label
                else f"[try manual search]({search_urls['slack']})"
            )

        status_label, next_steps, next_steps_short = _determine_status_and_next_steps(
            coverage, open_mrs, jira_tickets, len(uncovered)
        )

        uncov_labels = []
        for c in uncovered:
            jc = component_owners.get(c)
            uncov_labels.append(f"{c} ({jc})" if jc else c)

        all_labels = []
        for c in all_components:
            jc = component_owners.get(c)
            all_labels.append(f"{c} ({jc})" if jc else c)

        if len(all_labels) <= 3:
            display_components = ", ".join(all_labels)
        else:
            display_components = ", ".join(all_labels[:3]) + f" ... +{len(all_components) - 3} more"

        entry = {
            "rule": rule,
            "title": info.get("title", ""),
            "violation_count": info.get("count", len(all_components)),
            "total_components": len(all_components),
            "all_components": list(all_components),
            "covered_components": covered,
            "uncovered_components": uncovered,
            "covered_count": len(covered),
            "uncovered_count": len(uncovered),
            "ec_divergences": rule_divergences,
            "display_components": display_components,
            "exception_expiry": exception_expiry,
            "exception_details_by_component": exception_details,
            "open_merge_requests": open_mrs,
            "open_mr_label": mr_label,
            "open_mr_search_url": search_urls["mr"],
            "open_jira_tickets": jira_tickets,
            "open_jira_label": jira_label,
            "open_jira_search_url": search_urls["jira"],
            "next_steps": next_steps,
            "next_steps_short": next_steps_short,
            "status_label": status_label,
            "coverage": coverage,
            "coverage_label": coverage_label,
            "gate_status": gate["status"],
            "analyzed_release": analyzed_release,
        }
        if require_slack:
            entry["open_slack_threads"] = slack_threads
            entry["open_slack_label"] = slack_label
            entry["open_slack_search_url"] = search_urls["slack"]
        results.append(entry)

    summary = {
        "fully_covered": sum(1 for r in results if r["coverage"] == "fully_covered"),
        "partially_covered": sum(1 for r in results if r["coverage"] == "partially_covered"),
        "not_covered": sum(1 for r in results if r["coverage"] == "not_covered"),
        "total_violations": len(results),
    }

    _log(
        f"Coverage complete: {summary['fully_covered']} covered, "
        f"{summary['partially_covered']} partial, {summary['not_covered']} not covered"
    )

    report_meta = _load_report_metadata(analyzed_release, metadata_file)

    md_table = _render_violations_markdown_table(
        results, summary, report_meta=report_meta,
    )

    output = {
        "violations_source": violations_yaml_path,
        "environment": environment,
        "summary": summary,
        "violations": results,
        "markdown_table": md_table,
    }
    if ec_validation:
        output["ec_validation"] = ec_validation
    if component_owners:
        output["component_owners"] = component_owners
    return output


def _render_violations_markdown_table(
    results: list[dict],
    summary: dict,
    report_meta: dict | None = None,
) -> str:
    """Pre-render a markdown table from violations coverage results.

    Columns: #, Violation, Count, Status, Jira, Next Steps.
    """
    meta = report_meta or {}
    lines: list[str] = []

    header_parts = [f"**Release**: `{meta.get('release', 'unknown')}`"]
    source_path = meta.get("source_path")
    source_url = meta.get("source_url")
    if source_path and source_url:
        header_parts.append(f"**Source**: [{source_path}]({source_url})")
    elif source_path:
        header_parts.append(f"**Source**: {source_path}")
    created_at = meta.get("created_at")
    if created_at:
        header_parts.append(f"**Report date**: {created_at}")
    lines.append("\\\n".join(header_parts))
    lines.append("")

    lines.append(
        f"**Summary**: {summary['total_violations']} unique violations — "
        f"{summary['fully_covered']} fully covered, "
        f"{summary['partially_covered']} partially covered, "
        f"{summary['not_covered']} not covered."
    )
    lines.append("")

    lines.append("| # | Violation | Count | Status | Jira | Next Steps |")
    lines.append("|---|-----------|-------|--------|------|------------|")

    for i, v in enumerate(results, 1):
        rule = f"`{v['rule']}`"
        viol_count = v.get("violation_count", "—")
        status = v["status_label"]
        covered_count = v.get("covered_count", 0)
        total_count = v.get("total_components", 0)
        if v.get("coverage") in ("fully_covered",) and covered_count and total_count:
            status = f"Exception granted ({covered_count}/{total_count} components covered)"
        elif v.get("coverage") == "partially_covered" and total_count:
            uncovered = total_count - covered_count
            status = f"Exception granted ({covered_count}/{total_count} components covered, {uncovered} without coverage)"
        jira = v.get("open_jira_label", "")
        ns = v.get("next_steps_short", v["next_steps"])
        lines.append(f"| {i} | {rule} | {viol_count} | {status} | {jira} | {ns} |")

    lines.append("")
    lines.append("*See the **Resolution Guide** section below for full resolution details per violation.*")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch violations coverage check")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
    )
    parser.add_argument("--violations-yaml", default=None)
    parser.add_argument("--csv", default=None, help="Path to source CSV report (for ec validate image)")
    parser.add_argument("--clone-dir", default=None)
    parser.add_argument("--environment", default=None, choices=["prod", "stage"])
    parser.add_argument("--require-jira", type=lambda v: v.lower() in ("true", "1", "yes"), default=True)
    parser.add_argument("--require-slack", type=lambda v: v.lower() in ("true", "1", "yes"), default=True)
    parser.add_argument("--metadata-file", default=None, help="Path to fetch-metadata.json for report header")
    parser.add_argument(
        "--release",
        default=None,
        help="Target release for the report header and Jira version relevance check. "
        "When set, overrides the auto-detected release (first in violations YAML). "
        "Use this to ensure the correct release appears in the coverage table header.",
    )
    parser.add_argument(
        "--policy-files",
        default=None,
        help="Comma-separated list of policy file basenames (from resolve_release_context) "
        "to scope exception search and coverage gate. Auto-extracted from "
        "context.yaml when omitted.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON output to this file instead of stdout.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    context = None
    run_dir = None
    try:
        run_dir = conforma_context_ops.discover_run_dir(args.run_dir)
        context = conforma_context_ops.load(run_dir)
    except FileNotFoundError:
        if args.run_dir:
            raise

    environment = conforma_context_ops.resolve_arg(args, "environment", context, "environment")

    violations_yaml = args.violations_yaml
    if violations_yaml is None and context and run_dir:
        parse_output = conforma_context_ops.get(run_dir, "steps.parse.violations_yaml", None)
        if parse_output:
            violations_yaml = str(Path(run_dir) / parse_output)
    if not violations_yaml:
        print("Error: --violations-yaml is required when no run context is available", file=sys.stderr)
        return 1

    csv_path = args.csv
    if csv_path is None and context and run_dir:
        csv_files = conforma_context_ops.get(run_dir, "steps.fetch.csv_files", None)
        if csv_files:
            csv_path = str(Path(run_dir) / csv_files[0])
    if not csv_path:
        print("Error: --csv is required when no run context is available", file=sys.stderr)
        return 1

    release = args.release
    if release is None and context:
        release = conforma_context_ops.get(run_dir, "application.release", None)

    clone_dir = args.clone_dir

    pf: list[str] | None = None
    ssf: list[str] | None = None
    if args.policy_files:
        pf = [f.strip() for f in args.policy_files.split(",")]
    elif context:
        ctx_pf = conforma_context_ops.get(run_dir, "resolve.policy_files", None)
        if ctx_pf:
            pf = ctx_pf
        ctx_ssf = conforma_context_ops.get(run_dir, "resolve.self_service_files", None)
        if ctx_ssf:
            ssf = ctx_ssf

    if not pf:
        print(
            "ERROR: --policy-files is required (provide directly or via context.yaml)",
            file=sys.stderr,
        )
        return 1

    output_file = args.output
    if output_file is None and run_dir:
        output_file = str(Path(run_dir) / "coverage.json")

    result = check_violations_coverage(
        violations_yaml_path=violations_yaml,
        policy_files=pf,
        clone_dir=clone_dir,
        environment=environment,
        require_jira=args.require_jira,
        require_slack=args.require_slack,
        metadata_file=args.metadata_file,
        release=release,
        csv_path=csv_path,
        self_service_files=ssf,
    )
    output_json = json.dumps(result, indent=2)
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_json + "\n", encoding="utf-8")
    else:
        print(output_json)

    if run_dir and "error" not in result:
        step_outputs: dict = {"coverage_json": "coverage.json"}
        if clone_dir:
            step_outputs["clone_dir"] = conforma_context_ops.contract_home(Path(clone_dir))
        conforma_context_ops.update_step(run_dir, "coverage", "completed", **step_outputs)

    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
