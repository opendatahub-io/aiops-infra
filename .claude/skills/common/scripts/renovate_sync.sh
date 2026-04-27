#!/usr/bin/env bash
# renovate_sync.sh — waits for the enable-renovate PR to merge, then triggers
# sync-rhoai-renovate-configs to push the config to all repos.
# RHOAI only.
set -euo pipefail

WORKDIR=""
JIRA_URL=""
COMMON_SCRIPTS_DIR=""
RKC_URL=""

usage() {
  echo "Usage: $0 --workdir PATH --jira-url URL --scripts-dir PATH --rkc-url URL"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2";             shift 2 ;;
    --jira-url)    JIRA_URL="$2";            shift 2 ;;
    --scripts-dir) COMMON_SCRIPTS_DIR="$2";  shift 2 ;;
    --rkc-url)     RKC_URL="$2";             shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$WORKDIR" || -z "$JIRA_URL" || -z "$COMMON_SCRIPTS_DIR" || -z "$RKC_URL" ]] && usage

PIPELINE_STATE="$WORKDIR/pipeline_state.json"
RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')
WORKFLOW_FILE=".github/workflows/sync-renovate-configs.yml"

log() { echo "[renovate-sync $(date '+%H:%M:%S')] $*" >> "$WORKDIR/renovate_sync.log"; }
log "Started. Waiting for monitor_renovate.result == merged."

MAX_MINUTES=180; ELAPSED=0
while true; do
  if [[ -f "$WORKDIR/monitor_renovate.result" ]]; then
    R=$(cat "$WORKDIR/monitor_renovate.result" | tr -d '[:space:]')
    if [[ "$R" == "merged" ]]; then
      log "Renovate PR merged. Triggering sync-rhoai-renovate-configs..."
      break
    elif [[ "$R" == "closed" || "$R" == "pipeline_failed" || "$R" == "timeout" ]]; then
      log "ERROR: Renovate PR result: $R. Cannot sync. Check monitor_renovate.log."
      uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "Deferred renovate sync aborted: renovate PR finished with '$R'.
Check \$WORKDIR/monitor_renovate.result and re-run /sync-rhoai-renovate-configs manually." 2>/dev/null || true
      exit 1
    fi
  fi
  [[ $ELAPSED -ge $MAX_MINUTES ]] && {
    log "ERROR: Timed out waiting for renovate PR after ${MAX_MINUTES}m."
    exit 1
  }
  sleep 120; ELAPSED=$(( ELAPSED + 2 ))
done

RUN_ID=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" trigger \
  --repo-url "$RKC_URL" \
  --workflow "$WORKFLOW_FILE" \
  --ref main \
  --input "dry_run=false" \
  --input "renovate-config=all") || {
  log "ERROR: Failed to trigger sync-renovate-configs workflow."
  exit 1
}
log "Workflow triggered. Run ID: $RUN_ID"

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "renovate-sync-triggered" \
  --comment "sync-renovate-configs workflow triggered (Run #${RUN_ID}).
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}" 2>/dev/null || true

MONITOR_RESULT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" monitor \
  --repo-url "$RKC_URL" --run-id "$RUN_ID" --timeout 30 --poll-interval 60) || true
STATUS="${MONITOR_RESULT#status=}"

if [[ "$STATUS" == "success" ]]; then
  jq '.steps.renovate.status = "merged"' "$PIPELINE_STATE" > \
    "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "renovate-sync-done" \
    --remove-label "renovate-sync-triggered" \
    --comment "sync-renovate-configs workflow completed (Run #${RUN_ID}).
Renovate config is now synced to all registered component repositories." 2>/dev/null || true
  log "Renovate sync complete."
else
  log "ERROR: sync-renovate-configs workflow status: $STATUS"
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "sync-renovate-configs workflow failed ($STATUS).
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
Re-run /sync-rhoai-renovate-configs manually." 2>/dev/null || true
fi
