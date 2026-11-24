#!/usr/bin/env bash
# Master orchestrator for OCP version onboarding.
# Executes all 4 phases in sequence: release branches, main catalog, Tekton pipelines, Konflux.
#
# Usage:
#   bash run_ocp_onboarding.sh \
#     --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5,3.4" \
#     [--skip-phase 4] \
#     [--dry-run | --commit | --push]
#
# Prerequisites:
#   - Git repository: RHOAI-Build-Config (cloned locally)
#   - GitHub credentials (for phases 1-3)
#   - GitLab credentials + VPN (for phase 4)
#
# Environment Variables (Phase 4):
#   GITLAB_USER  - GitLab username
#   GITLAB_TOKEN - GitLab personal access token
#
# Options:
#   --action ACTION           onboard (default) or offboard selected releases
#   --ocp-version VER         OCP version to onboard (required)
#   --rhoai-versions LIST     Comma-separated RHOAI versions (required)
#   --repo-path PATH          Path to RHOAI-Build-Config for phases 1–3
#   --skip-phase N[,N...]     Skip specific phases (1-4)
#   --dry-run                 Show what would be done (default)
#   --commit                  Make commits but don't push
#   --push                    Make commits and push to remote
#   --help                    Show this help message

set -euo pipefail

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default values
OCP_VERSION=""
ACTION=onboard
RELEASE_DATA_PATH=""
REPO_ARGS=()
RANGE_ARGS=()
BUILD_ARGS=()
RHOAI_VERSIONS=""
SKIP_PHASES=""
MODE="dry-run"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
show_help() {
  cat << EOF
OCP Version Onboarding - Master Orchestrator

Usage: $0 --ocp-version VER --rhoai-versions LIST [OPTIONS]

Required:
  --ocp-version VER         OCP version to onboard (e.g., 5.0, 4.23)
  --rhoai-versions LIST     Comma-separated RHOAI versions (e.g., "3.6,3.5,3.4")

Options:
  --action ACTION           onboard (default) or offboard selected releases
  --release-data-path PATH  Konflux release-data checkout for offboard dry-run or commit
  --repo-path PATH          Path to RHOAI-Build-Config for phases 1–3
  --onboarded-range RANGE    Supported release range for the target OCP config entry
  --build-version VER       Full Tekton build version override for a single release line
  --skip-phase N[,N...]     Skip specific phases (1-4)
  --dry-run                 Show what would be done (default)
  --commit                  Make commits but don't push
  --push                    Make commits and push to remote
  --help                    Show this help message

Phases:
  Phase 1: Update RHOAI release branches (rhoai-x.y)
  Phase 2: Update main branch catalogs
  Phase 3: Generate Tekton PipelineRun YAMLs
  Phase 4: Create Konflux Application (requires VPN + GitLab)

Environment Variables (Phase 4 only):
  GITLAB_USER               GitLab username
  GITLAB_TOKEN              GitLab personal access token

Examples:
  # Dry run (safe, shows what would happen)
  $0 --ocp-version 5.0 --rhoai-versions "3.6,3.5,3.4" --dry-run

  # Execute phases 1-3 only (no GitLab/VPN needed)
  $0 --ocp-version 5.0 --rhoai-versions "3.6,3.5" --skip-phase 4 --push

  # Full onboarding with all phases
  $0 --ocp-version 5.0 --rhoai-versions "3.6,3.5,3.4" --push

EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --action)
      case "${2:-}" in
        onboard|offboard) ACTION="$2" ;;
        *) echo "ERROR: --action must be onboard or offboard" >&2; exit 1 ;;
      esac
      shift 2
      ;;
    --ocp-version)
      OCP_VERSION="$2"
      shift 2
      ;;
    --rhoai-versions)
      RHOAI_VERSIONS="$2"
      shift 2
      ;;
    --onboarded-range|--build-version)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "ERROR: $1 requires a value" >&2
        exit 1
      fi
      if [[ "$1" == --onboarded-range ]]; then
        RANGE_ARGS=("$1" "$2")
      else
        BUILD_ARGS=("$1" "$2")
      fi
      shift 2
      ;;
    --release-data-path)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "ERROR: --release-data-path requires a path" >&2
        exit 1
      fi
      RELEASE_DATA_PATH="$2"
      shift 2
      ;;
    --repo-path)
      if [[ -z "${2:-}" || "$2" == --* ]]; then
        echo "ERROR: --repo-path requires a path" >&2
        exit 1
      fi
      REPO_ARGS=(--repo-path "$2")
      shift 2
      ;;
    --skip-phase)
      SKIP_PHASES="$2"
      shift 2
      ;;
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --commit)
      MODE="commit"
      shift
      ;;
    --push)
      MODE="push"
      shift
      ;;
    --help)
      show_help
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      echo "Run with --help for usage information" >&2
      exit 1
      ;;
  esac
