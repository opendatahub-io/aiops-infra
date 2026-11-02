#!/usr/bin/env bash
# Parse a canonical RHOAI version string (x.y or x.y-ea-n) and export all derived variables.
#
# Usage:
#   eval "$(bash parse_rhoai_version.sh --version "3.4" [--component "my-comp"] [--release-category "Beta"] [--base-rhel-version rhel9|rhel10])"
#
# Exports (via eval):
#   VERSION_X, VERSION_Y, VERSION_N (empty for non-ea)
#   VERSION_VAR         (e.g. v3-4 or v3-4-ea-2)
#   BRANCH_VAR          (e.g. 3.4 or 3.4-ea.2)
#   BRANCH_NAME         (e.g. rhoai-3.4 or rhoai-3.4-ea.2)
#   RHOAI_MINOR_VERSION (e.g. 3.4.0 or 3.4.0-ea.2)
#   CONTENT_STREAM_TAG  (e.g. v3.4 or v3.4-ea.2)
#   REPOSITORY_NAME     (only when --component is provided:
#                         rhoai/<comp><suffix>  for GA/Tech Preview
#                         rhoai-beta/<comp><suffix>  for Beta/DevPreview)

set -euo pipefail

TARGET_RHOAI_VERSION=""
COMPONENT_NAME=""
OS_ARGS=()
RELEASE_CATEGORY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)          TARGET_RHOAI_VERSION="$2"; shift 2 ;;
    --component)        COMPONENT_NAME="$2";        shift 2 ;;
    --release-category) RELEASE_CATEGORY="$2";      shift 2 ;;
    --base-rhel-version) OS_ARGS=(--base-rhel-version "$2"); shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$TARGET_RHOAI_VERSION" ]] && { echo "ERROR: --version is required" >&2; exit 1; }

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OS_VARS=$(bash "$SCRIPT_DIR/resolve_rhel_version.sh" --product-context "RHOAI" "${OS_ARGS[@]}") || exit 1
eval "$OS_VARS"
printf 'BASE_RHEL_VERSION=%q\n' "$BASE_RHEL_VERSION"
printf 'IMAGE_REPO_SUFFIX=%q\n' "$IMAGE_REPO_SUFFIX"

if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"
  VERSION_Y="${BASH_REMATCH[2]}"
  VERSION_N="${BASH_REMATCH[3]}"
  VERSION_VAR="v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"
  BRANCH_VAR="${VERSION_X}.${VERSION_Y}-ea.${VERSION_N}"
  RHOAI_MINOR_VERSION="${VERSION_X}.${VERSION_Y}.0-ea.${VERSION_N}"
  CONTENT_STREAM_TAG="v${VERSION_X}.${VERSION_Y}-ea.${VERSION_N}"
elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"
  VERSION_Y="${BASH_REMATCH[2]}"
  VERSION_N=""
  VERSION_VAR="v${VERSION_X}-${VERSION_Y}"
  BRANCH_VAR="${VERSION_X}.${VERSION_Y}"
  RHOAI_MINOR_VERSION="${VERSION_X}.${VERSION_Y}.0"
  CONTENT_STREAM_TAG="v${VERSION_X}.${VERSION_Y}"
else
  echo "ERROR: Cannot parse version '${TARGET_RHOAI_VERSION}'." >&2
  echo "  Expected canonical form: x.y  OR  x.y-ea-n  (e.g. 3.4 or 3.4-ea-2)" >&2
  exit 1
fi

BRANCH_NAME="rhoai-${BRANCH_VAR}"

printf 'VERSION_X=%q\n'           "$VERSION_X"
printf 'VERSION_Y=%q\n'           "$VERSION_Y"
printf 'VERSION_N=%q\n'           "$VERSION_N"
printf 'VERSION_VAR=%q\n'         "$VERSION_VAR"
printf 'BRANCH_VAR=%q\n'          "$BRANCH_VAR"
printf 'BRANCH_NAME=%q\n'         "$BRANCH_NAME"
printf 'RHOAI_MINOR_VERSION=%q\n' "$RHOAI_MINOR_VERSION"
printf 'CONTENT_STREAM_TAG=%q\n'  "$CONTENT_STREAM_TAG"

if [[ -n "$COMPONENT_NAME" ]]; then
  PRODUCT_LINE="rhoai"
  [[ "$RELEASE_CATEGORY" == "Beta" || "$RELEASE_CATEGORY" == "DevPreview" ]] && PRODUCT_LINE="rhoai-beta"
  REPOSITORY_NAME="${PRODUCT_LINE}/${COMPONENT_NAME}${IMAGE_REPO_SUFFIX}"
  printf 'REPOSITORY_NAME=%q\n' "$REPOSITORY_NAME"
fi
