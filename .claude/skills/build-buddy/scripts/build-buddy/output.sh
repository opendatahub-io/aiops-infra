#!/usr/bin/env bash
# output.sh — Generate Markdown build-buddy report
#
# Usage:
#   source output.sh
#   generate_report <args...>
# Or:
#   bash output.sh --pr-name <name> --namespace <ns> --component <comp> ...

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
[[ -z "${BB_PP_IMAGE:-}" ]] && source "${SCRIPT_DIR}/config.sh"

# ── generate_report ─────────────────────────────────────────────────────────
# Generate a Markdown report file and optionally print to stdout.
#
# Parameters (all via flags):
#   --pr-name          PipelineRun name
#   --namespace        Namespace
#   --component        Component name
#   --jira-key         Jira issue key (optional)
#   --fix-engine       Name of the fix engine used
#   --verify-engine    Name of the verification engine used
#   --failed-task      Name of the failed task
#   --failed-step      Name of the failed step (optional)
#   --failure-category Failure category (build/test/infra/unknown)
#   --is-intermittent  true/false
#   --root-cause       Root cause description
#   --fix-steps        Numbered fix steps (multi-line string)
#   --verify-notes     Verification engine notes
#   --retrigger-status Status of retrigger attempt
#   --jira-status      Status of Jira update
#   --output-dir       Output directory (default: $BB_OUTPUT_DIR)
generate_report() {
  local pr_name="" namespace="" component="" jira_key=""
  local fix_engine="" verify_engine=""
  local failed_task="" failed_step="" failure_category="unknown"
  local is_intermittent="false"
  local root_cause="" fix_steps="" verify_notes=""
  local retrigger_status="N/A" jira_status="N/A"
  local output_dir="${BB_OUTPUT_DIR}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --pr-name)          pr_name="$2"; shift 2 ;;
      --namespace)        namespace="$2"; shift 2 ;;
      --component)        component="$2"; shift 2 ;;
      --jira-key)         jira_key="$2"; shift 2 ;;
      --fix-engine)       fix_engine="$2"; shift 2 ;;
      --verify-engine)    verify_engine="$2"; shift 2 ;;
      --failed-task)      failed_task="$2"; shift 2 ;;
      --failed-step)      failed_step="$2"; shift 2 ;;
      --failure-category) failure_category="$2"; shift 2 ;;
      --is-intermittent)  is_intermittent="$2"; shift 2 ;;
      --root-cause)       root_cause="$2"; shift 2 ;;
      --fix-steps)        fix_steps="$2"; shift 2 ;;
      --verify-notes)     verify_notes="$2"; shift 2 ;;
      --retrigger-status) retrigger_status="$2"; shift 2 ;;
      --jira-status)      jira_status="$2"; shift 2 ;;
      --output-dir)       output_dir="$2"; shift 2 ;;
      *) echo "WARN: Unknown flag '$1'" >&2; shift ;;
    esac
  done

  mkdir -p "$output_dir"

  # Sanitize filename: replace slashes and spaces
  local safe_name
  safe_name=$(echo "$pr_name" | tr '/ ' '__')
  local report_file="${output_dir}/report-${safe_name}.md"
  local timestamp
  timestamp=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

  cat > "$report_file" <<REPORT_EOF
# Build Buddy Report

**Generated:** ${timestamp}

## Metadata

| Field | Value |
|-------|-------|
| Component | ${component:-N/A} |
| PipelineRun | \`${pr_name:-N/A}\` |
| Namespace | \`${namespace:-N/A}\` |
| Jira | ${jira_key:-N/A} |
| Fix Engine | ${fix_engine:-N/A} |
| Verification Engine | ${verify_engine:-N/A} |

## Failure Summary

| Field | Value |
|-------|-------|
| Failed Task | ${failed_task:-N/A} |
| Failed Step | ${failed_step:-N/A} |
| Category | ${failure_category} |
| Intermittent | ${is_intermittent} |

## Root Cause

${root_cause:-_No root cause determined._}

## Fix Steps

${fix_steps:-_No fix steps generated._}

## Verification Notes

${verify_notes:-_No verification notes._}

## Actions Taken

| Action | Status |
|--------|--------|
| Retrigger | ${retrigger_status} |
| Jira Update | ${jira_status} |
REPORT_EOF

  echo "$report_file"
}

# ── format_jira_comment ─────────────────────────────────────────────────────
# Format the report content for a Jira comment (same template, no file header).
format_jira_comment() {
  local report_file="$1"

  if [[ ! -f "$report_file" ]]; then
    echo "ERROR: Report file '$report_file' not found." >&2
    return 1
  fi

  # Return the report content (Jira supports markdown-like formatting)
  cat "$report_file"
}

# ── Allow direct invocation ─────────────────────────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  generate_report "$@"
fi
