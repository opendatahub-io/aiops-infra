#!/usr/bin/env bash
# deferred_workflow.sh — waits for quay/krd/okc monitor result files to show "merged",
# then triggers the odh-konflux-onboarder workflow and monitors the resulting Tekton PR.
# ODH only.
set -euo pipefail

WORKDIR=""
JIRA_URL=""
COMMON_SCRIPTS_DIR=""
OKC_URL=""
OKC_PATH=""
WORKFLOW_FILE=""
REPO_NAME=""
REPO_BRANCH=""
BUILD_TYPE=""

usage() {
  echo "Usage: $0 --workdir PATH --jira-url URL --scripts-dir PATH --okc-url URL --okc-path PATH --workflow-file PATH --repo-name NAME --repo-branch BRANCH --build-type TYPE"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)        WORKDIR="$2";           shift 2 ;;
    --jira-url)       JIRA_URL="$2";          shift 2 ;;
    --scripts-dir)    COMMON_SCRIPTS_DIR="$2"; shift 2 ;;
    --okc-url)        OKC_URL="$2";           shift 2 ;;
    --okc-path)       OKC_PATH="$2";          shift 2 ;;
    --workflow-file)  WORKFLOW_FILE="$2";     shift 2 ;;
    --repo-name)      REPO_NAME="$2";         shift 2 ;;
    --repo-branch)    REPO_BRANCH="$2";       shift 2 ;;
    --build-type)     BUILD_TYPE="$2";        shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$WORKDIR" || -z "$JIRA_URL" || -z "$COMMON_SCRIPTS_DIR" || -z "$OKC_URL" || -z "$OKC_PATH" || -z "$WORKFLOW_FILE" || -z "$REPO_NAME" || -z "$REPO_BRANCH" || -z "$BUILD_TYPE" ]] && usage

PIPELINE_STATE="$WORKDIR/pipeline_state.json"

log() { echo "[deferred $(date '+%H:%M:%S')] $*" >> "$WORKDIR/deferred_workflow.log"; }
log "Started. Waiting for Quay MR, KRD MR, and OKC PR to merge."

wait_for_merge() {
  local label="$1" result_file="$WORKDIR/monitor_${1}.result"
  local max_minutes=180 elapsed=0
  while true; do
    if [[ -f "$result_file" ]]; then
      local r; r=$(cat "$result_file" | tr -d '[:space:]')
      [[ "$r" == "merged" ]] && { log "$label: merged."; return 0; }
      if [[ "$r" == "closed" || "$r" == "pipeline_failed" || "$r" == "timeout" ]]; then
        log "ERROR: $label finished with '$r'. Cannot proceed."
        return 1
      fi
    fi
    [[ $elapsed -ge $max_minutes ]] && { log "ERROR: Timed out waiting for $label after ${max_minutes}m."; return 1; }
    sleep 120
    elapsed=$(( elapsed + 2 ))
  done
}

wait_for_merge "quay" || {
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "Deferred workflow aborted: Quay MR did not merge successfully.
Check \$WORKDIR/monitor_quay.result and re-trigger the workflow manually." 2>/dev/null || true
  exit 1
}

wait_for_merge "krd" || {
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "Deferred workflow aborted: KRD MR did not merge successfully.
Check \$WORKDIR/monitor_krd.result and re-trigger the workflow manually." 2>/dev/null || true
  exit 1
}

wait_for_merge "okc" || {
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "Deferred workflow aborted: OKC PR did not merge successfully.
Check \$WORKDIR/monitor_okc.result and re-trigger the workflow manually." 2>/dev/null || true
  exit 1
}

log "Quay, KRD, and OKC all merged. Triggering odh-konflux-onboarder workflow..."

RUN_ID=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" trigger \
  --repo-url "$OKC_URL" \
  --workflow "$WORKFLOW_FILE" \
  --ref main \
  --input "component=${REPO_NAME}" \
  --input "pr_target_branch=${REPO_BRANCH}" \
  --input "build_type=${BUILD_TYPE}") || {
  log "ERROR: Workflow dispatch failed. Check GITHUB_TOKEN actions:write scope."
  exit 1
}
log "Workflow triggered. Run ID: $RUN_ID"

jq --arg rid "$RUN_ID" \
  '.steps.onboarder.run_id = $rid | .steps.onboarder.status = "workflow_running"' \
  "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment "odh-konflux-onboarder workflow triggered.

Component: $REPO_NAME | Branch: $REPO_BRANCH | Build type: $BUILD_TYPE
Workflow run: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}" 2>/dev/null || true

MONITOR_RESULT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" monitor \
  --repo-url "$OKC_URL" --run-id "$RUN_ID" --timeout 30) || true
WORKFLOW_STATUS="${MONITOR_RESULT#status=}"
log "Workflow status: $WORKFLOW_STATUS"

if [[ "$WORKFLOW_STATUS" != "success" ]]; then
  log "ERROR: Workflow run $RUN_ID finished with: $WORKFLOW_STATUS"
  jq '.steps.onboarder.status = "failed"' "$PIPELINE_STATE" > \
    "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "odh-konflux-onboarder workflow FAILED (${WORKFLOW_STATUS}).
Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}
Manual intervention required." 2>/dev/null || true
  exit 1
fi

STEP_LOGS=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" get-step-logs \
  --repo-url "$OKC_URL" --run-id "$RUN_ID" --step "Create pull request" 2>/dev/null || true)
TEKTON_PR=$(echo "$STEP_LOGS" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1 || true)
log "Tekton PR: ${TEKTON_PR:-<not found in logs>}"

jq --arg tpr "${TEKTON_PR:-}" \
  '.steps.onboarder.tekton_pr_url = $tpr | .steps.onboarder.status = "tekton_pr_raised"' \
  "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "tekton-pr-raised" \
  --comment "odh-konflux-onboarder workflow completed successfully.

Tekton PR: ${TEKTON_PR:-<check workflow run logs>}
Workflow run: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Monitoring Tekton PR for merge..." 2>/dev/null || true

if [[ -n "$TEKTON_PR" ]]; then
  log "Monitoring Tekton PR: $TEKTON_PR"
  TEKTON_RESULT=$(uv run --script "$COMMON_SCRIPTS_DIR/monitor_github_pr.py" \
    --pr-url "$TEKTON_PR" --timeout 60 2>>"$WORKDIR/deferred_workflow.log") || true

  if [[ "$TEKTON_RESULT" == "merged" ]]; then
    jq '.steps.onboarder.status = "merged"' "$PIPELINE_STATE" > \
      "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "tekton-pr-merged" \
      --comment "Tekton PR merged: $TEKTON_PR

Step 5 (Run CI/Nightly Build) is complete." 2>/dev/null || true
    log "Tekton PR merged. Step 5 complete."
  else
    jq '.steps.onboarder.status = "failed"' "$PIPELINE_STATE" > \
      "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
    log "ERROR: Tekton PR result: $TEKTON_RESULT. Check: $TEKTON_PR"
  fi
fi
log "Deferred workflow script complete."
