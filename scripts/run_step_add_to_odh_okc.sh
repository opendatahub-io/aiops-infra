#!/usr/bin/env bash
# Wrapper for the add-component-to-odh-konflux-central (okc) step — ODH variant.
#
# Generates PipelineRun YAMLs and raises a GitHub PR to odh-konflux-central.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure — stderr has error; pipeline_state.json NOT written
#   2  Component PipelineRun already exists — writes pipeline_state.json (status=done)
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

EXISTING_URL=$(jq -r '.steps.okc.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

CONTEXT_PATH=$(grep -m1    'context_path:'    "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}')
BUILD_TYPE=$(grep -m1      'build_type:'      "$YAML_FILE" | awk '{print $2}')

if [[ "$COMPONENT_NAME" == *-ci ]]; then
  KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"
else
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"
fi
REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"

OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
echo "ODH_KONFLUX_CENTRAL_REPO_URL=${ODH_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
echo "OKC_URL resolved to: $OKC_URL"
OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')

# Derived file/run names
PUSH_YAML_FILE="${COMPONENT_NAME}-push.yaml"
PR_YAML_FILE="${COMPONENT_NAME}-pull-request.yaml"
PUSH_RUN_NAME="${COMPONENT_NAME}-on-push"
PR_RUN_NAME="${COMPONENT_NAME}-on-pull-request"
SERVICE_ACCOUNT_NAME="build-pipeline-${KONFLUX_COMPONENT_NAME}"
NAMESPACE="open-data-hub-tenant"
APPLICATION="opendatahub-builds"

if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CONTEXT_PATH_NORMALIZED="."
else
  CONTEXT_PATH_NORMALIZED="$CONTEXT_PATH"
fi

if [[ -n "$CONTEXT_PATH_NORMALIZED" && ! "$CONTEXT_PATH_NORMALIZED" =~ ^[a-zA-Z0-9_./-]+$ ]]; then
  echo "ERROR: context_path contains invalid characters: $CONTEXT_PATH_NORMALIZED" >&2
  exit 1
fi

# Fast-path idempotency check via GitHub API
PUSH_API_URL="https://api.github.com/repos/${OKC_PATH}/contents/pipelineruns/${REPO_NAME}/${PUSH_YAML_FILE}?ref=main"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PUSH_API_URL" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "PipelineRun '${PUSH_YAML_FILE}' already exists in odh-konflux-central. No action needed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "okc-changes-done" \
    --comment "PipelineRun files for '$COMPONENT_NAME' already exist in odh-konflux-central at 'pipelineruns/$REPO_NAME/'. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step okc --status done
  exit 2
fi

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$OKC_URL" \
  --src-branch  "main" \
  --dest-branch "$JIRA_ID" \
  --sparse-files "pipelineruns/template pipelineruns/$REPO_NAME .github/workflows") || {
  echo "ERROR: Playpen setup for odh-konflux-central failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

# Detect prefetch method
eval "$(bash "$SCRIPTS_DIR/detect_prefetch_input.sh" \
  --repo-url    "$REPO_URL" \
  --context-path "$CONTEXT_PATH_NORMALIZED" 2>/dev/null)" || true

# Verify templates exist
[[ -f "$CLONE_DIR/pipelineruns/template/odh-component-push.yaml" ]] || {
  echo "ERROR: Push template not found at $CLONE_DIR/pipelineruns/template/odh-component-push.yaml" >&2; exit 1
}
[[ -f "$CLONE_DIR/pipelineruns/template/odh-component-pull-request.yaml" ]] || {
  echo "ERROR: PR template not found at $CLONE_DIR/pipelineruns/template/odh-component-pull-request.yaml" >&2; exit 1
}

mkdir -p "$CLONE_DIR/pipelineruns/$REPO_NAME"

# Generate push PipelineRun
PUSH_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PUSH_YAML_FILE"
cp "$CLONE_DIR/pipelineruns/template/odh-component-push.yaml" "$PUSH_FILE"
sed -i \
  -e "s|component-git-url|${REPO_URL}|g" \
  -e "s|odh-component-name-ci|${KONFLUX_COMPONENT_NAME}|g" \
  -e "s|odh-file-name-on-push|${PUSH_RUN_NAME}|g" \
  -e "s|quay.io/opendatahub/quayurl|quay.io/${QUAY_ORG}/${COMPONENT_NAME}|g" \
  -e "s|dockerfilepath|${DOCKERFILE_PATH}|g" \
  -e "/name: path-context/{n;s|value: .*|value: ${CONTEXT_PATH_NORMALIZED}|;}" \
  -e "s|build-pipeline-sa-namw|${SERVICE_ACCOUNT_NAME}|g" \
  -e "s|open-data-hub-tenant|${NAMESPACE}|g" \
  -e "s|opendatahub-builds|${APPLICATION}|g" \
  "$PUSH_FILE"

grep -q "name: $PUSH_RUN_NAME" "$PUSH_FILE" || {
  echo "ERROR: Push PipelineRun substitution failed — PUSH_RUN_NAME not found." >&2; exit 1
}

# Generate pull-request PipelineRun
PR_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PR_YAML_FILE"
cp "$CLONE_DIR/pipelineruns/template/odh-component-pull-request.yaml" "$PR_FILE"
sed -i \
  -e "s|build.appstudio.openshift.io/repo: #component-git-url?rev={{revision}}|build.appstudio.openshift.io/repo: ${REPO_URL}?rev={{revision}}|g" \
  -e "s|odh-component-name-ci|${KONFLUX_COMPONENT_NAME}|g" \
  -e "s|  name: #odh-file-name-on-pull-request|  name: ${PR_RUN_NAME}|g" \
  -e "s|quay.io/opendatahub/quayurl|quay.io/${QUAY_ORG}/${COMPONENT_NAME}|g" \
  -e "s|dockerfilepath|${DOCKERFILE_PATH}|g" \
  -e "/name: path-context/{n;s|value: .*|value: ${CONTEXT_PATH_NORMALIZED}|;}" \
  -e "s|    serviceAccountName: #build-pipeline-sa-name|    serviceAccountName: ${SERVICE_ACCOUNT_NAME}|g" \
  -e "s|open-data-hub-tenant|${NAMESPACE}|g" \
  -e "s|opendatahub-builds|${APPLICATION}|g" \
  "$PR_FILE"

grep -q "name: $PR_RUN_NAME" "$PR_FILE" || {
  echo "ERROR: PR PipelineRun substitution failed — PR_RUN_NAME not found." >&2; exit 1
}

# Update onboarder workflow component list
WORKFLOW_FILE="$CLONE_DIR/.github/workflows/odh-konflux-onboarder.yml"
if [[ -f "$WORKFLOW_FILE" ]] && ! grep -q "          - ${REPO_NAME}$" "$WORKFLOW_FILE" 2>/dev/null; then
  uv run --script "$SCRIPTS_DIR/edit_yaml.py" insert-list-item \
    "$WORKFLOW_FILE" \
    --list-key "on.workflow_dispatch.inputs.component.options" \
    --value "$REPO_NAME" || {
    echo "ERROR: Could not insert $REPO_NAME into onboarder workflow options." >&2; exit 1
  }
fi

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "pipelineruns/$REPO_NAME/$PUSH_YAML_FILE pipelineruns/$REPO_NAME/$PR_YAML_FILE .github/workflows/odh-konflux-onboarder.yml" \
  --message   "Add ${KONFLUX_COMPONENT_NAME} PipelineRuns for ${REPO_NAME}" \
  --branch    "$DEST_BRANCH"

# Raise PR
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$OKC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$OKC_URL" \
    --dest-branch "main" \
    --title       "Add ${KONFLUX_COMPONENT_NAME} PipelineRuns" \
    --description "Adds push and pull-request PipelineRun YAMLs for '${KONFLUX_COMPONENT_NAME}'.

Component repo: ${REPO_URL}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "okc-pr-raised" \
  --comment "GitHub PR raised to add '${KONFLUX_COMPONENT_NAME}' to odh-konflux-central.

PR URL: ${PR_URL}

Konflux CI will start building the component once this PR is merged." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step okc \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
