#!/usr/bin/env bash
# Parse component_onboarding_details.yaml, derive PRODUCT_CONTEXT + Quay vars,
# update pipeline_state.json, and mark non-applicable steps as skipped.
#
# Usage:
#   eval "$(bash parse_component_details.sh \
#     --workdir <dir> --jira-id <id> --scripts-dir <dir> [--pipeline-state <path>])"
#
# Exports (via eval): COMPONENT_NAME IS_OPERATOR REPO_URL REPO_BRANCH
#                     CONTEXT_PATH DOCKERFILE_PATH TARGET_RHOAI_VERSION
#                     PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI
#                     RELEASE_CATEGORY BASE_RHEL_VERSION IMAGE_REPO_SUFFIX
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

# Parse YAML structurally rather than matching lines. In particular, an absent OS
# value (legacy Jira attachment) differs from a present-but-empty invalid value.
INPUT_VARS=$(uv run --script "$SCRIPTS_DIR/read_onboarding_inputs.py" "$YAML_FILE") || exit 1
eval "$INPUT_VARS"
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
YAML_PC="${YAML_PC^^}"  # normalise to uppercase

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

# Resolve legacy RHOAI tickets to RHEL 9; preserve any explicitly supplied
# numeric RHEL major here. The schema, not this naming helper, gates 9/10.
OS_ARGS=()
if [[ "$BASE_RHEL_VERSION_PRESENT" == true ]]; then
  OS_ARGS=(--base-rhel-version "$BASE_RHEL_VERSION_INPUT")
fi

# --- Derive Quay vars ---
QUAY_VARS=$(bash "$SCRIPTS_DIR/derive_quay_vars.sh" \
  --product-context "$PRODUCT_CONTEXT" \
  --component-name  "$COMPONENT_NAME" "${OS_ARGS[@]}") || exit 1
eval "$QUAY_VARS"
# Sets: QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI BASE_RHEL_VERSION IMAGE_REPO_SUFFIX

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
    --arg os "$BASE_RHEL_VERSION" \
    --arg suffix "$IMAGE_REPO_SUFFIX" \
    '.component_name = $cn | .product_context = $pc | .quay_org = $qo | .quay_visibility = $qv | .quay_repo_uri = $qr | .is_operator = $io | .release_category = $rc | .base_rhel_version = $os | .image_repo_suffix = $suffix' \
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
Base OS   : ${BASE_RHEL_VERSION:-N/A}
EOF

# --- Emit eval-able exports ---
printf 'COMPONENT_NAME=%q\n'    "$COMPONENT_NAME"
printf 'IS_OPERATOR=%q\n'       "$IS_OPERATOR"
printf 'REPO_URL=%q\n'          "$REPO_URL"
printf 'REPO_BRANCH=%q\n'       "$REPO_BRANCH"
printf 'CONTEXT_PATH=%q\n'      "$CONTEXT_PATH"
printf 'DOCKERFILE_PATH=%q\n'   "$DOCKERFILE_PATH"
printf 'TARGET_RHOAI_VERSION=%q\n' "$TARGET_RHOAI_VERSION"
printf 'PRODUCT_CONTEXT=%q\n'   "$PRODUCT_CONTEXT"
printf 'QUAY_ORG=%q\n'          "$QUAY_ORG"
printf 'QUAY_VISIBILITY=%q\n'   "$QUAY_VISIBILITY"
printf 'QUAY_REPO_URI=%q\n'     "$QUAY_REPO_URI"
printf 'RELEASE_CATEGORY=%q\n'  "$RELEASE_CATEGORY"
printf 'BASE_RHEL_VERSION=%q\n' "$BASE_RHEL_VERSION"
printf 'IMAGE_REPO_SUFFIX=%q\n' "$IMAGE_REPO_SUFFIX"
