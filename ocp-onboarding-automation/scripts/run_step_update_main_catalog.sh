#!/usr/bin/env bash
# Update main branch catalog directories for a new OCP version.
# Creates catalog/rhoai-{version}/v{ocp}/ for each RHOAI version.
#
# Usage:
#   bash run_step_update_main_catalog.sh \
#     --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5,3.4" \
#     [--repo-path /path/to/RHOAI-Build-Config] \
#     [--commit] \
#     [--push] \
#     [--dry-run]
#
# Options:
#   --ocp-version VER         OCP version to onboard (required)
#   --rhoai-versions LIST     Comma-separated RHOAI versions (required)
#   --repo-path PATH          Path to RHOAI-Build-Config repo (default: auto-detect)
#   --commit                  Create git commit for changes
#   --push                    Push changes to remote (implies --commit)
#   --dry-run                 Show what would be done without making changes
#
# Example:
#   bash run_step_update_main_catalog.sh --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5" --dry-run

set -euo pipefail

OCP_VERSION=""
RHOAI_VERSIONS=""
REPO_PATH=""
DO_COMMIT=false
DO_PUSH=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version)      OCP_VERSION="$2"; shift 2 ;;
    --rhoai-versions)   RHOAI_VERSIONS="$2"; shift 2 ;;
    --repo-path)        REPO_PATH="$2"; shift 2 ;;
    --commit)           DO_COMMIT=true; shift ;;
    --push)             DO_COMMIT=true; DO_PUSH=true; shift ;;
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

# Auto-detect repository
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$REPO_PATH" ]]; then
  if [[ -d "/Users/mchamsed/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config" ]]; then
    REPO_PATH="/Users/mchamsed/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config"
  else
    echo "ERROR: Could not auto-detect RHOAI-Build-Config repository" >&2
    exit 1
  fi
fi

[[ ! -d "$REPO_PATH/.git" ]] && {
  echo "ERROR: Not a git repository: $REPO_PATH" >&2
  exit 1
}

# Parse OCP version
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Convert RHOAI versions to array
IFS=',' read -ra RHOAI_ARRAY <<< "$RHOAI_VERSIONS"

echo "============================================"
echo "OCP Version Onboarding - Main Branch Catalog"
echo "============================================"
echo "OCP version:      $OCP_VERSION_FULL"
echo "Base image:       $OCP_BASE_IMAGE"
echo "RHOAI versions:   ${#RHOAI_ARRAY[@]} (${RHOAI_VERSIONS})"
echo "Repository:       $REPO_PATH"
echo "Dry run:          $DRY_RUN"
echo "Commit changes:   $DO_COMMIT"
echo "Push to remote:   $DO_PUSH"
echo "============================================"
echo

# Checkout main branch
cd "$REPO_PATH"
if [[ "$DRY_RUN" == false ]]; then
  echo "Checking out main branch..."
  git checkout main || {
    echo "ERROR: Failed to checkout main branch" >&2
    exit 1
  }
  git pull --ff-only || echo "Warning: Could not fast-forward"
  echo
fi

# Track results
RESULTS_VERSIONS=()
RESULTS_STATUS=()
SUCCESSFUL=0
FAILED=0
SKIPPED=0

for RHOAI_VER in "${RHOAI_ARRAY[@]}"; do
  # Remove 'rhoai-' prefix if present
  RHOAI_VER="${RHOAI_VER#rhoai-}"

  CATALOG_PATH="catalog/rhoai-${RHOAI_VER}"

  echo "Processing rhoai-${RHOAI_VER}..."
  echo "----------------------------------------"

  # Check if catalog directory exists
  if [[ ! -d "$REPO_PATH/$CATALOG_PATH" ]]; then
    echo "  ⚠ Catalog directory not found: $CATALOG_PATH"
    RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
    RESULTS_STATUS+=("skipped (catalog not found)")
    ((SKIPPED++))
    echo
    continue
  fi

  # Update catalog directory
  if [[ "$DRY_RUN" == true ]]; then
    bash "$SCRIPT_DIR/update_catalog_directory.sh" \
      --catalog-dir "$REPO_PATH/$CATALOG_PATH" \
      --ocp-version "$OCP_VERSION" \
      --dry-run
    EXIT_CODE=0
  else
    if bash "$SCRIPT_DIR/update_catalog_directory.sh" \
      --catalog-dir "$REPO_PATH/$CATALOG_PATH" \
      --ocp-version "$OCP_VERSION"; then
      EXIT_CODE=$?
    else
      EXIT_CODE=$?
    fi
  fi

  if [[ $EXIT_CODE == 2 ]]; then
    echo "  ℹ Already up-to-date"
    RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
    RESULTS_STATUS+=("skipped (up-to-date)")
    ((SKIPPED++))
  elif [[ $EXIT_CODE != 0 ]]; then
    echo "  ERROR: Failed to update catalog"
    RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
    RESULTS_STATUS+=("failed")
    ((FAILED++))
  else
    echo "  ✓ Updated successfully"
    RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
    RESULTS_STATUS+=("success")
    ((SUCCESSFUL++))
  fi

  echo
done

# Commit changes if requested
if [[ "$DO_COMMIT" == true && "$DRY_RUN" == false ]]; then
  cd "$REPO_PATH"
  if git diff --quiet && git diff --cached --quiet; then
    echo "No changes to commit"
  else
    echo "Committing changes to main branch..."
    git add catalog/ || true

    COMMIT_MSG="Add OCP ${OCP_VERSION_FULL} support to main branch catalogs

- Updated catalog/rhoai-*/v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}/ directories
- Base image: ${OCP_BASE_IMAGE}

Co-Authored-By: OCP Onboarding Automation <noreply@redhat.com>"

    if git commit -m "$COMMIT_MSG"; then
      echo "  ✓ Committed changes"

      if [[ "$DO_PUSH" == true ]]; then
        echo "  Pushing to origin/main..."
        if git push origin main; then
          echo "  ✓ Pushed to remote"
        else
          echo "  ERROR: Failed to push"
          exit 1
        fi
      fi
    else
      echo "  ERROR: Failed to commit"
      exit 1
    fi
  fi
fi

# Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total RHOAI versions: ${#RHOAI_ARRAY[@]}"
echo "Successful:           $SUCCESSFUL"
echo "Failed:               $FAILED"
echo "Skipped:              $SKIPPED"
echo

if [[ ${#RESULTS_VERSIONS[@]} -gt 0 ]]; then
  echo "Results by version:"
  for ((i=0; i<${#RESULTS_VERSIONS[@]}; i++)); do
    printf "  %-25s %s\n" "${RESULTS_VERSIONS[$i]}" "${RESULTS_STATUS[$i]}"
  done
  echo
fi

if [[ $FAILED -gt 0 ]]; then
  echo "⚠ Some versions failed to update"
  exit 1
fi

echo "✓ Main branch catalog updates completed successfully"
