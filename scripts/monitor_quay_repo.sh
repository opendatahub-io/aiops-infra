#!/usr/bin/env bash
# Usage: monitor_quay_repo.sh --quay-repo <repo> --jira-url <url> --mr-url <url> --scripts-dir <dir> [--timeout 1800]
# Polls until the Quay repo exists, then updates Jira on success or timeout.
set -euo pipefail

QUAY_REPO=""
JIRA_URL=""
MR_URL=""
SCRIPTS_DIR=""
TIMEOUT=1800
POLL_INTERVAL=60

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quay-repo)   QUAY_REPO="$2";   shift 2 ;;
    --jira-url)    JIRA_URL="$2";    shift 2 ;;
    --mr-url)      MR_URL="$2";      shift 2 ;;
    --scripts-dir) SCRIPTS_DIR="$2"; shift 2 ;;
    --timeout)     TIMEOUT="$2";     shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
esac
done

for required in QUAY_REPO JIRA_URL MR_URL SCRIPTS_DIR; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 1
  fi
done

ELAPSED=0
echo "Waiting for Quay repo '$QUAY_REPO' to become available (timeout: ${TIMEOUT}s)..."

while [[ $ELAPSED -lt $TIMEOUT ]]; do
  if bash "$SCRIPTS_DIR/check_quay_repo.sh" "$QUAY_REPO" &>/dev/null; then
    echo "Quay repo '$QUAY_REPO' is now available after ${ELAPSED}s."
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "quay-repo-created" \
      --comment "Quay repository '$QUAY_REPO' has been created successfully.

GitLab MR: $MR_URL

The Quay repo is now available. You can proceed with the next onboarding steps."
    exit 0
  fi
  sleep "$POLL_INTERVAL"
  ELAPSED=$((ELAPSED + POLL_INTERVAL))
  echo "Still waiting... (${ELAPSED}/${TIMEOUT}s)"
done

echo "ERROR: Timed out after ${TIMEOUT}s waiting for '$QUAY_REPO'." >&2
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "quay-repo-timeout" \
  --comment "Timed out waiting for Quay repository '$QUAY_REPO' to be created after ${TIMEOUT}s.

GitLab MR: $MR_URL

Please check the MR status and verify the Quay repo creation pipeline completed successfully."
exit 1
