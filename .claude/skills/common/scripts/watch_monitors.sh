#!/usr/bin/env bash
# watch_monitors.sh — live view of background monitor activity for a pipeline run.
#
# Shows current status of all monitors, then follows events.log in real time.
# Only significant events appear (merges, Jira updates, retries, workflow triggers).
# Quiet per-minute polling stays in the individual monitor_<step>.log files.
#
# Usage:
#   bash "$COMMON_SCRIPTS_DIR/watch_monitors.sh" --workdir <WORKDIR>
#
# Press Ctrl-C to stop watching.
set -euo pipefail

WORKDIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) WORKDIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$WORKDIR" ]]; then
  echo "Usage: watch_monitors.sh --workdir <path>" >&2
  exit 1
fi

EVENTS_LOG="$WORKDIR/events.log"

# ── colour helpers ────────────────────────────────────────────────────────────
bold=$'\033[1m'; reset=$'\033[0m'
green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; cyan=$'\033[36m'; grey=$'\033[90m'

pid_running() {
  local pf="$1"
  [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null
}

result_of() {
  local rf="$WORKDIR/monitor_${1}.result"
  [[ -f "$rf" ]] && tr -d '[:space:]' < "$rf" || echo "—"
}

# ── current status snapshot ───────────────────────────────────────────────────
echo ""
echo "${bold}=== Monitor Status ===${reset}"
printf "  %-22s %-10s %s\n" "Monitor" "PID" "Result / State"
printf "  %-22s %-10s %s\n" "-------" "---" "--------------"

for name in quay krd okc operator; do
  pf="$WORKDIR/monitor_${name}.pid"
  pid=$( [[ -f "$pf" ]] && cat "$pf" || echo "—" )
  if pid_running "$pf"; then
    pid_label="${green}${pid} (running)${reset}"
  else
    pid_label="${grey}${pid} (stopped)${reset}"
  fi
  res=$(result_of "$name")
  case "$res" in
    merged)          res_label="${green}${res}${reset}" ;;
    closed|pipeline_failed|timeout) res_label="${red}${res}${reset}" ;;
    *)               res_label="${yellow}${res}${reset}" ;;
  esac
  printf "  %-22s %-10s %s\n" "$name" "$pid_label" "$res_label"
done

for name in deferred_workflow monitor_completion; do
  pf="$WORKDIR/${name}.pid"
  pid=$( [[ -f "$pf" ]] && cat "$pf" || echo "—" )
  if pid_running "$pf"; then
    pid_label="${green}${pid} (running)${reset}"
  else
    pid_label="${grey}${pid} (stopped)${reset}"
  fi
  printf "  %-22s %s\n" "$name" "$pid_label"
done

echo ""
echo "${bold}=== Live Events ===${reset}  ${grey}(Ctrl-C to stop)${reset}"
echo "${grey}Quiet polling stays in monitor_<step>.log — only significant activity shown here.${reset}"
echo ""

# ── follow events.log, colouring key words ────────────────────────────────────
touch "$EVENTS_LOG"
tail -f "$EVENTS_LOG" | while IFS= read -r line; do
  ts="$(date '+%H:%M:%S')"
  case "$line" in
    *MERGED*|*merged*)           echo "${green}${ts}  ${line}${reset}" ;;
    *ERROR*|*pipeline_failed*)   echo "${red}${ts}  ${line}${reset}" ;;
    *Jira*|*jira*)               echo "${cyan}${ts}  ${line}${reset}" ;;
    *retry*|*Retry*|*retrying*)  echo "${yellow}${ts}  ${line}${reset}" ;;
    *workflow*|*Workflow*)        echo "${cyan}${ts}  ${line}${reset}" ;;
    *Resolved*|*complete*)        echo "${bold}${green}${ts}  ${line}${reset}" ;;
    *)                            echo "${ts}  ${line}" ;;
  esac
done
