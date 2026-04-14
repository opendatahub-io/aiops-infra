#!/usr/bin/env bash
# monitor_pr.sh — background retry loop that monitors a GitHub PR or GitLab MR
# and posts a Jira update (label removal + comment) when it merges.
#
# Called by launch_monitor.sh via nohup. Should not be invoked directly.
#
# Usage:
#   monitor_pr.sh \
#     --step          NAME          \   # e.g. quay, krd, okc, operator
#     --url           URL           \   # full MR or PR URL
#     --type          github|gitlab \
#     --jira-url      URL           \
#     --label-remove  LABEL         \   # Jira label to remove on merge
#     --comment       TEXT          \   # Jira comment to post on merge
#     --result-file   PATH          \
#     --log-file      PATH          \
#     --scripts-dir   PATH          \
#     [--timeout      MINUTES]          # default: 120
set -euo pipefail

STEP="" URL="" TYPE="" JIRA_URL="" LABEL_REMOVE="" COMMENT=""
RESULT_FILE="" LOG_FILE="" SCRIPTS_DIR="" TIMEOUT_MINUTES=120

while [[ $# -gt 0 ]]; do
  case "$1" in
    --step)          STEP="$2";            shift 2 ;;
    --url)           URL="$2";             shift 2 ;;
    --type)          TYPE="$2";            shift 2 ;;
    --jira-url)      JIRA_URL="$2";        shift 2 ;;
    --label-remove)  LABEL_REMOVE="$2";    shift 2 ;;
    --comment)       COMMENT="$2";         shift 2 ;;
    --result-file)   RESULT_FILE="$2";     shift 2 ;;
    --log-file)      LOG_FILE="$2";        shift 2 ;;
    --scripts-dir)   SCRIPTS_DIR="$2";     shift 2 ;;
    --timeout)       TIMEOUT_MINUTES="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

EVENTS_LOG="$(dirname "$LOG_FILE")/events.log"

# log: detailed per-step log (polling noise, full output)
log()   { echo "[${STEP} $(date '+%H:%M:%S')] $*" >> "$LOG_FILE"; }

# event: significant moments only — written to both the step log and shared events.log
event() { local msg="[${STEP}] $*"; echo "$msg" >> "$LOG_FILE"; echo "$msg" >> "$EVENTS_LOG"; }

event "Started monitoring $URL (type=$TYPE, timeout=${TIMEOUT_MINUTES}m)"

while true; do
  if [[ "$TYPE" == "gitlab" ]]; then
    result=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/monitor_gitlab_mr.py" \
      --mr-url "$URL" --timeout "$TIMEOUT_MINUTES" 2>>"$LOG_FILE") || true
  elif [[ "$TYPE" == "github" ]]; then
    result=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
      --pr-url "$URL" --timeout "$TIMEOUT_MINUTES" 2>>"$LOG_FILE") || true
  else
    event "ERROR: unknown --type '$TYPE' (must be github or gitlab)"
    exit 1
  fi

  case "$result" in
    merged|closed|pipeline_failed|timeout)
      echo "$result" > "$RESULT_FILE"
      if [[ "$result" == "merged" ]]; then
        event "MERGED — posting Jira update (remove-label: $LABEL_REMOVE)"
        uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
          --remove-label "$LABEL_REMOVE" \
          --comment      "$COMMENT" 2>>"$LOG_FILE" || true
        event "Jira updated successfully."
      else
        event "Terminal result: $result — no Jira update."
      fi
      break
      ;;
    *)
      event "Connection error or unexpected result ('$result') — retrying in 60s"
      sleep 60
      ;;
  esac
done