done

# Validate required arguments
if [[ -z "$OCP_VERSION" ]]; then
  echo "ERROR: --ocp-version is required" >&2
  echo "Run with --help for usage information" >&2
  exit 1
fi

if [[ -z "$RHOAI_VERSIONS" ]]; then
  echo "ERROR: --rhoai-versions is required" >&2
  echo "Run with --help for usage information" >&2
  exit 1
fi

# Parse skip phases into array
SKIP_PHASE_ARRAY=()
if [[ -n "$SKIP_PHASES" ]]; then
  IFS=',' read -ra SKIP_PHASE_ARRAY <<< "$SKIP_PHASES"
fi

# Helper: Check if phase should be skipped
should_skip_phase() {
  local phase=$1
  # Handle empty array case
  [[ ${#SKIP_PHASE_ARRAY[@]} -eq 0 ]] && return 1
  for skip in "${SKIP_PHASE_ARRAY[@]}"; do
    [[ "$skip" == "$phase" ]] && return 0
  done
  return 1
}

# Build mode flags for subscripts
MODE_FLAGS=""
case "$MODE" in
  dry-run) MODE_FLAGS="--dry-run" ;;
  commit)  MODE_FLAGS="--commit" ;;
  push)    MODE_FLAGS="--push" ;;
esac

# Parse OCP version for display
parsed=$(bash "$SCRIPT_DIR/scripts/parse_ocp_version.sh" --version "$OCP_VERSION")
eval "$parsed"

