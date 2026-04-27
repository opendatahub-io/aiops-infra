#!/usr/bin/env bash
# Derives Quay org, relatedImages entry name, and stable image reference for bundle-patch.yaml.
# Outputs KEY=VALUE lines for eval in the caller.
set -euo pipefail

COMPONENT_NAME=""
PRODUCT_CONTEXT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component-name)  COMPONENT_NAME="$2";  shift 2 ;;
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$COMPONENT_NAME" || -z "$PRODUCT_CONTEXT" ]]; then
  echo "Usage: derive_bundle_vars.sh --component-name <name> --product-context <ODH|RHOAI>" >&2
  exit 1
fi

case "${PRODUCT_CONTEXT^^}" in
  ODH)   QUAY_ORG="opendatahub" ;;
  RHOAI) QUAY_ORG="rhoai" ;;
  *)
    echo "ERROR: Unknown PRODUCT_CONTEXT '${PRODUCT_CONTEXT}'. Expected 'ODH' or 'RHOAI'." >&2
    exit 1
    ;;
esac

RELATED_IMAGE_NAME="RELATED_IMAGE_$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_IMAGE"
STABLE_IMAGE="quay.io/${QUAY_ORG}/${COMPONENT_NAME}:odh-stable"

echo "QUAY_ORG=${QUAY_ORG}"
echo "RELATED_IMAGE_NAME=${RELATED_IMAGE_NAME}"
echo "STABLE_IMAGE=${STABLE_IMAGE}"
