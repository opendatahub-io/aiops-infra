#!/usr/bin/env bash
# Usage:
#   bash pipeline_state.sh get --state <file> --step <step> [--field <field>]
#   bash pipeline_state.sh set --state <file> --step <step> --field <field> --value <value>
# Atomic read/write of pipeline_state.json via a tmp-file pattern.
set -euo pipefail

COMMAND="${1:-}"
shift

STATE_FILE=""
STEP=""
FIELD=""
VALUE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state) STATE_FILE="$2"; shift 2 ;;
    --step)  STEP="$2";       shift 2 ;;
    --field) FIELD="$2";      shift 2 ;;
    --value) VALUE="$2";      shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$STATE_FILE" || -z "$STEP" ]]; then
  echo "ERROR: --state and --step are required" >&2
  exit 1
fi

if [[ ! -f "$STATE_FILE" ]]; then
  echo "ERROR: State file not found: $STATE_FILE" >&2
  exit 1
fi

case "$COMMAND" in
  get)
    if [[ -n "$FIELD" ]]; then
      jq -r ".steps.${STEP}.${FIELD}" "$STATE_FILE"
    else
      jq -r ".steps.${STEP}" "$STATE_FILE"
    fi
    ;;
  set)
    if [[ -z "$FIELD" || -z "$VALUE" ]]; then
      echo "ERROR: 'set' requires --field and --value" >&2
      exit 1
    fi
    TMP_FILE="${STATE_FILE}.tmp.$$"
    jq ".steps.${STEP}.${FIELD} = $(printf '%s' "$VALUE" | jq -Rs '.')" "$STATE_FILE" > "$TMP_FILE"
    mv "$TMP_FILE" "$STATE_FILE"
    ;;
  *)
    echo "ERROR: Unknown command '$COMMAND'. Use 'get' or 'set'." >&2
    exit 1
    ;;
esac