# Count RHOAI versions
IFS=',' read -ra RHOAI_ARRAY <<< "$RHOAI_VERSIONS"
RHOAI_COUNT=${#RHOAI_ARRAY[@]}

# Banner
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  OCP Version Onboarding - Master Script  ${NC}"
echo -e "${BLUE}============================================${NC}"
echo
echo "OCP Version:       $OCP_VERSION_FULL"
echo "Base Image:        $OCP_BASE_IMAGE"
echo "RHOAI Versions:    $RHOAI_COUNT (${RHOAI_VERSIONS})"
echo "Mode:              $MODE"
if [[ -n "$SKIP_PHASES" ]]; then
  echo "Skipping Phases:   ${SKIP_PHASES}"
fi
echo
echo -e "${BLUE}============================================${NC}"
echo

# Track results
PHASE_RESULTS=()
PHASE_NAMES=()
START_TIME=$(date +%s)

# Phase execution helper
run_phase() {
  local phase_num=$1
  local phase_name=$2
  local script_name=$3
  shift 3
  local script_args=("$@")

  PHASE_NAMES+=("$phase_name")

  if should_skip_phase "$phase_num"; then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}Phase $phase_num: $phase_name [SKIPPED]${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo
    PHASE_RESULTS+=("SKIP")
    return 0
  fi

  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE}Phase $phase_num: $phase_name${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo

  if bash "$SCRIPT_DIR/scripts/$script_name" "${script_args[@]}" $MODE_FLAGS; then
    echo
    echo -e "${GREEN}✓ Phase $phase_num completed successfully${NC}"
    echo
    PHASE_RESULTS+=("PASS")
  else
    echo
    echo -e "${RED}✗ Phase $phase_num failed${NC}"
    echo
    PHASE_RESULTS+=("FAIL")

    # Ask user if they want to continue
    echo -e "${YELLOW}Phase $phase_num failed. Continue with remaining phases?${NC}"
    read -p "Continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
      echo "Aborting remaining phases."
      return 1
    fi
  fi
}

if [[ "$ACTION" == offboard ]]; then
  if [[ -z "${REPO_ARGS[0]:-}" ]]; then
    echo "ERROR: Offboarding requires --repo-path" >&2
    exit 1
  fi
  if [[ -n "$RELEASE_DATA_PATH" && "$MODE" == push ]]; then
    echo "ERROR: Use --commit for offboarding with --release-data-path." >&2
    exit 1
  fi
  release_data_step="$SCRIPT_DIR/scripts/run_step_offboard_release_data.sh"
  if [[ -n "$RELEASE_DATA_PATH" && "$MODE" != dry-run ]] && ! should_skip_phase 4; then
    bash "$release_data_step" "$RELEASE_DATA_PATH" "$OCP_VERSION" "$RHOAI_VERSIONS" --dry-run
  fi
  offboard_args=(--ocp-version "$OCP_VERSION" --rhoai-versions "$RHOAI_VERSIONS" "${REPO_ARGS[@]}")
  main_step="$SCRIPT_DIR/scripts/run_step_offboard_main.sh"
  if ! should_skip_phase 2 && [[ "$MODE" != dry-run ]]; then
    bash "$main_step" "${offboard_args[@]}" ${RANGE_ARGS[@]+"${RANGE_ARGS[@]}"} --dry-run
  fi
  if ! should_skip_phase 1; then
    bash "$SCRIPT_DIR/scripts/run_step_update_release_branches.sh" \
      "${offboard_args[@]}" --action offboard "$MODE_FLAGS"
  fi
  if ! should_skip_phase 2; then
    if ! bash "$main_step" "${offboard_args[@]}" ${RANGE_ARGS[@]+"${RANGE_ARGS[@]}"} "$MODE_FLAGS"; then
      echo "ERROR: Main offboarding failed. Check the release branches for any changes already applied." >&2
      exit 1
    fi
  fi
  if [[ -n "$RELEASE_DATA_PATH" ]] && ! should_skip_phase 4; then
    if ! bash "$release_data_step" "$RELEASE_DATA_PATH" "$OCP_VERSION" "$RHOAI_VERSIONS" "$MODE_FLAGS"; then
      echo "ERROR: Release-data offboarding failed after RHOAI-Build-Config processing." >&2
      exit 1
    fi
  fi
  echo "RHOAI-Build-Config offboarding $MODE completed."
  exit 0
fi

# Phase 1: Update Release Branches
run_phase 1 "Update RHOAI Release Branches" \
  "run_step_update_release_branches.sh" \
  --ocp-version "$OCP_VERSION" \
  --rhoai-versions "$RHOAI_VERSIONS" \
  ${REPO_ARGS[@]+"${REPO_ARGS[@]}"}

# Phase 2: Update Main Branch Catalogs
run_phase 2 "Update Main Branch Catalogs" \
  "run_step_update_main_catalog.sh" \
  --ocp-version "$OCP_VERSION" \
  --rhoai-versions "$RHOAI_VERSIONS" \
  ${REPO_ARGS[@]+"${REPO_ARGS[@]}"} \
  ${RANGE_ARGS[@]+"${RANGE_ARGS[@]}"}

# Phase 3: Generate Tekton Pipelines
run_phase 3 "Generate Tekton PipelineRuns" \
  "run_step_generate_tekton_pipelines.sh" \
  --ocp-version "$OCP_VERSION" \
  --rhoai-versions "$RHOAI_VERSIONS" \
  ${REPO_ARGS[@]+"${REPO_ARGS[@]}"} \
  ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"}

# Phase 4: Konflux Integration (requires VPN + GitLab)
if ! should_skip_phase 4; then
  # Check prerequisites for Phase 4
  if [[ "$MODE" != "dry-run" ]]; then
    MISSING_PREREQS=false

    if [[ -z "${GITLAB_USER:-}" ]]; then
      echo -e "${YELLOW}⚠ GITLAB_USER environment variable not set${NC}"
      MISSING_PREREQS=true
    fi

    if [[ -z "${GITLAB_TOKEN:-}" ]]; then
      echo -e "${YELLOW}⚠ GITLAB_TOKEN environment variable not set${NC}"
      MISSING_PREREQS=true
    fi

    if [[ "$MISSING_PREREQS" == true ]]; then
      echo
      echo -e "${YELLOW}Phase 4 requires GitLab credentials. Options:${NC}"
      echo "  1. Export GITLAB_USER and GITLAB_TOKEN, then re-run"
      echo "  2. Skip phase 4 with: --skip-phase 4"
      echo "  3. Continue in dry-run mode (read-only)"
      echo
      read -p "Skip Phase 4? [y/N] " -n 1 -r
      echo
      if [[ $REPLY =~ ^[Yy]$ ]]; then
        SKIP_PHASE_ARRAY+=("4")
      fi
    fi
  fi
fi

run_phase 4 "Create Konflux Application" \
  "run_step_create_konflux_app.sh" \
  --ocp-version "$OCP_VERSION"

# Calculate duration
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

# Final Summary
echo
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}         ONBOARDING SUMMARY             ${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
echo
echo "OCP Version:       $OCP_VERSION_FULL"
echo "RHOAI Versions:    $RHOAI_COUNT (${RHOAI_VERSIONS})"
echo "Mode:              $MODE"
echo "Duration:          ${MINUTES}m ${SECONDS}s"
echo
echo "Phase Results:"
for i in "${!PHASE_NAMES[@]}"; do
  phase_name="${PHASE_NAMES[$i]}"
  result="${PHASE_RESULTS[$i]}"

  case "$result" in
    PASS) echo -e "  ${GREEN}✓${NC} Phase $((i+1)): $phase_name" ;;
    FAIL) echo -e "  ${RED}✗${NC} Phase $((i+1)): $phase_name" ;;
    SKIP) echo -e "  ${YELLOW}⊘${NC} Phase $((i+1)): $phase_name [skipped]" ;;
  esac
done

echo
echo -e "${BLUE}════════════════════════════════════════${NC}"

# Check if any phase failed
FAILED=false
for result in "${PHASE_RESULTS[@]}"; do
  [[ "$result" == "FAIL" ]] && FAILED=true
done

if [[ "$FAILED" == true ]]; then
  echo -e "${RED}⚠ Some phases failed. Review output above.${NC}"
  exit 1
elif [[ "$MODE" == "dry-run" ]]; then
  echo -e "${GREEN}✓ Dry run completed successfully${NC}"
  echo
  echo "Next steps:"
  echo "  1. Review the output above"
  echo "  2. Run with --commit to make commits (no push)"
  echo "  3. Run with --push to commit and push changes"
  exit 0
else
  echo -e "${GREEN}✓ All phases completed successfully!${NC}"
  echo
  echo "OCP ${OCP_VERSION_FULL} has been onboarded for:"
  for ver in "${RHOAI_ARRAY[@]}"; do
    echo "  - RHOAI ${ver#rhoai-}"
  done
  echo

  if [[ "$MODE" == "commit" ]]; then
    echo "Changes committed locally. Run with --push to push to remote."
  fi

  exit 0
fi
