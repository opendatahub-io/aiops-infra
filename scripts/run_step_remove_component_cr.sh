#!/usr/bin/env bash
# Offboarding: delete Konflux Component CR from the OpenShift cluster.
#
# Annotates ImageRepository CRs with skip-repository-deletion before deleting
# the Component CR so that shipped Quay images are preserved.
#
# This step is interactive — it prints what it will delete and waits for
# confirmation (reads a single character from /dev/tty).
#
# Exit codes:
#   0  Component CR deleted successfully; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Component CR not found (already removed); writes pipeline_state.json (status=done)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
CONFIRM="false"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    --confirm)  CONFIRM="true"; shift ;;
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

CURRENT_STATUS=$(jq -r '.steps.remove_component_cr.status // "pending"' "$PIPELINE_STATE")
if [[ "$CURRENT_STATUS" == "done" ]]; then
  echo "Component CR removal already done."
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

# Derive namespace and cluster instance
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  CLUSTER_INSTANCE="internal"
  KONFLUX_NAMESPACE="rhoai-tenant"
else
  CLUSTER_INSTANCE="external"
  KONFLUX_NAMESPACE="open-data-hub-tenant"
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

# Log in to the cluster
bash "$SCRIPTS_DIR/login_to_konflux_cluster.sh" "$CLUSTER_INSTANCE" || {
  echo "ERROR: Could not log in to the $CLUSTER_INSTANCE Konflux cluster." >&2; exit 1
}

# Check if the Component CR exists
if ! oc get component "$KONFLUX_COMPONENT_NAME" -n "$KONFLUX_NAMESPACE" &>/dev/null 2>&1; then
  echo "Component CR '${KONFLUX_COMPONENT_NAME}' not found in namespace '${KONFLUX_NAMESPACE}' — already removed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-component-cr-removed" \
    --comment "Component CR '${KONFLUX_COMPONENT_NAME}' already absent from namespace '${KONFLUX_NAMESPACE}'. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_component_cr --status done
  exit 2
fi

# Find associated ImageRepository CRs
IMAGE_REPOS=$(oc get imagerepository -n "$KONFLUX_NAMESPACE" -o json 2>/dev/null | \
  jq -r --arg comp "$KONFLUX_COMPONENT_NAME" \
    '.items[] | select(.metadata.labels["appstudio.openshift.io/component"] == $comp) | .metadata.name' 2>/dev/null || true)

echo ""
echo "================================================================"
echo "  Component CR deletion — confirmation required"
echo "================================================================"
echo ""
echo "  Namespace  : $KONFLUX_NAMESPACE"
echo "  Cluster    : $CLUSTER_INSTANCE"
echo "  Component  : $KONFLUX_COMPONENT_NAME"
echo ""

if [[ -n "$IMAGE_REPOS" ]]; then
  echo "  ImageRepository CRs to annotate (skip-repository-deletion=true):"
  while IFS= read -r repo; do
    echo "    - $repo"
  done <<< "$IMAGE_REPOS"
else
  echo "  No ImageRepository CRs found for this component."
fi

echo ""
echo "  This will:"
echo "    1. Annotate ImageRepository CRs to preserve Quay images"
echo "    2. DELETE the Component CR (also removes Repository CR, PaC webhooks)"
echo ""
echo "================================================================"

if [[ "$CONFIRM" != "true" ]]; then
  echo ""
  echo "Pass --confirm to execute, or re-run the skill and confirm when prompted."
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_component_cr --status awaiting_confirmation
  exit 0
fi

# Annotate ImageRepository CRs to preserve Quay images
if [[ -n "$IMAGE_REPOS" ]]; then
  echo "Annotating ImageRepository CRs with skip-repository-deletion=true..."
  while IFS= read -r repo; do
    oc annotate imagerepository "$repo" -n "$KONFLUX_NAMESPACE" \
      image-controller.appstudio.redhat.com/skip-repository-deletion="true" \
      --overwrite || {
      echo "ERROR: Failed to annotate ImageRepository '$repo'." >&2; exit 1
    }
    echo "  Annotated: $repo"
  done <<< "$IMAGE_REPOS"
fi

# Delete the Component CR
echo "Deleting Component CR '${KONFLUX_COMPONENT_NAME}'..."
oc delete component "$KONFLUX_COMPONENT_NAME" -n "$KONFLUX_NAMESPACE" || {
  echo "ERROR: Failed to delete Component CR '${KONFLUX_COMPONENT_NAME}'." >&2; exit 1
}

# Verify deletion
sleep 2
if oc get component "$KONFLUX_COMPONENT_NAME" -n "$KONFLUX_NAMESPACE" &>/dev/null 2>&1; then
  echo "ERROR: Component CR '${KONFLUX_COMPONENT_NAME}' still exists after deletion." >&2; exit 1
fi

echo "Component CR '${KONFLUX_COMPONENT_NAME}' deleted successfully."

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-component-cr-removed" \
  --comment "[step:remove_component_cr] Component CR '${KONFLUX_COMPONENT_NAME}' deleted from namespace '${KONFLUX_NAMESPACE}'.

ImageRepository CRs annotated with skip-repository-deletion=true to preserve Quay images." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_component_cr --status done

echo "COMPONENT_CR_DELETED=${KONFLUX_COMPONENT_NAME}"
