#!/usr/bin/env bash
# Derives Konflux/OKC pipeline variable names and image tags from component inputs.
# Outputs KEY=VALUE lines for eval in the caller.
set -euo pipefail

COMPONENT_NAME=""
REPO_URL=""
BUILD_TYPE=""
OUTPUT_IMAGE_TAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component-name)   COMPONENT_NAME="$2";   shift 2 ;;
    --repo-url)         REPO_URL="$2";          shift 2 ;;
    --build-type)       BUILD_TYPE="$2";        shift 2 ;;
    --output-image-tag) OUTPUT_IMAGE_TAG="$2";  shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$COMPONENT_NAME" || -z "$REPO_URL" || -z "$BUILD_TYPE" ]]; then
  echo "Usage: derive_okc_pipeline_vars.sh --component-name <name> --repo-url <url> --build-type <CI|RELEASE> [--output-image-tag <tag>]" >&2
  exit 1
fi

if [[ "$COMPONENT_NAME" == *-ci ]]; then
  KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"
else
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"
fi

REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"

PUSH_RUN_NAME="${COMPONENT_NAME}-on-push"
PR_RUN_NAME="${COMPONENT_NAME}-on-pull-request"
PUSH_YAML_FILE="${COMPONENT_NAME}-push.yaml"
PR_YAML_FILE="${COMPONENT_NAME}-pull-request.yaml"
SERVICE_ACCOUNT_NAME="build-pipeline-${KONFLUX_COMPONENT_NAME}"

case "${BUILD_TYPE^^}" in
  CI)
    PUSH_OUTPUT_IMAGE_TAG="odh-stable"
    PR_OUTPUT_IMAGE_TAG="odh-pr"
    ;;
  RELEASE)
    if [[ -z "$OUTPUT_IMAGE_TAG" ]]; then
      echo "ERROR: BUILD_TYPE is RELEASE but --output-image-tag is not set." >&2
      echo "  Add 'output_image_tag: <tag>' under inputs: in component_onboarding_details.yaml and re-run." >&2
      exit 1
    fi
    PUSH_OUTPUT_IMAGE_TAG="$OUTPUT_IMAGE_TAG"
    PR_OUTPUT_IMAGE_TAG="$OUTPUT_IMAGE_TAG"
    ;;
  *)
    echo "ERROR: Unknown BUILD_TYPE '${BUILD_TYPE}'. Expected 'CI' or 'RELEASE'." >&2
    exit 1
    ;;
esac

echo "KONFLUX_COMPONENT_NAME=${KONFLUX_COMPONENT_NAME}"
echo "REPO_NAME=${REPO_NAME}"
echo "PUSH_RUN_NAME=${PUSH_RUN_NAME}"
echo "PR_RUN_NAME=${PR_RUN_NAME}"
echo "PUSH_YAML_FILE=${PUSH_YAML_FILE}"
echo "PR_YAML_FILE=${PR_YAML_FILE}"
echo "SERVICE_ACCOUNT_NAME=${SERVICE_ACCOUNT_NAME}"
echo "PUSH_OUTPUT_IMAGE_TAG=${PUSH_OUTPUT_IMAGE_TAG}"
echo "PR_OUTPUT_IMAGE_TAG=${PR_OUTPUT_IMAGE_TAG}"
