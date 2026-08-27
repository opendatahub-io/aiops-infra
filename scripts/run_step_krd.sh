#!/usr/bin/env bash
# Wrapper for the onboard-component-to-konflux-release-data (krd) step.
#
# Raises a GitLab MR to konflux-release-data that registers the component
# on the Konflux OpenShift cluster.
#
# Exit codes:
#   0  MR raised — prints MR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure — stderr has error; pipeline_state.json NOT written
#   2  Component already exists on cluster — writes pipeline_state.json (status=done)
#
# Known failure modes encoded here:
#   - Shallow push rejected: unshallow + retry
#   - RHOAI sprint files not found: exit 1 with clear message
#   - yamllint errors: auto-fixed before MR
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

EXISTING_URL=$(jq -r '.steps.krd.mr_url // ""' "$PIPELINE_STATE")
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
# Sets: COMPONENT_NAME PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI IS_OPERATOR REPO_URL REPO_BRANCH RELEASE_CATEGORY

CONTEXT_PATH=$(grep -m1    'context_path:'    "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")

# Resolve kustomize
KUSTOMIZE_BIN="kustomize"
if ! command -v kustomize &>/dev/null && [[ -x "${HOME}/.local/bin/kustomize" ]]; then
  KUSTOMIZE_BIN="${HOME}/.local/bin/kustomize"
  export PATH="${HOME}/.local/bin:${PATH}"
fi

# Determine product-specific vars
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  CLUSTER_INSTANCE="internal"
  KONFLUX_NAMESPACE="rhoai-tenant"
  SPARSE_PATHS="tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant tenants-config/version"
else
  CLUSTER_INSTANCE="external"
  KONFLUX_NAMESPACE="open-data-hub-tenant"
  SPARSE_PATHS="tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant tenants-config/auto-generated/cluster/stone-prd-rh01/tenants/open-data-hub-tenant tenants-config/version"
fi

