#!/usr/bin/env bash
# Usage: eval "$(bash derive_quay_vars.sh --product-context <ODH|RHOAI> --component-name <name> [--base-rhel-version rhelN])"
# Outputs: QUAY_ORG, QUAY_VISIBILITY, QUAY_REPO_URI, BASE_RHEL_VERSION, IMAGE_REPO_SUFFIX
set -euo pipefail

PRODUCT_CONTEXT=""
COMPONENT_NAME=""
OS_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    --component-name)  COMPONENT_NAME="$2";  shift 2 ;;
    --base-rhel-version) OS_ARGS=(--base-rhel-version "$2"); shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$PRODUCT_CONTEXT" || -z "$COMPONENT_NAME" ]]; then
  echo "ERROR: --product-context and --component-name are required" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OS_VARS=$(uv run --script "$SCRIPT_DIR/resolve_rhel_version.py" \
  --product-context "$PRODUCT_CONTEXT" "${OS_ARGS[@]}") || exit 1
eval "$OS_VARS"

case "$PRODUCT_CONTEXT" in
  ODH)
    QUAY_ORG="opendatahub"
    QUAY_VISIBILITY="public"
    QUAY_REPO_URI="quay.io/opendatahub/${COMPONENT_NAME}"
    ;;
  RHOAI)
    QUAY_ORG="rhoai"
    QUAY_VISIBILITY="private"
    QUAY_REPO_URI="quay.io/rhoai/${COMPONENT_NAME}${IMAGE_REPO_SUFFIX}"
    ;;
  *)
    echo "ERROR: Unknown product_context '$PRODUCT_CONTEXT'. Expected 'ODH' or 'RHOAI'." >&2
    exit 1
    ;;
esac

printf 'QUAY_ORG=%q\n'        "$QUAY_ORG"
printf 'QUAY_VISIBILITY=%q\n' "$QUAY_VISIBILITY"
printf 'QUAY_REPO_URI=%q\n'   "$QUAY_REPO_URI"
printf 'BASE_RHEL_VERSION=%q\n' "$BASE_RHEL_VERSION"
printf 'IMAGE_REPO_SUFFIX=%q\n' "$IMAGE_REPO_SUFFIX"
