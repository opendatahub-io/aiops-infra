#!/usr/bin/env bash
# Wrapper for adding component to ReleasePlanAdmission (RPA) files in konflux-release-data.
# RHOAI only — exits with 2 (skipped) for ODH.
#
# Exit codes:
#   0  MR raised — prints MR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure — stderr has error; pipeline_state.json NOT written
#   2  Already present or ODH (skipped) — writes pipeline_state.json (status=done/skipped)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"
export GIT_SSL_NO_VERIFY=true

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

EXISTING_URL=$(jq -r '.steps.krd_rpa.mr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "MR already recorded in state: $EXISTING_URL"
  echo "MR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

if [[ "$PRODUCT_CONTEXT" != "RHOAI" ]]; then
  echo "RPA files are RHOAI-only — skipping for ${PRODUCT_CONTEXT}."
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step krd_rpa --status skipped
  exit 2
fi

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")
[[ -z "$TARGET_RHOAI_VERSION" ]] && {
  echo "ERROR: target_rhoai_version required for RHOAI but missing from YAML." >&2; exit 1
}

if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"; VERSION_Y="${BASH_REMATCH[2]}"; VERSION_N="${BASH_REMATCH[3]}"
  RPA_VAR="v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"; VERSION_Y="${BASH_REMATCH[2]}"
  RPA_VAR="v${VERSION_X}-${VERSION_Y}"
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-v${VERSION_X}-${VERSION_Y}"
else
  echo "ERROR: Cannot parse target_rhoai_version '${TARGET_RHOAI_VERSION}'." >&2; exit 1
fi

PRODUCT_LINE="rhoai"
[[ "$RELEASE_CATEGORY" == "Beta" ]] && PRODUCT_LINE="rhoai-beta"

KRD_URL="${KONFLUX_RELEASE_DATA_REPO_URL:-https://gitlab.cee.redhat.com/releng/konflux-release-data.git}"
SPARSE_PATHS="config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai"

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
  --src-url     "$KRD_URL" \
  --src-branch  main \
  --dest-branch "${JIRA_ID}-rpa" \
  --sparse-files "$SPARSE_PATHS") || {
  echo "ERROR: Playpen setup for konflux-release-data (RPA) failed. Check VPN and GITLAB_TOKEN." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

CHANGES_MADE=false

# RPA stage file
RPA_STAGE="$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-stage.yaml"
[[ ! -f "$RPA_STAGE" ]] && {
  echo "ERROR: rhoai-onprem-${RPA_VAR}-components-stage.yaml not found. Sprint onboarding pending." >&2; exit 1
}
if ! grep -q "name: ${COMPONENT_NAME}-${RPA_VAR}" "$RPA_STAGE" 2>/dev/null; then
  uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-rpa-component \
    "$RPA_STAGE" \
    --array-key "spec.data.mapping.components" \
    --name "${COMPONENT_NAME}-${RPA_VAR}" \
    --url "registry.stage.redhat.io/${PRODUCT_LINE}/${COMPONENT_NAME}-rhel9" || {
    echo "ERROR: Could not append to RPA stage file." >&2; exit 1
  }
  CHANGES_MADE=true
fi

# RPA prod file
RPA_PROD="$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-prod.yaml"
[[ ! -f "$RPA_PROD" ]] && {
  echo "ERROR: rhoai-onprem-${RPA_VAR}-components-prod.yaml not found. Sprint onboarding pending." >&2; exit 1
}
if ! grep -q "name: ${COMPONENT_NAME}-${RPA_VAR}" "$RPA_PROD" 2>/dev/null; then
  uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-rpa-component \
    "$RPA_PROD" \
    --array-key "spec.data.mapping.components" \
    --name "${COMPONENT_NAME}-${RPA_VAR}" \
    --url "registry.redhat.io/${PRODUCT_LINE}/${COMPONENT_NAME}-rhel9" || {
    echo "ERROR: Could not append to RPA prod file." >&2; exit 1
  }
  CHANGES_MADE=true
fi

if [[ "$CHANGES_MADE" == "false" ]]; then
  echo "Component '${COMPONENT_NAME}' already present in RPA files — no action needed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "krd-rpa-mr-merged" \
    --comment "Component '${COMPONENT_NAME}' already present in ReleasePlanAdmission files. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step krd_rpa --status done
  exit 2
fi

cd "$CLONE_DIR"
git add -A
git commit -m "Add ${KONFLUX_COMPONENT_NAME} to ReleasePlanAdmission files"

git push origin "$DEST_BRANCH" || {
  git fetch --unshallow origin || { echo "ERROR: Push failed — git fetch --unshallow failed." >&2; exit 1; }
  git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed after unshallow." >&2; exit 1; }
}

MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$KRD_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$KRD_URL" \
    --dest-branch main \
    --title       "Add ${KONFLUX_COMPONENT_NAME} to ReleasePlanAdmission" \
    --description "Add '${COMPONENT_NAME}' component mapping to stage and prod ReleasePlanAdmission files.

Product: RHOAI
Component: ${COMPONENT_NAME}
RPA version: ${RPA_VAR}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "krd-rpa-mr-raised" \
  --comment "[step:krd_rpa] GitLab MR raised to add '${KONFLUX_COMPONENT_NAME}' to ReleasePlanAdmission files.

MR URL: ${MR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step krd_rpa \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
