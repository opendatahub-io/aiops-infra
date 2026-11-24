#!/usr/bin/env bash
# Orchestrate updates to all RHOAI release branches for a new OCP version.
# This is the main script for Phase 2: Release Branch Automation.
#
# For each RHOAI version:
#   1. Clone/checkout the rhoai-x.y branch
#   2. Create catalog/v{ocp}/ directory (copy from latest + update Dockerfile)
#   3. Update config/build-config.yaml (add to build and release sections)
#   4. Commit changes
#   5. Optionally push to remote
#
# Usage:
#   bash run_step_update_release_branches.sh \
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
#   --commit                  Create git commits for changes
#   --push                    Push changes to remote (implies --commit)
#   --dry-run                 Show what would be done without making changes
#   --action ACTION           onboard (default) or offboard
#
# Returns:
#   0 - Success
#   1 - Error
#
# Examples:
#   # Dry run for OCP 5.0 onboarding
#   bash run_step_update_release_branches.sh --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5" --dry-run
#
#   # Actually onboard with commit
#   bash run_step_update_release_branches.sh --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5,3.4" --commit
#
#   # Onboard and push
#   bash run_step_update_release_branches.sh --ocp-version 5.0 \
#     --rhoai-versions "3.6" --push

set -euo pipefail

OCP_VERSION=""
RHOAI_VERSIONS=""
REPO_PATH=""
DO_COMMIT=false
DO_PUSH=false
DRY_RUN=false
ACTION="onboard"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version)      OCP_VERSION="$2"; shift 2 ;;
    --rhoai-versions)   RHOAI_VERSIONS="$2"; shift 2 ;;
    --repo-path)        REPO_PATH="$2"; shift 2 ;;
    --commit)           DO_COMMIT=true; shift ;;
    --push)             DO_COMMIT=true; DO_PUSH=true; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    --action)           ACTION="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done
DRY_RUN_ARGS=()
if [[ "$DRY_RUN" == true ]]; then
  DRY_RUN_ARGS=(--dry-run)
fi


[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

[[ -z "$RHOAI_VERSIONS" ]] && {
  echo "ERROR: --rhoai-versions is required" >&2
  echo "  Example: --rhoai-versions \"3.6,3.5,3.4\"" >&2
  exit 1
}

# Auto-detect repository if not provided
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "$REPO_PATH" ]]; then
  if [[ -d "/Users/mchamsed/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config" ]]; then
    REPO_PATH="/Users/mchamsed/git-workspace/tools/rhoai-onboarding/repos-location/RHOAI-Build-Config"
  else
    echo "ERROR: Could not auto-detect RHOAI-Build-Config repository" >&2
    echo "  Use --repo-path to specify the location" >&2
    exit 1
  fi
fi

[[ ! -d "$REPO_PATH/.git" ]] && {
  echo "ERROR: Not a git repository: $REPO_PATH" >&2
  exit 1
}

# Parse OCP version
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Convert comma-separated RHOAI versions to array
IFS=',' read -ra RHOAI_ARRAY <<< "$RHOAI_VERSIONS"

echo "=========================================="
echo "OCP Version Onboarding - Release Branches"
echo "=========================================="
echo "OCP version:      $OCP_VERSION_FULL"
echo "Base image:       $OCP_BASE_IMAGE"
echo "RHOAI versions:   ${#RHOAI_ARRAY[@]} (${RHOAI_VERSIONS})"
echo "Repository:       $REPO_PATH"
echo "Action:           $ACTION"
echo "Dry run:          $DRY_RUN"
echo "Commit changes:   $DO_COMMIT"
echo "Push to remote:   $DO_PUSH"
echo "=========================================="
echo

# Track success/failure for summary (use simple arrays for bash 3.x compatibility)
RESULTS_BRANCHES=()
RESULTS_STATUS=()
TOTAL_VERSIONS="${#RHOAI_ARRAY[@]}"
SUCCESSFUL=0
FAILED=0
SKIPPED=0

