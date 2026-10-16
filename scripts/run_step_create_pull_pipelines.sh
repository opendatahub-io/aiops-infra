#!/usr/bin/env bash
# Wrapper for the create-pull-pipelines-in-rhoai-konflux-central step (RHOAI only).
#
# Generates a pull-request PipelineRun YAML and raises a PR targeting main
# in rhoai-konflux-central.
#
# Application, component, service account, and rhoai-version come from
# target_rhoai_version via parse_rhoai_version.sh. That input is the version
# the ticket asked for. This script does not look up a newer development branch
# when the ticket targets an older release.
#
# rhoai-init (RHOAIENG-97056) has not added a task parameter or a new task
# version. pathInRepo stays pipelines/multi-arch-container-build.yaml.
#
# --render-only --details <component_onboarding_details.yaml>
#   Prints the PipelineRun YAML and exits. Optional --prefetch-input skips
#   repository inspection. Used by unit tests.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure — stderr has error; pipeline_state.json NOT written
#   2  Pull PipelineRun already exists — writes pipeline_state.json (status=done)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
RENDER_ONLY=0
DETAILS_FILE=""
PREFETCH_INPUT_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    --render-only) RENDER_ONLY=1; shift ;;
    --details) DETAILS_FILE="$2"; shift 2 ;;
    --prefetch-input) PREFETCH_INPUT_ARG="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$RENDER_ONLY" -eq 1 ]]; then
  YAML_FILE="$DETAILS_FILE"
  [[ -n "$YAML_FILE" && -f "$YAML_FILE" ]] || {
    echo "ERROR: --details must point at component_onboarding_details.yaml" >&2
    exit 1
  }
else
  [[ -z "$JIRA_URL" ]] && { echo "ERROR: --jira-url is required" >&2; exit 1; }

  JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
  WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
  PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"

  [[ ! -f "$PIPELINE_STATE" ]] && {
    echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
  }

  EXISTING_URL=$(jq -r '.steps.pull_pipelines.pr_url // ""' "$PIPELINE_STATE")
  if [[ -n "$EXISTING_URL" ]]; then
    echo "PR already recorded in state: $EXISTING_URL"
    echo "PR_URL=$EXISTING_URL"
    exit 0
  fi

  YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
  [[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }
fi

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}' | tr -d '"')
REPO_URL=$(grep -m1       'repo_url:'       "$YAML_FILE" | awk '{print $2}' | tr -d '"')
CONTEXT_PATH=$(grep -m1   'context_path:'   "$YAML_FILE" | awk '{print $2}' | tr -d '"')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}' | tr -d '"')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' | tr -d '"')

ARCHITECTURES=()
while IFS= read -r arch; do
  ARCHITECTURES+=("$arch")
