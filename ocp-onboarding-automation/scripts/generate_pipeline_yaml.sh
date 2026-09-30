#!/usr/bin/env bash
# Generate a Tekton PipelineRun YAML file for RHOAI FBC fragment builds.
# Uses templates and variable substitution.
#
# Usage:
#   bash generate_pipeline_yaml.sh \
#     --rhoai-version 3.6 \
#     --ocp-version 5.0 \
#     --output-file /path/to/output.yaml
#
# Options:
#   --rhoai-version VER   RHOAI version (e.g., "3.6", "3.5-ea.2")
#   --ocp-version VER     OCP version (e.g., "5.0", "4.19")
#   --output-file FILE    Output YAML file path (required)
#   --dry-run             Print to stdout instead of writing file

set -euo pipefail

RHOAI_VERSION=""
OCP_VERSION=""
OUTPUT_FILE=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --rhoai-version) RHOAI_VERSION="$2"; shift 2 ;;
    --ocp-version)   OCP_VERSION="$2"; shift 2 ;;
    --output-file)   OUTPUT_FILE="$2"; shift 2 ;;
    --dry-run)       DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$RHOAI_VERSION" ]] && {
  echo "ERROR: --rhoai-version is required" >&2
  exit 1
}

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

[[ -z "$OUTPUT_FILE" && "$DRY_RUN" == false ]] && {
  echo "ERROR: --output-file is required (unless --dry-run)" >&2
  exit 1
}

# Parse versions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Parse RHOAI version
# Always use fallback parsing for now (simple and reliable)
RHOAI_VER_CLEAN="${RHOAI_VERSION#rhoai-}"  # Remove rhoai- prefix if present
VERSION_VAR="${RHOAI_VER_CLEAN//[.-]/-}"    # 3.6 → 3-6, 3.5-ea.2 → 3-5-ea-2
BRANCH_VAR="${RHOAI_VER_CLEAN//-ea./-ea-}"  # 3.5-ea.2 → 3.5-ea-2
BRANCH_NAME="rhoai-${BRANCH_VAR}"
RHOAI_MINOR_VERSION="${RHOAI_VER_CLEAN}.0"  # Simple append .0

# Generate component-specific variables
# For main branch: rhoai-36, ocp-419, 3-6, 4-19
RHOAI_VAR="${VERSION_VAR//[.-]/}"      # Remove all dots and dashes: 36, 35ea2
OCP_VAR="${OCP_VERSION_VAR}"           # From parse_ocp_version: 50, 419

# Component name: rhoai-fbc-fragment-rhoai-36-ocp-50-push.yaml
COMPONENT_NAME="rhoai-fbc-fragment-rhoai-${RHOAI_VAR}-ocp-${OCP_VAR}"
PIPELINE_NAME="${COMPONENT_NAME}-on-push"

# Application name: rhoai-fbc-fragment-ocp-50
APP_NAME="rhoai-fbc-fragment-ocp-${OCP_VAR}"

# Output image tag: ocp-5.0-rhoai-3.6
IMAGE_TAG="ocp-${OCP_VERSION_FULL}-rhoai-${RHOAI_VER_CLEAN}"

# Path context: catalog/rhoai-3.6/v5.0
PATH_CONTEXT="catalog/rhoai-${RHOAI_VER_CLEAN}/v${OCP_VERSION_FULL}"

# Build args file: catalog/rhoai-3.6/catalog_build_args.map
BUILD_ARGS_FILE="catalog/rhoai-${RHOAI_VER_CLEAN}/catalog_build_args.map"

# Service account: build-pipeline-rhoai-fbc-fragment-ocp-50
SERVICE_ACCOUNT="build-pipeline-${APP_NAME}"

# CEL expression path: catalog/rhoai-3.6/v5.0/rhods-operator/catalog.yaml
CEL_PATH="${PATH_CONTEXT}/rhods-operator/catalog.yaml"

# Force trigger file: builds/force-trigger-rhoai-3.6.txt
FORCE_TRIGGER="builds/force-trigger-rhoai-${RHOAI_VER_CLEAN}.txt"

# Generate the YAML content
YAML_CONTENT="apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  annotations:
    build.appstudio.openshift.io/repo: https://github.com/red-hat-data-services/RHOAI-Build-Config?rev={{revision}}
    build.appstudio.redhat.com/commit_sha: '{{revision}}'
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    pipelinesascode.tekton.dev/max-keep-runs: '3'
    pipelinesascode.tekton.dev/on-cel-expression: event == \"push\" && target_branch == \"main\" && (\"${CEL_PATH}\".pathChanged() || \"${FORCE_TRIGGER}\".pathChanged())
  labels:
    appstudio.openshift.io/application: ${APP_NAME}
    appstudio.openshift.io/component: ${APP_NAME}
    pipelines.appstudio.openshift.io/type: build
  name: ${PIPELINE_NAME}
  namespace: rhoai-tenant
spec:
  timeouts:
    pipeline: 24h
    tasks: 12h
  params:
  - name: git-url
    value: '{{source_url}}'
  - name: revision
    value: '{{revision}}'
  - name: additional-tags
    value:
    - '${IMAGE_TAG}'
  - name: output-image
    value: quay.io/rhoai/rhoai-fbc-fragment:${IMAGE_TAG}-{{revision}}
  - name: build-platforms
    value:
    - linux/x86_64
    - linux/ppc64le
    - linux/s390x
    - linux/arm64
  - name: dockerfile
    value: Dockerfile
  - name: path-context
    value: ${PATH_CONTEXT}
  - name: build-args-file
    value: ${BUILD_ARGS_FILE}
  - name: skip-checks
    value: false
  - name: build-source-image
    value: true
  - name: build-type
    value: \"stage\"   # Possible values: 'nightly', 'stage', 'ci'
  - name: rhoai-version
    value: \"${RHOAI_MINOR_VERSION}\"
  - name: ocp-version
    value: \"${OCP_VERSION_FULL}\"
  - name: fbc-pipeline-branch
    value: \"${BRANCH_NAME}\"
  pipelineRef:
    resolver: git
    params:
    - name: url
      value: https://github.com/red-hat-data-services/konflux-central.git
    - name: revision
      value: \"\$(params.fbc-pipeline-branch)\"
    - name: pathInRepo
      value: pipelines/fbc-fragment-build.yaml
  taskRunTemplate:
    serviceAccountName: ${SERVICE_ACCOUNT}
  workspaces:
  - name: git-auth
    secret:
      secretName: '{{ git_auth_secret }}'
status: {}"

# Output
if [[ "$DRY_RUN" == true ]]; then
  echo "$YAML_CONTENT"
else
  echo "$YAML_CONTENT" > "$OUTPUT_FILE"
  echo "Generated pipeline: $OUTPUT_FILE"
fi
