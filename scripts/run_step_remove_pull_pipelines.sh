#!/usr/bin/env bash
# Offboarding: remove pull-request PipelineRun from rhoai-konflux-central (RHOAI only).
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Pull PipelineRun not found (already removed) — writes pipeline_state.json (status=done)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$JIRA_URL" ]] && { echo "ERROR: --jira-url is required" >&2; exit 1; }

JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN_PREFIX=""
if [[ "${OFFBOARD_DRY_RUN:-false}" == "true" ]]; then
  DRY_RUN_PREFIX="[DRY RUN] "
fi

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.remove_pull_pipelines.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
REPO_URL=$(grep -m1       'repo_url:'       "$YAML_FILE" | awk '{print $2}')
REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"

PIPELINERUN_FILE="${COMPONENT_NAME}-pull-request.yaml"

RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')

# Check if pull-request PipelineRun exists on main
API_URL="https://api.github.com/repos/${RKC_PATH}/contents/pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}?ref=main"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$API_URL" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "Pull-request PipelineRun '${PIPELINERUN_FILE}' not found on main — already removed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-pull-pipelines-pr-merged" \
    --comment "${DRY_RUN_PREFIX}Pull-request PipelineRun '${PIPELINERUN_FILE}' already absent from rhoai-konflux-central. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_pull_pipelines --status done
  exit 2
fi

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$RKC_URL" \
  --src-branch  "main" \
  --dest-branch "${JIRA_ID}-offboard-pull" \
  --sparse-files "pipelineruns/$REPO_NAME") || {
  echo "ERROR: Playpen setup failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

TEKTON_DIR="$CLONE_DIR/pipelineruns/$REPO_NAME/.tekton"
TARGET_FILE="$TEKTON_DIR/$PIPELINERUN_FILE"
[[ -f "$TARGET_FILE" ]] && rm "$TARGET_FILE"

cd "$CLONE_DIR"
git add -A
git commit -m "Remove ${COMPONENT_NAME} pull-request PipelineRun (offboarding)"
git push origin "$DEST_BRANCH" || {
  git fetch --unshallow origin 2>/dev/null || true
  git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed." >&2; exit 1; }
}

PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$RKC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$RKC_URL" \
    --dest-branch "main" \
    --title       "${DRY_RUN_PREFIX}Remove ${COMPONENT_NAME} pull-request PipelineRun (offboarding)" \
    --description "Removes pull-request PipelineRun YAML for '${COMPONENT_NAME}'.

Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-pull-pipelines-pr-raised" \
  --comment "${DRY_RUN_PREFIX}[step:remove_pull_pipelines] GitHub PR raised to remove '${COMPONENT_NAME}' pull-request PipelineRun.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_pull_pipelines \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
