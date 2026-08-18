#!/usr/bin/env bash
# Parse component_offboarding_details.yaml and derive variables for offboarding.
#
# Usage:
#   eval "$(bash parse_offboarding_details.sh \
#     --workdir <dir> --jira-id <id> --scripts-dir <dir>)"
#
# Exports (via eval): COMPONENT_NAME IS_OPERATOR REPO_URL
#                     PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI
# Summary is printed to stderr so it does not pollute the eval output.

set -euo pipefail

WORKDIR=""
JIRA_ID=""
SCRIPTS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2";     shift 2 ;;
    --jira-id)     JIRA_ID="$2";     shift 2 ;;
    --scripts-dir) SCRIPTS_DIR="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$WORKDIR" ]]     && { echo "ERROR: --workdir is required"     >&2; exit 1; }
[[ -z "$JIRA_ID" ]]     && { echo "ERROR: --jira-id is required"     >&2; exit 1; }
[[ -z "$SCRIPTS_DIR" ]] && { echo "ERROR: --scripts-dir is required" >&2; exit 1; }

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
JSON_FILE="$WORKDIR/component_offboarding_details.json"

[[ -f "$YAML_FILE" ]] || { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
IS_OPERATOR=$(grep -m1    'is_operator:'    "$YAML_FILE" | awk '{print $2}')
REPO_URL=$(grep -m1       'repo_url:'       "$YAML_FILE" | awk '{print $2}')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' | tr -d '"' || true)

for _field in COMPONENT_NAME REPO_URL; do
  [[ -z "${!_field}" ]] && {
    echo "ERROR: Missing required field '${_field}' in $YAML_FILE" >&2; exit 1
  }
done
[[ -z "$IS_OPERATOR" ]] && IS_OPERATOR="false"

# Derive PRODUCT_CONTEXT from YAML, fall back to Jira key prefix
YAML_PC=$(grep -m1 'product_context:' "$YAML_FILE" | awk '{print $2}' | tr -d '"' || true)
YAML_PC=$(echo "$YAML_PC" | tr '[:lower:]' '[:upper:]')

if [[ "$YAML_PC" == "RHOAI" || "$YAML_PC" == "ODH" ]]; then
  PRODUCT_CONTEXT="$YAML_PC"
elif [[ "$JIRA_ID" == RHOAIENG* ]]; then
  PRODUCT_CONTEXT="RHOAI"
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

# Derive Quay vars (needed by some removal steps)
eval "$(bash "$SCRIPTS_DIR/derive_quay_vars.sh" \
  --product-context "$PRODUCT_CONTEXT" \
  --component-name  "$COMPONENT_NAME")"

cat >&2 <<EOF
[offboarding] Component : $COMPONENT_NAME
[offboarding] Product   : $PRODUCT_CONTEXT
[offboarding] Quay repo : $QUAY_REPO_URI ($QUAY_VISIBILITY)
[offboarding] Operator  : $IS_OPERATOR
EOF

printf 'COMPONENT_NAME=%q\n'    "$COMPONENT_NAME"
printf 'IS_OPERATOR=%q\n'       "$IS_OPERATOR"
printf 'REPO_URL=%q\n'          "$REPO_URL"
printf 'PRODUCT_CONTEXT=%q\n'   "$PRODUCT_CONTEXT"
printf 'QUAY_ORG=%q\n'          "$QUAY_ORG"
printf 'QUAY_VISIBILITY=%q\n'   "$QUAY_VISIBILITY"
printf 'QUAY_REPO_URI=%q\n'     "$QUAY_REPO_URI"
printf 'TARGET_RHOAI_VERSION=%q\n' "${TARGET_RHOAI_VERSION:-}"
