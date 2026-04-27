#!/usr/bin/env bash
# init_pipeline.sh — validates the Jira URL, creates the working directory,
# and initializes or resumes pipeline_state.json.
# Prints shell variable assignments to stdout for eval.
set -euo pipefail

JIRA_URL=""

usage() {
  echo "Usage: $0 --jira-url URL"
  echo "  URL format: https://redhat.atlassian.net/browse/RHOAIENG-1234"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$JIRA_URL" ]] && usage

if [[ "$JIRA_URL" != *"/browse/"* ]]; then
  echo "ERROR: Invalid Jira URL format. Expected: https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL##*/}"
WORKDIR="$(pwd)/${JIRA_ID}"
PIPELINE_STATE="$WORKDIR/pipeline_state.json"

mkdir -p "$WORKDIR"

if [[ ! -f "$PIPELINE_STATE" ]]; then
  cat > "$PIPELINE_STATE" <<EOF
{
  "jira_url": "${JIRA_URL}",
  "jira_id": "${JIRA_ID}",
  "component_name": "",
  "product_context": "",
  "quay_org": "",
  "quay_visibility": "",
  "quay_repo_uri": "",
  "is_operator": false,
  "steps": {
    "validate":          { "status": "pending" },
    "quay":              { "mr_url": "",  "status": "pending" },
    "krd":               { "mr_url": "",  "status": "pending" },
    "okc":               { "pr_url": "",  "status": "pending" },
    "onboarder":         { "run_id": "", "tekton_pr_url": "", "status": "pending" },
    "operator":          { "pr_url": "",  "status": "pending" },
    "bundle":            { "pr_url": "",  "status": "pending" },
    "dockerfile_labels": { "pr_url": "",  "status": "pending" },
    "delivery_repo":     { "mr_url": "",  "status": "pending" },
    "auto_merge":        { "pr_url": "",  "status": "pending" },
    "renovate":          { "pr_url": "",  "status": "pending" }
  }
}
EOF
  echo "Initialized new pipeline state: $PIPELINE_STATE" >&2
else
  echo "Resuming from existing state:" >&2
  jq -r '.steps | to_entries[] | "  \(.key): \(.value.status)"' "$PIPELINE_STATE" >&2
fi

# Print assignments for eval
echo "JIRA_ID=${JIRA_ID}"
echo "WORKDIR=${WORKDIR}"
