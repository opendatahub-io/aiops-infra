#!/usr/bin/env bash
# Create or update a catalog/v{ocp}/ directory by copying from the latest existing version
# and updating the Dockerfile to use the correct OCP base image.
#
# Usage:
#   bash update_catalog_directory.sh --catalog-dir /path/to/catalog \
#     --ocp-version 5.0
#
# Options:
#   --catalog-dir DIR    Path to catalog directory (required)
#   --ocp-version VER    OCP version to create (required)
#   --source-version VER Source OCP version to copy from (optional, auto-detected)
#   --dry-run            Show what would be done without making changes
#
# Returns:
#   0 - Success (directory created/updated)
#   1 - Error
#   2 - Directory already exists and is up-to-date

set -euo pipefail

CATALOG_DIR=""
OCP_VERSION=""
SOURCE_VERSION=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --catalog-dir)     CATALOG_DIR="$2"; shift 2 ;;
    --ocp-version)     OCP_VERSION="$2"; shift 2 ;;
    --source-version)  SOURCE_VERSION="$2"; shift 2 ;;
    --dry-run)         DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CATALOG_DIR" ]] && {
  echo "ERROR: --catalog-dir is required" >&2
  exit 1
}

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

[[ ! -d "$CATALOG_DIR" ]] && {
  echo "ERROR: Catalog directory not found: $CATALOG_DIR" >&2
  exit 1
}

# Parse target OCP version
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

TARGET_DIR="$CATALOG_DIR/v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}"
TARGET_DOCKERFILE="$TARGET_DIR/Dockerfile"

# Check if target already exists and has correct base image
if [[ -f "$TARGET_DOCKERFILE" ]]; then
  CURRENT_BASE=$(grep -m1 '^FROM ' "$TARGET_DOCKERFILE" | awk '{print $2}')
  if [[ "$CURRENT_BASE" == "$OCP_BASE_IMAGE" ]]; then
    echo "Catalog directory v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR} already exists with correct base image"
    exit 2
  fi
fi

# Auto-detect source version if not provided
if [[ -z "$SOURCE_VERSION" ]]; then
  SOURCE_VERSION=$(bash "$SCRIPT_DIR/find_latest_ocp_version.sh" --catalog-dir "$CATALOG_DIR" --format version)
  echo "Auto-detected source version: $SOURCE_VERSION"
fi

SOURCE_DIR="$CATALOG_DIR/v${SOURCE_VERSION}"

[[ ! -d "$SOURCE_DIR" ]] && {
  echo "ERROR: Source directory not found: $SOURCE_DIR" >&2
  exit 1
}

echo "Creating catalog directory for OCP v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}..."
echo "  Source: v${SOURCE_VERSION}"
echo "  Target: v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}"
echo "  Base image: $OCP_BASE_IMAGE"

if [[ "$DRY_RUN" == true ]]; then
  echo "[DRY RUN] Would execute:"
  echo "  1. Copy $SOURCE_DIR → $TARGET_DIR"
  echo "  2. Update Dockerfile FROM line to: $OCP_BASE_IMAGE"
  exit 0
fi

# Create target directory by copying source
if [[ -d "$TARGET_DIR" ]]; then
  echo "  Directory exists, updating..."
else
  echo "  Copying from v${SOURCE_VERSION}..."
  cp -r "$SOURCE_DIR" "$TARGET_DIR"
fi

# Update Dockerfile base image
if [[ -f "$TARGET_DOCKERFILE" ]]; then
  echo "  Updating Dockerfile..."

  # Get the current FROM line
  CURRENT_FROM=$(grep -m1 '^FROM ' "$TARGET_DOCKERFILE")

  # Replace with new base image (preserve any build stage name after FROM)
  if [[ "$CURRENT_FROM" =~ ^FROM[[:space:]]+[^[:space:]]+[[:space:]]+AS[[:space:]]+([^[:space:]]+) ]]; then
    # Has AS clause: FROM image AS stage-name
    STAGE_NAME="${BASH_REMATCH[1]}"
    NEW_FROM="FROM $OCP_BASE_IMAGE AS $STAGE_NAME"
  else
    # No AS clause: FROM image
    NEW_FROM="FROM $OCP_BASE_IMAGE"
  fi

  # Use sed to replace the FROM line (macOS and Linux compatible)
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "1,/^FROM /s|^FROM .*|$NEW_FROM|" "$TARGET_DOCKERFILE"
  else
    sed -i "1,/^FROM /s|^FROM .*|$NEW_FROM|" "$TARGET_DOCKERFILE"
  fi

  echo "  ✓ Updated FROM $CURRENT_FROM"
  echo "           → $NEW_FROM"
else
  echo "ERROR: Dockerfile not found: $TARGET_DOCKERFILE" >&2
  exit 1
fi

echo "Successfully created catalog directory for OCP v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}"
