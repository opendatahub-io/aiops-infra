#!/usr/bin/env bash
# Update config/config.yaml on main branch to add or remove an OCP version.
# This is different from build-config.yaml - config.yaml is on main branch only.
#
# Usage:
#   bash update_config_yaml.sh --config-file /path/to/config.yaml \
#     --ocp-version 5.0 --action onboard
#
# Options:
#   --config-file FILE   Path to config.yaml (required)
#   --ocp-version VER    OCP version to add/remove (required)
#   --action ACTION      onboard or offboard (required)
#   --dry-run            Show changes without modifying file
#
# Returns:
#   0 - Success
#   1 - Error
#   2 - No changes needed (already present/absent)

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

# Parse OCP version
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

VERSION_NAME="${OCP_VERSION_DOTTED#v}"  # Remove 'v' prefix

# Check current state
# Note: config.yaml structure may vary by repository
# Assuming similar structure to build-config.yaml
EXISTS=$(yq eval ".supported-ocp-versions[] | select(. == \"v${VERSION_NAME}\")" "$CONFIG_FILE" 2>/dev/null || echo "")

if [[ "$ACTION" == "onboard" ]]; then
  if [[ -n "$EXISTS" ]]; then
    echo "OCP version v${VERSION_NAME} already exists in config.yaml"
    exit 2
  fi

  echo "Adding OCP v${VERSION_NAME} to config.yaml..."

  if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Would add v${VERSION_NAME} to supported-ocp-versions"
    exit 0
  fi

  # Add to supported-ocp-versions array
  yq eval -i ".supported-ocp-versions += [\"v${VERSION_NAME}\"]" "$CONFIG_FILE"
  echo "  ✓ Added v${VERSION_NAME}"

elif [[ "$ACTION" == "offboard" ]]; then
  if [[ -z "$EXISTS" ]]; then
    echo "OCP version v${VERSION_NAME} not found in config.yaml"
    exit 2
  fi

  echo "Removing OCP v${VERSION_NAME} from config.yaml..."

  if [[ "$DRY_RUN" == true ]]; then
    echo "[DRY RUN] Would remove v${VERSION_NAME} from supported-ocp-versions"
    exit 0
  fi

  # Remove from supported-ocp-versions array
  yq eval -i "del(.supported-ocp-versions[] | select(. == \"v${VERSION_NAME}\"))" "$CONFIG_FILE"
  echo "  ✓ Removed v${VERSION_NAME}"

else
  echo "ERROR: Invalid action: $ACTION (must be 'onboard' or 'offboard')" >&2
  exit 1
fi

echo "Successfully ${ACTION}ed OCP v${VERSION_NAME} in config.yaml"
