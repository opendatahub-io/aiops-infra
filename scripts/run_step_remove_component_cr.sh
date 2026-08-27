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

DRY_RUN_PREFIX=""
if [[ "${OFFBOARD_DRY_RUN:-false}" == "true" ]]; then
  DRY_RUN_PREFIX="[DRY RUN] "
fi

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

# Build list of Component CR names to delete
CR_NAMES=()
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  [[ -z "$TARGET_RHOAI_VERSION" ]] && {
    echo "ERROR: target_rhoai_version required for RHOAI but missing." >&2; exit 1
  }
  if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
    CR_NAMES+=("${COMPONENT_NAME}-v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-ea-${BASH_REMATCH[3]}")
  elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
    CR_NAMES+=("${COMPONENT_NAME}-v${BASH_REMATCH[1]}-${BASH_REMATCH[2]}")
  else
    echo "ERROR: Cannot parse target_rhoai_version '${TARGET_RHOAI_VERSION}'." >&2; exit 1
  fi
else
  # ODH: builds uses -ci suffix, release uses bare name
  BUILDS_NAME=$( [[ "$COMPONENT_NAME" == *-ci ]] && echo "$COMPONENT_NAME" || echo "${COMPONENT_NAME}-ci" )
  RELEASE_NAME="${COMPONENT_NAME%-ci}"

  case "$ODH_APPLICATIONS" in
    builds)  CR_NAMES+=("$BUILDS_NAME") ;;
    release) CR_NAMES+=("$RELEASE_NAME") ;;
    both)    CR_NAMES+=("$BUILDS_NAME" "$RELEASE_NAME") ;;
    *) echo "ERROR: Invalid odh_applications value '${ODH_APPLICATIONS}'. Use builds, release, or both." >&2; exit 1 ;;
  esac
fi

# Log in to the cluster
bash "$SCRIPTS_DIR/login_to_konflux_cluster.sh" "$CLUSTER_INSTANCE" || {
  echo "ERROR: Could not log in to the $CLUSTER_INSTANCE Konflux cluster." >&2; exit 1
}

# Check which CRs actually exist on the cluster
FOUND_CRS=()
for cr in "${CR_NAMES[@]}"; do
  if oc get component "$cr" -n "$KONFLUX_NAMESPACE" &>/dev/null 2>&1; then
    FOUND_CRS+=("$cr")
  else
    echo "Component CR '$cr' not found — already removed."
  fi
done

if [[ ${#FOUND_CRS[@]} -eq 0 ]]; then
  echo "All targeted Component CRs already removed from namespace '${KONFLUX_NAMESPACE}'."
  uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
    --add-label "offboard-component-cr-removed" \
    --comment "${DRY_RUN_PREFIX}Component CRs (${CR_NAMES[*]}) already absent from namespace '${KONFLUX_NAMESPACE}'. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_component_cr --status done
  exit 2
fi

# Collect ImageRepository CRs for all found components (bash 3.2 compatible)
IMAGE_REPOS_DIR=$(mktemp -d)
trap 'rm -rf "$IMAGE_REPOS_DIR"' EXIT
ALL_IMAGE_REPOS=""
for cr in "${FOUND_CRS[@]}"; do
  repos=$(oc get imagerepository -n "$KONFLUX_NAMESPACE" -o json 2>/dev/null | \
    jq -r --arg comp "$cr" \
      '.items[] | select(.metadata.labels["appstudio.openshift.io/component"] == $comp) | .metadata.name' 2>/dev/null || true)
  echo "$repos" > "$IMAGE_REPOS_DIR/$cr"
  [[ -n "$repos" ]] && ALL_IMAGE_REPOS="${ALL_IMAGE_REPOS}${repos}"$'\n'
done

echo ""
echo "================================================================"
echo "  Component CR deletion — confirmation required"
echo "================================================================"
echo ""
echo "  Namespace  : $KONFLUX_NAMESPACE"
echo "  Cluster    : $CLUSTER_INSTANCE"
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
  echo "  Application: rhoai-${VERSION_VAR}"
else
  echo "  Application: $ODH_APPLICATIONS"
fi
echo ""
for cr in "${FOUND_CRS[@]}"; do
  echo "  Component  : $cr"
  cr_repos=$(cat "$IMAGE_REPOS_DIR/$cr" 2>/dev/null || true)
  if [[ -n "$cr_repos" ]]; then
    echo "    ImageRepository CRs to annotate (skip-repository-deletion=true):"
    while IFS= read -r repo; do
      [[ -n "$repo" ]] && echo "      - $repo"
    done <<< "$cr_repos"
  else
    echo "    No ImageRepository CRs found."
  fi
  echo ""
done

echo "  This will:"
echo "    1. Annotate ImageRepository CRs to preserve Quay images"
echo "    2. DELETE the Component CR(s) (also removes Repository CR, PaC webhooks)"
echo ""
echo "================================================================"

if [[ "$CONFIRM" != "true" ]]; then
  echo ""
  echo "Pass --confirm to execute, or re-run the skill and confirm when prompted."
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_component_cr --status awaiting_confirmation
  exit 0
fi

if [[ -n "$DRY_RUN_PREFIX" ]]; then
  echo "[DRY RUN] Skipping oc annotate and oc delete — would have deleted: ${FOUND_CRS[*]}"
  uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
    --add-label "offboard-component-cr-removed" \
    --comment "${DRY_RUN_PREFIX}[step:remove_component_cr] Would delete Component CRs (${FOUND_CRS[*]}) from namespace '${KONFLUX_NAMESPACE}'. Skipped in dry-run mode." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_component_cr --status done
  echo "COMPONENT_CR_DELETED=${FOUND_CRS[*]} (dry-run)"
  exit 0
fi

# Annotate and delete each Component CR
DELETED_CRS=()
for cr in "${FOUND_CRS[@]}"; do
  # Annotate ImageRepository CRs to preserve Quay images
  cr_repos=$(cat "$IMAGE_REPOS_DIR/$cr" 2>/dev/null || true)
  if [[ -n "$cr_repos" ]]; then
    echo "Annotating ImageRepository CRs for '$cr'..."
    while IFS= read -r repo; do
      [[ -z "$repo" ]] && continue
      oc annotate imagerepository "$repo" -n "$KONFLUX_NAMESPACE" \
        image-controller.appstudio.redhat.com/skip-repository-deletion="true" \
        --overwrite || {
        echo "ERROR: Failed to annotate ImageRepository '$repo'." >&2; exit 1
      }
      echo "  Annotated: $repo"
    done <<< "$cr_repos"
  fi

  echo "Deleting Component CR '$cr'..."
  oc delete component "$cr" -n "$KONFLUX_NAMESPACE" || {
    echo "ERROR: Failed to delete Component CR '$cr'." >&2; exit 1
  }

  sleep 2
  if oc get component "$cr" -n "$KONFLUX_NAMESPACE" &>/dev/null 2>&1; then
    echo "ERROR: Component CR '$cr' still exists after deletion." >&2; exit 1
  fi

  echo "Component CR '$cr' deleted successfully."
  DELETED_CRS+=("$cr")
done

uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
  --add-label "offboard-component-cr-removed" \
  --comment "[step:remove_component_cr] Component CRs deleted from namespace '${KONFLUX_NAMESPACE}':
$(printf '  - %s\n' "${DELETED_CRS[@]}")

ImageRepository CRs annotated with skip-repository-deletion=true to preserve Quay images." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_component_cr --status done

echo "COMPONENT_CR_DELETED=${DELETED_CRS[*]}"
