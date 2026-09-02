#!/usr/bin/env bash
# Offboarding: remove PipelineRun files from Konflux Central.
#
# ODH: removes push + pull-request PipelineRun YAMLs from odh-konflux-central
# RHOAI: removes push PipelineRun YAML from rhoai-konflux-central (version branch)
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  PipelineRun files not found (already removed) — writes pipeline_state.json (status=done)
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

EXISTING_URL=$(jq -r '.steps.remove_okc.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"

if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  [[ -z "$TARGET_RHOAI_VERSION" ]] && {
    echo "ERROR: target_rhoai_version required for RHOAI." >&2; exit 1
  }
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"

  RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
  RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')
  CENTRAL_URL="$RKC_URL"
  CENTRAL_PATH="$RKC_PATH"
  SRC_BRANCH="$BRANCH_NAME"
  PIPELINERUN_FILE="${COMPONENT_NAME}-${VERSION_VAR}-push.yaml"

  # Check if file exists
  API_URL="https://api.github.com/repos/${CENTRAL_PATH}/contents/pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}?ref=${SRC_BRANCH}"
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "$API_URL" 2>/dev/null || echo "000")

  if [[ "$HTTP_STATUS" != "200" ]]; then
    echo "PipelineRun '${PIPELINERUN_FILE}' not found on branch '${SRC_BRANCH}' — already removed."
    uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
      --add-label "offboard-okc-pr-merged" \
      --comment "${DRY_RUN_PREFIX}Push PipelineRun '${PIPELINERUN_FILE}' already absent from rhoai-konflux-central. No action needed." || true
    bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
      --state "$PIPELINE_STATE" --step remove_okc --status done
    exit 2
  fi

  cd "$WORKDIR"
  PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
    --src-url     "$CENTRAL_URL" \
    --src-branch  "$SRC_BRANCH" \
    --dest-branch "${JIRA_ID}-offboard" \
    --sparse-files "pipelineruns/$REPO_NAME") || {
    echo "ERROR: Playpen setup failed." >&2; exit 1
  }
  CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
  DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

  TEKTON_DIR="$CLONE_DIR/pipelineruns/$REPO_NAME/.tekton"
  TARGET_FILE="$TEKTON_DIR/$PIPELINERUN_FILE"
  [[ -f "$TARGET_FILE" ]] && rm "$TARGET_FILE"
  FILES_CHANGED="pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE"
  COMMIT_MSG="${DRY_RUN_PREFIX}Remove ${COMPONENT_NAME}-${VERSION_VAR} push PipelineRun (offboarding)"
  PR_TARGET="$SRC_BRANCH"

else
  OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
  OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
  CENTRAL_URL="$OKC_URL"
  CENTRAL_PATH="$OKC_PATH"
  SRC_BRANCH="main"

  if [[ "$COMPONENT_NAME" == *-ci ]]; then
    KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"
  else
    KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"
  fi

  PUSH_YAML="${COMPONENT_NAME}-push.yaml"
  PR_YAML="${COMPONENT_NAME}-pull-request.yaml"

  # Check if push file exists
  API_URL="https://api.github.com/repos/${CENTRAL_PATH}/contents/pipelineruns/${REPO_NAME}/${PUSH_YAML}?ref=main"
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "$API_URL" 2>/dev/null || echo "000")

  if [[ "$HTTP_STATUS" != "200" ]]; then
    echo "PipelineRun files for '${COMPONENT_NAME}' not found in odh-konflux-central — already removed."
    uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
      --add-label "offboard-okc-pr-merged" \
      --comment "${DRY_RUN_PREFIX}PipelineRun files for '${COMPONENT_NAME}' already absent from odh-konflux-central. No action needed." || true
    bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
      --state "$PIPELINE_STATE" --step remove_okc --status done
    exit 2
  fi

  cd "$WORKDIR"
  PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
    --src-url     "$CENTRAL_URL" \
    --src-branch  "main" \
    --dest-branch "${JIRA_ID}-offboard" \
    --sparse-files "pipelineruns/$REPO_NAME") || {
    echo "ERROR: Playpen setup failed." >&2; exit 1
  }
  CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
  DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

  FILES_CHANGED=""
  PUSH_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PUSH_YAML"
  PR_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PR_YAML"
  [[ -f "$PUSH_FILE" ]] && { rm "$PUSH_FILE"; FILES_CHANGED="pipelineruns/$REPO_NAME/$PUSH_YAML"; }
  [[ -f "$PR_FILE" ]] && { rm "$PR_FILE"; FILES_CHANGED="$FILES_CHANGED pipelineruns/$REPO_NAME/$PR_YAML"; }
  COMMIT_MSG="${DRY_RUN_PREFIX}Remove ${COMPONENT_NAME} PipelineRuns (offboarding)"
  PR_TARGET="main"
fi

cd "$CLONE_DIR"
git add -A
git commit -m "$COMMIT_MSG"
git push origin "$DEST_BRANCH" || {
  git fetch --unshallow origin 2>/dev/null || true
  git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed." >&2; exit 1; }
}

PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$CENTRAL_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$CENTRAL_URL" \
    --dest-branch "$PR_TARGET" \
    --title       "$COMMIT_MSG" \
    --description "Removes PipelineRun files for '${COMPONENT_NAME}' (offboarding).

Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
  --add-label "offboard-okc-pr-raised" \
  --comment "${DRY_RUN_PREFIX}[step:remove_okc] GitHub PR raised to remove '${COMPONENT_NAME}' PipelineRuns.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_okc \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