for RHOAI_VER in "${RHOAI_ARRAY[@]}"; do
  # Remove 'rhoai-' prefix if present
  RHOAI_VER="${RHOAI_VER#rhoai-}"

  BRANCH_NAME="rhoai-${RHOAI_VER}"

  echo "Processing $BRANCH_NAME..."
  echo "----------------------------------------"

  # Check if branch exists
  cd "$REPO_PATH"
  if ! git rev-parse --verify "$BRANCH_NAME" &>/dev/null; then
    if ! git rev-parse --verify "origin/$BRANCH_NAME" &>/dev/null; then
      echo "  ⚠ Branch $BRANCH_NAME not found (local or remote), skipping"
      RESULTS_BRANCHES+=("$BRANCH_NAME")
      RESULTS_STATUS+=("skipped (branch not found)")
      ((++SKIPPED))
      echo
      continue
    fi
  fi

  # Checkout branch
  echo "  Checking out branch $BRANCH_NAME..."
  if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY RUN] Would: git checkout $BRANCH_NAME"
  else
    if ! git checkout "$BRANCH_NAME" 2>/dev/null; then
      echo "  ERROR: Failed to checkout $BRANCH_NAME"
      RESULTS_BRANCHES+=("$BRANCH_NAME")
      RESULTS_STATUS+=("failed (checkout error)")
      ((++FAILED))
      echo
      continue
    fi
    git pull --ff-only || echo "  Warning: Could not fast-forward"
  fi

  # Step 1: Update catalog directory
  echo "  Step 1/2: Creating catalog directory..."
  CATALOG_DIR="$REPO_PATH/catalog"

  CATALOG_EXIT=0
  bash "$SCRIPT_DIR/update_catalog_directory.sh" \
    --catalog-dir "$CATALOG_DIR" \
    --ocp-version "$OCP_VERSION" \
    ${DRY_RUN_ARGS[@]+"${DRY_RUN_ARGS[@]}"} || CATALOG_EXIT=$?

  if [[ $CATALOG_EXIT == 2 ]]; then
    echo "  ℹ Catalog directory already up-to-date"
  elif [[ $CATALOG_EXIT != 0 ]]; then
    echo "  ERROR: Failed to update catalog directory"
    RESULTS_BRANCHES+=("$BRANCH_NAME")
    RESULTS_STATUS+=("failed (catalog update error)")
    ((++FAILED))
    echo
    continue
  fi

  # Step 2: Update build-config.yaml
  echo "  Step 2/2: Updating build-config.yaml..."
  BUILD_CONFIG="$REPO_PATH/config/build-config.yaml"

  if [[ -f "$BUILD_CONFIG" ]]; then
    CONFIG_EXIT=0
    bash "$SCRIPT_DIR/update_build_config.sh" \
      --config-file "$BUILD_CONFIG" \
      --ocp-version "$OCP_VERSION" \
      --action "$ACTION" \
      ${DRY_RUN_ARGS[@]+"${DRY_RUN_ARGS[@]}"} || CONFIG_EXIT=$?

    if [[ $CONFIG_EXIT == 2 ]]; then
      echo "  ℹ build-config.yaml already up-to-date"
    elif [[ $CONFIG_EXIT != 0 ]]; then
      echo "  ERROR: Failed to update build-config.yaml"
      RESULTS_BRANCHES+=("$BRANCH_NAME")
      RESULTS_STATUS+=("failed (build-config error)")
      ((++FAILED))
      echo
      continue
    fi
  else
    echo "  ⚠ build-config.yaml not found, skipping"
  fi

  # Step 3: Commit changes
  if [[ "$DO_COMMIT" == true && "$DRY_RUN" == false ]]; then
    cd "$REPO_PATH"
    if git diff --quiet && git diff --cached --quiet; then
      echo "  ℹ No changes to commit"
      RESULTS_BRANCHES+=("$BRANCH_NAME")
      RESULTS_STATUS+=("success (no changes)")
      ((++SKIPPED))
    else
      echo "  Committing changes..."
      git add catalog/ config/ || true
      COMMIT_MSG="Add OCP ${OCP_VERSION_FULL} support

- Added catalog/v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}/ directory
- Updated config/build-config.yaml with OCP ${OCP_VERSION_FULL}

Co-Authored-By: OCP Onboarding Automation <noreply@redhat.com>"

      if git commit -m "$COMMIT_MSG"; then
        echo "  ✓ Committed changes"

        if [[ "$DO_PUSH" == true ]]; then
          echo "  Pushing to origin/$BRANCH_NAME..."
          if git push origin "$BRANCH_NAME"; then
            echo "  ✓ Pushed to remote"
            RESULTS_BRANCHES+=("$BRANCH_NAME")
            RESULTS_STATUS+=("success (pushed)")
            ((++SUCCESSFUL))
          else
            echo "  ERROR: Failed to push"
            RESULTS_BRANCHES+=("$BRANCH_NAME")
            RESULTS_STATUS+=("success (committed, push failed)")
            ((++FAILED))
          fi
        else
          RESULTS_BRANCHES+=("$BRANCH_NAME")
          RESULTS_STATUS+=("success (committed)")
          ((++SUCCESSFUL))
        fi
      else
        echo "  ERROR: Failed to commit"
        RESULTS_BRANCHES+=("$BRANCH_NAME")
        RESULTS_STATUS+=("failed (commit error)")
        ((++FAILED))
      fi
    fi
  elif [[ "$DRY_RUN" == true ]]; then
    RESULTS_BRANCHES+=("$BRANCH_NAME")
    RESULTS_STATUS+=("dry-run")
    ((++SUCCESSFUL))
  else
    RESULTS_BRANCHES+=("$BRANCH_NAME")
    RESULTS_STATUS+=("success (changes not committed)")
    ((++SUCCESSFUL))
  fi

  echo "  ✓ Completed $BRANCH_NAME"
  echo
done

# Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total RHOAI versions: $TOTAL_VERSIONS"
echo "Successful:           $SUCCESSFUL"
echo "Failed:               $FAILED"
echo "Skipped:              $SKIPPED"
echo

if [[ ${#RESULTS_BRANCHES[@]} -gt 0 ]]; then
  echo "Results by branch:"
  for ((i=0; i<${#RESULTS_BRANCHES[@]}; i++)); do
    printf "  %-25s %s\n" "${RESULTS_BRANCHES[$i]}" "${RESULTS_STATUS[$i]}"
  done
  echo
fi

if [[ $FAILED -gt 0 ]]; then
  echo "⚠ Some branches failed to update"
  exit 1
fi

echo "✓ Release branch updates completed successfully"
