#!/usr/bin/env bash
# launch_monitor.sh — launches monitor_pr.sh in the background via nohup,
# writes a PID file, and returns immediately.
#
# Usage:
#   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
#     --step         NAME          \   # e.g. quay, krd, okc, operator
#     --url          URL           \   # full MR or PR URL
#     --type         github|gitlab \
#     --jira-url     URL           \
#     --label-remove LABEL         \   # Jira label to remove on merge
#     --comment      TEXT          \   # Jira comment to post on merge
#     --workdir      PATH          \   # directory for log/result/pid files
#     --scripts-dir  PATH          \
#     [--timeout     MINUTES]          # default: 120
#
# Output files (all under --workdir):
#   monitor_<step>.log    — combined stdout/stderr from monitor_pr.sh
#   monitor_<step>.result — single line: merged|closed|pipeline_failed|timeout
#   monitor_<step>.pid    — PID of the background process
set -euo pipefail

STEP="" URL="" TYPE="" JIRA_URL="" LABEL_REMOVE="" COMMENT=""
WORKDIR="" SCRIPTS_DIR="" TIMEOUT_MINUTES=120

while [[ $# -gt 0 ]]; do
  case "$1" in
    --step)          STEP="$2";            shift 2 ;;
    --url)           URL="$2";             shift 2 ;;
    --type)          TYPE="$2";            shift 2 ;;
    --jira-url)      JIRA_URL="$2";        shift 2 ;;
    --label-remove)  LABEL_REMOVE="$2";    shift 2 ;;
    --comment)       COMMENT="$2";         shift 2 ;;
    --workdir)       WORKDIR="$2";         shift 2 ;;
    --scripts-dir)   SCRIPTS_DIR="$2";     shift 2 ;;
    --timeout)       TIMEOUT_MINUTES="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

LOG_FILE="$WORKDIR/monitor_${STEP}.log"
RESULT_FILE="$WORKDIR/monitor_${STEP}.result"
PID_FILE="$WORKDIR/monitor_${STEP}.pid"

nohup bash "$SCRIPTS_DIR/monitor_pr.sh" \
  --step         "$STEP"            \
  --url          "$URL"             \
  --type         "$TYPE"            \
  --jira-url     "$JIRA_URL"        \
  --label-remove "$LABEL_REMOVE"    \
  --comment      "$COMMENT"         \
  --result-file  "$RESULT_FILE"     \
  --log-file     "$LOG_FILE"        \
  --scripts-dir  "$SCRIPTS_DIR"     \
  --timeout      "$TIMEOUT_MINUTES" \
  >> "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
echo "[WRAPPER] Background monitor for $STEP started (PID=$(cat "$PID_FILE"))"
echo "[WRAPPER] Log: $LOG_FILE"
