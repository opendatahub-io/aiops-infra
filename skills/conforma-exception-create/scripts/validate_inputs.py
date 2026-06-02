#!/usr/bin/env python3
"""Validate inputs for the conforma-exception-create skill.

Handles:
- RHOAI version parsing and comparison
- Component name vs version reconciliation
- effectiveUntil date calculation (+7 days buffer)
- Justification enum validation
- FBC detection
- Self-service rule eligibility check
- Path determination (A, B, or C)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

JUSTIFICATIONS = {
    "1": (
        "violation was not fixed in time before code-freeze of the current"
        " rhoai release, it is planned to be fixed in the next release"
    ),
    "2": (
        "violation can't be fixed in this rhoai release as it's already been"
        " code-frozen/released and major code changes are not allowed in"
        " subreleases/z-stream releases"
    ),
}

SELF_SERVICE_RULES = frozenset(
    [
        "schedule.weekday_restriction",
        "test.no_failed_tests:fbc-target-index-pruning-check",
    ]
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

    Container image names end in -rhel9 (or -ubi9) without a version suffix.
    Konflux component names always end in -vX-Y (e.g. -v2-25, -v3-3, -v3-5-ea-1).
    """
    if re.search(r"-rhel\d+$", component) or re.search(r"-ubi\d+$", component):
        if not re.search(r"v\d+-\d+", component):
            return (
                f"'{component}' looks like a container image name (ends in -rhel9/-ubi9 "
                f"without a version suffix). Konflux component names always include a "
                f"version suffix like -v2-25 or -v3-3. Use the component name, not the "
                f"image name."
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


def compute_effective_until(base_date_str: str) -> str:
    """Add 7 days to the base date and return RFC3339 timestamp."""
    try:
        base_date = datetime.strptime(base_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(
            f"--effective-until-date must be YYYY-MM-DD format, got: '{base_date_str}'"
        ) from exc

    if base_date.date() <= datetime.now(timezone.utc).date():
        raise ValueError(f"--effective-until-date must be a future date, got: '{base_date_str}'")

    effective = base_date + timedelta(days=7)
    return effective.strftime("%Y-%m-%dT00:00:00Z")


def detect_fbc(components: list[str]) -> bool:
    """Detect if any component is an FBC fragment."""
    return any("fbc" in c.lower() for c in components)


def determine_path(rule: str, is_fips: bool, is_self_service: bool) -> str:
    """Determine the exception path (A, B, or C)."""
    if is_self_service or rule in SELF_SERVICE_RULES:
        return "C"
    if is_fips:
        return "B"
    return "A"


def lookup_component_names(
    image_base: str, rhoai_versions: list[str], rpa_dir: str | None = None
) -> dict[str, list[str]]:
    """Look up Konflux component names from ReleasePlanAdmission files.

    Given a container image base name (e.g. 'odh-openvino-model-server') and
    a list of RHOAI versions, search the ReleasePlanAdmission YAML files for
    matching component names.

    Args:
        image_base: Base image name without -rhel9 suffix or version.
        rhoai_versions: List of version strings (e.g. ['rhoai-2.25', 'rhoai-3.3']).
        rpa_dir: Path to the ReleasePlanAdmission/rhoai/ directory. If None, uses
                 the standard local checkout path.

    Returns:
        Dict mapping version -> list of matching component names found.
    """
    from pathlib import Path

    if rpa_dir is None:
        rpa_dir_path = Path.home() / (
            "dev/gitlab/releng/konflux-release-data/config/"
            "stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai"
        )
    else:
        rpa_dir_path = Path(rpa_dir)

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

        rpa_file = rpa_dir_path / f"rhoai-onprem-{ver_slug}-components-prod.yaml"
        if not rpa_file.exists():
            results[ver_str] = []
            continue

        content = rpa_file.read_text(encoding="utf-8")
        matches = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- name:"):
                comp_name = stripped.removeprefix("- name:").strip()
                if image_base in comp_name and suffix in comp_name:
                    matches.append(comp_name)
        results[ver_str] = matches

    return results


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
        from cli_runner import run_acli

        result = run_acli(
            ["jira", "workitem", "view", ticket_key, "--json"], timeout=30
        )
        if result.returncode != 0:
            return {"warning": f"Cannot fetch {ticket_key}: {result.stderr.strip()}"}

        import json as _json

        data = _json.loads(result.stdout)
        fields = data.get("fields", {})
        issue_type = fields.get("issuetype", {}).get("name", "Unknown")
        priority = fields.get("priority", {}).get("name", "Unknown")
        summary = fields.get("summary", "")

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
    except Exception as exc:
        return {"warning": f"Cannot validate {ticket_key} type: {exc}"}


def build_confirmation_summary(
    rule: str,
    components: list[str],
    version: str,
    effective_until: str | None,
    path: str,
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
        items.append(f"effectiveUntil: {effective_until} (base date + 7 days)")
    items.append(f"Exception path: {path}")
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

    path = determine_path(args.rule, args.fips, args.self_service)

    if path in ("A", "B") and not args.justification:
        errors.append("--justification is required for Paths A and B (non-self-service)")
    if args.justification and args.justification not in JUSTIFICATIONS:
        errors.append(f"--justification must be '1' or '2', got: '{args.justification}'")

    effective_until = None
    if path != "C" or args.effective_until_date:
        if not args.effective_until_date:
            errors.append("--effective-until-date is required")
        else:
            try:
                effective_until = compute_effective_until(args.effective_until_date)
            except ValueError as exc:
                errors.append(str(exc))

    is_fbc = detect_fbc(components)
    requires_approval = version_gte_threshold(version) and path != "C"

    if path == "C" and args.rule not in SELF_SERVICE_RULES and not args.self_service:
        warnings.append(
            f"Rule '{args.rule}' is not a known self-service rule. "
            "Use --self-service to force Path C."
        )

    rhoaieng_info = check_rhoaieng_ticket_type(args.rhoaieng_url)
    if rhoaieng_info and rhoaieng_info.get("warning"):
        warnings.append(rhoaieng_info["warning"])

    confirmation_items = build_confirmation_summary(
        rule=args.rule,
        components=components,
        version=str(version),
        effective_until=effective_until,
        path=path,
        rhoaieng_info=rhoaieng_info,
    )

    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "confirmation_required": confirmation_items,
        "path": path,
        "version": str(version),
        "version_parsed": {
            "major": version.major,
            "minor": version.minor,
            "qualifier": version.qualifier,
            "patch": version.patch,
        },
        "components": components,
        "rule": args.rule,
        "justification": JUSTIFICATIONS.get(args.justification, ""),
        "justification_id": args.justification,
        "effective_until": effective_until,
        "effective_until_base": args.effective_until_date,
        "is_fbc": is_fbc,
        "is_fips": args.fips,
        "is_self_service": path == "C",
        "requires_approval": requires_approval,
        "environment": args.environment,
        "rhoaieng_url": args.rhoaieng_url,
        "psx_url": args.psx_url,
        "rhoaieng_info": rhoaieng_info,
        "dry_run": args.dry_run,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate inputs for conforma-exception-create")
    parser.add_argument("--rhoai-version", required=True, help="e.g., rhoai-3.3")
    parser.add_argument("--rule", required=True, help="Policy rule to exempt")
    parser.add_argument(
        "--components", required=True, help="Comma-separated Konflux component names"
    )
    parser.add_argument("--justification", help="'1' or '2' (required for Paths A/B)")
    parser.add_argument("--effective-until-date", help="Base date YYYY-MM-DD (script adds +7 days)")
    parser.add_argument(
        "--environment",
        default="prod",
        choices=["prod", "stage"],
        help="Target environment (default: prod)",
    )
    parser.add_argument("--rhoaieng-url", help="Existing RHOAIENG ticket URL")
    parser.add_argument("--psx-url", help="Existing PSX/OCPEXCEPT ticket URL")
    parser.add_argument("--fips", action="store_true", help="FIPS exception (routes to OCPEXCEPT)")
    parser.add_argument("--self-service", action="store_true", help="Force self-service Path C")
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
            [v.strip() for v in args.lookup_versions.split(",")]
            if args.lookup_versions
            else [args.rhoai_version]
        )
        found = lookup_component_names(args.lookup_components, versions, args.rpa_dir)
        print(json.dumps({"lookup_results": found}, indent=2))
        return 0

    result = validate_all(args)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
