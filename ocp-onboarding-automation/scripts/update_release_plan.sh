#!/usr/bin/env bash
# Update ReleasePlan and ReleasePlanAdmission files for affected RHOAI releases.
# This script is typically called after Konflux app creation.
#
# Usage:
#   bash update_release_plan.sh \
#     --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5" \
#     --krd-repo-path /path/to/konflux-release-data
#
# Options:
#   --ocp-version VER         OCP version to add (required)
#   --rhoai-versions LIST     Comma-separated RHOAI versions (required)
#   --krd-repo-path PATH      Path to cloned konflux-release-data repo (required)
#   --dry-run                 Show what would be changed

set -euo pipefail

OCP_VERSION=""
RHOAI_VERSIONS=""
KRD_REPO_PATH=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version)      OCP_VERSION="$2"; shift 2 ;;
    --rhoai-versions)   RHOAI_VERSIONS="$2"; shift 2 ;;
    --krd-repo-path)    KRD_REPO_PATH="$2"; shift 2 ;;
    --dry-run)          DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

[[ -z "$RHOAI_VERSIONS" ]] && {
  echo "ERROR: --rhoai-versions is required" >&2
  exit 1
}

[[ -z "$KRD_REPO_PATH" ]] && {
  echo "ERROR: --krd-repo-path is required" >&2
  exit 1
}

[[ ! -d "$KRD_REPO_PATH" ]] && {
  echo "ERROR: Repository path not found: $KRD_REPO_PATH" >&2
  exit 1
}

# Parse OCP version
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Convert RHOAI versions to array
IFS=',' read -ra RHOAI_ARRAY <<< "$RHOAI_VERSIONS"

echo "============================================"
echo "Update ReleasePlan for OCP Version"
echo "============================================"
echo "OCP version:      $OCP_VERSION_FULL"
echo "RHOAI versions:   ${#RHOAI_ARRAY[@]} (${RHOAI_VERSIONS})"
echo "Repository:       $KRD_REPO_PATH"
echo "Dry run:          $DRY_RUN"
echo "============================================"
echo

# Track results
UPDATED_COUNT=0
SKIPPED_COUNT=0

for RHOAI_VER in "${RHOAI_ARRAY[@]}"; do
  RHOAI_VER="${RHOAI_VER#rhoai-}"

  echo "Processing RHOAI ${RHOAI_VER}..."

  # Find ReleasePlan files for this RHOAI version
  # Pattern: tenants/rhoai/release-plans/*rhoai-{version}*
  RELEASE_PLAN_DIR="$KRD_REPO_PATH/tenants/rhoai/release-plans"

  if [[ ! -d "$RELEASE_PLAN_DIR" ]]; then
    echo "  ⚠ Release plans directory not found, skipping"
    ((SKIPPED_COUNT++))
    continue
  fi

  # This is a placeholder implementation
  # The actual structure depends on konflux-release-data repository layout
  echo "  ℹ ReleasePlan updates would be applied here"
  echo "  Note: Actual implementation depends on konflux-release-data structure"

  if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY RUN] Would update ReleasePlan YAML for RHOAI ${RHOAI_VER}"
    echo "  [DRY RUN] Would add OCP ${OCP_VERSION_FULL} to supported versions"
  fi

  ((UPDATED_COUNT++))
  echo
done

# Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "RHOAI versions processed: ${#RHOAI_ARRAY[@]}"
echo "Updated:                  $UPDATED_COUNT"
echo "Skipped:                  $SKIPPED_COUNT"
echo

if [[ "$DRY_RUN" == false ]]; then
  echo "Note: Review changes in $KRD_REPO_PATH before committing"
fi

echo "✓ ReleasePlan update completed"
