#!/usr/bin/env bash
# Parse an OCP version string and export all derived variables.
#
# Usage:
#   eval "$(bash parse_ocp_version.sh --version "5.0")"
#   eval "$(bash parse_ocp_version.sh --version "4.19")"
#
# Exports (via stdout for eval):
#   OCP_VERSION_MAJOR        (e.g. 5, 4)
#   OCP_VERSION_MINOR        (e.g. 0, 19)
#   OCP_VERSION_DOTTED       (e.g. "v5.0", "v4.19")
#   OCP_VERSION_VAR          (e.g. "50", "419" - for filenames/labels)
#   OCP_VERSION_DASHED       (e.g. "5-0", "4-19" - for branch names)
#   OCP_BASE_IMAGE_REGISTRY  (e.g. "openshift5", "openshift4")
#   OCP_BASE_IMAGE           (full base image URL)
#
# Examples:
#   Input: "5.0"  → OCP_VERSION_MAJOR=5, OCP_VERSION_MINOR=0, OCP_VERSION_VAR="50"
#   Input: "4.19" → OCP_VERSION_MAJOR=4, OCP_VERSION_MINOR=19, OCP_VERSION_VAR="419"

set -euo pipefail

OCP_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) OCP_VERSION="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$OCP_VERSION" ]] && {
  echo "ERROR: --version is required" >&2
  echo "  Usage: parse_ocp_version.sh --version <version>" >&2
  echo "  Example: parse_ocp_version.sh --version 5.0" >&2
  exit 1
}

# Parse version string: expect format "X.Y" (e.g., "5.0", "4.19")
if [[ "$OCP_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  OCP_VERSION_MAJOR="${BASH_REMATCH[1]}"
  OCP_VERSION_MINOR="${BASH_REMATCH[2]}"
elif [[ "$OCP_VERSION" =~ ^v([0-9]+)\.([0-9]+)$ ]]; then
  # Also accept "v5.0" format
  OCP_VERSION_MAJOR="${BASH_REMATCH[1]}"
  OCP_VERSION_MINOR="${BASH_REMATCH[2]}"
else
  echo "ERROR: Cannot parse OCP version '${OCP_VERSION}'." >&2
  echo "  Expected format: X.Y  (e.g., 5.0, 4.19)" >&2
  echo "  Alternative format: vX.Y  (e.g., v5.0, v4.19)" >&2
  exit 1
fi

# Derive computed variables
OCP_VERSION_FULL="${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}"
OCP_VERSION_DOTTED="v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}"
OCP_VERSION_VAR="${OCP_VERSION_MAJOR}${OCP_VERSION_MINOR}"
OCP_VERSION_DASHED="${OCP_VERSION_MAJOR}-${OCP_VERSION_MINOR}"

# Determine base image registry path based on major version
# OCP 5.x uses openshift5, OCP 4.x uses openshift4
if [[ "$OCP_VERSION_MAJOR" == "5" ]]; then
  OCP_BASE_IMAGE_REGISTRY="openshift5"
elif [[ "$OCP_VERSION_MAJOR" == "4" ]]; then
  OCP_BASE_IMAGE_REGISTRY="openshift4"
else
  echo "ERROR: Unsupported OCP major version: ${OCP_VERSION_MAJOR}" >&2
  echo "  Only OCP 4.x and 5.x are supported" >&2
  exit 1
fi

# Construct full base image URL
OCP_BASE_IMAGE="registry.redhat.io/${OCP_BASE_IMAGE_REGISTRY}/ose-operator-registry-rhel9:v${OCP_VERSION_MAJOR}.${OCP_VERSION_MINOR}"

# Export all variables for eval
printf 'OCP_VERSION_MAJOR=%q\n'       "$OCP_VERSION_MAJOR"
printf 'OCP_VERSION_MINOR=%q\n'       "$OCP_VERSION_MINOR"
printf 'OCP_VERSION_FULL=%q\n'        "$OCP_VERSION_FULL"
printf 'OCP_VERSION_DOTTED=%q\n'      "$OCP_VERSION_DOTTED"
printf 'OCP_VERSION_VAR=%q\n'         "$OCP_VERSION_VAR"
printf 'OCP_VERSION_DASHED=%q\n'      "$OCP_VERSION_DASHED"
printf 'OCP_BASE_IMAGE_REGISTRY=%q\n' "$OCP_BASE_IMAGE_REGISTRY"
printf 'OCP_BASE_IMAGE=%q\n'          "$OCP_BASE_IMAGE"
