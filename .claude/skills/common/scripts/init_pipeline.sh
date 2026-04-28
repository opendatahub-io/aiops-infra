#!/usr/bin/env bash
# Usage: eval "$(bash init_pipeline.sh --jira-url <url> [--workdir-override <path>])"
# Extends init_workdir.sh: also creates pipeline_state.json and sets PIPELINE_STATE.
set -euo pipefail

JIRA_URL=""
WORKDIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url)         JIRA_URL="$2";         shift 2 ;;
    --workdir-override) WORKDIR_OVERRIDE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$JIRA_URL" ]]; then
  echo "ERROR: --jira-url is required" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL%/}"
JIRA_ID="${JIRA_ID##*/}"

if [[ -z "$JIRA_ID" ]]; then
  echo "ERROR: Could not extract issue ID from URL: $JIRA_URL" >&2
  exit 1
fi

if [[ -n "$WORKDIR_OVERRIDE" ]]; then
  WORKDIR="$WORKDIR_OVERRIDE"
else
  WORKDIR="$(pwd)/${JIRA_ID}"
fi

mkdir -p "$WORKDIR"

PIPELINE_STATE="${WORKDIR}/pipeline_state.json"

if [[ ! -f "$PIPELINE_STATE" ]]; then
  cat > "$PIPELINE_STATE" <<'EOF'
{
  "steps": {
    "quay":     {"status": "pending", "mr_url": ""},
    "krd":      {"status": "pending", "mr_url": ""},
    "okc":      {"status": "pending", "pr_url": ""},
    "operator": {"status": "pending", "pr_url": ""},
    "bundle":   {"status": "pending", "pr_url": ""},
    "rkc":      {"status": "pending", "pr_url": ""},
    "workflow": {"status": "pending"}
  }
}
EOF
  echo "Created pipeline state: $PIPELINE_STATE" >&2
else
  echo "Resuming from existing pipeline state: $PIPELINE_STATE" >&2
  jq '.steps | to_entries[] | "\(.key): \(.value.status)"' -r "$PIPELINE_STATE" >&2
fi

printf 'JIRA_ID=%q\n' "$JIRA_ID"
printf 'WORKDIR=%q\n' "$WORKDIR"
printf 'PIPELINE_STATE=%q\n' "$PIPELINE_STATE"
