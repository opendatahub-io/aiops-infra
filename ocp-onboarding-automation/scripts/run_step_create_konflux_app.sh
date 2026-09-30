#!/usr/bin/env bash
# Create Konflux Application and Component for a new OCP version.
# Clones konflux-release-data, generates ocp-{version}.yaml, updates kustomization.yaml,
# and creates a GitLab MR.
#
# Usage:
#   bash run_step_create_konflux_app.sh \
#     --ocp-version 5.0 \
#     [--repo-url https://gitlab.cee.redhat.com/releng/konflux-release-data.git] \
#     [--dry-run]
#
# Prerequisites:
#   - VPN connection to gitlab.cee.redhat.com
#   - GITLAB_USER and GITLAB_TOKEN environment variables
#
# Options:
#   --ocp-version VER     OCP version to onboard (required)
#   --repo-url URL        GitLab repo URL (default: konflux-release-data)
#   --dry-run             Show what would be done without making changes

set -euo pipefail

OCP_VERSION=""
REPO_URL="https://gitlab.cee.redhat.com/releng/konflux-release-data.git"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version) OCP_VERSION="$2"; shift 2 ;;
    --repo-url)    REPO_URL="$2"; shift 2 ;;
    --dry-run)     DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

# Check prerequisites
if [[ "$DRY_RUN" == false ]]; then
  [[ -z "${GITLAB_USER:-}" ]] && {
    echo "ERROR: GITLAB_USER environment variable not set" >&2
    exit 1
  }

  [[ -z "${GITLAB_TOKEN:-}" ]] && {
    echo "ERROR: GITLAB_TOKEN environment variable not set" >&2
    exit 1
  }
fi

# Parse OCP version
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

echo "============================================"
echo "Create Konflux App for OCP Version"
echo "============================================"
echo "OCP version:      $OCP_VERSION_FULL"
echo "App name:         rhoai-fbc-fragment-ocp-${OCP_VERSION_VAR}"
echo "Repository:       $REPO_URL"
echo "Dry run:          $DRY_RUN"
echo "============================================"
echo

if [[ "$DRY_RUN" == true ]]; then
  echo "[DRY RUN] Would perform:"
  echo "  1. Clone konflux-release-data repository"
  echo "  2. Create branch: onboard-ocp-${OCP_VERSION_DASHED}"
  echo "  3. Generate: tenants/rhoai/applications/ocp-${OCP_VERSION_VAR}.yaml"
  echo
  bash "$SCRIPT_DIR/generate_konflux_app_yaml.sh" \
    --ocp-version "$OCP_VERSION" \
    --dry-run | head -20
  echo "     ..."
  echo
  echo "  4. Update: tenants/rhoai/applications/kustomization.yaml"
  echo "     - Add: ocp-${OCP_VERSION_VAR}.yaml to resources"
  echo "  5. Commit and push changes"
  echo "  6. Create GitLab Merge Request"
  echo
  echo "[DRY RUN] Complete - no changes made"
  exit 0
fi

# Real execution
WORK_DIR="/tmp/ocp-onboarding-konflux-$$"
REPO_DIR="$WORK_DIR/konflux-release-data"

echo "Setting up working directory..."
mkdir -p "$WORK_DIR"

echo "Cloning konflux-release-data..."
CLONE_URL="${REPO_URL/https:\/\//https://${GITLAB_USER}:${GITLAB_TOKEN}@}"

if ! GIT_SSL_NO_VERIFY=true git clone "$CLONE_URL" "$REPO_DIR" 2>&1; then
  echo "ERROR: Failed to clone repository" >&2
  rm -rf "$WORK_DIR"
  exit 1
fi

cd "$REPO_DIR"
git checkout main
git pull origin main

# Create branch
BRANCH_NAME="onboard-ocp-${OCP_VERSION_DASHED}"
git checkout -b "$BRANCH_NAME" 2>/dev/null || git checkout "$BRANCH_NAME"

echo

# Generate files
TARGET_DIR="tenants/rhoai/applications"
FILENAME="ocp-${OCP_VERSION_VAR}.yaml"

echo "Generating $FILENAME..."
mkdir -p "$REPO_DIR/$TARGET_DIR"
bash "$SCRIPT_DIR/generate_konflux_app_yaml.sh" \
  --ocp-version "$OCP_VERSION" \
  --output-file "$REPO_DIR/$TARGET_DIR/$FILENAME"

# Update kustomization
KUSTOMIZATION="$REPO_DIR/$TARGET_DIR/kustomization.yaml"
if [[ -f "$KUSTOMIZATION" ]]; then
  echo "Updating kustomization.yaml..."
  if grep -q "$FILENAME" "$KUSTOMIZATION"; then
    echo "  ℹ Already present"
  else
    # Add to resources (simple append for now)
    echo "- $FILENAME" >> "$KUSTOMIZATION"
    echo "  ✓ Added to resources"
  fi
fi

# Commit
echo
echo "Committing changes..."
git add "$TARGET_DIR/"

COMMIT_MSG="Onboard OCP ${OCP_VERSION_FULL} Konflux application

- Added $TARGET_DIR/$FILENAME
- Updated kustomization.yaml

Co-Authored-By: OCP Onboarding Automation <noreply@redhat.com>"

if git diff --cached --quiet; then
  echo "  ℹ No changes to commit"
else
  git commit -m "$COMMIT_MSG"
  echo "  ✓ Committed"

  echo "Pushing to GitLab..."
  if GIT_SSL_NO_VERIFY=true git push -u origin "$BRANCH_NAME" 2>&1; then
    echo "  ✓ Pushed branch: $BRANCH_NAME"
    echo
    echo "GitLab MR URL:"
    echo "  https://gitlab.cee.redhat.com/releng/konflux-release-data/-/merge_requests/new?merge_request[source_branch]=$BRANCH_NAME"
  else
    echo "  ERROR: Failed to push" >&2
    exit 1
  fi
fi

# Cleanup
cd /
rm -rf "$WORK_DIR"

echo
echo "✓ Konflux application creation completed"
