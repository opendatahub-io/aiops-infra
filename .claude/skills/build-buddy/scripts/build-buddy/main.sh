#!/usr/bin/env bash
# main.sh — Build Buddy entry point
#
# Orchestrates: prereqs → PP container → analyze → output
# AI tasks (Jira resolution, intermittent classification, verification)
# are handled by the SKILL.md orchestrator; this script handles the
# bash-level plumbing.
#
# Usage:
#   bash main.sh --input <url> [--execution-mode interactive|ci] \
#                [--dry-run] [--allow-retrigger true|false] \
#                [--pp-image <image>] [--output-dir <dir>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source dependencies
# shellcheck source=config.sh
source "${SCRIPT_DIR}/config.sh"
# shellcheck source=pp-container.sh
source "${SCRIPT_DIR}/pp-container.sh"
# shellcheck source=retrigger.sh
source "${SCRIPT_DIR}/retrigger.sh"
# shellcheck source=output.sh
source "${SCRIPT_DIR}/output.sh"

# ── Parse arguments ─────────────────────────────────────────────────────────
INPUT_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)            INPUT_URL="$2"; shift 2 ;;
    --execution-mode)   BB_EXECUTION_MODE="$2"; shift 2 ;;
    --dry-run)          BB_DRY_RUN="true"; shift ;;
    --allow-retrigger)  BB_ALLOW_RETRIGGER="$2"; shift 2 ;;
    --pp-image)         BB_PP_IMAGE="$2"; shift 2 ;;
    --output-dir)       BB_OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: bash main.sh --input <url> [options]"
      echo ""
      echo "Options:"
      echo "  --input <url>              Jira URL or Konflux PipelineRun URL (required)"
      echo "  --execution-mode <mode>    interactive (default) or ci"
      echo "  --dry-run                  Report only, no actions"
      echo "  --allow-retrigger <bool>   Allow auto-retrigger (default: true)"
      echo "  --pp-image <image>         PP container image"
      echo "  --output-dir <dir>         Output directory"
      exit 0
      ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$INPUT_URL" ]]; then
  echo "ERROR: --input is required." >&2
  echo "  Usage: bash main.sh --input <url>" >&2
  exit 1
fi

# ── Step 1: Check prerequisites ─────────────────────────────────────────────
echo "=== Step 1: Prerequisites ==="
bash "${SCRIPT_DIR}/prereqs.sh" || {
  echo "ERROR: Prerequisites check failed. Aborting." >&2
  exit 1
}

# ── Step 2: Export configuration ────────────────────────────────────────────
echo ""
echo "=== Configuration ==="
echo "  Input URL:       $INPUT_URL"
echo "  Execution mode:  $BB_EXECUTION_MODE"
echo "  Dry run:         $BB_DRY_RUN"
echo "  Allow retrigger: $BB_ALLOW_RETRIGGER"
echo "  PP Image:        $BB_PP_IMAGE"
echo "  Output dir:      $BB_OUTPUT_DIR"

mkdir -p "$BB_OUTPUT_DIR"

# ── Step 3: Determine input type ────────────────────────────────────────────
echo ""
echo "=== Step 2: Input Resolution ==="
INPUT_TYPE="unknown"

if echo "$INPUT_URL" | grep -qE 'atlassian\.net|jira'; then
  INPUT_TYPE="jira"
  echo "  Detected: Jira URL"
  echo "  NOTE: Jira → PipelineRun URL resolution is handled by the SKILL.md orchestrator."
  # The SKILL.md orchestrator will parse the Jira issue and extract the pipeline URL,
  # then call this script again with the resolved URL, or set PIPELINE_URL env var.
elif echo "$INPUT_URL" | grep -qE 'pipelinerun|PipelineRun'; then
  INPUT_TYPE="pipelinerun"
  echo "  Detected: PipelineRun URL"
else
  echo "  WARN: Could not auto-detect URL type. Treating as PipelineRun URL."
  INPUT_TYPE="pipelinerun"
fi

# Export for the orchestrator
export BB_INPUT_URL="$INPUT_URL"
export BB_INPUT_TYPE="$INPUT_TYPE"
export BB_EXECUTION_MODE
export BB_DRY_RUN
export BB_ALLOW_RETRIGGER

# ── Step 4: Start Pipeline-Pilot container ──────────────────────────────────
echo ""
echo "=== Step 3: Pipeline-Pilot Container ==="
PP_AVAILABLE="false"

# Set up EXIT trap for cleanup
trap 'echo "Cleaning up..."; pp_stop 2>/dev/null || true' EXIT

if pp_start; then
  PP_AVAILABLE="true"
  echo "Pipeline-Pilot container ready."
else
  echo "WARN: Pipeline-Pilot container failed to start."
  echo "  Falling back to MCP-based analysis."
fi

export PP_AVAILABLE

# ── Step 5: Analyze (if PP available and input is PipelineRun) ──────────────
echo ""
echo "=== Step 4: Analysis ==="
PP_ANALYSIS_FILE="${BB_OUTPUT_DIR}/pp-analysis.json"

if [[ "$PP_AVAILABLE" == "true" && "$INPUT_TYPE" == "pipelinerun" ]]; then
  echo "Running Pipeline-Pilot analyze..."
  if pp_analyze "$INPUT_URL" --output-file "$PP_ANALYSIS_FILE" > /dev/null 2>&1; then
    echo "PP analysis complete: $PP_ANALYSIS_FILE"
    export BB_FIX_ENGINE="pipeline-pilot"
  else
    echo "WARN: PP analysis failed. Orchestrator will use MCP fallback."
    export BB_FIX_ENGINE="mcp-fallback"
  fi
else
  echo "PP not available or input needs resolution. Orchestrator will handle analysis."
  export BB_FIX_ENGINE="mcp-fallback"
fi

echo ""
echo "=== Script Phase Complete ==="
echo "  Fix engine:     ${BB_FIX_ENGINE:-pending}"
echo "  PP available:   $PP_AVAILABLE"
echo "  Input type:     $INPUT_TYPE"
echo "  Analysis file:  ${PP_ANALYSIS_FILE:-N/A}"
echo ""
echo "Returning control to SKILL.md orchestrator for:"
echo "  - AI-based intermittent classification"
echo "  - Verification engine pass"
echo "  - Retrigger decision"
echo "  - Jira update"
echo "  - Final report generation"
