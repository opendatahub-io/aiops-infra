#!/usr/bin/env bash
# Wrapper for the add-component-to-rhoai-konflux-central (okc) step — RHOAI variant.
#
# Generates a push PipelineRun YAML and raises a GitHub PR to the version-specific
# branch of rhoai-konflux-central.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure — stderr has error; pipeline_state.json NOT written
#   2  PipelineRun already exists — writes pipeline_state.json (status=done)
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

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
REPO_URL=$(grep -m1       'repo_url:'       "$YAML_FILE" | awk '{print $2}')
REPO_BRANCH=$(grep -m1    'repo_branch:'    "$YAML_FILE" | awk '{print $2}')
CONTEXT_PATH=$(grep -m1   'context_path:'   "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' | tr -d '"')
ARCHITECTURES=()
while IFS= read -r arch; do
  ARCHITECTURES+=("$arch")
done < <(awk '/^  architectures:/{found=1;next} found && /^  - /{print $2} found && /^  [a-z]/{exit}' "$YAML_FILE")
[[ ${#ARCHITECTURES[@]} -eq 0 ]] && {
  mapfile -t ARCHITECTURES < <(grep -A20 'architectures:' "$YAML_FILE" | grep '^ *- ' | awk '{print $2}')
}

[[ -z "$TARGET_RHOAI_VERSION" ]] && {
  echo "ERROR: target_rhoai_version missing from YAML." >&2; exit 1
}

eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
# Sets: VERSION_VAR, BRANCH_VAR, BRANCH_NAME, RHOAI_MINOR_VERSION, CONTENT_STREAM_TAG

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
PIPELINERUN_FILE="${COMPONENT_NAME}-${VERSION_VAR}-push.yaml"

if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CONTEXT_PATH_NORMALIZED="."
else
  CONTEXT_PATH_NORMALIZED="$CONTEXT_PATH"
fi

RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
echo "RHOAI_KONFLUX_CENTRAL_REPO_URL=${RHOAI_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
echo "RKC_URL resolved to: $RKC_URL"
RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')

# Fast-path: check if PipelineRun already exists in branch
PIPELINE_API_URL="https://api.github.com/repos/${RKC_PATH}/contents/pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}?ref=${BRANCH_NAME}"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PIPELINE_API_URL" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "PipelineRun '${PIPELINERUN_FILE}' already exists in branch '${BRANCH_NAME}'."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "rkc-changes-done" \
    --comment "PipelineRun '${PIPELINERUN_FILE}' already exists in rhoai-konflux-central at branch '${BRANCH_NAME}'. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step okc --status done
  exit 2
fi

# Ensure the version branch exists
bash "$SCRIPTS_DIR/ensure_github_branch.sh" \
  --repo-path   "$RKC_PATH" \
  --branch-name "$BRANCH_NAME" || {
  echo "ERROR: Failed to ensure branch '$BRANCH_NAME' in $RKC_PATH." >&2; exit 1
}

# Clone from version branch
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$RKC_URL" \
  --src-branch  "$BRANCH_NAME" \
  --dest-branch "$JIRA_ID" \
  --sparse-files "pipelineruns/$REPO_NAME") || {
  echo "ERROR: Playpen setup failed for rhoai-konflux-central." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

# Detect prefetch input
PREFETCH_INPUT="[]"
eval "$(bash "$SCRIPTS_DIR/detect_prefetch_input.sh" \
  --repo-url    "$REPO_URL" \
  --context-path "$CONTEXT_PATH_NORMALIZED" 2>/dev/null)" || true

# Build platform list
PLATFORMS=()
for arch in "${ARCHITECTURES[@]}"; do
  case "$arch" in
    x86_64)  PLATFORMS+=("linux/x86_64") ;;
    arm64)   PLATFORMS+=("linux-m2xlarge/arm64") ;;
    ppc64le) PLATFORMS+=("linux/ppc64le") ;;
    s390x)   PLATFORMS+=("linux/s390x") ;;
    *)       echo "WARN: Unknown architecture '$arch' — skipping" ;;
  esac