done < <(awk '/^  architectures:/{found=1;next} found && /^  - /{print $2} found && /^  [a-z]/{exit}' "$YAML_FILE")
[[ ${#ARCHITECTURES[@]} -eq 0 ]] && {
  mapfile -t ARCHITECTURES < <(grep -A20 'architectures:' "$YAML_FILE" | grep '^ *- ' | awk '{print $2}')
}

[[ -z "$TARGET_RHOAI_VERSION" ]] && {
  echo "ERROR: target_rhoai_version missing." >&2; exit 1
}

eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
# Sets: VERSION_VAR, BRANCH_NAME, RHOAI_MINOR_VERSION

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
PIPELINERUN_FILE="${COMPONENT_NAME}-pull-request.yaml"

if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CONTEXT_PATH_NORMALIZED="."
else
  CONTEXT_PATH_NORMALIZED="$CONTEXT_PATH"
fi

RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')

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

if [[ -n "$PREFETCH_INPUT_ARG" ]]; then
  PREFETCH_INPUT="$PREFETCH_INPUT_ARG"
else
  # Detect prefetch input
  PREFETCH_INPUT="[]"
  eval "$(bash "$SCRIPTS_DIR/detect_prefetch_input.sh" \
    --repo-url    "$REPO_URL" \
    --context-path "$CONTEXT_PATH_NORMALIZED" 2>/dev/null)" || true
fi

PLATFORM_LIST=""
for p in "${PLATFORMS[@]}"; do
  PLATFORM_LIST+="    - ${p}"$'\n'
done
PLATFORM_LIST="${PLATFORM_LIST%$'\n'}"

if [[ -z "$PREFETCH_INPUT" || "$PREFETCH_INPUT" == "[]" ]]; then
  PREFETCH_PARAM_BLOCK=""
else
  PREFETCH_PARAM_BLOCK="  - name: prefetch-input
    value: |
      ${PREFETCH_INPUT}"
fi

# GAP Stage 2 PR PipelineRun (RHOAIENG-97051 / konflux-central PR #3630).
# The on-CEL file condition matches the development push pipeline's standard
# filter, with the event changed to pull_request and the release-branch guard
# removed. The pipeline revision selects a release branch when the PR target
# matches rhoai-X.Y or rhoai-X.Y-ea.N, and main otherwise.
render_pull_pipelinerun() {
  cat <<PIPELINERUN_EOF
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  annotations:
    build.appstudio.openshift.io/repo: ${REPO_URL}?rev={{revision}}
    build.appstudio.redhat.com/commit_sha: '{{revision}}'
    build.appstudio.redhat.com/pull_request_number: '{{pull_request_number}}'
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    pipelinesascode.tekton.dev/cancel-in-progress: "true"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    pipelinesascode.tekton.dev/on-comment: "^/build-konflux"
    pipelinesascode.tekton.dev/on-cel-expression: |-
      event == "pull_request"
      && (files.all.exists(p, ! p.matches('^\\\\.tekton/')) || ".tekton/${PIPELINERUN_FILE}".pathChanged())
  labels:
    appstudio.openshift.io/application: rhoai-${VERSION_VAR}
    appstudio.openshift.io/component: ${COMPONENT_NAME}-${VERSION_VAR}
    pipelines.appstudio.openshift.io/type: build
  name: ${COMPONENT_NAME}-on-pull-request-{{pull_request_number}}
  namespace: rhoai-tenant
spec:
  params:
  - name: git-url
    value: '{{source_url}}'
  - name: revision
    value: '{{revision}}'
  - name: output-image
    value: quay.io/rhoai/${COMPONENT_NAME}-rhel9:on-pr-{{pull_request_number}}
  - name: dockerfile
    value: ${DOCKERFILE_PATH}
  - name: path-context
    value: ${CONTEXT_PATH_NORMALIZED}
  - name: image-expires-after
    value: 30d
  - name: enable-slack-failure-notification
    value: "false"
  - name: hermetic
    value: true
  - name: rhoai-version
    value: "${RHOAI_MINOR_VERSION}"
${PREFETCH_PARAM_BLOCK}
  - name: build-source-image
    value: true
  - name: build-image-index
    value: true
  - name: build-platforms
    value:
${PLATFORM_LIST}
  pipelineRef:
    resolver: git
    params:
    - name: url
      value: ${RKC_URL}
    - name: revision
      value: '{{ cel: pac.target_branch.matches("^rhoai-\\\\d+\\\\.\\\\d+(-ea\\\\.\\\\d+)?\$") ? pac.target_branch : "main" }}'
    - name: pathInRepo
      value: pipelines/multi-arch-container-build.yaml
  taskRunTemplate:
    serviceAccountName: build-pipeline-${COMPONENT_NAME}-${VERSION_VAR}
    podTemplate:
      imagePullSecrets:
      - name: redhat-appstudio-staginguser-pull-secret
  timeouts:
    pipeline: 8h
  workspaces:
  - name: git-auth
    secret:
      secretName: '{{ git_auth_secret }}'
PIPELINERUN_EOF
}

if [[ "$RENDER_ONLY" -eq 1 ]]; then
  render_pull_pipelinerun
  exit 0
fi

# Fast-path: check if pull-request PipelineRun already exists on main
PR_PIPELINE_API_URL="https://api.github.com/repos/${RKC_PATH}/contents/pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}?ref=main"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PR_PIPELINE_API_URL" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
  echo "Pull-request PipelineRun '${PIPELINERUN_FILE}' already exists on main."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "rkc-pull-changes-done" \
    --comment "Pull-request PipelineRun '${PIPELINERUN_FILE}' already exists in rhoai-konflux-central on main. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step pull_pipelines --status done
  exit 2
fi

# Clone from main
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$RKC_URL" \
  --src-branch  "main" \
  --dest-branch "$JIRA_ID-pull" \
  --sparse-files "pipelineruns/$REPO_NAME") || {
  echo "ERROR: Playpen setup failed for rhoai-konflux-central (pull-pipelines)." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

TEKTON_DIR=$(find "$CLONE_DIR/pipelineruns/$REPO_NAME" -maxdepth 1 -iname ".tekton" -type d 2>/dev/null | head -1 || echo "")
[[ -z "$TEKTON_DIR" ]] && {
  TEKTON_DIR="$CLONE_DIR/pipelineruns/$REPO_NAME/.tekton"
  mkdir -p "$TEKTON_DIR"
}
PIPELINERUN_PATH="$TEKTON_DIR/$PIPELINERUN_FILE"

render_pull_pipelinerun > "$PIPELINERUN_PATH"

bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE" \
  --message   "Add ${COMPONENT_NAME} pull-request PipelineRun" \
  --branch    "$DEST_BRANCH"

PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$RKC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$RKC_URL" \
    --dest-branch "main" \
    --title       "Add ${COMPONENT_NAME} pull-request PipelineRun" \
    --description "Adds pull-request PipelineRun YAML for '${COMPONENT_NAME}'.

Component repo: ${REPO_URL}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "rkc-pull-pr-raised" \
  --comment "GitHub PR raised to add '${COMPONENT_NAME}' pull-request PipelineRun to rhoai-konflux-central.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step pull_pipelines \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
