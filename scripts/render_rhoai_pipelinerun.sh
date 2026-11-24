#!/usr/bin/env bash
# Render a RHOAI Konflux PipelineRun for a pull-request (P01) or push (P02) event.
#
# The pull-request and push generators share this single template so the two
# files cannot drift. The intentional differences are:
#
#   pull-request: hardcoded linux/x86_64 + linux-m2xlarge/arm64 platforms,
#                 P01 routing, on-pr tag, image expiry, Slack failure
#                 notification, standard OCI labels, no additional-tags
#   push:         user-selected platforms, P02 routing, branch tag,
#                 additional-tags, no additional-labels
#
# The legacy `pipelinesascode.tekton.dev/on-comment` annotation is not emitted.
# Manual retriggers are handled by the `issue_comment` event in the PR CEL
# expression, matching konflux-central's current convention.
#
# Usage:
#   render_rhoai_pipelinerun.sh \
#     --mode pull-request|push \
#     --component-name <name> \
#     --version-var <vX-Y[-ea-N]> \
#     --branch-name <rhoai-X.Y[-ea.N]> \
#     --repo-url <https://github.com/org/repo> \
#     --context-path <path> \
#     --dockerfile-path <path> \
#     --rhoai-minor-version <X.Y.0[-ea.N]> \
#     --konflux-central-url <url> \
#     [--platforms <comma-separated-platforms>] \
#     [--prefetch-input <json>]
#
# `--platforms` is required for push mode. Pull-request mode always renders
# linux/x86_64 and linux-m2xlarge/arm64, regardless of the onboarding
# architectures.
set -euo pipefail

MODE=""
COMPONENT_NAME=""
VERSION_VAR=""
BRANCH_NAME=""
REPO_URL=""
CONTEXT_PATH="."
DOCKERFILE_PATH=""
RHOAI_MINOR_VERSION=""
KONFLUX_CENTRAL_URL="https://github.com/red-hat-data-services/konflux-central.git"
PLATFORMS_CSV=""
PREFETCH_INPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)                  MODE="$2";                  shift 2 ;;
    --component-name)        COMPONENT_NAME="$2";        shift 2 ;;
    --version-var)           VERSION_VAR="$2";           shift 2 ;;
    --branch-name)           BRANCH_NAME="$2";           shift 2 ;;
    --repo-url)              REPO_URL="$2";              shift 2 ;;
    --context-path)          CONTEXT_PATH="$2";          shift 2 ;;
    --dockerfile-path)       DOCKERFILE_PATH="$2";       shift 2 ;;
    --rhoai-minor-version)   RHOAI_MINOR_VERSION="$2";   shift 2 ;;
    --konflux-central-url)   KONFLUX_CENTRAL_URL="$2";  shift 2 ;;
    --platforms)             PLATFORMS_CSV="$2";         shift 2 ;;
    --prefetch-input)        PREFETCH_INPUT="$2";        shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ "$MODE" == "pull-request" || "$MODE" == "push" ]] || {
  echo "ERROR: --mode must be 'pull-request' or 'push'." >&2
  exit 1
}

for _var in COMPONENT_NAME VERSION_VAR BRANCH_NAME REPO_URL DOCKERFILE_PATH RHOAI_MINOR_VERSION; do
  [[ -n "${!_var}" ]] || {
    echo "ERROR: --$(echo "$_var" | tr '[:upper:]_' '[:lower:]-') is required." >&2
    exit 1
  }
done

if [[ "$MODE" == "pull-request" ]]; then
  # Pull-request builds always target the same two platforms so PR coverage
  # matches current konflux-central pull-request files. The push PipelineRun
  # keeps the architectures selected on the onboarding ticket.
  PLATFORMS_CSV="linux/x86_64,linux-m2xlarge/arm64"
fi
[[ -n "$PLATFORMS_CSV" ]] || {
  echo "ERROR: --platforms is required for push mode." >&2
  exit 1
}

