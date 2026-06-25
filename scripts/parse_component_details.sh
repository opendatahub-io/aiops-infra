#!/usr/bin/env bash
# Parse component_onboarding_details.yaml, derive PRODUCT_CONTEXT + Quay vars,
# update pipeline_state.json, and mark non-applicable steps as skipped.
#
# Usage:
#   eval "$(bash parse_component_details.sh \
#     --workdir <dir> --jira-id <id> --scripts-dir <dir> [--pipeline-state <path>])"
#
# Exports (via eval): COMPONENT_NAME IS_OPERATOR REPO_URL REPO_BRANCH
#                     PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI
#                     RELEASE_CATEGORY
# Side effect: updates pipeline_state.json when --pipeline-state is provided.
# Summary is printed to stderr so it does not pollute the eval output.

set -euo pipefail

WORKDIR=""
JIRA_ID=""
SCRIPTS_DIR=""
PIPELINE_STATE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)        WORKDIR="$2";        shift 2 ;;
    --jira-id)        JIRA_ID="$2";        shift 2 ;;
    --scripts-dir)    SCRIPTS_DIR="$2";    shift 2 ;;
    --pipeline-state) PIPELINE_STATE="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$WORKDIR" ]]     && { echo "ERROR: --workdir is required"     >&2; exit 1; }
[[ -z "$JIRA_ID" ]]     && { echo "ERROR: --jira-id is required"     >&2; exit 1; }
[[ -z "$SCRIPTS_DIR" ]] && { echo "ERROR: --scripts-dir is required" >&2; exit 1; }

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
JSON_FILE="$WORKDIR/component_onboarding_details.json"

[[ -f "$YAML_FILE" ]] || { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

# --- Parse YAML fields ---
COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
IS_OPERATOR=$(grep -m1    'is_operator:'    "$YAML_FILE" | awk '{print $2}')
REPO_URL=$(grep -m1       'repo_url:'       "$YAML_FILE" | awk '{print $2}')
REPO_BRANCH=$(grep -m1    'repo_branch:'    "$YAML_FILE" | awk '{print $2}')
RELEASE_CATEGORY=$(grep -m1 'release_category:' "$YAML_FILE" \
  | sed 's/^[[:space:]]*release_category:[[:space:]]*//' | tr -d '"' || true)
[[ -z "$RELEASE_CATEGORY" ]] && RELEASE_CATEGORY="Generally Available"

for _field in COMPONENT_NAME REPO_URL REPO_BRANCH; do
  [[ -z "${!_field}" ]] && {
    echo "ERROR: Missing required field '${_field}' in $YAML_FILE" >&2; exit 1
  }
done
[[ -z "$IS_OPERATOR" ]] && IS_OPERATOR="false"

# --- Derive PRODUCT_CONTEXT ---
# Primary source: component_onboarding_details.yaml (authoritative).
# Fallback: Jira key prefix, then Jira issue summary.
YAML_PC=$(grep -m1 'product_context:' "$YAML_FILE" | awk '{print $2}' | tr -d '"' || true)
YAML_PC=$(echo "$YAML_PC" | tr '[:lower:]' '[:upper:]')  # normalise to uppercase

if [[ "$YAML_PC" == "RHOAI" || "$YAML_PC" == "ODH" ]]; then
  PRODUCT_CONTEXT="$YAML_PC"
elif [[ "$JIRA_ID" == RHOAIENG* ]]; then
  PRODUCT_CONTEXT="RHOAI"
elif [[ "$JIRA_ID" == RHODS* ]]; then
  PRODUCT_CONTEXT="ODH"
elif [[ -f "$JSON_FILE" ]]; then
  SUMMARY=$(jq -r '.fields.summary // ""' "$JSON_FILE" 2>/dev/null || echo "")
  if echo "$SUMMARY" | grep -qi 'rhoai'; then
    PRODUCT_CONTEXT="RHOAI"
  elif echo "$SUMMARY" | grep -qi '\bodh\b'; then
    PRODUCT_CONTEXT="ODH"
  else
    echo "ERROR: Cannot determine PRODUCT_CONTEXT from YAML, Jira key '${JIRA_ID}', or summary." >&2
    exit 1
  fi
else
  echo "ERROR: Cannot determine PRODUCT_CONTEXT from YAML or Jira key '${JIRA_ID}'." >&2
  exit 1
fi

# --- Derive Quay vars ---
eval "$(bash "$SCRIPTS_DIR/derive_quay_vars.sh" \
  --product-context "$PRODUCT_CONTEXT" \
  --component-name  "$COMPONENT_NAME")"
# Sets: QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI

# --- Update pipeline_state.json (if provided) ---
if [[ -n "$PIPELINE_STATE" && -f "$PIPELINE_STATE" ]]; then
  jq \
    --arg cn "$COMPONENT_NAME" \
    --arg pc "$PRODUCT_CONTEXT" \
    --arg qo "$QUAY_ORG" \
    --arg qv "$QUAY_VISIBILITY" \
    --arg qr "$QUAY_REPO_URI" \
    --argjson io "${IS_OPERATOR}" \
    --arg rc "$RELEASE_CATEGORY" \
    '.component_name = $cn | .product_context = $pc | .quay_org = $qo | .quay_visibility = $qv | .quay_repo_uri = $qr | .is_operator = $io | .release_category = $rc' \
    "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"

  # Mark non-applicable steps as skipped
  if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
    bash "$SCRIPTS_DIR/pipeline_state.sh" set \
      --state "$PIPELINE_STATE" --step onboarder --field status --value "skipped"
    echo "[parse_component_details] RHOAI: onboarder step marked as skipped." >&2
  else
    for _step in dockerfile_labels delivery_repo auto_merge renovate; do
      bash "$SCRIPTS_DIR/pipeline_state.sh" set \
        --state "$PIPELINE_STATE" --step "$_step" --field status --value "skipped"
    done
    echo "[parse_component_details] ODH: RHOAI-only steps marked as skipped." >&2
  fi
fi

# --- Print summary to stderr ---
cat >&2 <<EOF
Component : $COMPONENT_NAME
Product   : $PRODUCT_CONTEXT
Quay repo : $QUAY_REPO_URI ($QUAY_VISIBILITY)
Operator  : $IS_OPERATOR
Category  : $RELEASE_CATEGORY
EOF

# --- Emit eval-able exports ---
printf 'COMPONENT_NAME=%q\n'    "$COMPONENT_NAME"
printf 'IS_OPERATOR=%q\n'       "$IS_OPERATOR"
printf 'REPO_URL=%q\n'          "$REPO_URL"
printf 'REPO_BRANCH=%q\n'       "$REPO_BRANCH"
printf 'PRODUCT_CONTEXT=%q\n'   "$PRODUCT_CONTEXT"
printf 'QUAY_ORG=%q\n'          "$QUAY_ORG"
printf 'QUAY_VISIBILITY=%q\n'   "$QUAY_VISIBILITY"
printf 'QUAY_REPO_URI=%q\n'     "$QUAY_REPO_URI"
printf 'RELEASE_CATEGORY=%q\n'  "$RELEASE_CATEGORY"
