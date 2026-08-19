#!/usr/bin/env bash
# Check current PR/MR status for all steps in pr_raised/mr_raised state.
# Updates pipeline_state.json in place and prints newly-merged step keys to stdout.
#
# Usage:
#   NEWLY_MERGED=$(bash check_pr_mr_status.sh \
#     --state <pipeline_state.json> --scripts-dir <dir>)
#
# Stdout: newline-separated list of step keys that transitioned to "merged" this run.
# Stderr: progress messages.
# Side-effect: updates pipeline_state.json (status → "merged" or "closed").

set -euo pipefail

PIPELINE_STATE=""
SCRIPTS_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state)       PIPELINE_STATE="$2"; shift 2 ;;
    --scripts-dir) SCRIPTS_DIR="$2";    shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

for _arg in PIPELINE_STATE SCRIPTS_DIR; do
  [[ -z "${!_arg}" ]] && { echo "ERROR: --$(echo "$_arg" | tr '[:upper:]' '[:lower:]') is required (use underscores as hyphens)" >&2; exit 1; }
done

[[ -f "$PIPELINE_STATE" ]] || { echo "ERROR: $PIPELINE_STATE not found" >&2; exit 1; }

NEWLY_MERGED=()

# Iterate all steps that are in pr_raised or mr_raised status
STEP_KEYS=$(jq -r '.steps | to_entries[] | select(.value.status == "pr_raised" or .value.status == "mr_raised") | .key' "$PIPELINE_STATE")

for STEP_KEY in $STEP_KEYS; do
  # Get the URL (prefer pr_url, fall back to mr_url)
  URL=$(jq -r --arg k "$STEP_KEY" '.steps[$k].pr_url // .steps[$k].mr_url // ""' "$PIPELINE_STATE")

  if [[ -z "$URL" ]]; then
    echo "[check] $STEP_KEY: no URL recorded — skipping" >&2
    continue
  fi

  echo "[check] $STEP_KEY: checking $URL" >&2

  # Determine type from URL
  if [[ "$URL" == *"github.com"* ]]; then
    RESULT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
      --pr-url "$URL" --check-only 2>/dev/null || true)
  else
    RESULT=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/monitor_gitlab_mr.py" \
      --mr-url "$URL" --check-only 2>/dev/null || true)
  fi

  STATE=$(echo "$RESULT" | sed -n 's/.*state=\([^ ]*\).*/\1/p' | head -1)

  echo "[check] $STEP_KEY: state=$STATE" >&2

  if [[ "$STATE" == "merged" ]]; then
    TMP=$(mktemp)
    NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    jq --arg k "$STEP_KEY" --arg ts "$NOW" \
      '.steps[$k].status = "merged" | .last_status_change_at = $ts' \
      "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    NEWLY_MERGED+=("$STEP_KEY")
    echo "[check] $STEP_KEY: marked merged" >&2
  elif [[ "$STATE" == "closed" ]]; then
    TMP=$(mktemp)
    NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    jq --arg k "$STEP_KEY" --arg ts "$NOW" \
      '.steps[$k].status = "pending" | .steps[$k].pr_url = null | .steps[$k].mr_url = null | .last_status_change_at = $ts' \
      "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    echo "[check] $STEP_KEY: PR/MR closed without merging — reset to pending (will re-raise on next run)" >&2
  else
    echo "[check] $STEP_KEY: still open/draft — no change" >&2
  fi
done

# Print newly merged steps to stdout for the orchestrator to consume
for KEY in "${NEWLY_MERGED[@]:-}"; do
  [[ -n "$KEY" ]] && echo "$KEY"
done
