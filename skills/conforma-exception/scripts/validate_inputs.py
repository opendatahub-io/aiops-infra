#!/usr/bin/env python3
"""validate_inputs — Validate inputs for the conforma-exception skill.

PUBLIC API:
    parse_rhoai_version(version_str) -> RhoaiVersion  [line 71]
    version_gte_threshold(version) -> bool  [line 86]
    check_image_name_vs_component_name(component) -> str | None  [line 108]
    reconcile_component_version(component, version) -> str | None  [line 126]
    compute_effective_until(base_date_str) -> str  [line 145]
    detect_fbc(components) -> bool  [line 165]
    determine_workflow(rule) -> tuple[str | None, list[dict]]  [line 170]
    workflow_has_step(workflow, step_id) -> bool  [line 188]
    workflow_get_step(workflow, step_id) -> dict | None  [line 193]
    workflow_is_self_service(workflow) -> bool  [line 201]
    lookup_component_names(image_base, rhoai_versions, rpa_dir) -> dict[str, list[str]]  [line 209]
    check_rhoaieng_ticket_type(rhoaieng_url) -> dict | None  [line 329]
    build_confirmation_summary(rule, components, version, effective_until, workflow_steps, rhoaieng_info) -> list[str]  [line 373]
    validate_all(args) -> dict  [line 402]
    parse_args() -> argparse.Namespace  [line 560]
    main() -> int  [line 606]

INTERNAL SECTIONS:
    RhoaiVersion: _search_rpa_file, _search_pds_template

DEPENDENCIES: argparse, conforma_context_ops, datetime, json, os, pathlib, re, sys, typing

"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import _setup_env  # noqa: F401 -- adds shared scripts/ to sys.path

import conforma_context_ops  # noqa: E402

# Relative paths within a konflux-release-data clone for component name lookups.
# RPA = ReleasePlanAdmission (primary source, version-specific files)
# PDS = ProjectDevelopmentStream source files (fallback, uses {{.versionName}} placeholders)
#       These are the authoritative source; the auto-generated/ folder is derived from them.
# These are populated by Konflux tenant env discovery (or manually via ~/.conforma/.env).
_KONFLUX_CLUSTER_DOMAIN = os.environ.get("KONFLUX_CLUSTER_DOMAIN", "")
_KONFLUX_CLUSTER_ID = os.environ.get("KONFLUX_CLUSTER_ID", "")
_TENANT = os.environ.get("KONFLUX_TENANT", "")
KONFLUX_RPA_SUBPATH = os.environ.get(
    "KONFLUX_RPA_SUBPATH",
    f"config/{_KONFLUX_CLUSTER_DOMAIN}/product/ReleasePlanAdmission" if _KONFLUX_CLUSTER_DOMAIN else "",
)
KONFLUX_PDS_SUBPATH = os.environ.get(
    "KONFLUX_PDS_SUBPATH",
    f"tenants-config/cluster/{_KONFLUX_CLUSTER_ID}/tenants/{_TENANT}" if _KONFLUX_CLUSTER_ID and _TENANT else "",
)

APPROVAL_THRESHOLD_VERSION = (3, 5, "ea", 1)


class RhoaiVersion(NamedTuple):
    major: int
    minor: int
    qualifier: str
    patch: int

    def __str__(self) -> str:
        base = f"rhoai-{self.major}.{self.minor}"
        if self.qualifier:
            return f"{base}-{self.qualifier}.{self.patch}"
        return base

    def to_component_suffix(self) -> str:
        """Convert version to the suffix used in component names.

        rhoai-3.3 -> v3-3
        rhoai-3.5-ea.1 -> v3-5-ea-1
        """
        base = f"v{self.major}-{self.minor}"
        if self.qualifier:
            return f"{base}-{self.qualifier}-{self.patch}"
        return base


def parse_rhoai_version(version_str: str) -> RhoaiVersion:
    """Parse a version string like 'rhoai-3.3' or 'rhoai-3.5-ea.1'."""
    stripped = version_str.removeprefix("rhoai-")
    match = re.match(r"^(\d+)\.(\d+)(?:-([a-z]+)\.(\d+))?$", stripped)
    if not match:
        raise ValueError(
            f"Invalid RHOAI version format: '{version_str}'. "
            "Expected: rhoai-X.Y or rhoai-X.Y-qualifier.N (e.g., rhoai-3.3, rhoai-3.5-ea.1)"
        )
    major, minor = int(match.group(1)), int(match.group(2))
    qualifier = match.group(3) or ""
    patch = int(match.group(4)) if match.group(4) else 0
    return RhoaiVersion(major, minor, qualifier, patch)


def version_gte_threshold(version: RhoaiVersion) -> bool:
    """Check if version >= 3.5-ea.1 (approval threshold)."""
    v_tuple = (version.major, version.minor, version.qualifier or "z", version.patch)
    threshold = (
        APPROVAL_THRESHOLD_VERSION[0],
        APPROVAL_THRESHOLD_VERSION[1],
        APPROVAL_THRESHOLD_VERSION[2],
        APPROVAL_THRESHOLD_VERSION[3],
    )
    if v_tuple[0] != threshold[0]:
        return v_tuple[0] > threshold[0]
    if v_tuple[1] != threshold[1]:
        return v_tuple[1] > threshold[1]
    if v_tuple[2] == "z" and threshold[2] != "z":
        return True
    if v_tuple[2] != "z" and threshold[2] == "z":
        return False
    if v_tuple[2] != threshold[2]:
        return v_tuple[2] > threshold[2]
    return v_tuple[3] >= threshold[3]


def check_image_name_vs_component_name(component: str) -> str | None:
    """Detect if a name looks like a container image name rather than a Konflux component name.

    Container image names (e.g. -rhel9, -ubi9 suffixed) are not Konflux
    component names. Konflux component names always end in -vX-Y (e.g. -v2-25,
    -v3-3, -v3-5-ea-1) and are the correct identifiers for exception Merge Requests.
    """
    if re.search(r"-rhel\d+$", component) or re.search(r"-ubi\d+$", component):
        if not re.search(r"v\d+-\d+", component):
            return (
                f"'{component}' looks like a container image name (ends in "
                f"-rhel9/-ubi9 without a version suffix), not a Konflux component name. "
                f"Konflux component names always include a version suffix like -v2-25 "
                f"or -v3-3. Use the Konflux component name, not the container image name."
            )
    return None


def reconcile_component_version(component: str, version: RhoaiVersion) -> str | None:
    """Check if component name contains version info matching the RHOAI version.

    Returns None if valid, or an error message if mismatched.
    """
    expected_suffix = version.to_component_suffix()
    version_pattern = re.compile(r"v\d+-\d+(?:-[a-z]+-\d+)?")
    match = version_pattern.search(component)
    if not match:
        return None
    actual_suffix = match.group(0)
    if actual_suffix != expected_suffix:
        return (
            f"Component '{component}' contains version '{actual_suffix}' "
            f"but --rhoai-version is '{version}' (expected suffix '{expected_suffix}')"
        )
    return None


def compute_effective_until(base_date_str: str, *, eos_buffer: bool = False) -> str:
    """Parse a base date and return RFC3339 timestamp.

    When eos_buffer=True (date sourced from RHOAI end-of-support table), adds
    a +7 day buffer. When eos_buffer=False (user-provided or Jira-sourced
    date), the date is used as-is.
    """
    try:
        base_date = datetime.strptime(base_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"--effective-until-date must be YYYY-MM-DD format, got: '{base_date_str}'") from exc

    if base_date.date() <= datetime.now(timezone.utc).date():
        raise ValueError(f"--effective-until-date must be a future date, got: '{base_date_str}'")

    if eos_buffer:
        base_date += timedelta(days=7)
    return base_date.strftime("%Y-%m-%dT00:00:00Z")


def detect_fbc(components: list[str]) -> bool:
    """Detect if any component is an FBC fragment."""
    return any("fbc" in c.lower() for c in components)


def determine_workflow(rule: str) -> tuple[str | None, list[dict]]:
    """Determine the workflow steps from exception_templates.yaml.

    Returns (category_id, workflow_steps). If no template matches, returns
    (None, []) and the caller should treat it as an error.
    """
    from create_jira_ticket import _load_templates, match_template_category

    category_id = match_template_category(rule)
    if not category_id:
        return None, []

    data = _load_templates()
    cat = data.get("categories", {}).get(category_id, {})
    workflow = cat.get("workflow", [])
    return category_id, workflow


def workflow_has_step(workflow: list[dict], step_id: str) -> bool:
    """Check if a workflow contains a step with the given ID."""
    return any(s.get("step") == step_id for s in workflow)


def workflow_get_step(workflow: list[dict], step_id: str) -> dict | None:
    """Get a specific step from the workflow by ID."""
    for s in workflow:
        if s.get("step") == step_id:
            return s
    return None


def workflow_is_self_service(workflow: list[dict]) -> bool:
    """A workflow is self-service if it has no ProdSec or OCPEXCEPT step."""
    return (
        not workflow_has_step(workflow, "prodsec_form_submission")
        and not workflow_has_step(workflow, "psx_exception_jira")
    )


def lookup_component_names(
    image_base: str, rhoai_versions: list[str], rpa_dir: str | None = None
) -> dict[str, list[str]]:
    """Look up Konflux component names from ReleasePlanAdmission and PDS files.

    Given a container image base name (e.g. 'odh-openvino-model-server') and
    a list of RHOAI versions, search:
      1. ReleasePlanAdmission YAML files (primary)
      2. ProjectDevelopmentStream template files (fallback if RPA returns empty)

    Args:
        image_base: Base image name without -rhel9 suffix or version.
        rhoai_versions: List of version strings (e.g. ['rhoai-2.25', 'rhoai-3.3']).
        rpa_dir: Path to the konflux-release-data clone root. If None, uses
                 the standard local checkout path.

    Returns:
        Dict mapping version -> list of matching component names found.
    """
    from pathlib import Path

    if rpa_dir is None:
        clone_root = conforma_context_ops.discover_work_dir() / "konflux-release-data"
    else:
        rpa_dir_path = Path(rpa_dir)
        if rpa_dir_path.name == "rhoai" or KONFLUX_RPA_SUBPATH.endswith(str(rpa_dir_path.relative_to(rpa_dir_path.anchor))):
            clone_root = rpa_dir_path
            while clone_root.name != "konflux-release-data" and clone_root != clone_root.parent:
                clone_root = clone_root.parent
            if clone_root.name != "konflux-release-data":
                clone_root = rpa_dir_path
        else:
            clone_root = rpa_dir_path

    resolved_root = clone_root.resolve()
    rpa_path = (resolved_root / KONFLUX_RPA_SUBPATH).resolve()
    pds_path = (resolved_root / KONFLUX_PDS_SUBPATH).resolve()
    if not rpa_path.is_relative_to(resolved_root) or not pds_path.is_relative_to(resolved_root):
        raise ValueError(
            f"Path traversal detected: rpa_path={rpa_path} or pds_path={pds_path} "
            f"escapes clone_root={resolved_root}"
        )

    results: dict[str, list[str]] = {}
    for ver_str in rhoai_versions:
        try:
            version = parse_rhoai_version(ver_str)
        except ValueError:
            results[ver_str] = []
            continue

        suffix = version.to_component_suffix()
        ver_slug = f"v{version.major}-{version.minor}"
        if version.qualifier:
            ver_slug = f"{ver_slug}-{version.qualifier}-{version.patch}"

        matches = _search_rpa_file(rpa_path, ver_slug, image_base, suffix)

        if not matches:
            matches = _search_pds_template(pds_path, ver_slug, image_base, suffix)

        results[ver_str] = matches

    return results


def _search_rpa_file(rpa_path: Path, ver_slug: str, image_base: str, suffix: str) -> list[str]:
    """Search ReleasePlanAdmission file for component names."""
    rpa_file = rpa_path / f"rhoai-onprem-{ver_slug}-components-prod.yaml"
    if not rpa_file.exists():
        return []

    content = rpa_file.read_text(encoding="utf-8")
    matches = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- name:"):
            comp_name = stripped.removeprefix("- name:").strip()
            if image_base in comp_name and suffix in comp_name:
                matches.append(comp_name)
    return matches


def _search_pds_template(pds_path: Path, ver_slug: str, image_base: str, suffix: str) -> list[str]:
    """Search ProjectDevelopmentStream source file for component names.

    Source PDS files live at:
      tenants-config/cluster/<CLUSTER_ID>/tenants/<NAMESPACE>/v<X>.<Y>/
        ProjectDevelopmentStream-v<X>.<Y>.yaml
    They use {{.versionName}} as a placeholder which resolves to the
    hyphenated version suffix (e.g. 'v3-3'). We substitute it to derive
    real component names.
    """
    # Convert hyphenated slug (v3-3, v3-4-ea-1) to dotted dir name (v3.3, v3.4-ea.1)
    # Pattern: numeric hyphens become dots, the '-ea' separator stays as hyphen.
    # e.g. v3-3 → v3.3, v3-4-ea-1 → v3.4-ea.1, v3-5-ea-2 → v3.5-ea.2
    if "-ea-" in ver_slug:
        base, ea_num = ver_slug.rsplit("-ea-", 1)
        base_dotted = base.replace("-", ".", 1)
        dotted_ver = f"{base_dotted}-ea.{ea_num}"
    else:
        dotted_ver = ver_slug.replace("-", ".", 1)

    pds_file = pds_path / dotted_ver / f"ProjectDevelopmentStream-{dotted_ver}.yaml"
    if not pds_file.exists():
        return []

    content = pds_file.read_text(encoding="utf-8")
    matches = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:") or stripped.startswith("componentName:"):
            value = stripped.split(":", 1)[1].strip()
            resolved = value.replace("{{.versionName}}", suffix)
            if image_base in resolved and suffix in resolved:
                if resolved not in matches:
                    matches.append(resolved)
    return matches


def check_rhoaieng_ticket_type(rhoaieng_url: str | None) -> dict | None:
    """Check if the provided RHOAIENG ticket is the expected type (Blocker Bug).

    Returns a dict with ticket metadata and a warning if the type is unexpected,
    or None if no URL provided.
    """
    if not rhoaieng_url:
        return None

    ticket_key_match = re.search(r"(RHOAIENG-\d+)", rhoaieng_url)
    if not ticket_key_match:
        return {"warning": f"Cannot extract ticket key from URL: {rhoaieng_url}"}

    ticket_key = ticket_key_match.group(1)
    try:
        import jira_ops

        issue_data = jira_ops.get_issue(ticket_key, fields=["priority"])
        if issue_data.get("error"):
            return {"warning": f"Cannot fetch {ticket_key}: {issue_data['error']}"}

        issue_type = issue_data.get("issue_type", "Unknown")
        priority = issue_data.get("priority", "Unknown")
        summary = issue_data.get("summary", "")

        info: dict = {
            "key": ticket_key,
            "type": issue_type,
            "priority": priority,
            "summary": summary,
        }

        if issue_type != "Bug" or priority != "Blocker":
            info["warning"] = (
                f"{ticket_key} is a '{issue_type}' with priority '{priority}'. "
                f"The exception process expects a Blocker Bug (cloned from RHOAIENG-62569). "
                f"Options: (a) create a proper Blocker Bug and link to this ticket, "
                f"or (b) use as-is (non-standard). Confirm with user."
            )
        return info
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"warning": f"Cannot validate {ticket_key} type: {exc}"}


def build_confirmation_summary(
    rule: str,
    components: list[str],
    version: str,
    effective_until: str | None,
    workflow_steps: list[dict],
    rhoaieng_info: dict | None,
) -> list[str]:
    """Build a list of items the agent MUST present to the user for confirmation.

    The agent should show each item and wait for explicit user approval before proceeding.
    """
    items = []
    items.append(f"Rule: {rule}")
    items.append(f"Components: {', '.join(components)}")
    items.append(f"RHOAI version: {version}")
    if effective_until:
        items.append(f"effectiveUntil: {effective_until}")
    step_names = [s.get("step", "?") for s in workflow_steps]
    items.append(f"Workflow steps: {' -> '.join(step_names)}")
    if rhoaieng_info:
        items.append(
            f"RHOAIENG ticket: {rhoaieng_info.get('key', 'N/A')} "
            f"(type={rhoaieng_info.get('type', '?')}, "
            f"priority={rhoaieng_info.get('priority', '?')})"
        )
    return items


def validate_all(args: argparse.Namespace) -> dict:
    """Run all validations and return structured result."""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        version = parse_rhoai_version(args.rhoai_version)
    except ValueError as exc:
        errors.append(str(exc))
        return {"valid": False, "errors": errors, "warnings": warnings}

    components = [c.strip() for c in args.components.split(",") if c.strip()]
    if not components:
        errors.append("--components must contain at least one component name")

    for comp in components:
        image_name_error = check_image_name_vs_component_name(comp)
        if image_name_error:
            errors.append(image_name_error)
        mismatch = reconcile_component_version(comp, version)
        if mismatch:
            errors.append(mismatch)

    category_id, workflow_steps = determine_workflow(args.rule)
    if not category_id:
        errors.append(
            f"Rule '{args.rule}' does not match any template in exception_templates.yaml "
            f"and no catch-all 'other' category is available. "
            f"Add a matching category before creating an exception."
        )
        return {"valid": False, "errors": errors, "warnings": warnings}

    is_other_category = category_id == "other"
    if is_other_category:
        from create_jira_ticket import lookup_rule_in_catalog

        rule_info = lookup_rule_in_catalog(args.rule)
        if rule_info:
            warnings.append(
                f"Rule '{args.rule}' matched as '{rule_info['name']}' from the "
                f"Conforma redhat collection. No specific template exists — using "
                f"catch-all 'other' category. The agent must gather all exception "
                f"text fields (scope, risk, remediation, impact) from the user. "
                f"Docs: {rule_info.get('docs', 'N/A')}"
            )
        else:
            warnings.append(
                f"Rule '{args.rule}' is not in the known Conforma redhat collection "
                f"rule catalog. Using catch-all 'other' category. Confirm with the "
                f"user that this is the correct rule code. The agent must gather all "
                f"exception text fields from the user."
            )

    is_self_service = workflow_is_self_service(workflow_steps)

    # --- Stage workflow override: filter steps not applicable to stage ---
    if args.environment == "stage":
        stage_drop_steps = {"rhoaieng_approval_jira", "prodsec_form_submission", "psx_exception_jira"}
        workflow_steps = [s for s in workflow_steps if s.get("step") not in stage_drop_steps]
        for s in workflow_steps:
            if s.get("step") == "exception_merge_request":
                s["self_service"] = True
        is_self_service = True

    from create_jira_ticket import _load_templates

    data = _load_templates()
    cat = data.get("categories", {}).get(category_id, {})
    applicable_justifications = cat.get("applicable_justifications", [])

    justification_id = getattr(args, "justification", None)
    if justification_id:
        if justification_id not in applicable_justifications:
            errors.append(
                f"Justification '{justification_id}' is not applicable for category "
                f"'{category_id}'. Valid choices: {applicable_justifications}"
            )
    elif applicable_justifications:
        justification_id = applicable_justifications[0]

    effective_until = None
    if not is_self_service or args.effective_until_date:
        if not args.effective_until_date:
            errors.append("--effective-until-date is required")
        else:
            try:
                effective_until = compute_effective_until(args.effective_until_date)
            except ValueError as exc:
                errors.append(str(exc))

    is_fbc = detect_fbc(components)
    requires_approval = version_gte_threshold(version) and not is_self_service
    if args.environment == "stage":
        requires_approval = False

    # --fix-target-version is mandatory
    fix_target_version = getattr(args, "fix_target_version", None)
    if not fix_target_version:
        errors.append("--fix-target-version is required (target RHOAI version for the fix)")

    # Resolve violation jira URL from new or deprecated flags
    violation_jira_url = getattr(args, "violation_jira_url", None) or getattr(args, "rhoaieng_url", None)

    rhoaieng_info = check_rhoaieng_ticket_type(violation_jira_url)
    if rhoaieng_info and rhoaieng_info.get("warning"):
        warnings.append(rhoaieng_info["warning"])

    confirmation_items = build_confirmation_summary(
        rule=args.rule,
        components=components,
        version=str(version),
        effective_until=effective_until,
        workflow_steps=workflow_steps,
        rhoaieng_info=rhoaieng_info,
    )

    rule_catalog_info = None
    if is_other_category:
        rule_catalog_info = lookup_rule_in_catalog(args.rule)

    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "confirmation_required": confirmation_items,
        "workflow_steps": workflow_steps,
        "workflow_category": category_id,
        "is_other_category": is_other_category,
        "rule_catalog_info": rule_catalog_info,
        "version": str(version),
        "version_parsed": {
            "major": version.major,
            "minor": version.minor,
            "qualifier": version.qualifier,
            "patch": version.patch,
        },
        "components": components,
        "rule": args.rule,
        "effective_until": effective_until,
        "effective_until_base": args.effective_until_date,
        "is_fbc": is_fbc,
        "is_self_service": is_self_service,
        "requires_approval": requires_approval,
        "justification_id": justification_id,
        "applicable_justifications": applicable_justifications,
        "environment": args.environment,
        "rhoaieng_url": violation_jira_url,
        "violation_jira_url": violation_jira_url,
        "remediation_jira_url": getattr(args, "remediation_jira_url", None),
        "approval_jira_url": getattr(args, "approval_jira_url", None),
        "fix_target_version": fix_target_version,
        "psx_url": args.psx_url,
        "rhoaieng_info": rhoaieng_info,
        "dry_run": args.dry_run,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate inputs for conforma-exception")
    parser.add_argument("--rhoai-version", required=True, help="e.g., rhoai-3.3")
    parser.add_argument("--rule", required=True, help="Policy rule to exempt")
    parser.add_argument("--components", required=True, help="Comma-separated Konflux component names")
    parser.add_argument(
        "--effective-until-date", help="Date YYYY-MM-DD (used as-is; +7 day buffer only applies to EOS-sourced dates)"
    )
    parser.add_argument(
        "--environment",
        default="prod",
        choices=["prod", "stage"],
        help="Target environment (default: prod)",
    )
    parser.add_argument("--rhoaieng-url", help="Deprecated alias for --violation-jira-url")
    parser.add_argument("--violation-jira-url", help="Existing RHOAIENG violation report ticket URL")
    parser.add_argument("--remediation-jira-url", help="Existing RHOAIENG remediation ticket URL")
    parser.add_argument("--approval-jira-url", help="Existing RHOAIENG approval ticket URL")
    parser.add_argument("--fix-target-version", help="Target RHOAI version for the fix (required)")
    parser.add_argument("--psx-url", help="Existing PSX/OCPEXCEPT ticket URL")
    parser.add_argument(
        "--justification", default=None, help="Justification template ID (e.g., dev_preview, code_frozen)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating anything")
    parser.add_argument(
        "--lookup-components",
        default=None,
        help=(
            "Image base name to look up in ReleasePlanAdmission files "
            "(e.g. 'odh-openvino-model-server'). Returns matching Konflux "
            "component names for confirmation."
        ),
    )
    parser.add_argument(
        "--lookup-versions",
        default=None,
        help="Comma-separated RHOAI versions for component lookup (used with --lookup-components)",
    )
    parser.add_argument(
        "--rpa-dir",
        default=None,
        help="Path to ReleasePlanAdmission/rhoai/ directory (for component lookup)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.lookup_components:
        versions = (
            [v.strip() for v in args.lookup_versions.split(",")] if args.lookup_versions else [args.rhoai_version]
        )
        found = lookup_component_names(args.lookup_components, versions, args.rpa_dir)
        print(json.dumps({"lookup_results": found}, indent=2))
        return 0

    result = validate_all(args)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
