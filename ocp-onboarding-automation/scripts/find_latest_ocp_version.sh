#!/usr/bin/env bash
# Find the latest (highest) OCP version in a catalog directory.
# Used to determine which existing OCP directory to copy when creating a new one.
#
# Usage:
#   bash find_latest_ocp_version.sh --catalog-dir /path/to/catalog
#   bash find_latest_ocp_version.sh --catalog-dir /path/to/catalog --format path
#
# Options:
#   --catalog-dir DIR   Path to catalog directory (required)
#   --format FORMAT     Output format: version (default) or path
#
# Output formats:
#   version - Just the version (e.g., "4.22", "5.0")
#   path    - Full directory name (e.g., "v4.22", "v5.0")
#
# Returns:
#   0 - Success, prints the latest version
#   1 - Error (no catalog dir, no OCP versions found)

set -euo pipefail

CATALOG_DIR=""
OUTPUT_FORMAT="version"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --catalog-dir) CATALOG_DIR="$2"; shift 2 ;;
    --format)      OUTPUT_FORMAT="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CATALOG_DIR" ]] && {
  echo "ERROR: --catalog-dir is required" >&2
  echo "  Usage: find_latest_ocp_version.sh --catalog-dir /path/to/catalog" >&2
  exit 1
}

[[ ! -d "$CATALOG_DIR" ]] && {
  echo "ERROR: Catalog directory not found: $CATALOG_DIR" >&2
  exit 1
}

# Find all v{major}.{minor} directories
# Pattern: v4.19, v4.20, v4.21, v4.22, v5.0, etc.
OCP_DIRS=$(find "$CATALOG_DIR" -maxdepth 1 -type d -name 'v[0-9]*.[0-9]*' -exec basename {} \; 2>/dev/null | sort -V || true)

if [[ -z "$OCP_DIRS" ]]; then
  echo "ERROR: No OCP version directories found in $CATALOG_DIR" >&2
  echo "  Expected directories matching pattern: v4.*, v5.*" >&2
  exit 1
fi

# Get the latest version (last in version-sorted list)
LATEST_DIR=$(echo "$OCP_DIRS" | tail -1)
LATEST_VERSION="${LATEST_DIR#v}"

# Output in requested format
case "$OUTPUT_FORMAT" in
  version)
    echo "$LATEST_VERSION"
    ;;
  path)
    echo "$LATEST_DIR"
    ;;
  *)
    echo "ERROR: Unknown format: $OUTPUT_FORMAT" >&2
    echo "  Supported formats: version, path" >&2
    exit 1
    ;;
esac
