#!/usr/bin/env bash
# Auto-detect the base image registry path for a given OCP version.
# This script verifies the base image exists in the Red Hat registry.
#
# Usage:
#   bash detect_ocp_base_image.sh --version "5.0"
#   bash detect_ocp_base_image.sh --version "4.19" --verify
#
# Options:
#   --version VERSION   OCP version to check (required)
#   --verify            Verify the image exists using skopeo (optional)
#
# Outputs:
#   Prints the full base image URL to stdout
#   Returns 0 if image is valid (or verification skipped)
#   Returns 1 if image doesn't exist (when --verify is used)

set -euo pipefail

OCP_VERSION=""
VERIFY_IMAGE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) OCP_VERSION="$2"; shift 2 ;;
    --verify)  VERIFY_IMAGE=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --version is required" >&2
  echo "  Usage: detect_ocp_base_image.sh --version <version> [--verify]" >&2
  exit 1
}

# Use parse_ocp_version.sh to get standardized variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Output the base image URL
echo "$OCP_BASE_IMAGE"

# Optionally verify the image exists
if [[ "$VERIFY_IMAGE" == true ]]; then
  if ! command -v skopeo &>/dev/null; then
    echo "WARNING: skopeo not found, skipping image verification" >&2
    exit 0
  fi

  echo "Verifying image exists: $OCP_BASE_IMAGE" >&2

  if skopeo inspect "docker://$OCP_BASE_IMAGE" &>/dev/null; then
    echo "✓ Image verified: $OCP_BASE_IMAGE" >&2
  else
    echo "ERROR: Image not found: $OCP_BASE_IMAGE" >&2
    echo "  The base image may not exist in the Red Hat registry yet." >&2
    echo "  Check https://catalog.redhat.com/software/containers/search" >&2
    exit 1
  fi
fi
