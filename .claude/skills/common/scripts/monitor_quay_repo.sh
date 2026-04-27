#!/usr/bin/env bash
# monitor_quay_repo.sh — polls check_quay_repo.sh until a Quay repo appears or times out.
# Optionally updates Jira on success or timeout.
# Exit 0: repo confirmed live; Exit 1: timed out.
set -euo pipefail

QUAY_REPO=""
JIRA_URL=""
MR_URL=""
COMMON_SCRIPTS_DIR=""
POLL_INTERVAL=60
MAX_WAIT=1800

usage() {
  echo "Usage: $0 --quay-repo quay.io/org/repo --scripts-dir PATH [--jira-url URL] [--mr-url URL] [--poll-interval SECS] [--max-wait SECS]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quay-repo)     QUAY_REPO="$2";           shift 2 ;;
    --jira-url)      JIRA_URL="$2";            shift 2 ;;
    --mr-url)        MR_URL="$2";              shift 2 ;;
    --scripts-dir)   COMMON_SCRIPTS_DIR="$2";  shift 2 ;;
    --poll-interval) POLL_INTERVAL="$2";       shift 2 ;;
    --max-wait)      MAX_WAIT="$2";            shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$QUAY_REPO" || -z "$COMMON_SCRIPTS_DIR" ]] && usage

echo "Monitoring ${QUAY_REPO} for creation (timeout: $((MAX_WAIT / 60)) minutes)..."

ELAPSED=0
CHECK_EXIT=1

while true; do
  bash "$COMMON_SCRIPTS_DIR/check_quay_repo.sh" "$QUAY_REPO"
  CHECK_EXIT=$?

  if [[ $CHECK_EXIT -eq 0 ]]; then
    break
  elif [[ $CHECK_EXIT -eq 2 ]]; then
    echo "WARNING: check_quay_repo.sh returned a tool error. Retrying..."
  fi
  # Exit 1 = not yet created; keep polling

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    CHECK_EXIT=3
    break
  fi

  REMAINING=$(( (MAX_WAIT - ELAPSED) / 60 ))
  echo "  ${QUAY_REPO} not yet available (elapsed=${ELAPSED}s, remaining≈${REMAINING}m). Retrying in ${POLL_INTERVAL}s..."
  sleep "$POLL_INTERVAL"
  ELAPSED=$(( ELAPSED + POLL_INTERVAL ))
done

if [[ $CHECK_EXIT -eq 0 ]]; then
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "quay-repo-created" \
      --comment "Quay repository successfully created: ${QUAY_REPO}

Confirmed by skopeo after GitOps reconciliation completed.
Step 2 (Create Quay Repo) is complete."
  fi
  echo "✓ ${QUAY_REPO} is live on Quay."
  echo "  Step 2 (Create Quay Repo) complete."
  exit 0
else
  MR_INFO=""
  [[ -n "$MR_URL" ]] && MR_INFO="
The MR was merged (${MR_URL}) so reconciliation may still be in progress."

  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "Quay repo monitoring timed out after $((MAX_WAIT / 60)) minutes. ${QUAY_REPO} has not yet appeared.${MR_INFO}

Re-run /create-quay-repo to re-check — it will short-circuit at Step 3 once the repo exists."
  fi
  echo "WARNING: ${QUAY_REPO} not visible after $((MAX_WAIT / 60)) minutes."
  [[ -n "$MR_URL" ]] && echo "The MR was merged so app-interface reconciliation may still be running."
  echo "Re-run this skill later — it will short-circuit at Step 3 once the repo exists."
  exit 1
fi