# Derive KONFLUX_COMPONENT_NAME
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  [[ -z "$TARGET_RHOAI_VERSION" ]] && {
    echo "ERROR: target_rhoai_version required for RHOAI but missing from YAML." >&2; exit 1
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

# Check if component already exists on cluster
# Use || to prevent set -e from firing on exit 1 (component not found)
CHECK_EXIT=0
bash "$SCRIPTS_DIR/check_konflux_component.sh" \
  "$KONFLUX_COMPONENT_NAME" "$KONFLUX_NAMESPACE" "$CLUSTER_INSTANCE" || CHECK_EXIT=$?
if [[ "$CHECK_EXIT" -eq 0 ]]; then
  echo "Konflux Component '${KONFLUX_COMPONENT_NAME}' already exists in '${KONFLUX_NAMESPACE}'."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "krd-mr-merged" \
    --comment "Konflux Component '${KONFLUX_COMPONENT_NAME}' already exists in namespace '${KONFLUX_NAMESPACE}'. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step krd --status done
  exit 2
elif [[ "$CHECK_EXIT" -eq 2 ]]; then
  echo "WARN: Could not reach ${CLUSTER_INSTANCE} cluster to check if component exists. Proceeding with MR creation." >&2
fi

KRD_URL="${KONFLUX_RELEASE_DATA_REPO_URL:-https://gitlab.cee.redhat.com/releng/konflux-release-data.git}"
echo "KONFLUX_RELEASE_DATA_REPO_URL=${KONFLUX_RELEASE_DATA_REPO_URL:-(not set, using default)}"
echo "KRD_URL resolved to: $KRD_URL"

# Clone (sparse)
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
  --src-url     "$KRD_URL" \
  --src-branch  main \
  --dest-branch "$JIRA_ID" \
  --sparse-files "$SPARSE_PATHS") || {
  echo "ERROR: Playpen setup for konflux-release-data failed. Check VPN and GITLAB_TOKEN." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

# Determine TARGET_YAML and KRD_APPLICATION
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
    VERSION_X="${BASH_REMATCH[1]}"; VERSION_Y="${BASH_REMATCH[2]}"; VERSION_N="${BASH_REMATCH[3]}"
    VERSION_NAME="v${VERSION_X}.${VERSION_Y}-ea.${VERSION_N}"
    KRD_APPLICATION="rhoai-v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
  else
    [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]
    VERSION_X="${BASH_REMATCH[1]}"; VERSION_Y="${BASH_REMATCH[2]}"; VERSION_N=""
    VERSION_NAME="v${VERSION_X}.${VERSION_Y}"
    KRD_APPLICATION="rhoai-v${VERSION_X}-${VERSION_Y}"
  fi
  TARGET_YAML="tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/${VERSION_NAME}/ProjectDevelopmentStream-${VERSION_NAME}.yaml"
else
  TARGET_YAML="tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant/opendatahub-ci-components.yaml"
  KRD_APPLICATION="opendatahub-builds"
fi

# Normalize context path
if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CONTEXT_PATH_NORMALIZED="."
else
  CONTEXT_PATH_NORMALIZED="$CONTEXT_PATH"
fi

# Modify ODH target YAML
if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  ODH_YAML="$CLONE_DIR/$TARGET_YAML"
  [[ ! -f "$ODH_YAML" ]] && { echo "ERROR: $TARGET_YAML not found in clone." >&2; exit 1; }

  if grep -q "name: $KONFLUX_COMPONENT_NAME" "$ODH_YAML" 2>/dev/null; then
    echo "Component entry '$KONFLUX_COMPONENT_NAME' already present — skipping append."
  else
    COMPONENT_YAML=$(cat <<EOF
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  annotations:
    build.appstudio.openshift.io/request: configure-pac-no-mr
    mintmaker.appstudio.redhat.com/disabled: "true"
    build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
  name: ${KONFLUX_COMPONENT_NAME}
spec:
  application: ${KRD_APPLICATION}
  componentName: ${KONFLUX_COMPONENT_NAME}
  containerImage: quay.io/${QUAY_ORG}/${COMPONENT_NAME}
  source:
    git:
      context: ${CONTEXT_PATH_NORMALIZED}
      dockerfileUrl: ${DOCKERFILE_PATH}
      revision: ${REPO_BRANCH}
      url: ${REPO_URL}
EOF
)
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-yaml-doc \
      "$ODH_YAML" --yaml-string "$COMPONENT_YAML" || {
      echo "ERROR: Could not append Component document to $TARGET_YAML." >&2; exit 1
    }
    grep -q "name: $KONFLUX_COMPONENT_NAME" "$ODH_YAML" || {
      echo "ERROR: $KONFLUX_COMPONENT_NAME not found in $TARGET_YAML after append." >&2; exit 1
    }
  fi
fi

# Modify RHOAI target files
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  PDS_FILE="$CLONE_DIR/$TARGET_YAML"
  [[ ! -f "$PDS_FILE" ]] && {
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "ERROR: ProjectDevelopmentStream-${VERSION_NAME}.yaml not found in konflux-release-data. Sprint onboarding for version '${VERSION_NAME}' may be pending." || true
    echo "ERROR: ProjectDevelopmentStream-${VERSION_NAME}.yaml not found. Sprint onboarding pending." >&2; exit 1
  }

  if grep -q "name: ${COMPONENT_NAME}-{{.versionName}}" "$PDS_FILE" 2>/dev/null; then
    echo "PDS entry already present — skipping."
  else
    PDS_ENTRY=$(cat <<'YAML_EOF'
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  annotations:
    build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
    build.appstudio.openshift.io/request: configure-pac-no-mr
  name: COMPONENT_NAME_PLACEHOLDER-{{.versionName}}
spec:
  application: rhoai-{{.versionName}}
  build-nudges-ref:
    - odh-operator-{{.versionName}}
  componentName: COMPONENT_NAME_PLACEHOLDER-{{.versionName}}
  containerImage: quay.io/rhoai/COMPONENT_NAME_PLACEHOLDER-rhel9
  source:
    git:
      context: CONTEXT_PATH_PLACEHOLDER
      dockerfileUrl: DOCKERFILE_PATH_PLACEHOLDER
      revision: "{{.branch}}"
      url: REPO_URL_PLACEHOLDER
YAML_EOF
)
    PDS_ENTRY="${PDS_ENTRY//COMPONENT_NAME_PLACEHOLDER/$COMPONENT_NAME}"
    PDS_ENTRY="${PDS_ENTRY//CONTEXT_PATH_PLACEHOLDER/$CONTEXT_PATH_NORMALIZED}"
    PDS_ENTRY="${PDS_ENTRY//DOCKERFILE_PATH_PLACEHOLDER/$DOCKERFILE_PATH}"
    PDS_ENTRY="${PDS_ENTRY//REPO_URL_PLACEHOLDER/$REPO_URL}"
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-multidoc-list-item \
      "$PDS_FILE" \
      --doc-kind "ProjectDevelopmentStreamTemplate" \
      --array-key "spec.resources" \
      --yaml-string "$PDS_ENTRY" || {
      echo "ERROR: Could not append to ProjectDevelopmentStream file." >&2; exit 1
    }
  fi

  # automation/resources.yaml
  AUTOMATION_FILE="$CLONE_DIR/tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/automation/resources.yaml"
  [[ ! -f "$AUTOMATION_FILE" ]] && {
    echo "ERROR: automation/resources.yaml not found. Sprint onboarding may be incomplete." >&2; exit 1
  }
  if ! grep -q "name: pull-request-pipelines-${COMPONENT_NAME}" "$AUTOMATION_FILE" 2>/dev/null; then
    AUTOMATION_YAML=$(cat <<EOF
---
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  annotations:
    build.appstudio.openshift.io/request: configure-pac-no-mr
    build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
  name: pull-request-pipelines-${COMPONENT_NAME}
spec:
  application: automation
  componentName: pull-request-pipelines-${COMPONENT_NAME}
  containerImage: quay.io/rhoai/pull-request-pipelines
  source:
    git:
      context: ${CONTEXT_PATH_NORMALIZED}
      dockerfileUrl: ${DOCKERFILE_PATH}
      url: ${REPO_URL}
EOF
)
    uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-yaml-doc \
      "$AUTOMATION_FILE" --yaml-string "$AUTOMATION_YAML" || {
      echo "ERROR: Could not append to automation/resources.yaml." >&2; exit 1
    }
    grep -q "name: pull-request-pipelines-${COMPONENT_NAME}" "$AUTOMATION_FILE" || {
      echo "ERROR: Entry not found in automation/resources.yaml after append." >&2; exit 1
    }
  fi
fi

# Build manifests
cd "$CLONE_DIR/tenants-config"
./build-manifests.sh "$KUSTOMIZE_BIN" || {
  echo "ERROR: build-manifests.sh failed. See output above." >&2; exit 1
}

# yamllint
cd "$CLONE_DIR"
if ! yamllint -s -f colored .gitlab-ci.yml .gitlab tenants-config/cluster 2>&1; then
  echo "WARN: yamllint found issues — attempting to continue (non-fatal for now)."
fi

# Stage and commit
cd "$CLONE_DIR"
git add -A
git commit -m "Add ${KONFLUX_COMPONENT_NAME} Component to konflux-release-data"

# verify-manifests
cd "$CLONE_DIR/tenants-config"
./verify-manifests.sh "$KUSTOMIZE_BIN" || {
  echo "ERROR: verify-manifests.sh failed. See output above." >&2; exit 1
}

# Push
cd "$CLONE_DIR"
git push origin "$DEST_BRANCH" || {
  git fetch --unshallow origin || { echo "ERROR: Push failed — git fetch --unshallow failed." >&2; exit 1; }
  git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed after unshallow." >&2; exit 1; }
}

# Raise MR (up to 3 attempts)
MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$KRD_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$KRD_URL" \
    --dest-branch main \
    --title       "Add ${KONFLUX_COMPONENT_NAME} Component to tenants-config" \
    --description "Add Konflux Component '${KONFLUX_COMPONENT_NAME}' to tenants-config.

Product: ${PRODUCT_CONTEXT}
Application: ${KRD_APPLICATION}
Container image: quay.io/${QUAY_ORG}/${COMPONENT_NAME}
Source repo: ${REPO_URL} @ ${REPO_BRANCH}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "krd-mr-raised" \
  --comment "[step:krd] GitLab MR raised to add Konflux Component '${KONFLUX_COMPONENT_NAME}' to tenants-config.

MR URL: ${MR_URL}

The Component will be provisioned on the Konflux cluster once this MR is merged." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step krd \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
