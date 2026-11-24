#!/usr/bin/env bash
# Update config/build-config.yaml to add or remove an OCP version.
# Modifies both the 'build' and 'release' sections.
#
# Usage:
#   bash update_build_config.sh --config-file /path/to/build-config.yaml \
#     --ocp-version 5.0 --action onboard
#
#   bash update_build_config.sh --config-file /path/to/build-config.yaml \
#     --ocp-version 4.17 --action offboard
#
# Options:
#   --config-file FILE   Path to build-config.yaml (required)
#   --ocp-version VER    OCP version to add/remove (required)
#   --action ACTION      onboard or offboard (required)
#   --dry-run            Show changes without modifying file
#
# Returns:
#   0 - Success (changes made or would be made in dry-run)
#   1 - Error
#   2 - No changes needed (version already present/absent)

set -euo pipefail

CONFIG_FILE=""
OCP_VERSION=""
ACTION=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-file) CONFIG_FILE="$2"; shift 2 ;;
    --ocp-version) OCP_VERSION="$2"; shift 2 ;;
    --action)      ACTION="$2"; shift 2 ;;
    --dry-run)     DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$CONFIG_FILE" ]] && {
  echo "ERROR: --config-file is required" >&2
  exit 1
}

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

[[ -z "$ACTION" ]] && {
  echo "ERROR: --action is required (onboard or offboard)" >&2
  exit 1
}

[[ ! -f "$CONFIG_FILE" ]] && {
  echo "ERROR: Config file not found: $CONFIG_FILE" >&2
  exit 1
}

# Validate yq is available
if ! command -v yq &>/dev/null; then
  echo "ERROR: yq is required but not found" >&2
  echo "  Install with: brew install yq" >&2
  exit 1
fi

# Parse OCP version to get variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Determine version string for YAML (v5.0, v4.19, etc.)
VERSION_NAME="${OCP_VERSION_DOTTED#v}"  # Remove 'v' prefix (5.0, 4.19)

# Check if version already exists
BUILD_EXISTS=$(yq eval ".config.\"supported-ocp-versions\".build[] | select(.name == \"v${VERSION_NAME}\") | .name" "$CONFIG_FILE" || echo "")
RELEASE_EXISTS=$(yq eval ".config.\"supported-ocp-versions\".release[] | select(. == \"v${VERSION_NAME}\")" "$CONFIG_FILE" || echo "")

if [[ "$ACTION" == "onboard" ]]; then
  # Check if already present
  if [[ -n "$BUILD_EXISTS" && -n "$RELEASE_EXISTS" ]]; then
    echo "OCP version v${VERSION_NAME} already exists in build-config.yaml"
    exit 2
  fi

  echo "Adding OCP v${VERSION_NAME} to build-config.yaml..."

  if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Would add:"
    echo "  .config.supported-ocp-versions.build[] += {name: \"v${VERSION_NAME}\", base-image: \"${OCP_BASE_IMAGE}\"}"
    echo "  .config.supported-ocp-versions.release[] += \"v${VERSION_NAME}\""
    exit 0
  fi

  # Add to build section (array of objects with name and base-image)
  if [[ -z "$BUILD_EXISTS" ]]; then
    yq eval -i ".config.\"supported-ocp-versions\".build += [{\"name\": \"v${VERSION_NAME}\", \"base-image\": \"${OCP_BASE_IMAGE}\"}]" "$CONFIG_FILE"
    echo "  ✓ Added to build section"
  fi

  # Add to release section (array of strings)
  if [[ -z "$RELEASE_EXISTS" ]]; then
    yq eval -i ".config.\"supported-ocp-versions\".release += [\"v${VERSION_NAME}\"]" "$CONFIG_FILE"
    echo "  ✓ Added to release section"
  fi

  echo "Successfully added OCP v${VERSION_NAME}"

elif [[ "$ACTION" == "offboard" ]]; then
  # Check if present
  if [[ -z "$BUILD_EXISTS" && -z "$RELEASE_EXISTS" ]]; then
    echo "OCP version v${VERSION_NAME} not found in build-config.yaml"
    exit 2
  fi

  echo "Removing OCP v${VERSION_NAME} from build-config.yaml..."

  if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Would remove v${VERSION_NAME} from build and release sections"
    exit 0
  fi

  # Remove from build section
  if [[ -n "$BUILD_EXISTS" ]]; then
    yq eval -i "del(.config.\"supported-ocp-versions\".build[] | select(.name == \"v${VERSION_NAME}\"))" "$CONFIG_FILE"
    echo "  ✓ Removed from build section"
  fi

  # Remove from release section
  if [[ -n "$RELEASE_EXISTS" ]]; then
    yq eval -i "del(.config.\"supported-ocp-versions\".release[] | select(. == \"v${VERSION_NAME}\"))" "$CONFIG_FILE"
    echo "  ✓ Removed from release section"
  fi

  echo "Successfully removed OCP v${VERSION_NAME}"

else
  echo "ERROR: Invalid action: $ACTION (must be 'onboard' or 'offboard')" >&2
  exit 1
fi