done
[[ ${#PLATFORMS[@]} -eq 0 ]] && {
  echo "ERROR: No valid architectures found." >&2; exit 1
}

TEKTON_DIR=$(find "$CLONE_DIR/pipelineruns/$REPO_NAME" -maxdepth 1 -iname ".tekton" -type d 2>/dev/null | head -1 || echo "")
[[ -z "$TEKTON_DIR" ]] && {
  TEKTON_DIR="$CLONE_DIR/pipelineruns/$REPO_NAME/.tekton"
  mkdir -p "$TEKTON_DIR"
}
PIPELINERUN_PATH="$TEKTON_DIR/$PIPELINERUN_FILE"

# Build platform YAML block
PLATFORM_LIST=""
for p in "${PLATFORMS[@]}"; do
  PLATFORM_LIST+="    - ${p}"$'\n'
done
PLATFORM_LIST="${PLATFORM_LIST%$'\n'}"

if [[ "$PREFETCH_INPUT" == "[]" ]]; then
  PREFETCH_PARAM_BLOCK=""
else
  PREFETCH_PARAM_BLOCK="  - name: prefetch-input
    value: |
      ${PREFETCH_INPUT}"
fi

cat > "$PIPELINERUN_PATH" <<PIPELINERUN_EOF

apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  annotations:
    build.appstudio.openshift.io/repo: ${REPO_URL}?rev={{revision}}
    build.appstudio.redhat.com/commit_sha: '{{revision}}'
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    pipelinesascode.tekton.dev/cancel-in-progress: "false"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    build.appstudio.openshift.io/build-nudge-files: "build/operator-nudging.yaml"
    pipelinesascode.tekton.dev/on-cel-expression: |
      event == "push"
      && target_branch == "${BRANCH_NAME}"
      && ( files.all.exists(p, !p.matches('^\\\\.tekton/')) || ".tekton/${COMPONENT_NAME}-${VERSION_VAR}-push.yaml".pathChanged() )
  labels:
    appstudio.openshift.io/application: rhoai-${VERSION_VAR}
    appstudio.openshift.io/component: ${COMPONENT_NAME}-${VERSION_VAR}
    pipelines.appstudio.openshift.io/type: build
  name: ${COMPONENT_NAME}-${VERSION_VAR}-on-push
  namespace: rhoai-tenant
spec:
  params:
  - name: git-url
    value: '{{source_url}}'
  - name: revision
    value: '{{revision}}'
  - name: additional-tags
    value:
    - '{{target_branch}}-{{revision}}'
  - name: output-image
    value: quay.io/rhoai/${COMPONENT_NAME}-rhel9:{{target_branch}}
  - name: rhoai-version
    value: "${RHOAI_MINOR_VERSION}"
  - name: dockerfile
    value: ${DOCKERFILE_PATH}
  - name: path-context
    value: ${CONTEXT_PATH_NORMALIZED}
  - name: hermetic
    value: true
${PREFETCH_PARAM_BLOCK}
  - name: build-platforms
    value:
${PLATFORM_LIST}
  pipelineRef:
    params:
    - name: url
      value: ${RKC_URL}
    - name: revision
      value: '{{ target_branch }}'
    - name: pathInRepo
      value: pipelines/multi-arch-container-build.yaml
    resolver: git
  taskRunTemplate:
    serviceAccountName: build-pipeline-${COMPONENT_NAME}-${VERSION_VAR}
    podTemplate:
      imagePullSecrets:
      - name: redhat-appstudio-staginguser-pull-secret
  timeouts:
    pipeline: 2h
PIPELINERUN_EOF

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE" \
  --message   "Add ${COMPONENT_NAME}-${VERSION_VAR} push PipelineRun" \
  --branch    "$DEST_BRANCH"

# Raise PR targeting the version branch
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$RKC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$RKC_URL" \
    --dest-branch "$BRANCH_NAME" \
    --title       "Add ${COMPONENT_NAME}-${VERSION_VAR} push PipelineRun" \
    --description "Adds push PipelineRun YAML for '${COMPONENT_NAME}' targeting branch '${BRANCH_NAME}'.

Component repo: ${REPO_URL}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "rkc-pr-raised" \
  --comment "GitHub PR raised to add '${COMPONENT_NAME}-${VERSION_VAR}' push PipelineRun to rhoai-konflux-central.

PR URL: ${PR_URL}
Target branch: ${BRANCH_NAME}

Konflux CI will start building the component once this PR is merged." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step okc \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
