#!/usr/bin/env bash
# Wrapper for the add-rhoai-dockerfile-labels step (supplementary, RHOAI only).
#
# Checks mandatory RHOAI OCI labels in the component Dockerfile.
# If all labels are present and correct, exits 2 (done). Otherwise clones
# the component repo, adds labels, and raises a GitHub PR.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Labels already correct — writes pipeline_state.json (status=done)
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

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.dockerfile_labels.pr_url // ""' "$PIPELINE_STATE" 2>/dev/null || echo "")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

INPUT_VARS=$(uv run --script "$SCRIPTS_DIR/read_onboarding_inputs.py" "$YAML_FILE") || exit 1
eval "$INPUT_VARS"
OS_ARGS=()
if [[ "$BASE_RHEL_VERSION_PRESENT" == true ]]; then
  OS_ARGS=(--base-rhel-version "$BASE_RHEL_VERSION_INPUT")
fi
OS_VARS=$(uv run --script "$SCRIPTS_DIR/resolve_rhel_version.py" \
  --product-context RHOAI "${OS_ARGS[@]}") || exit 1
eval "$OS_VARS"

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
REPO_URL=$(grep -m1       'repo_url:'       "$YAML_FILE" | awk '{print $2}')
REPO_BRANCH=$(grep -m1    'repo_branch:'    "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}')

[[ -z "$COMPONENT_NAME" || -z "$REPO_URL" ]] && {
  echo "ERROR: component_name or repo_url missing from YAML." >&2; exit 1
}
[[ -z "$DOCKERFILE_PATH" ]] && DOCKERFILE_PATH="Dockerfile"

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
REPO_PATH=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')

echo "COMPONENT_NAME  : $COMPONENT_NAME"
echo "REPO_URL        : $REPO_URL"
echo "DOCKERFILE_PATH : $DOCKERFILE_PATH"

# Check current Dockerfile for mandatory labels
CHECK_RESULT=$(uv run --script "$SCRIPTS_DIR/check_dockerfile_digests.py" \
  --repo-path      "$REPO_PATH" \
  --dockerfile     "$DOCKERFILE_PATH" \
  --component-name "$COMPONENT_NAME" \
  --github-token   "$GITHUB_TOKEN" 2>/dev/null || echo "NEEDS_UPDATE")

if [[ "$CHECK_RESULT" == "OK" ]]; then
  echo "All mandatory RHOAI labels are already present and correct."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "dockerfile-labels-pr-merged" \
    --comment "Dockerfile for '${COMPONENT_NAME}' already has all mandatory RHOAI labels. No PR needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step dockerfile_labels --status done \
    2>/dev/null || true
  exit 2
fi

# Clone component repo and update Dockerfile labels
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$REPO_URL" \
  --src-branch  "$REPO_BRANCH" \
  --dest-branch "${JIRA_ID}-dockerfile-labels" \
  --sparse-files "$DOCKERFILE_PATH") || {
  echo "ERROR: Playpen setup for component repo failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

DOCKERFILE_ABS="$CLONE_DIR/$DOCKERFILE_PATH"
[[ ! -f "$DOCKERFILE_ABS" ]] && {
  echo "ERROR: Dockerfile not found at $DOCKERFILE_ABS." >&2; exit 1
}

# Update labels in Dockerfile
uv run --script "$SCRIPTS_DIR/update_dockerfile_labels.py" \
  --dockerfile     "$DOCKERFILE_ABS" \
  --name           "rhoai/${COMPONENT_NAME}${IMAGE_REPO_SUFFIX}" \
  --component      "${COMPONENT_NAME}${IMAGE_REPO_SUFFIX}" \
  --default        "$COMPONENT_NAME" || {
  echo "ERROR: Could not update Dockerfile labels." >&2; exit 1
}

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$DOCKERFILE_PATH" \
  --message   "Add mandatory RHOAI OCI labels to Dockerfile

Adds name, com.redhat.component, summary, description, maintainer,
io.k8s.display-name, io.k8s.description labels for RHOAI compliance.

Related: ${JIRA_ID}" \
  --branch "$DEST_BRANCH"

# Raise PR (up to 3 attempts)
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$REPO_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$REPO_URL" \
    --dest-branch "$REPO_BRANCH" \
    --title       "Add mandatory RHOAI OCI labels to Dockerfile" \
    --description "Adds mandatory RHOAI OCI labels to \`${DOCKERFILE_PATH}\`.

Labels added: name, com.redhat.component, summary, description, maintainer,
io.k8s.display-name, io.k8s.description

Component: ${COMPONENT_NAME}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "dockerfile-labels-pr-raised" \
  --comment "[step:dockerfile_labels] GitHub PR raised to add mandatory RHOAI OCI labels to ${REPO_NAME} Dockerfile.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step dockerfile_labels \
  --status pr_raised --url "$PR_URL" --url-field pr_url \
  2>/dev/null || true

echo "PR_URL=${PR_URL}"
