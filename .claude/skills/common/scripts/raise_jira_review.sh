#!/usr/bin/env bash
# Read pipeline_state.json, build a PR/MR summary table, and transition Jira to "Review".
#
# Usage:
#   bash raise_jira_review.sh \
#     --workdir <dir> --jira-url <url> --scripts-dir <dir> \
#     --component-name <n> --product-context ODH|RHOAI
#
# Reads: $WORKDIR/pipeline_state.json
# Calls: update_jira_issue.py  (requires uv in PATH)

set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
COMPONENT_NAME=""
PRODUCT_CONTEXT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)         WORKDIR="$2";         shift 2 ;;
    --jira-url)        JIRA_URL="$2";        shift 2 ;;
    --scripts-dir)     SCRIPTS_DIR="$2";     shift 2 ;;
    --component-name)  COMPONENT_NAME="$2";  shift 2 ;;
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

for _arg in WORKDIR JIRA_URL SCRIPTS_DIR COMPONENT_NAME PRODUCT_CONTEXT; do
  [[ -z "${!_arg}" ]] && { echo "ERROR: --${_arg,,} is required" >&2; exit 1; }
done

PIPELINE_STATE="$WORKDIR/pipeline_state.json"
[[ -f "$PIPELINE_STATE" ]] || { echo "ERROR: $PIPELINE_STATE not found" >&2; exit 1; }

# Extract PR/MR URLs from pipeline_state.json
QUAY_MR=$(jq   -r '.steps.quay.mr_url // "N/A"'               "$PIPELINE_STATE")
KRD_MR=$(jq    -r '.steps.krd.mr_url // "N/A"'                "$PIPELINE_STATE")
OKC_PR=$(jq    -r '.steps.okc.pr_url // "N/A"'                "$PIPELINE_STATE")
OP_PR=$(jq     -r '.steps.operator.pr_url // "N/A"'            "$PIPELINE_STATE")
BDLPR=$(jq     -r '.steps.bundle.pr_url // "N/A"'              "$PIPELINE_STATE")
LABELS_PR=$(jq -r '.steps.dockerfile_labels.pr_url // "N/A"'   "$PIPELINE_STATE")
DELIV_MR=$(jq  -r '.steps.delivery_repo.mr_url // "N/A"'       "$PIPELINE_STATE")
AM_PR=$(jq     -r '.steps.auto_merge.pr_url // "N/A"'          "$PIPELINE_STATE")
RENOV_PR=$(jq  -r '.steps.renovate.pr_url // "N/A"'            "$PIPELINE_STATE")
IS_OP=$(jq     -r '.is_operator'                               "$PIPELINE_STATE")

# Build conditional display values based on product context
if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  STEP5_VAL="auto-triggered once Steps 3+4 are merged (background script running)"
  STEP8_VAL="N/A (ODH)"
  STEP9_VAL="N/A (ODH)"
  STEP10_VAL="N/A (ODH)"
  STEP11_PR_VAL="N/A (ODH)"
  STEP11_SYNC_VAL="N/A (ODH)"
else
  STEP5_VAL="N/A (RHOAI)"
  STEP8_VAL="$LABELS_PR"
  STEP9_VAL="$DELIV_MR"
  STEP10_VAL="$AM_PR"
  STEP11_PR_VAL="$RENOV_PR"
  STEP11_SYNC_VAL="deferred; will trigger on renovate PR merge"
fi

[[ "$IS_OP" == "true" ]] && STEP6_VAL="$OP_PR" || STEP6_VAL="N/A (is_operator=false)"

REVIEW_COMMENT="All PRs and MRs raised for '${COMPONENT_NAME}' onboarding. Pending review and merge.

| Step    | Description        | URL / Status                                                              |
|---------|--------------------|---------------------------------------------------------------------------|
| Step 2  | Quay MR            | ${QUAY_MR}                                                                |
| Step 3  | KRD MR             | ${KRD_MR}                                                                 |
| Step 4  | OKC/RKC PR         | ${OKC_PR}                                                                 |
| Step 5  | Tekton/Workflow     | ${STEP5_VAL}                                                              |
| Step 6  | Operator PR        | ${STEP6_VAL}                                                              |
| Step 7  | Bundle PR          | ${BDLPR}                                                                  |
| Step 8  | Dockerfile Labels  | ${STEP8_VAL}                                                              |
| Step 9  | Delivery Repo MR   | ${STEP9_VAL}                                                              |
| Step 10 | Auto-Merge PR      | ${STEP10_VAL}                                                             |
| Step 11 | Renovate PR        | ${STEP11_PR_VAL}                                                          |
| Step 11 | Renovate Sync      | ${STEP11_SYNC_VAL}                                                        |

Background monitors are running. Jira will be moved to Resolved automatically when all PRs/MRs are merged."

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "onboarding-in-review" \
  --status "Review" \
  --comment "$REVIEW_COMMENT"

echo "[WRAPPER] Jira transitioned to Review and updated with PR/MR summary."
