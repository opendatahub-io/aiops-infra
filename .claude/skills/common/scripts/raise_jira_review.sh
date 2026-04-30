#!/usr/bin/env bash
# Read pipeline_state.json, build a PR/MR summary table, and transition Jira to "Review".
#
# Usage:
#   bash raise_jira_review.sh \
#     --workdir <dir> --jira-url <url> --scripts-dir <dir> \
#     --component-name <n> --product-context ODH|RHOAI \
#     [--assignee <displayName>]
#
# Reads: $WORKDIR/pipeline_state.json
# Calls: update_jira_issue.py  (requires uv in PATH)

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
  [[ -z "${!_arg}" ]] && { echo "ERROR: --${_arg,,} is required" >&2; exit 1; }
done

PIPELINE_STATE="$WORKDIR/pipeline_state.json"
[[ -f "$PIPELINE_STATE" ]] || { echo "ERROR: $PIPELINE_STATE not found" >&2; exit 1; }

# Read product context from state file if not passed (backward compat)
if [[ -z "$PRODUCT_CONTEXT" ]]; then
  PRODUCT_CONTEXT=$(jq -r '.product_context // ""' "$PIPELINE_STATE")
fi

IS_OP=$(jq -r '.is_operator // "false"' "$PIPELINE_STATE")

fmt_url() {
  local url="$1"
  [[ -z "$url" || "$url" == "null" ]] && echo "N/A" || echo "$url"
}

QUAY_MR=$(jq        -r '.steps.quay.mr_url // ""'              "$PIPELINE_STATE")
KRD_MR=$(jq         -r '.steps.krd.mr_url // ""'               "$PIPELINE_STATE")
OKC_PR=$(jq         -r '.steps.okc.pr_url // ""'               "$PIPELINE_STATE")
PULL_PR=$(jq        -r '.steps.pull_pipelines.pr_url // ""'    "$PIPELINE_STATE")
OP_PR=$(jq          -r '.steps.operator.pr_url // ""'          "$PIPELINE_STATE")
BUNDLE_PR=$(jq      -r '.steps.bundle.pr_url // ""'            "$PIPELINE_STATE")
DELIV_MR=$(jq       -r '.steps.delivery_repo.mr_url // ""'     "$PIPELINE_STATE")
PRODUCT_MR=$(jq     -r '.steps.product_listing.mr_url // ""'   "$PIPELINE_STATE")
AM_PR=$(jq          -r '.steps.auto_merge.pr_url // ""'        "$PIPELINE_STATE")
RENOV_PR=$(jq       -r '.steps.renovate.pr_url // ""'          "$PIPELINE_STATE")

QUAY_STATUS=$(jq    -r '.steps.quay.status // "pending"'          "$PIPELINE_STATE")
KRD_STATUS=$(jq     -r '.steps.krd.status // "pending"'           "$PIPELINE_STATE")
OKC_STATUS=$(jq     -r '.steps.okc.status // "pending"'           "$PIPELINE_STATE")
PULL_STATUS=$(jq    -r '.steps.pull_pipelines.status // "skipped"' "$PIPELINE_STATE")
OP_STATUS=$(jq      -r '.steps.operator.status // "skipped"'      "$PIPELINE_STATE")
BUNDLE_STATUS=$(jq  -r '.steps.bundle.status // "pending"'        "$PIPELINE_STATE")
DELIV_STATUS=$(jq   -r '.steps.delivery_repo.status // "skipped"' "$PIPELINE_STATE")
PROD_STATUS=$(jq    -r '.steps.product_listing.status // "skipped"' "$PIPELINE_STATE")
AM_STATUS=$(jq      -r '.steps.auto_merge.status // "skipped"'    "$PIPELINE_STATE")
RENOV_STATUS=$(jq   -r '.steps.renovate.status // "skipped"'      "$PIPELINE_STATE")
RENOV_SYNC_STATUS=$(jq -r '.steps.renovate_sync.status // "skipped"' "$PIPELINE_STATE")
WORKFLOW_STATUS=$(jq   -r '.steps.onboarder_workflow.status // "skipped"' "$PIPELINE_STATE")

tag_line=""
[[ -n "$ASSIGNEE" ]] && tag_line="@${ASSIGNEE} — please review the open PRs/MRs."$'\n\n'

if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  REVIEW_COMMENT="${tag_line}All PRs and MRs raised for '${COMPONENT_NAME}' onboarding. Pending review and merge.

| Step | Description | Status | URL |
|------|-------------|--------|-----|
| 1 | Create Quay repo | ${QUAY_STATUS} | $(fmt_url "$QUAY_MR") |
| 2 | Onboard to Konflux release data | ${KRD_STATUS} | $(fmt_url "$KRD_MR") |
| 3 | Add to ODH Konflux central | ${OKC_STATUS} | $(fmt_url "$OKC_PR") |
| 4 | Trigger ODH onboarder workflow | ${WORKFLOW_STATUS} | auto-triggered once Steps 2+3 are merged |
| 5 | Integrate with ODH Operator | ${OP_STATUS} | $(fmt_url "$OP_PR") |
| 6 | Integrate with bundle | ${BUNDLE_STATUS} | $(fmt_url "$BUNDLE_PR") |

Re-run the skill to advance the pipeline after PRs/MRs are merged."
else
  REVIEW_COMMENT="${tag_line}All PRs and MRs raised for '${COMPONENT_NAME}' onboarding. Pending review and merge.

| Step | Description | Status | URL |
|------|-------------|--------|-----|
| 1  | Create Quay repo | ${QUAY_STATUS} | $(fmt_url "$QUAY_MR") |
| 2  | Onboard to Konflux release data | ${KRD_STATUS} | $(fmt_url "$KRD_MR") |
| 3  | Add to RHOAI Konflux central | ${OKC_STATUS} | $(fmt_url "$OKC_PR") |
| 4  | Add pull pipelines (RHOAI Konflux) | ${PULL_STATUS} | $(fmt_url "$PULL_PR") |
| 5  | Integrate with ODH Operator | ${OP_STATUS} | $(fmt_url "$OP_PR") |
| 6  | Integrate with bundle | ${BUNDLE_STATUS} | $(fmt_url "$BUNDLE_PR") |
| 7  | Create RHOAI delivery repo | ${DELIV_STATUS} | $(fmt_url "$DELIV_MR") |
| 8  | Update RHOAI product listing | ${PROD_STATUS} | $(fmt_url "$PRODUCT_MR") (triggered after Step 7 merges) |
| 9  | Setup auto-merge | ${AM_STATUS} | $(fmt_url "$AM_PR") |
| 10 | Enable Renovate | ${RENOV_STATUS} | $(fmt_url "$RENOV_PR") |
| 11 | Sync Renovate configs (workflow) | ${RENOV_SYNC_STATUS} | auto-triggered after Step 10 merges |

Re-run the skill to advance the pipeline after PRs/MRs are merged."
fi

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "onboarding-in-review" \
  --status "Review" \
  --comment "$REVIEW_COMMENT"

echo "[raise_jira_review] Jira transitioned to Review with PR/MR summary."
