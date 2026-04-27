#!/usr/bin/env bash
# resolve_image_digest.sh — resolves a container image digest via skopeo.
# If the image is not yet published, generates a random placeholder SHA256.
# Stdout: "digest=sha256:abc..." or "digest=placeholder:randomhex"
# Exit 0: real digest found; Exit 1: image not found, placeholder generated.
set -euo pipefail

IMAGE=""

usage() {
  echo "Usage: $0 --image quay.io/org/repo:tag"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$IMAGE" ]] && usage

REAL_DIGEST=$(skopeo inspect --no-creds "docker://${IMAGE}" 2>/dev/null \
  | jq -r '.Digest // ""' 2>/dev/null || echo "")

if [[ -n "$REAL_DIGEST" && "$REAL_DIGEST" == sha256:* ]]; then
  echo "digest=${REAL_DIGEST}"
  exit 0
else
  PLACEHOLDER=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  echo "digest=placeholder:${PLACEHOLDER}"
  exit 1
fi
