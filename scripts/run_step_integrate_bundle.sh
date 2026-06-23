#!/usr/bin/env bash
# Wrapper for the integrate-component-with-bundle step.
#
# Adds a relatedImages entry to the build-config repository and raises a GitHub PR.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Component already present in bundle — writes pipeline_state.json (status=done)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$JIRA_URL" ]] && { echo "ERROR: --jira-url is required" >&2; exit 1; }

JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.bundle.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"
# Sets: COMPONENT_NAME PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI IS_OPERATOR REPO_URL REPO_BRANCH

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")

if [[ "$PRODUCT_CONTEXT" == "RHOAI" && -z "$TARGET_RHOAI_VERSION" ]]; then
  echo "ERROR: target_rhoai_version required for RHOAI bundle integration but missing." >&2; exit 1
fi

# Resolve BC_URL from product context
# BUILD_CONFIG_REPO_URL is kept for backward compat but prefer the split vars:
# RHOAI_BUILD_CONFIG_REPO_URL / ODH_BUILD_CONFIG_REPO_URL (handled inside resolve_bc_url.sh)
eval "$(bash "$SCRIPTS_DIR/resolve_bc_url.sh" \
  --product-context "$PRODUCT_CONTEXT")"
# Sets: BC_URL, BC_PATH
echo "BC_URL : $BC_URL"

if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
fi

# Resolve related image
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  QUAY_REPO_NAME="${COMPONENT_NAME}-rhel9"
else
  QUAY_REPO_NAME="$COMPONENT_NAME"
fi

eval "$(bash "$SCRIPTS_DIR/resolve_bundle_image.sh" \
  --component-name "$COMPONENT_NAME" \
  --quay-org       "$QUAY_ORG" \
  --quay-repo      "$QUAY_REPO_NAME")"
# Sets: RELATED_IMAGE_NAME, RELATED_IMAGE_VALUE, USING_PLACEHOLDER

# Clone (sparse) — RHOAI uses the version branch, ODH uses main
cd "$WORKDIR"
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  SRC_BRANCH="$BRANCH_NAME"
  SPARSE="bundle config"
else
  SRC_BRANCH="main"
  SPARSE="bundle"
fi

PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$BC_URL" \
  --src-branch  "$SRC_BRANCH" \
  --dest-branch "$JIRA_ID" \
  --sparse-files "$SPARSE") || {
  echo "ERROR: Playpen setup for build-config failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

BUNDLE_PATCH="$CLONE_DIR/bundle/bundle-patch.yaml"
[[ ! -f "$BUNDLE_PATCH" ]] && {
  echo "ERROR: bundle/bundle-patch.yaml not found in $CLONE_DIR." >&2; exit 1
}

# Check idempotency
if grep -qF "$RELATED_IMAGE_NAME" "$BUNDLE_PATCH" 2>/dev/null; then
  echo "Entry '${RELATED_IMAGE_NAME}' already present in bundle-patch.yaml."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "bundle-changes-done" \
    --comment "Bundle relatedImages entry '${RELATED_IMAGE_NAME}' already present in ${BC_PATH}. No PR needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step bundle --status done
  exit 2
fi

# Update bundle-patch.yaml — add relatedImages entry
uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-array-entry \
  "$BUNDLE_PATCH" \
  --array-key relatedImages \
  --name      "$RELATED_IMAGE_NAME" \
  --value     "$RELATED_IMAGE_VALUE" || {
  echo "ERROR: Could not update bundle-patch.yaml." >&2; exit 1
}

FILES_CHANGED="bundle/bundle-patch.yaml"

# Update Dockerfile git labels (if a Dockerfile exists in the bundle dir)
BUNDLE_DOCKERFILE="$CLONE_DIR/bundle/Dockerfile"
if [[ -f "$BUNDLE_DOCKERFILE" ]]; then
  eval "$(uv run --script "$SCRIPTS_DIR/update_bundle_dockerfile_git_labels.py" \
    "$BUNDLE_DOCKERFILE" \
    --component-name "$COMPONENT_NAME")" || true
  FILES_CHANGED="$FILES_CHANGED bundle/Dockerfile"
fi

# RHOAI: also update config/build-config.yaml
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  BC_CONFIG="$CLONE_DIR/config/build-config.yaml"
  if [[ -f "$BC_CONFIG" ]] && ! grep -qF "$COMPONENT_NAME" "$BC_CONFIG" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-build-config-component \
      "$BC_CONFIG" \
      --component-name "$COMPONENT_NAME" \
      --version-var    "${VERSION_VAR:-}" \
      --repo-url       "$REPO_URL" \
      --repo-branch    "$REPO_BRANCH" 2>/dev/null || true
    FILES_CHANGED="$FILES_CHANGED config/build-config.yaml"
  fi
fi

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir     "$CLONE_DIR" \
  --files         "$FILES_CHANGED" \
  --message       "Add ${COMPONENT_NAME} to bundle relatedImages" \
  --branch        "$DEST_BRANCH" \
  --target-branch "$SRC_BRANCH" \
  --jira-url      "$JIRA_URL"

# Raise PR
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$BC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$BC_URL" \
    --dest-branch "$SRC_BRANCH" \
    --title       "Add ${COMPONENT_NAME} to bundle relatedImages" \
    --description "Adds relatedImages entry for '${COMPONENT_NAME}' to bundle/bundle-patch.yaml.

Image: ${RELATED_IMAGE_VALUE}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "bundle-pr-raised" \
  --comment "[step:bundle] GitHub PR raised to add '${COMPONENT_NAME}' to bundle relatedImages in ${BC_PATH}.

PR URL: ${PR_URL}
Image: ${RELATED_IMAGE_VALUE}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step bundle \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
