#!/usr/bin/env bash
# Usage: eval "$(bash resolve_bundle_image.sh --component-name <name> --quay-org <org> [--quay-repo <repo>])"
# Computes the relatedImages entry name and value for bundle/bundle-patch.yaml.
#
# --quay-repo defaults to --component-name when not provided.
# For RHOAI components, pass --quay-repo "${COMPONENT_NAME}-rhel9".
#
# Outputs (via eval):
#   RELATED_IMAGE_NAME   e.g. RELATED_IMAGE_ODH_AI_FIRST_DEMO_IMAGE
#   RELATED_IMAGE_VALUE  e.g. quay.io/opendatahub/odh-ai-first-demo@sha256:abc123...
#   USING_PLACEHOLDER    'true' if real digest was not available, 'false' otherwise
set -euo pipefail

COMPONENT_NAME=""
QUAY_ORG=""
QUAY_REPO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component-name) COMPONENT_NAME="$2"; shift 2 ;;
    --quay-org)       QUAY_ORG="$2";       shift 2 ;;
    --quay-repo)      QUAY_REPO="$2";      shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$COMPONENT_NAME" ]] && { echo "ERROR: --component-name is required" >&2; exit 1; }
[[ -z "$QUAY_ORG" ]]       && { echo "ERROR: --quay-org is required" >&2; exit 1; }

# Default quay repo to component name when not explicitly set
[[ -z "$QUAY_REPO" ]] && QUAY_REPO="$COMPONENT_NAME"

# Derive the YAML entry name: uppercase, hyphens → underscores, wrapped in prefix/suffix
RELATED_IMAGE_NAME="RELATED_IMAGE_$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_IMAGE"

# Try to fetch the real digest from Quay
STABLE_IMAGE="quay.io/${QUAY_ORG}/${QUAY_REPO}:odh-stable"
REAL_DIGEST=""

if command -v skopeo &>/dev/null; then
  REAL_DIGEST=$(skopeo inspect --no-creds "docker://${STABLE_IMAGE}" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Digest',''))" \
    2>/dev/null || echo "")
fi

if [[ -n "$REAL_DIGEST" && "$REAL_DIGEST" == sha256:* ]]; then
  RELATED_IMAGE_VALUE="quay.io/${QUAY_ORG}/${QUAY_REPO}@${REAL_DIGEST}"
  USING_PLACEHOLDER="false"
  echo "[resolve_bundle_image] Real digest fetched from Quay: $REAL_DIGEST" >&2
else
  PLACEHOLDER_DIGEST=$(python3 -c 'import secrets; print("sha256:" + secrets.token_hex(32))')
  RELATED_IMAGE_VALUE="quay.io/${QUAY_ORG}/${QUAY_REPO}@${PLACEHOLDER_DIGEST}"
  USING_PLACEHOLDER="true"
  echo "[resolve_bundle_image] WARNING: Image not yet published — using placeholder digest." >&2
  echo "  Update bundle-patch.yaml with the real digest before merging the PR." >&2
fi

printf 'RELATED_IMAGE_NAME=%q\n'  "$RELATED_IMAGE_NAME"
printf 'RELATED_IMAGE_VALUE=%q\n' "$RELATED_IMAGE_VALUE"
printf 'USING_PLACEHOLDER=%q\n'   "$USING_PLACEHOLDER"
