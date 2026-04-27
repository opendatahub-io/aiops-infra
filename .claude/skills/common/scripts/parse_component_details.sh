#!/usr/bin/env bash
# parse_component_details.sh — reads component_onboarding_details.yaml, derives
# PRODUCT_CONTEXT and Quay variables, updates pipeline_state.json, and marks
# non-applicable steps as skipped.
# Prints shell variable assignments to stdout for eval.
set -euo pipefail

WORKDIR=""
JIRA_ID=""

usage() {
  echo "Usage: $0 --workdir PATH --jira-id JIRA_ID"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)  WORKDIR="$2";  shift 2 ;;
    --jira-id)  JIRA_ID="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$WORKDIR" || -z "$JIRA_ID" ]] && usage

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
JSON_FILE="$WORKDIR/component_onboarding_details.json"
PIPELINE_STATE="$WORKDIR/pipeline_state.json"

if [[ ! -f "$YAML_FILE" ]]; then
  echo "ERROR: $YAML_FILE not found. Run validate-component-onboarding-jira first." >&2
  exit 1
fi

# Extract fields from YAML using python3 (uv ensures python3 is available)
COMPONENT_NAME=$(python3 -c "
import yaml, sys
with open('$YAML_FILE') as f:
    d = yaml.safe_load(f)
print(d.get('inputs', {}).get('component_name', ''))
")
IS_OPERATOR=$(python3 -c "
import yaml, sys
with open('$YAML_FILE') as f:
    d = yaml.safe_load(f)
print(str(d.get('inputs', {}).get('is_operator', False)).lower())
")
REPO_URL=$(python3 -c "
import yaml, sys
with open('$YAML_FILE') as f:
    d = yaml.safe_load(f)
print(d.get('inputs', {}).get('repo_url', ''))
")
REPO_BRANCH=$(python3 -c "
import yaml, sys
with open('$YAML_FILE') as f:
    d = yaml.safe_load(f)
print(d.get('inputs', {}).get('repo_branch', ''))
")

if [[ -z "$COMPONENT_NAME" || -z "$REPO_URL" || -z "$REPO_BRANCH" ]]; then
  echo "ERROR: Could not extract required fields from $YAML_FILE." >&2
  exit 1
fi

# Derive PRODUCT_CONTEXT from Jira ID prefix
PRODUCT_CONTEXT="UNKNOWN"
if [[ "$JIRA_ID" == RHOAIENG-* ]]; then
  PRODUCT_CONTEXT="RHOAI"
elif [[ "$JIRA_ID" == RHODS-* ]]; then
  PRODUCT_CONTEXT="ODH"
elif [[ -f "$JSON_FILE" ]]; then
  SUMMARY=$(jq -r '.fields.summary // ""' "$JSON_FILE" 2>/dev/null || true)
  if echo "$SUMMARY" | grep -qi "RHOAI"; then
    PRODUCT_CONTEXT="RHOAI"
  elif echo "$SUMMARY" | grep -qi "ODH"; then
    PRODUCT_CONTEXT="ODH"
  fi
fi

# Derive Quay variables
if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  QUAY_ORG="opendatahub"
  QUAY_VISIBILITY="public"
  QUAY_REPO_URI="quay.io/opendatahub/${COMPONENT_NAME}"
elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  QUAY_ORG="rhoai"
  QUAY_VISIBILITY="private"
  QUAY_REPO_URI="quay.io/rhoai/${COMPONENT_NAME}-rhel9"
else
  QUAY_ORG=""
  QUAY_VISIBILITY=""
  QUAY_REPO_URI=""
fi

# Update pipeline_state.json with derived values
jq \
  --arg cn  "$COMPONENT_NAME" \
  --arg pc  "$PRODUCT_CONTEXT" \
  --arg qo  "$QUAY_ORG" \
  --arg qv  "$QUAY_VISIBILITY" \
  --arg qr  "$QUAY_REPO_URI" \
  --argjson io "$([ "$IS_OPERATOR" = "true" ] && echo true || echo false)" \
  '.component_name = $cn | .product_context = $pc | .quay_org = $qo | .quay_visibility = $qv | .quay_repo_uri = $qr | .is_operator = $io' \
  "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"

# Mark non-applicable steps as skipped
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  jq '.steps.onboarder.status = "skipped"' "$PIPELINE_STATE" > \
    "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
elif [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  jq '.steps.dockerfile_labels.status = "skipped"
    | .steps.delivery_repo.status = "skipped"
    | .steps.auto_merge.status = "skipped"
    | .steps.renovate.status = "skipped"' \
    "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
fi

# Print assignments for eval
echo "COMPONENT_NAME=${COMPONENT_NAME}"
echo "IS_OPERATOR=${IS_OPERATOR}"
echo "REPO_URL=${REPO_URL}"
echo "REPO_BRANCH=${REPO_BRANCH}"
echo "PRODUCT_CONTEXT=${PRODUCT_CONTEXT}"
echo "QUAY_ORG=${QUAY_ORG}"
echo "QUAY_VISIBILITY=${QUAY_VISIBILITY}"
echo "QUAY_REPO_URI=${QUAY_REPO_URI}"
