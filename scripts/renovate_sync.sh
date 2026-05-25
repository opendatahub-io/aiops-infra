#!/usr/bin/env bash
# Background script: waits for the Renovate PR (RKC) to merge, then triggers the sync-renovate-configs workflow.
# Usage: nohup bash renovate_sync.sh --workdir X --jira-url X --scripts-dir X --rkc-url X \
#          >> "$WORKDIR/renovate_sync.log" 2>&1 &
set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
RKC_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2";     shift 2 ;;
    --jira-url)    JIRA_URL="$2";    shift 2 ;;
    --scripts-dir) SCRIPTS_DIR="$2"; shift 2 ;;
    --rkc-url)     RKC_URL="$2";     shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for required in WORKDIR JIRA_URL SCRIPTS_DIR RKC_URL; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 1
  fi
done

PIPELINE_STATE="${WORKDIR}/pipeline_state.json"

echo "[renovate_sync] Starting. Waiting for RKC PR to merge..."

while true; do
  RKC_STATUS=$(bash "$SCRIPTS_DIR/pipeline_state.sh" get --state "$PIPELINE_STATE" --step rkc --field status 2>/dev/null || echo "pending")

  if [[ "$RKC_STATUS" == "merged" ]]; then
    echo "[renovate_sync] RKC PR merged. Triggering sync-renovate-configs workflow..."
    break
  fi

  echo "[renovate_sync] RKC=$RKC_STATUS — waiting 60s..."
  sleep 60
done

# Trigger sync workflow via the run-odh-konflux-onboarder skill approach
# The RHOAI Renovate sync workflow is in the rhoai-konflux-central repo
RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||' | cut -d'/' -f1-2)
SYNC_WORKFLOW=".github/workflows/sync-renovate-configs.yml"

uv run --script "$SCRIPTS_DIR/run_github_workflow.py" \
  "https://github.com/${RKC_PATH}" \
  "$SYNC_WORKFLOW"

bash "$SCRIPTS_DIR/pipeline_state.sh" set --state "$PIPELINE_STATE" --step rkc --field sync_status --value triggered

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment "Renovate sync workflow triggered successfully.

  RKC PR   : $RKC_URL

sync-renovate-configs workflow triggered after RKC PR merged."

echo "[renovate_sync] Done."
