#!/usr/bin/env bash
# Offboarding: remove component from konflux-release-data.
#
# ODH: removes Component document from opendatahub-ci-components.yaml
# RHOAI: removes from ProjectDevelopmentStream YAML, RPA stage/prod, automation/resources.yaml
#
# Exit codes:
#   0  MR raised — prints MR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Component not found (already removed) — writes pipeline_state.json (status=done)
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

EXISTING_URL=$(jq -r '.steps.remove_krd.mr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "MR already recorded in state: $EXISTING_URL"
  echo "MR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")

KUSTOMIZE_BIN="kustomize"
if ! command -v kustomize &>/dev/null && [[ -x "${HOME}/.local/bin/kustomize" ]]; then
  KUSTOMIZE_BIN="${HOME}/.local/bin/kustomize"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  SPARSE_PATHS="tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai"
else
  SPARSE_PATHS="tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant tenants-config/auto-generated/cluster/stone-prd-rh01/tenants/open-data-hub-tenant"
fi

# Derive KONFLUX_COMPONENT_NAME
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  [[ -z "$TARGET_RHOAI_VERSION" ]] && {
    echo "ERROR: target_rhoai_version required for RHOAI but missing." >&2; exit 1
  }
  if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
    KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-ea-${BASH_REMATCH[3]}"
  elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
    KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}"
  else
    echo "ERROR: Cannot parse target_rhoai_version '${TARGET_RHOAI_VERSION}'." >&2; exit 1
  fi
else
  if [[ "$COMPONENT_NAME" == *-ci ]]; then
    KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"
  else
    KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"
  fi
fi

KRD_URL="${KONFLUX_RELEASE_DATA_REPO_URL:-https://gitlab.cee.redhat.com/releng/konflux-release-data.git}"
echo "KRD_URL resolved to: $KRD_URL"

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
  --src-url     "$KRD_URL" \
  --src-branch  main \
  --dest-branch "${JIRA_ID}-offboard" \
  --sparse-files "$SPARSE_PATHS") || {
  echo "ERROR: Playpen setup for konflux-release-data failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

CHANGES_MADE=false

if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  TARGET_YAML="tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant/opendatahub-ci-components.yaml"
  ODH_YAML="$CLONE_DIR/$TARGET_YAML"
  [[ ! -f "$ODH_YAML" ]] && { echo "ERROR: $TARGET_YAML not found." >&2; exit 1; }

  if grep -q "name: $KONFLUX_COMPONENT_NAME" "$ODH_YAML" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-yaml-doc \
      "$ODH_YAML" --name "$KONFLUX_COMPONENT_NAME" || {
      echo "ERROR: Could not remove $KONFLUX_COMPONENT_NAME from $TARGET_YAML." >&2; exit 1
    }
    CHANGES_MADE=true
  fi

elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"

  if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
    VERSION_X="${BASH_REMATCH[1]}"; VERSION_Y="${BASH_REMATCH[2]}"; VERSION_N="${BASH_REMATCH[3]}"
    VERSION_NAME="v${VERSION_X}.${VERSION_Y}-ea.${VERSION_N}"
    RPA_VAR="v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
  else
    [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]
    VERSION_X="${BASH_REMATCH[1]}"; VERSION_Y="${BASH_REMATCH[2]}"; VERSION_N=""
    VERSION_NAME="v${VERSION_X}.${VERSION_Y}"
    RPA_VAR="v${VERSION_X}-${VERSION_Y}"
  fi

  # Remove from ProjectDevelopmentStream YAML
  PDS_FILE="$CLONE_DIR/tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/${VERSION_NAME}/ProjectDevelopmentStream-${VERSION_NAME}.yaml"
  if [[ -f "$PDS_FILE" ]] && grep -q "name: ${COMPONENT_NAME}-{{.versionName}}" "$PDS_FILE" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-multidoc-list-item \
      "$PDS_FILE" \
      --doc-kind "ProjectDevelopmentStreamTemplate" \
      --array-key "spec.resources" \
      --name "${COMPONENT_NAME}-" || true
    CHANGES_MADE=true
  fi

  # Remove from RPA stage
  RPA_STAGE="$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-stage.yaml"
  if [[ -f "$RPA_STAGE" ]] && grep -q "name: ${COMPONENT_NAME}-${RPA_VAR}" "$RPA_STAGE" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-rpa-component \
      "$RPA_STAGE" \
      --array-key "spec.data.mapping.components" \
      --name "${COMPONENT_NAME}-${RPA_VAR}" || true
    CHANGES_MADE=true
  fi

  # Remove from RPA prod
  RPA_PROD="$CLONE_DIR/config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-${RPA_VAR}-components-prod.yaml"
  if [[ -f "$RPA_PROD" ]] && grep -q "name: ${COMPONENT_NAME}-${RPA_VAR}" "$RPA_PROD" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-rpa-component \
      "$RPA_PROD" \
      --array-key "spec.data.mapping.components" \
      --name "${COMPONENT_NAME}-${RPA_VAR}" || true
    CHANGES_MADE=true
  fi

  # Remove from automation/resources.yaml
  AUTOMATION_FILE="$CLONE_DIR/tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/automation/resources.yaml"
  if [[ -f "$AUTOMATION_FILE" ]] && grep -q "name: pull-request-pipelines-${COMPONENT_NAME}" "$AUTOMATION_FILE" 2>/dev/null; then
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-yaml-doc \
      "$AUTOMATION_FILE" --name "pull-request-pipelines-${COMPONENT_NAME}" || true
    CHANGES_MADE=true
  fi
fi

if [[ "$CHANGES_MADE" == "false" ]]; then
  echo "Component '${KONFLUX_COMPONENT_NAME}' not found in konflux-release-data — already removed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-krd-mr-merged" \
    --comment "Component '${KONFLUX_COMPONENT_NAME}' already absent from konflux-release-data. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_krd --status done
  exit 2
fi

# Build manifests
cd "$CLONE_DIR/tenants-config"
./build-manifests.sh "$KUSTOMIZE_BIN" || {
  echo "ERROR: build-manifests.sh failed." >&2; exit 1
}

cd "$CLONE_DIR"
yamllint -s -f colored .gitlab-ci.yml .gitlab tenants-config/cluster 2>&1 || true

cd "$CLONE_DIR"
git add -A
git commit -m "Remove ${KONFLUX_COMPONENT_NAME} Component from konflux-release-data"

cd "$CLONE_DIR/tenants-config"
./verify-manifests.sh "$KUSTOMIZE_BIN" || {
  echo "ERROR: verify-manifests.sh failed." >&2; exit 1
}

cd "$CLONE_DIR"
git push origin "$DEST_BRANCH" || {
  git fetch --unshallow origin || { echo "ERROR: Push failed." >&2; exit 1; }
  git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed after unshallow." >&2; exit 1; }
}

MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$KRD_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$KRD_URL" \
    --dest-branch main \
    --title       "Remove ${KONFLUX_COMPONENT_NAME} Component (offboarding)" \
    --description "Removes Konflux Component '${KONFLUX_COMPONENT_NAME}' from konflux-release-data.

Product: ${PRODUCT_CONTEXT}
Component: ${COMPONENT_NAME}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-krd-mr-raised" \
  --comment "[step:remove_krd] GitLab MR raised to remove '${KONFLUX_COMPONENT_NAME}' from konflux-release-data.

MR URL: ${MR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_krd \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
