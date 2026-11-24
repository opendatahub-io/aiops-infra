#!/usr/bin/env bash
# Generate ocp-{version}.yaml file for Konflux application and component.
# This creates the Konflux Application and Component resources for a new OCP version.
#
# Usage:
#   bash generate_konflux_app_yaml.sh \
#     --ocp-version 5.0 \
#     --output-file /path/to/ocp-50.yaml
#
# Options:
#   --ocp-version VER     OCP version (required)
#   --output-file FILE    Output YAML file path (required)
#   --dry-run             Print to stdout instead of writing file

set -euo pipefail

OCP_VERSION=""
OUTPUT_FILE=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ocp-version)   OCP_VERSION="$2"; shift 2 ;;
    --output-file)   OUTPUT_FILE="$2"; shift 2 ;;
    --dry-run)       DRY_RUN=true; shift ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --ocp-version is required" >&2
  exit 1
}

[[ -z "$OUTPUT_FILE" && "$DRY_RUN" == false ]] && {
  echo "ERROR: --output-file is required (unless --dry-run)" >&2
  exit 1
}

# Parse OCP version
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
eval "$(bash "$SCRIPT_DIR/parse_ocp_version.sh" --version "$OCP_VERSION")"

# Generate names
# OCP 5.0 → ocp-50, OCP 4.19 → ocp-419
APP_NAME="rhoai-fbc-fragment-ocp-${OCP_VERSION_VAR}"
COMPONENT_NAME="${APP_NAME}"
NAMESPACE="rhoai-tenant"

# Generate the YAML content
# Based on existing ocp-418.yaml, ocp-419.yaml patterns
YAML_CONTENT="---
apiVersion: appstudio.redhat.com/v1alpha1
kind: Application
metadata:
  name: ${APP_NAME}
  namespace: ${NAMESPACE}
spec:
  displayName: ${APP_NAME}
---
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  name: ${APP_NAME}
  namespace: ${NAMESPACE}
spec:
  application: ${APP_NAME}
  componentName: ${APP_NAME}
  source:
    git:
      url: https://github.com/red-hat-data-services/RHOAI-Build-Config
      context: ./
      dockerfileUrl: Dockerfile
      revision: main"

# Output
if [[ "$DRY_RUN" == true ]]; then
  echo "$YAML_CONTENT"
else
  echo "$YAML_CONTENT" > "$OUTPUT_FILE"
  echo "Generated Konflux app YAML: $OUTPUT_FILE"
fi
