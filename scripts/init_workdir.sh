#!/usr/bin/env bash
# Usage: eval "$(bash init_workdir.sh --jira-url <url> [--workdir-override <path>])"
# Outputs shell variable assignments for JIRA_ID and WORKDIR.
# Creates the working directory if it doesn't exist.
# When --jira-url is empty, JIRA_ID is set to "" and WORKDIR defaults to $(pwd).
set -euo pipefail

JIRA_URL=""
WORKDIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url)         JIRA_URL="$2";          shift 2 ;;
    --workdir-override) WORKDIR_OVERRIDE="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$JIRA_URL" ]]; then
  # No Jira URL: use current directory and empty JIRA_ID
  JIRA_ID=""
  WORKDIR="${WORKDIR_OVERRIDE:-$(pwd)}"
else
  # Extract the last non-empty path segment as the issue ID
  JIRA_ID="${JIRA_URL%/}"
  JIRA_ID="${JIRA_ID##*/}"

  if [[ -z "$JIRA_ID" ]]; then
    echo "ERROR: Could not extract issue ID from URL: $JIRA_URL" >&2
    exit 1
  fi

  if [[ -n "$WORKDIR_OVERRIDE" ]]; then
    WORKDIR="$WORKDIR_OVERRIDE"
  elif [[ -d "$(pwd)/${JIRA_ID}" ]]; then
    WORKDIR="$(pwd)/${JIRA_ID}"
  else
    WORKDIR="$(pwd)/.work/${JIRA_ID}"
  fi
fi

mkdir -p "$WORKDIR"

# Output eval-able variable assignments
printf 'JIRA_ID=%q\n' "$JIRA_ID"
printf 'WORKDIR=%q\n' "$WORKDIR"
