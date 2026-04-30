#!/usr/bin/env bash
# Background script: polls pipeline_state.json until all active steps are complete, then resolves Jira.
# Usage: nohup bash monitor_completion.sh --workdir X --jira-url X --scripts-dir X \
#          >> "$WORKDIR/monitor_completion.log" 2>&1 &
set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
POLL_INTERVAL=120

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2";     shift 2 ;;
    --jira-url)    JIRA_URL="$2";    shift 2 ;;
    --scripts-dir) SCRIPTS_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for required in WORKDIR JIRA_URL SCRIPTS_DIR; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 1
  fi
done

PIPELINE_STATE="${WORKDIR}/pipeline_state.json"

echo "[monitor_completion] Starting. Polling pipeline state every ${POLL_INTERVAL}s..."

_all_complete() {
  # Returns 0 if all non-pending steps are merged/done/skipped/triggered
  local incomplete
  incomplete=$(jq '[.steps | to_entries[] | select(.value.status != "skipped") | select(.value.status | IN("merged", "done", "triggered")) | .key] | length' "$PIPELINE_STATE")
  local total
  total=$(jq '[.steps | to_entries[] | select(.value.status != "skipped") | .key] | length' "$PIPELINE_STATE")
  [[ "$incomplete" -eq "$total" ]]
}

while true; do
  if _all_complete; then
    echo "[monitor_completion] All active steps complete."
    break
  fi

  SUMMARY=$(jq -r '.steps | to_entries[] | "\(.key): \(.value.status)"' "$PIPELINE_STATE" | paste -sd ', ')
  echo "[monitor_completion] In progress — $SUMMARY"
  sleep "$POLL_INTERVAL"
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --status "Resolved" \
  --comment "All onboarding steps have completed successfully.

$(jq -r '.steps | to_entries[] | "  \(.key): \(.value.status)"' "$PIPELINE_STATE")

The component onboarding is complete. Resolving this ticket."

echo "[monitor_completion] Jira resolved. Done."
