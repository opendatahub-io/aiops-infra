#!/usr/bin/env bash
# Create Konflux Application and Component for a new OCP version.
# Clones konflux-release-data, generates ocp-{version}.yaml, updates kustomization.yaml,
# and prints a GitLab merge request creation URL.
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
#   --rhoai-versions LIST Comma-separated release lines for stage and production plans
#   --repo-url URL        GitLab repo URL (default: konflux-release-data)
#   --dry-run             Show what would be done without making changes
#   --commit              Save a local commit in a temporary checkout
#   --push                Push the Konflux branch (default)

set -euo pipefail

OCP_VERSION=""
RHOAI_VERSIONS=""
REPO_URL="https://gitlab.cee.redhat.com/releng/konflux-release-data.git"
DRY_RUN=false
DO_PUSH=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version) OCP_VERSION="$2"; shift 2 ;;
    --rhoai-versions) RHOAI_VERSIONS="$2"; shift 2 ;;
    --repo-url)    REPO_URL="$2"; shift 2 ;;
    --commit)      DO_PUSH=false; shift ;;
    --push)        DO_PUSH=true; shift ;;
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
  echo "  3. Generate the Konflux application configuration for ocp-${OCP_VERSION_VAR}.yaml"
  echo
  bash "$SCRIPT_DIR/generate_konflux_app_yaml.sh" \
    --ocp-version "$OCP_VERSION" \
    --dry-run | head -20
  echo "     ..."
  echo
  echo "  4. Update the application directory’s kustomization.yaml"
  echo "     - Add: ocp-${OCP_VERSION_VAR}.yaml to resources"
  if [[ -n "$RHOAI_VERSIONS" ]]; then
    echo "  Add stage and production ReleasePlans and admission entries for: $RHOAI_VERSIONS"
  fi
  echo "  5. Commit and push changes"
  echo "  6. Create GitLab Merge Request"
  echo
  echo "[DRY RUN] Complete - no changes made"
  exit 0
fi

# Real execution
WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/ocp-onboarding-konflux.XXXXXX")
if [[ "$DO_PUSH" == true ]]; then
  trap 'rm -rf -- "$WORK_DIR"' EXIT
fi
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
if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH_NAME"; then
  git checkout --track "origin/$BRANCH_NAME"
else
  git checkout -b "$BRANCH_NAME"
fi

echo

# The current release-data layout uses source and generated development streams.
TENANT_DIR=tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant
GENERATED_DIR=tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant
FILENAME="ocp-${OCP_VERSION_VAR}.yaml"
TARGET_DIR=tenants/rhoai/applications
if [[ -d "$TENANT_DIR/fbc-fragments" ]]; then
  TARGET_DIR="$TENANT_DIR/fbc-fragments"
  export NEW_APP="rhoai-fbc-fragment-ocp-$OCP_VERSION_VAR"
  export NEW_OCP="$OCP_VERSION_DOTTED" NEW_OCP_ID="$OCP_VERSION_VAR"
  if [[ ! -e "$TARGET_DIR/$FILENAME" ]]; then
    template=$(find "$TARGET_DIR" -maxdepth 1 -type f -name 'ocp-*.yaml' | sort -V | tail -n 1)
    if [[ -z "$template" ]]; then
      echo "ERROR: No existing Konflux development stream template in $TARGET_DIR" >&2
      exit 1
    fi
    yq '
      .metadata.name = strenv(NEW_APP) |
      with(select(.kind == "ProjectDevelopmentStream");
        .spec.template.name = strenv(NEW_APP) |
        (.spec.template.values[] | select(.name == "ocpVersion") | .value) = strenv(NEW_OCP) |
        (.spec.template.values[] | select(.name == "ocpVersionName") | .value) = strenv(NEW_OCP_ID))
    ' "$template" > "$TARGET_DIR/$FILENAME"
  fi
  mkdir -p "$GENERATED_DIR"
  for kind in ProjectDevelopmentStream ProjectDevelopmentStreamTemplate; do
    kind_filename=$(printf '%s' "$kind" | tr '[:upper:]' '[:lower:]')
    generated="$GENERATED_DIR/projctl.konflux.dev_v1beta1_${kind_filename}_$NEW_APP.yaml"
    if [[ ! -e "$generated" ]]; then
      export STREAM_KIND="$kind"
      yq -e 'select(.kind == strenv(STREAM_KIND)) | .metadata.namespace = "rhoai-tenant"' \
        "$TARGET_DIR/$FILENAME" > "$generated"
    fi
  done
elif [[ ! -e "$TARGET_DIR/$FILENAME" && ! -L "$TARGET_DIR/$FILENAME" ]]; then
  echo "Generating $FILENAME..."
  mkdir -p "$TARGET_DIR"
  bash "$SCRIPT_DIR/generate_konflux_app_yaml.sh" \
    --ocp-version "$OCP_VERSION" \
    --output-file "$TARGET_DIR/$FILENAME"
fi

# Update kustomization
KUSTOMIZATION="$REPO_DIR/$TARGET_DIR/kustomization.yaml"
if [[ -f "$KUSTOMIZATION" ]]; then
  echo "Updating kustomization.yaml..."
  resources=$(yq -r '.resources[]' "$KUSTOMIZATION")
  if ! grep -Fxq -- "$FILENAME" <<< "$resources"; then
    KUSTOMIZE_RESOURCE="$FILENAME" yq -i \
      '.resources += [strenv(KUSTOMIZE_RESOURCE)]' "$KUSTOMIZATION"
  fi
fi

if [[ -n "$RHOAI_VERSIONS" ]]; then
  bash "$SCRIPT_DIR/update_release_plan.sh" --ocp-version "$OCP_VERSION" \
    --rhoai-versions "$RHOAI_VERSIONS" --krd-repo-path "$REPO_DIR"
fi

# Commit
echo
echo "Committing changes..."
git add -A

COMMIT_MSG="Onboard OCP ${OCP_VERSION_FULL} Konflux application

- Added $TARGET_DIR/$FILENAME
- Updated Kustomize resources and selected release plans

Co-Authored-By: OCP Onboarding Automation <noreply@redhat.com>"

if git diff --cached --quiet; then
  echo "  ℹ No changes to commit"
else
  git commit -m "$COMMIT_MSG"
  echo "  ✓ Committed"

  if [[ "$DO_PUSH" == false ]]; then
    echo "Konflux commit saved in $REPO_DIR"
    exit 0
  fi

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


echo
echo "✓ Konflux application creation completed"
