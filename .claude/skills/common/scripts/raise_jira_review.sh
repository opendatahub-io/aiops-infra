#!/usr/bin/env bash
# raise_jira_review.sh — reads pipeline_state.json, builds the onboarding review
# comment table, and transitions Jira to Review status.
set -euo pipefail

WORKDIR=""
JIRA_URL=""
COMMON_SCRIPTS_DIR=""

usage() {
  echo "Usage: $0 --workdir PATH --jira-url URL --scripts-dir PATH"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2";             shift 2 ;;
    --jira-url)    JIRA_URL="$2";            shift 2 ;;
    --scripts-dir) COMMON_SCRIPTS_DIR="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$WORKDIR" || -z "$JIRA_URL" || -z "$COMMON_SCRIPTS_DIR" ]] && usage

PIPELINE_STATE="$WORKDIR/pipeline_state.json"

COMPONENT_NAME=$(jq -r '.component_name'                        "$PIPELINE_STATE")
PRODUCT_CONTEXT=$(jq -r '.product_context'                      "$PIPELINE_STATE")
IS_OP=$(jq -r           '.is_operator'                          "$PIPELINE_STATE")
QUAY_MR=$(jq -r  '.steps.quay.mr_url // "N/A"'                 "$PIPELINE_STATE")
KRD_MR=$(jq -r   '.steps.krd.mr_url // "N/A"'                  "$PIPELINE_STATE")
OKC_PR=$(jq -r   '.steps.okc.pr_url // "N/A"'                  "$PIPELINE_STATE")
OP_PR=$(jq -r    '.steps.operator.pr_url // "N/A"'              "$PIPELINE_STATE")
BDLPR=$(jq -r    '.steps.bundle.pr_url // "N/A"'                "$PIPELINE_STATE")
LABELS_PR=$(jq -r '.steps.dockerfile_labels.pr_url // "N/A"'   "$PIPELINE_STATE")
DELIV_MR=$(jq -r  '.steps.delivery_repo.mr_url // "N/A"'       "$PIPELINE_STATE")
AM_PR=$(jq -r     '.steps.auto_merge.pr_url // "N/A"'          "$PIPELINE_STATE")
RENOV_PR=$(jq -r  '.steps.renovate.pr_url // "N/A"'            "$PIPELINE_STATE")

STEP5_VAL=$([ "$PRODUCT_CONTEXT" = "ODH" ] \
  && echo "auto-triggered once Steps 3+4 are merged (background script running)" \
  || echo "N/A (RHOAI)")
STEP6_VAL=$([ "$IS_OP" = "true" ] && echo "$OP_PR" || echo "N/A (is_operator=false)")
STEP8_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$LABELS_PR"  || echo "N/A (ODH)")
STEP9_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$DELIV_MR"   || echo "N/A (ODH)")
STEP10_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$AM_PR"     || echo "N/A (ODH)")
STEP11_PR_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$RENOV_PR" || echo "N/A (ODH)")
STEP11_SYNC_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] \
  && echo "deferred; will trigger on renovate PR merge" \
  || echo "N/A (ODH)")

REVIEW_COMMENT="All PRs and MRs raised for '${COMPONENT_NAME}' onboarding. Pending review and merge.

| Step    | Description        | URL / Status                                                              |
|---------|--------------------|---------------------------------------------------------------------------|
| Step 2  | Quay MR            | ${QUAY_MR}                                                                |
| Step 3  | KRD MR             | ${KRD_MR}                                                                 |
| Step 4  | OKC/RKC PR         | ${OKC_PR}                                                                 |
| Step 5  | Tekton/Workflow    | ${STEP5_VAL}                                                              |
| Step 6  | Operator PR        | ${STEP6_VAL}                                                              |
| Step 7  | Bundle PR          | ${BDLPR}                                                                  |
| Step 8  | Dockerfile Labels  | ${STEP8_VAL}                                                              |
| Step 9  | Delivery Repo MR   | ${STEP9_VAL}                                                              |
| Step 10 | Auto-Merge PR      | ${STEP10_VAL}                                                             |
| Step 11 | Renovate PR        | ${STEP11_PR_VAL}                                                          |
| Step 11 | Renovate Sync      | ${STEP11_SYNC_VAL}                                                        |

Background monitors are running. Jira will be moved to Resolved automatically when all PRs/MRs are merged."

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "onboarding-in-review" \
  --status "Review" \
  --comment "$REVIEW_COMMENT"