PLATFORM_LIST=""
IFS=',' read -r -a _platforms <<< "$PLATFORMS_CSV"
for _platform in "${_platforms[@]}"; do
  _platform="${_platform#"${_platform%%[![:space:]]*}"}"
  _platform="${_platform%"${_platform##*[![:space:]]}"}"
  [[ -n "$_platform" ]] || continue
  PLATFORM_LIST+="    - ${_platform}"$'\n'
done
PLATFORM_LIST="${PLATFORM_LIST%$'\n'}"
[[ -n "$PLATFORM_LIST" ]] || {
  echo "ERROR: No valid platforms supplied." >&2
  exit 1
}

PREFETCH_PARAM_BLOCK=""
if [[ -n "$PREFETCH_INPUT" && "$PREFETCH_INPUT" != "[]" ]]; then
  PREFETCH_INDENTED=$(printf '%s\n' "$PREFETCH_INPUT" | sed 's/^/      /')
  PREFETCH_PARAM_BLOCK="  - name: prefetch-input
    value: |
${PREFETCH_INDENTED}"
fi

if [[ "$MODE" == "pull-request" ]]; then
  PIPELINERUN_FILE="${COMPONENT_NAME}-pull-request.yaml"
  PIPELINE_REF_REVISION='{{ cel: pac.target_branch.matches("^rhoai-\\d+\\.\\d+(-ea\\.\\d+)?$") ? pac.target_branch : "main" }}'
  OUTPUT_IMAGE="quay.io/rhoai/${COMPONENT_NAME}-rhel9:on-pr-{{pull_request_number}}"
  META_NAME="${COMPONENT_NAME}-on-pull-request-{{pull_request_number}}"
else
  PIPELINERUN_FILE="${COMPONENT_NAME}-${VERSION_VAR}-push.yaml"
  PIPELINE_REF_REVISION='{{ target_branch }}'
  OUTPUT_IMAGE="quay.io/rhoai/${COMPONENT_NAME}-rhel9:{{target_branch}}"
  META_NAME="${COMPONENT_NAME}-${VERSION_VAR}-on-push"
fi

cat <<PIPELINERUN_HEADER
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  annotations:
    build.appstudio.openshift.io/repo: ${REPO_URL}?rev={{revision}}
    build.appstudio.redhat.com/commit_sha: '{{revision}}'
PIPELINERUN_HEADER

if [[ "$MODE" == "pull-request" ]]; then
  cat <<PIPELINERUN_PR_ANNOTATIONS
    build.appstudio.redhat.com/pull_request_number: '{{pull_request_number}}'
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    pipelinesascode.tekton.dev/cancel-in-progress: "true"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    pipelinesascode.tekton.dev/on-cel-expression: |-
      konflux_cluster == "stone-prod-p01"
      && (event == "pull_request" || event == "issue_comment")
      && (files.all.exists(p, ! p.matches('^\\\\.tekton/')) || ".tekton/${PIPELINERUN_FILE}".pathChanged())
PIPELINERUN_PR_ANNOTATIONS
else
  cat <<PIPELINERUN_PUSH_ANNOTATIONS
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    pipelinesascode.tekton.dev/cancel-in-progress: "false"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    build.appstudio.openshift.io/build-nudge-files: "build/operator-nudging.yaml"
    pipelinesascode.tekton.dev/on-cel-expression: |-
      konflux_cluster == "stone-prod-p02"
      && event == "push"
      && target_branch == "${BRANCH_NAME}"
      && (files.all.exists(p, ! p.matches('^\\\\.tekton/')) || ".tekton/${PIPELINERUN_FILE}".pathChanged())
PIPELINERUN_PUSH_ANNOTATIONS
fi

cat <<PIPELINERUN_BODY
  labels:
    appstudio.openshift.io/application: rhoai-${VERSION_VAR}
    appstudio.openshift.io/component: ${COMPONENT_NAME}-${VERSION_VAR}
    pipelines.appstudio.openshift.io/type: build
  name: ${META_NAME}
  namespace: rhoai-tenant
spec:
  params:
  - name: git-url
    value: '{{source_url}}'
  - name: revision
    value: '{{revision}}'
PIPELINERUN_BODY

if [[ "$MODE" == "push" ]]; then
  cat <<PIPELINERUN_PUSH_PARAMS
  - name: additional-tags
    value:
    - '{{target_branch}}-{{revision}}'
PIPELINERUN_PUSH_PARAMS
fi

cat <<PIPELINERUN_OUTPUT
  - name: output-image
    value: ${OUTPUT_IMAGE}
PIPELINERUN_OUTPUT

if [[ "$MODE" == "pull-request" ]]; then
  cat <<PIPELINERUN_PR_PARAMS
  - name: additional-labels
    value:
    - version=on-pr-{{revision}}
    - io.openshift.tags=${COMPONENT_NAME}
  - name: image-expires-after
    value: 30d
  - name: enable-slack-failure-notification
    value: "false"
PIPELINERUN_PR_PARAMS
fi

cat <<PIPELINERUN_COMMON_PARAMS
  - name: dockerfile
    value: ${DOCKERFILE_PATH}
  - name: path-context
    value: ${CONTEXT_PATH}
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
      value: ${KONFLUX_CENTRAL_URL}
    - name: revision
      value: '${PIPELINE_REF_REVISION}'
    - name: pathInRepo
      value: pipelines/multi-arch-container-build.yaml
  taskRunSpecs:
  - pipelineTaskName: rpms-signature-scan
    stepSpecs:
    - name: rpms-signature-scan
      computeResources:
        requests:
          cpu: "500m"
          memory: "1Gi"
        limits:
          cpu: "500m"
          memory: "1Gi"
  taskRunTemplate:
    serviceAccountName: build-pipeline-${COMPONENT_NAME}-${VERSION_VAR}
  workspaces:
  - name: git-auth
    secret:
      secretName: '{{ git_auth_secret }}'
PIPELINERUN_COMMON_PARAMS
