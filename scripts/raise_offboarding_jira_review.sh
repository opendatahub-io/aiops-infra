#!/usr/bin/env bash
# Read pipeline_state.json, build a PR/MR summary table, and transition Jira to "Review".
#
# Usage:
#   bash raise_offboarding_jira_review.sh \
#     --workdir <dir> --jira-url <url> --scripts-dir <dir> \
#     --component-name <n> --product-context ODH|RHOAI \
#     [--assignee <displayName>]
#
# Reads: $WORKDIR/pipeline_state.json
# Calls: update_offboarding_jira.py  (requires uv in PATH)

set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
COMPONENT_NAME=""
PRODUCT_CONTEXT=""
ASSIGNEE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)         WORKDIR="$2";         shift 2 ;;
    --jira-url)        JIRA_URL="$2";        shift 2 ;;
    --scripts-dir)     SCRIPTS_DIR="$2";     shift 2 ;;
    --component-name)  COMPONENT_NAME="$2";  shift 2 ;;
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    --assignee)        ASSIGNEE="$2";        shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

for _arg in WORKDIR JIRA_URL SCRIPTS_DIR COMPONENT_NAME PRODUCT_CONTEXT; do
  [[ -z "${!_arg}" ]] && { echo "ERROR: --$(echo "$_arg" | tr '[:upper:]' '[:lower:]') is required" >&2; exit 1; }
done

PIPELINE_STATE="$WORKDIR/pipeline_state.json"
[[ -f "$PIPELINE_STATE" ]] || { echo "ERROR: $PIPELINE_STATE not found" >&2; exit 1; }

# Read product context from state file if not passed (backward compat)
if [[ -z "$PRODUCT_CONTEXT" ]]; then
  PRODUCT_CONTEXT=$(jq -r '.product_context // ""' "$PIPELINE_STATE")
fi

IS_OP=$(jq -r '.is_operator // "false"' "$PIPELINE_STATE")
PIPELINE_TYPE=$(jq -r '.pipeline_type // "onboarding"' "$PIPELINE_STATE")

if [[ "$PIPELINE_TYPE" == "offboarding" ]]; then
  REVIEW_LABEL="offboarding-in-review"
else
  REVIEW_LABEL="onboarding-in-review"
fi

uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
  --add-label "$REVIEW_LABEL" \
  --status "Review"

echo "[raise_jira_review] Jira transitioned to Review with PR/MR summary."
