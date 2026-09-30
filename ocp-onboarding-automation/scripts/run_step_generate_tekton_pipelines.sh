#!/usr/bin/env bash
# Generate Tekton PipelineRun YAML files for OCP version onboarding.
# Creates one pipeline file per RHOAI version in .tekton/ directory.
#
# Usage:
#   bash run_step_generate_tekton_pipelines.sh \
#     --ocp-version 5.0 \
#     --rhoai-versions "3.6,3.5,3.4" \
#     [--repo-path /path/to/RHOAI-Build-Config] \
#     [--commit] \
#     [--push] \
#     [--dry-run]
#
# Options:
#   --ocp-version VER         OCP version (required)
#   --rhoai-versions LIST     Comma-separated RHOAI versions (required)
#   --repo-path PATH          Path to RHOAI-Build-Config repo (default: auto-detect)
#   --commit                  Create git commit for generated files
#   --push                    Push changes to remote (implies --commit)
#   --dry-run                 Show what would be generated without creating files
#
# Example:
#   bash run_step_generate_tekton_pipelines.sh --ocp-version 5.0 \
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

echo "==========================================="
echo "Generate Tekton Pipelines for OCP Version"
echo "==========================================="
echo "OCP version:      $OCP_VERSION_FULL"
echo "RHOAI versions:   ${#RHOAI_ARRAY[@]} (${RHOAI_VERSIONS})"
echo "Repository:       $REPO_PATH"
echo "Dry run:          $DRY_RUN"
echo "Commit changes:   $DO_COMMIT"
echo "Push to remote:   $DO_PUSH"
echo "==========================================="
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
GENERATED_FILES=()
RESULTS_VERSIONS=()
RESULTS_STATUS=()
SUCCESSFUL=0
FAILED=0

for RHOAI_VER in "${RHOAI_ARRAY[@]}"; do
  # Remove 'rhoai-' prefix if present
  RHOAI_VER="${RHOAI_VER#rhoai-}"

  # Generate compact version strings for filename
  RHOAI_VAR="${RHOAI_VER//[.-]/}"  # 3.6 → 36, 3.5-ea.2 → 35ea2
  OCP_VAR="${OCP_VERSION_VAR}"     # 50, 419

  PIPELINE_FILE=".tekton/rhoai-fbc-fragment-rhoai-${RHOAI_VAR}-ocp-${OCP_VAR}-push.yaml"
  FULL_PATH="$REPO_PATH/$PIPELINE_FILE"

  echo "Processing rhoai-${RHOAI_VER}..."
  echo "  Pipeline file: $PIPELINE_FILE"

  if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY RUN] Would generate:"
    bash "$SCRIPT_DIR/generate_pipeline_yaml.sh" \
      --rhoai-version "$RHOAI_VER" \
      --ocp-version "$OCP_VERSION" \
      --dry-run | head -20
    echo "  ..."
    RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
    RESULTS_STATUS+=("dry-run")
    ((SUCCESSFUL++))
  else
    # Create .tekton directory if it doesn't exist
    mkdir -p "$REPO_PATH/.tekton"

    # Generate pipeline YAML
    if bash "$SCRIPT_DIR/generate_pipeline_yaml.sh" \
      --rhoai-version "$RHOAI_VER" \
      --ocp-version "$OCP_VERSION" \
      --output-file "$FULL_PATH"; then

      echo "  ✓ Generated: $PIPELINE_FILE"
      GENERATED_FILES+=("$PIPELINE_FILE")
      RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
      RESULTS_STATUS+=("success")
      ((SUCCESSFUL++))
    else
      echo "  ERROR: Failed to generate pipeline"
      RESULTS_VERSIONS+=("rhoai-${RHOAI_VER}")
      RESULTS_STATUS+=("failed")
      ((FAILED++))
    fi
  fi

  echo
done

# Commit changes if requested
if [[ "$DO_COMMIT" == true && "$DRY_RUN" == false && ${#GENERATED_FILES[@]} -gt 0 ]]; then
  cd "$REPO_PATH"

  echo "Committing generated pipeline files..."
  git add .tekton/ || true

  COMMIT_MSG="Add Tekton pipelines for OCP ${OCP_VERSION_FULL}

Generated pipeline files:
$(printf '  - %s\n' "${GENERATED_FILES[@]}")

Co-Authored-By: OCP Onboarding Automation <noreply@redhat.com>"

  if git commit -m "$COMMIT_MSG"; then
    echo "  ✓ Committed ${#GENERATED_FILES[@]} pipeline files"

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
    echo "  ℹ No changes to commit (files may already exist)"
  fi
fi

# Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Total RHOAI versions: ${#RHOAI_ARRAY[@]}"
echo "Successful:           $SUCCESSFUL"
echo "Failed:               $FAILED"
echo

if [[ ${#RESULTS_VERSIONS[@]} -gt 0 ]]; then
  echo "Results by version:"
  for ((i=0; i<${#RESULTS_VERSIONS[@]}; i++)); do
    printf "  %-25s %s\n" "${RESULTS_VERSIONS[$i]}" "${RESULTS_STATUS[$i]}"
  done
  echo
fi

if [[ $FAILED -gt 0 ]]; then
  echo "⚠ Some pipeline generations failed"
  exit 1
fi

echo "✓ Tekton pipeline generation completed successfully"
