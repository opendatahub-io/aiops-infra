#!/usr/bin/env python3
"""generate_resolution_guide — Generate a unified Conforma Resolution Guide.

PUBLIC API:
    generate_resolution_guide(violations_yaml_path, coverage_json_path, reports_dir, catalog_path, release, source_path, source_created_at, source_sha, policy_dir_url, policy_files, tooling_health_path, todo_file, analysis_output_file, end_of_support, confirmation_display, code_freeze_date, upcoming_release_date) -> str  [line 1213]
    main() -> int  [line 1364]

INTERNAL SECTIONS:
    Main: _load_catalog, _match_catalog_entry, _match_fallback_reference, _match_known_false_alert, _render_metadata_header, ... (+20 more)

DEPENDENCIES: analyze_csv_report, argparse, conforma_constants, conforma_context_ops, conforma_counting, datetime, json, parse_violations, pathlib, re

"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _setup_env  # noqa: F401, E402

import conforma_context_ops  # noqa: E402
import conforma_counting  # noqa: E402
import release_dates  # noqa: E402
import yaml  # noqa: E402
from parse_violations import build_semantic_detail_lookup  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import analyze_csv_report as analysis  # noqa: E402

from conforma_constants import (  # noqa: E402
    CONFORMA_REPORTER_URL,
    RESOLUTION_GUIDE_FILENAME,
    TODO_PREVIEW_FILENAME,
    VERIFY_NEXT_STEP,
)

from guide_renderers import render_metadata_header as _render_metadata_header  # noqa: F401 — backward compat re-export
from guide_renderers import render_key_takeaways as _render_key_takeaways  # noqa: F401 — backward compat re-export
from guide_renderers import render_summary as _render_summary  # noqa: F401 — backward compat re-export
from guide_renderers import render_coverage_table as _render_coverage_table  # noqa: F401 — backward compat re-export
from guide_renderers import render_work_scope as _render_work_scope  # noqa: F401 — backward compat re-export
from guide_renderers import render_resolution_guide as _render_resolution_guide  # noqa: F401 — backward compat re-export
from guide_renderers import render_divergence_warning as _render_divergence_warning  # noqa: F401 — backward compat re-export
from guide_renderers import render_excepted_violation as _render_excepted_violation  # noqa: F401 — backward compat re-export
from guide_renderers import render_components_table as _render_components_table  # noqa: F401 — backward compat re-export
from guide_renderers import render_partial_coverage_header as _render_partial_coverage_header  # noqa: F401 — backward compat re-export
from guide_renderers import render_known_false_alerts as _render_known_false_alerts  # noqa: F401 — backward compat re-export
from guide_renderers import render_cataloged_violation as _render_cataloged_violation  # noqa: F401 — backward compat re-export
from guide_renderers import render_uncataloged_violation as _render_uncataloged_violation  # noqa: F401 — backward compat re-export
from guide_renderers import render_warnings_section as _render_warnings_section  # noqa: F401 — backward compat re-export
from guide_renderers import render_statistical_breakdown as _render_statistical_breakdown  # noqa: F401 — backward compat re-export
from guide_renderers import render_tooling_health as _render_tooling_health  # noqa: F401 — backward compat re-export
from guide_renderers import write_todo_preview as _write_todo_preview  # noqa: F401 — backward compat re-export
from guide_renderers import render_todo as _render_todo  # noqa: F401 — backward compat re-export


def _load_catalog(catalog_path: Path) -> dict:
    """Load the violation catalog YAML."""
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    return data


def _match_catalog_entry(rule_code: str, catalog: dict) -> dict | None:
    """Find a catalog violation entry matching the given rule code.

    Tries exact match on conforma_rule_codes first, then base_code prefix match.
    """
    base_code = rule_code.split(":")[0]
    violations = catalog.get("violations", [])

    for entry in violations:
        codes = entry.get("conforma_rule_codes", [])
        if rule_code in codes or base_code in codes:
            return entry

    for entry in violations:
        codes = entry.get("conforma_rule_codes", [])
        for code in codes:
            if base_code.startswith(code) or code.startswith(base_code):
                return entry

    return None


def _match_fallback_reference(rule_code: str, catalog: dict) -> dict | None:
    """Find the longest-matching fallback reference for a rule code."""
    base_code = rule_code.split(":")[0]
    fallbacks = catalog.get("fallback_references", [])

    best_match = None
    best_len = 0

    for fb in fallbacks:
        prefix = fb.get("code_prefix", "")
        if base_code.startswith(prefix) or base_code == prefix:
            if len(prefix) > best_len:
                best_match = fb
                best_len = len(prefix)

    return best_match


def _match_known_false_alert(rule_code: str, component: str, catalog: dict) -> dict | None:
    """Check if a violation matches a known false alert."""
    base_code = rule_code.split(":")[0]
    alerts = catalog.get("known_false_alerts", [])

    for alert in alerts:
        alert_codes = alert.get("conforma_rule_codes", [])
        if not alert_codes or base_code in alert_codes or rule_code in alert_codes:
            applies_to = alert.get("applies_to", "")
            if applies_to:
                import fnmatch

                if fnmatch.fnmatch(component, applies_to):
                    return alert
    return None


def _violation_anchor(rule: str) -> str:
    """Return a stable HTML id for a violation section anchor.

    Replaces ``.`` and ``:`` with ``-`` so the anchor is safe in URI
    fragments (colons have special meaning; dots break CSS selectors).
    The ``violation-`` prefix scopes it away from any other document ids.

    Examples:
        hermetic_task.hermetic                        -> violation-hermetic_task-hermetic
        rpm_signature.allowed:9386b48a1a693c5c        -> violation-rpm_signature-allowed-9386b48a1a693c5c
    """
    safe = rule.replace(".", "-").replace(":", "-")
    return f"violation-{safe}"


def _component_stem(name: str) -> str:
    """Strip the RHOAI version suffix from a Konflux component name.

    The suffix always starts with ``-v{major}-{minor}`` (e.g. ``-v3-5``,
    ``-v3-5-ea-2``, ``-v2-25``).  Requiring two hyphen-separated digit groups
    after ``v`` prevents false-stripping on mid-name segments such as
    ``-vllm`` (letter follows v) or ``-cuda121`` (c follows cuda).

    Examples:
        odh-vllm-cpu-v3-5-ea-2               -> odh-vllm-cpu
        odh-workbench-jupyter-minimal-v3-4    -> odh-workbench-jupyter-minimal
        odh-pipeline-runtime-py312-v2-25      -> odh-pipeline-runtime-py312
        odh-generic-tool (no suffix)          -> odh-generic-tool  (unchanged)
    """
    return re.sub(r"-v\d+-\d+.*$", "", name)


def _tooling_health_executive_line(tooling_health_data: dict) -> str | None:
    """Generate a one-liner for the Executive Summary when tooling is unhealthy."""
    tools = tooling_health_data.get("tools", [])
    unhealthy = [t for t in tools if t.get("health", {}).get("status") in ("unhealthy", "error")]
    if not unhealthy:
        return None

    parts = []
    for tool in unhealthy:
        name = tool.get("name", "unknown")
        health = tool.get("health", {})
        last_success = health.get("last_success")
        latest_run = tool.get("latest_run")

        if last_success:
            ls_timestamp = last_success.get("completed_at", "")[:16].replace("T", " ")
            ls_url = last_success.get("url")
            ls_label = f"[{ls_timestamp}]({ls_url})" if ls_url else ls_timestamp
        else:
            ls_label = "unknown"
        ls_info = f", last success: {ls_label}"

        fail_info = ""
        if latest_run:
            fail_timestamp = latest_run.get("updated_at", latest_run.get("created_at", ""))[:16].replace("T", " ")
            fail_url = latest_run.get("url")
            fail_label = f"[{fail_timestamp}]({fail_url})" if fail_url else fail_timestamp
            fail_info = f", latest failure: {fail_label}"

        parts.append(f"{name} workflow failing{ls_info}{fail_info}")

    return f"- **Tooling unhealthy** -- {'; '.join(parts)}"


def generate_resolution_guide(
    violations_yaml_path: str,
    coverage_json_path: str,
    reports_dir: str,
    catalog_path: str,
    release: str,
    source_path: str,
    source_created_at: str,
    source_sha: str = "",
    policy_dir_url: str = "",
    policy_files: list[dict[str, str]] | None = None,
    tooling_health_path: str | None = None,
    todo_file: str | None = None,
    analysis_output_file: str | None = None,
    end_of_support: str = "",
    confirmation_display: str = "",
    code_freeze_date: str = "",
    upcoming_release_date: str = "",
) -> str:
    """Generate the full resolution guide markdown content.

    When ``todo_file`` is provided, writes a TODO preview file (action
    items, metadata header, violations breakdown) for chat display.
    The full resolution guide (all sections) is always generated as the
    primary output submitted to GitHub.
    """
    violations_yaml = Path(violations_yaml_path)
    coverage_json = Path(coverage_json_path)
    reports = Path(reports_dir)
    catalog_file = Path(catalog_path)

    if not violations_yaml.exists():
        raise FileNotFoundError(f"Violations YAML not found: {violations_yaml}")
    if not coverage_json.exists():
        raise FileNotFoundError(f"Coverage JSON not found: {coverage_json}")
    if not reports.is_dir():
        raise FileNotFoundError(f"Reports directory not found: {reports}")
    if not catalog_file.exists():
        raise FileNotFoundError(f"Violation catalog not found: {catalog_file}")

    coverage_data = json.loads(coverage_json.read_text(encoding="utf-8"))
    catalog = _load_catalog(catalog_file)

    # Load component ownership from violations YAML
    viol_data = yaml.safe_load(violations_yaml.read_text(encoding="utf-8"))
    component_owners: dict[str, str | None] = {}
    by_component = viol_data.get("violation_data", {}).get("violations_by_component", {})
    for comp, info in by_component.items():
        jc = info.get("jira_component")
        if jc is not None:
            component_owners[comp] = jc

    # Load tooling health data if provided
    tooling_health_data: dict | None = None
    if tooling_health_path:
        th_path = Path(tooling_health_path)
        if th_path.exists():
            try:
                tooling_health_data = json.loads(th_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    # Run statistical analysis
    records = analysis.load_reports_dir(reports)
    warnings = analysis.load_warnings_dir(reports)
    analysis_result = analysis.analyze(records, upcoming=warnings)

    # Assemble sections
    ref = source_sha or release
    source_csv_url = f"{CONFORMA_REPORTER_URL}/blob/{ref}/{source_path}"

    # Extract work_scope per rule from violations YAML
    work_scope_by_rule: dict[str, dict] = {}
    by_rule_data = viol_data.get("violation_data", {}).get("violations_by_rule", {})
    for rule, rule_info in by_rule_data.items():
        ws = rule_info.get("work_scope")
        if ws:
            work_scope_by_rule[rule] = ws

    counts = conforma_counting.count_from_records(records, code_field="code")

    metadata_header = _render_metadata_header(release, source_path, source_created_at, source_sha, policy_dir_url, policy_files, end_of_support=end_of_support, confirmation_display=confirmation_display, code_freeze_date=code_freeze_date, upcoming_release_date=upcoming_release_date, total_violations=counts.violations)
    tooling_health = _render_tooling_health(tooling_health_data) if tooling_health_data else ""
    key_takeaways = _render_key_takeaways(coverage_data, analysis_result, counts.by_component_rule, tooling_health_data, violations_yaml_data=viol_data, upcoming_release_date=upcoming_release_date, policy_files=policy_files, release=release)
    summary_metrics = _render_summary(coverage_data, analysis_result, counts.by_component_rule)
    todo = _render_todo(coverage_data, analysis_result, counts.by_component_rule, tooling_health_data, upcoming_release_date=upcoming_release_date)

    sections = [
        todo,
        metadata_header,
        key_takeaways,
        summary_metrics,
        tooling_health,
        _render_coverage_table(coverage_data),
        _render_resolution_guide(coverage_data, catalog, work_scope_by_rule, source_csv_url, policy_files=policy_files, detail_lookup=build_semantic_detail_lookup(viol_data)[0] if viol_data else None),
        _render_warnings_section(analysis_result, component_owners),
        _render_statistical_breakdown(analysis_result, component_owners),
    ]

    SECTION_SPACER = "\n&nbsp;\n"
    guide = SECTION_SPACER.join(s for s in sections if s)
    if todo_file:
        _write_todo_preview(
            todo_file,
            todo=todo,
            metadata_header=metadata_header,
            key_takeaways=key_takeaways,
        )

    if analysis_output_file:
        analysis_path = Path(analysis_output_file)
        if analysis_path.exists():
            analysis_header = _render_metadata_header(
                release, source_path, source_created_at, source_sha,
                policy_dir_url, policy_files, end_of_support=end_of_support,
                confirmation_display=confirmation_display, title_prefix="Conforma Analysis",
                upcoming_release_date=upcoming_release_date,
                code_freeze_date=code_freeze_date,
            )
            existing_content = analysis_path.read_text(encoding="utf-8")
            existing_lines = existing_content.split("\n")
            cleaned_lines = []
            skip_old_header = True
            for line in existing_lines:
                if skip_old_header and (line.startswith("**Report**:") or line.startswith("# Conforma Violations Analysis")):
                    continue
                skip_old_header = False
                cleaned_lines.append(line)
            analysis_path.write_text(analysis_header + "\n".join(cleaned_lines), encoding="utf-8")

    return guide


def _find_default_catalog() -> Path:
    """Find the default violation catalog relative to this script."""
    here = Path(__file__).resolve().parent
    # scripts/ -> conforma-analyze/ -> skills/ -> repo/skills/references/
    candidate = here.parent.parent / "references" / "violation-catalog.yaml"
    if candidate.exists():
        return candidate
    # Try from repo root
    repo_root = here.parent.parent.parent
    candidate2 = repo_root / "skills" / "references" / "violation-catalog.yaml"
    if candidate2.exists():
        return candidate2
    raise FileNotFoundError("Cannot find violation-catalog.yaml. Use --catalog to specify its path.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a unified Conforma Resolution Guide")
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Conforma run directory (auto-discovered from ~/.conforma/.conforma-active if omitted)",
    )
    parser.add_argument("--violations-yaml", default=None, help="Path to parsed violations YAML")
    parser.add_argument("--coverage-json", default=None, help="Path to coverage check JSON output")
    parser.add_argument("--reports-dir", default=None, help="Directory containing CSV reports")
    parser.add_argument(
        "--catalog",
        default=None,
        help="Path to violation-catalog.yaml (default: auto-detect)",
    )
    parser.add_argument("--release", default=None, help="Release name (e.g. rhoai-3.5-ea.2)")
    parser.add_argument(
        "--metadata-file",
        default=None,
        help="Path to fetch-metadata.json (step 4 output). When provided, "
        "--source-path, --source-created-at, --source-sha are auto-extracted "
        "for the given --release and become optional.",
    )
    parser.add_argument(
        "--source-path",
        default=None,
        help="CSV source path in the repo. Auto-extracted from --metadata-file when omitted.",
    )
    parser.add_argument(
        "--source-created-at",
        default=None,
        help="When the source CSV was generated (ISO timestamp). Auto-extracted from --metadata-file when omitted.",
    )
    parser.add_argument(
        "--source-sha",
        default="",
        help="Git commit SHA of the source CSV. Auto-extracted from --metadata-file when omitted.",
    )
    parser.add_argument(
        "--policy-dir-url",
        default="",
        help="URL to the conforma policy directory. Auto-extracted from context.yaml when omitted.",
    )
    parser.add_argument(
        "--policy-files-json",
        default="",
        help='JSON array of {name, url} objects for policy config files. Auto-extracted from context.yaml when omitted.',
    )
    parser.add_argument(
        "--end-of-support",
        default="",
        help="Release end-of-support date (YYYY-MM-DD). Auto-extracted from context.yaml when omitted.",
    )
    parser.add_argument(
        "--upcoming-release-date",
        default="",
        help="Upcoming release date (YYYY-MM-DD). Auto-extracted from context.yaml when omitted.",
    )
    parser.add_argument(
        "--code-freeze-date",
        default="",
        help="Code freeze date (YYYY-MM-DD). Auto-extracted from context.yaml when omitted.",
    )
    parser.add_argument(
        "--tooling-health-json",
        default=None,
        help="Path to tooling-health.json from check_tooling_health.py (optional)",
    )
    parser.add_argument("--output", default=None, help="Output file path")
    parser.add_argument(
        "--todo-file",
        default=None,
        help="Path to write TODO preview file for chat display. "
        "Contains action items, metadata, and violations breakdown.",
    )
    parser.add_argument(
        "--analysis-output-file",
        default=None,
        help="Path to the analysis output markdown file (step 6 output).",
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

    release = args.release
    if release is None and context:
        release = conforma_context_ops.get(run_dir, "application.release", None)
    if not release:
        print("Error: --release is required when no run context is available", file=sys.stderr)
        return 1

    violations_yaml = args.violations_yaml
    if violations_yaml is None and context and run_dir:
        parse_output = conforma_context_ops.get(run_dir, "steps.parse.violations_yaml", None)
        if parse_output:
            violations_yaml = str(Path(run_dir) / parse_output)
    if not violations_yaml:
        print("Error: --violations-yaml is required when no run context is available", file=sys.stderr)
        return 1

    coverage_json = args.coverage_json
    if coverage_json is None and context and run_dir:
        cov_output = conforma_context_ops.get(run_dir, "steps.coverage.coverage_json", None)
        if cov_output:
            coverage_json = str(Path(run_dir) / cov_output)
    if not coverage_json:
        print("Error: --coverage-json is required when no run context is available", file=sys.stderr)
        return 1

    reports_dir = args.reports_dir
    if reports_dir is None and run_dir:
        reports_dir = str(run_dir)
    if not reports_dir:
        print("Error: --reports-dir is required when no run context is available", file=sys.stderr)
        return 1

    output_file = args.output
    if output_file is None and run_dir:
        output_file = str(Path(run_dir) / RESOLUTION_GUIDE_FILENAME)
    if not output_file:
        print("Error: --output is required when no run context is available", file=sys.stderr)
        return 1

    todo_file = args.todo_file
    if todo_file is None and run_dir:
        todo_file = str(Path(run_dir) / TODO_PREVIEW_FILENAME)

    analysis_output_file = args.analysis_output_file
    if analysis_output_file is None and run_dir:
        candidate = Path(run_dir) / "conforma-analysis.md"
        if candidate.exists():
            analysis_output_file = str(candidate)

    tooling_health_json = args.tooling_health_json
    if tooling_health_json is None and context and run_dir:
        th_output = conforma_context_ops.get(run_dir, "steps.tooling_health.health_json", None)
        if th_output:
            candidate = Path(run_dir) / th_output
            if candidate.exists():
                tooling_health_json = str(candidate)

    catalog_path = args.catalog or str(_find_default_catalog())

    source_path = args.source_path
    source_created_at = args.source_created_at
    source_sha = args.source_sha
    policy_dir_url = args.policy_dir_url
    end_of_support = args.end_of_support
    upcoming_release_date = args.upcoming_release_date
    code_freeze_date = args.code_freeze_date

    metadata_file = args.metadata_file
    if metadata_file is None and run_dir:
        candidate = Path(run_dir) / "fetch-metadata.json"
        if candidate.exists():
            metadata_file = str(candidate)

    if metadata_file:
        try:
            metadata = json.loads(Path(metadata_file).read_text(encoding="utf-8"))
            release_meta = metadata.get("releases", {}).get(release, {})
            if not source_path:
                source_path = release_meta.get("source_path", "")
            if not source_created_at:
                source_created_at = release_meta.get("created_at", "")
            if not source_sha:
                source_sha = release_meta.get("source_sha", "")
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARNING: Could not read metadata file: {exc}", file=sys.stderr)
    elif context and run_dir:
        if not source_path:
            source_path = conforma_context_ops.get(run_dir, "steps.fetch.source_path", "")
        if not source_created_at:
            source_created_at = conforma_context_ops.get(run_dir, "steps.fetch.source_created_at", "")
        if not source_sha:
            source_sha = conforma_context_ops.get(run_dir, "steps.fetch.source_sha", "")

    if context:
        if not policy_dir_url:
            policy_dir_url = conforma_context_ops.get(run_dir, "resolve.links.policy_dir", "")
        if not end_of_support:
            end_of_support = conforma_context_ops.get(run_dir, "resolve.end_of_support", "")
        if not upcoming_release_date:
            upcoming_release_date = conforma_context_ops.get(run_dir, "resolve.upcoming_release_date", "")
        if not code_freeze_date:
            code_freeze_date = conforma_context_ops.get(run_dir, "resolve.code_freeze_date", "")

    policy_files = None
    if args.policy_files_json:
        try:
            policy_files = json.loads(args.policy_files_json)
        except json.JSONDecodeError:
            print("WARNING: --policy-files-json is not valid JSON, ignoring", file=sys.stderr)
    elif context:
        ctx_links_pf = conforma_context_ops.get(run_dir, "resolve.links.policy_files", None)
        if ctx_links_pf:
            policy_files = ctx_links_pf
        else:
            ctx_pf = conforma_context_ops.get(run_dir, "resolve.policy_files", None)
            if ctx_pf:
                policy_files = [{"name": f, "url": ""} for f in ctx_pf]
        ctx_ss = conforma_context_ops.get(run_dir, "resolve.links.self_service_exception_files", None)
        if ctx_ss:
            policy_files = list(policy_files or []) + [
                {"name": f"exceptions/{f['name']}", "url": f["url"]} for f in ctx_ss
            ]

    if not source_path or not source_created_at:
        print(
            "ERROR: --source-path and --source-created-at are required "
            "(provide them directly, via --metadata-file, or via context.yaml)",
            file=sys.stderr,
        )
        return 1

    try:
        content = generate_resolution_guide(
            violations_yaml_path=violations_yaml,
            coverage_json_path=coverage_json,
            reports_dir=reports_dir,
            catalog_path=catalog_path,
            release=release,
            source_path=source_path,
            source_created_at=source_created_at,
            source_sha=source_sha,
            policy_dir_url=policy_dir_url,
            policy_files=policy_files,
            tooling_health_path=tooling_health_json,
            todo_file=todo_file,
            analysis_output_file=analysis_output_file,
            end_of_support=end_of_support,
            confirmation_display=conforma_context_ops.get(run_dir, "resolve.confirmation_display", "") if context else "",
            upcoming_release_date=upcoming_release_date,
            code_freeze_date=code_freeze_date,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Resolution guide written to {output_path}", file=sys.stderr)

    if run_dir:
        step_outputs: dict = {
            "guide_file": output_path.name,
        }
        if todo_file:
            step_outputs["todo_file"] = Path(todo_file).name
        if analysis_output_file:
            step_outputs["analysis_file"] = Path(analysis_output_file).name
        conforma_context_ops.update_step(run_dir, "resolution_guide", "completed", **step_outputs)

    print(json.dumps({"output": str(output_path), "release": release}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
