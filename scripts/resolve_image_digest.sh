#!/usr/bin/env bash
# Usage: DIGEST=$(bash resolve_image_digest.sh --image "quay.io/org/image:tag")
# Prints the sha256 digest on stdout, or exits 1 if the image is not found.
set -euo pipefail

IMAGE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$IMAGE" ]]; then
  echo "ERROR: --image is required" >&2
  exit 1
fi

if ! command -v skopeo &>/dev/null; then
  echo "ERROR: skopeo is not installed. Install with: brew install skopeo" >&2
  exit 1
fi

INSPECT_OUTPUT=$(skopeo inspect --format '{{.Digest}}' "docker://${IMAGE}" 2>/tmp/skopeo_err) || {
  err=$(<"/tmp/skopeo_err")
  if echo "$err" | grep -qiE "not found|does not exist|manifest unknown|unauthorized"; then
    echo "ERROR: Image not found: $IMAGE" >&2
    echo "  The image may not have been pushed yet. Use a placeholder digest if needed." >&2
    exit 1
  fi
  echo "ERROR: skopeo inspect failed: $err" >&2
  exit 1
}

echo "$INSPECT_OUTPUT"
