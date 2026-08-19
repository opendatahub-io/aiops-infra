#!/usr/bin/env bash
# Offboarding: remove component from bundle relatedImages (and build-config for RHOAI).
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Component not found in bundle (already removed) — writes pipeline_state.json (status=done)
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

DRY_RUN_PREFIX=""
if [[ "${OFFBOARD_DRY_RUN:-false}" == "true" ]]; then
  DRY_RUN_PREFIX="[DRY RUN] "
fi

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.remove_bundle.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")

eval "$(bash "$SCRIPTS_DIR/resolve_bc_url.sh" \
  --product-context "$PRODUCT_CONTEXT")"
echo "BC_URL : $BC_URL"

if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
fi

# Derive related image name
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  QUAY_REPO_NAME="${COMPONENT_NAME}-rhel9"
else
  QUAY_REPO_NAME="$COMPONENT_NAME"
fi
eval "$(bash "$SCRIPTS_DIR/resolve_bundle_image.sh" \
  --component-name "$COMPONENT_NAME" \
  --quay-org       "$QUAY_ORG" \
  --quay-repo      "$QUAY_REPO_NAME")"

# Clone
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
  --dest-branch "${JIRA_ID}-offboard" \
  --sparse-files "$SPARSE") || {
  echo "ERROR: Playpen setup for build-config failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

BUNDLE_PATCH="$CLONE_DIR/bundle/bundle-patch.yaml"
[[ ! -f "$BUNDLE_PATCH" ]] && {
  echo "ERROR: bundle/bundle-patch.yaml not found." >&2; exit 1
}

CHANGES_MADE=false

# Remove relatedImages entry
if grep -qF "$RELATED_IMAGE_NAME" "$BUNDLE_PATCH" 2>/dev/null; then
  uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-array-entry \
    "$BUNDLE_PATCH" \
    --array-key "patch.relatedImages" \
    --name      "$RELATED_IMAGE_NAME" || true
  CHANGES_MADE=true
fi

FILES_CHANGED="bundle/bundle-patch.yaml"

# Remove Dockerfile git-label ARGs and LABEL entries
BUNDLE_DOCKERFILE="$CLONE_DIR/bundle/Dockerfile"
if [[ -f "$BUNDLE_DOCKERFILE" ]]; then
  GIT_URL_LABEL="$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_GIT_URL"
  GIT_COMMIT_LABEL="$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_GIT_COMMIT"

  DOCKERFILE_CHANGED=false

  # Remove ARG declarations
  if grep -q "^ARG ${GIT_URL_LABEL}=" "$BUNDLE_DOCKERFILE" 2>/dev/null; then
    sed -i '' "/^ARG ${GIT_URL_LABEL}=/d" "$BUNDLE_DOCKERFILE"
    sed -i '' "/^ARG ${GIT_COMMIT_LABEL}=/d" "$BUNDLE_DOCKERFILE"
    DOCKERFILE_CHANGED=true
  fi

  # Remove LABEL entries (component.git.url and component.git.commit lines)
  if grep -q "${COMPONENT_NAME}\.git\.url=" "$BUNDLE_DOCKERFILE" 2>/dev/null; then
    sed -i '' "/${COMPONENT_NAME}\.git\.url=/d" "$BUNDLE_DOCKERFILE"
    sed -i '' "/${COMPONENT_NAME}\.git\.commit=/d" "$BUNDLE_DOCKERFILE"
    DOCKERFILE_CHANGED=true
  fi

  if [[ "$DOCKERFILE_CHANGED" == "true" ]]; then
    FILES_CHANGED="$FILES_CHANGED bundle/Dockerfile"
    CHANGES_MADE=true
  fi
fi

# Remove bundle_build_args.map entries
BUNDLE_ARGS_MAP="$CLONE_DIR/bundle/bundle_build_args.map"
if [[ -f "$BUNDLE_ARGS_MAP" ]]; then
  GIT_URL_LABEL="$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_GIT_URL"
  GIT_COMMIT_LABEL="$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_GIT_COMMIT"

  if grep -q "^${GIT_URL_LABEL}=" "$BUNDLE_ARGS_MAP" 2>/dev/null; then
    sed -i '' "/^${GIT_URL_LABEL}=/d" "$BUNDLE_ARGS_MAP"
    sed -i '' "/^${GIT_COMMIT_LABEL}=/d" "$BUNDLE_ARGS_MAP"
    FILES_CHANGED="$FILES_CHANGED bundle/bundle_build_args.map"
    CHANGES_MADE=true
  fi
fi

# RHOAI: also remove from config/build-config.yaml
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  BC_CONFIG="$CLONE_DIR/config/build-config.yaml"
  REPO_MAPPING_KEY="rhoai/${COMPONENT_NAME}-rhel9"
  if [[ -f "$BC_CONFIG" ]] && grep -qF "$REPO_MAPPING_KEY" "$BC_CONFIG" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-build-config-component \
      "$BC_CONFIG" \
      --key "$REPO_MAPPING_KEY" 2>/dev/null || true
    FILES_CHANGED="$FILES_CHANGED config/build-config.yaml"
    CHANGES_MADE=true
  fi
fi

if [[ "$CHANGES_MADE" == "false" ]]; then
  echo "Component '${COMPONENT_NAME}' not found in bundle — already removed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-bundle-pr-merged" \
    --comment "${DRY_RUN_PREFIX}Component '${COMPONENT_NAME}' already absent from bundle-patch.yaml. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_bundle --status done
  exit 2
fi

bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$FILES_CHANGED" \
  --message   "Remove ${COMPONENT_NAME} from bundle relatedImages (offboarding)" \
  --branch    "$DEST_BRANCH"

PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$BC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$BC_URL" \
    --dest-branch "$SRC_BRANCH" \
    --title       "${DRY_RUN_PREFIX}Remove ${COMPONENT_NAME} from bundle relatedImages (offboarding)" \
    --description "Removes relatedImages entry for '${COMPONENT_NAME}' from bundle/bundle-patch.yaml.

Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-bundle-pr-raised" \
  --comment "${DRY_RUN_PREFIX}[step:remove_bundle] GitHub PR raised to remove '${COMPONENT_NAME}' from bundle relatedImages.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_bundle \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
