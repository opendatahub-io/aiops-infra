#!/usr/bin/env bash
# Background script: waits for KRD + OKC to merge, then triggers the ODH Konflux onboarder workflow.
# Usage: nohup bash deferred_workflow.sh --workdir X --jira-url X --scripts-dir X \
#          --okc-url X --okc-path X --workflow-file X --repo-name X --repo-branch X --build-type X \
#          >> "$WORKDIR/deferred_workflow.log" 2>&1 &
set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
OKC_URL=""
OKC_PATH=""
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"
REPO_NAME=""
REPO_BRANCH=""
BUILD_TYPE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)       WORKDIR="$2";        shift 2 ;;
    --jira-url)      JIRA_URL="$2";       shift 2 ;;
    --scripts-dir)   SCRIPTS_DIR="$2";    shift 2 ;;
    --okc-url)       OKC_URL="$2";        shift 2 ;;
    --okc-path)      OKC_PATH="$2";       shift 2 ;;
    --workflow-file) WORKFLOW_FILE="$2";  shift 2 ;;
    --repo-name)     REPO_NAME="$2";      shift 2 ;;
    --repo-branch)   REPO_BRANCH="$2";    shift 2 ;;
    --build-type)    BUILD_TYPE="$2";     shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for required in WORKDIR JIRA_URL SCRIPTS_DIR OKC_URL OKC_PATH REPO_NAME REPO_BRANCH BUILD_TYPE; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 1
  fi
done

PIPELINE_STATE="${WORKDIR}/pipeline_state.json"

echo "[deferred_workflow] Starting. Waiting for KRD and OKC to merge..."

# Wait for both KRD and OKC steps to reach 'merged' status
while true; do
  RELEASE_DATA_STATUS=$(bash "$SCRIPTS_DIR/pipeline_state.sh" get --state "$PIPELINE_STATE" --step krd --field status 2>/dev/null || echo "pending")
  OKC_STATUS=$(bash "$SCRIPTS_DIR/pipeline_state.sh" get --state "$PIPELINE_STATE" --step okc --field status 2>/dev/null || echo "pending")

  if [[ "$RELEASE_DATA_STATUS" == "merged" && "$OKC_STATUS" == "merged" ]]; then
    echo "[deferred_workflow] KRD and OKC both merged. Triggering workflow..."
    break
  fi

  echo "[deferred_workflow] KRD=$RELEASE_DATA_STATUS OKC=$OKC_STATUS — waiting 60s..."
  sleep 60
done

# Trigger the GitHub Actions workflow
uv run --script "$SCRIPTS_DIR/run_github_workflow.py" \
  "$OKC_URL" \
  "$WORKFLOW_FILE" \
  --inputs "repo-name=$REPO_NAME,repo-branch=$REPO_BRANCH,build-type=$BUILD_TYPE"

bash "$SCRIPTS_DIR/pipeline_state.sh" set --state "$PIPELINE_STATE" --step workflow --field status --value triggered

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment "ODH Konflux onboarder workflow triggered successfully.

  Repository  : $REPO_NAME
  Branch      : $REPO_BRANCH
  Build type  : $BUILD_TYPE
  Workflow    : $WORKFLOW_FILE

Workflow was triggered after KRD and OKC PRs merged."

echo "[deferred_workflow] Done."
