#!/usr/bin/env bash
# Usage: eval "$(bash parse_jira_url.sh "${1:-}")"
# Validates and extracts JIRA_URL and JIRA_ID from the first positional argument.
# When the argument is empty, both variables are set to empty strings.
# Exits 1 if a non-empty argument does not contain '/browse/'.
set -euo pipefail

RAW_ARG="${1:-}"

if [[ -n "$RAW_ARG" && "$RAW_ARG" != *"/browse/"* ]]; then
  echo "ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

JIRA_URL="$RAW_ARG"
JIRA_ID="${JIRA_URL##*/}"   # last path segment, e.g. RHOAIENG-1234; empty when JIRA_URL is empty

printf 'JIRA_URL=%q\n' "$JIRA_URL"
printf 'JIRA_ID=%q\n'  "$JIRA_ID"
