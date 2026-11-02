#!/usr/bin/env bash
# Internal repository naming contract; policy authorization is the caller's responsibility.
# Usage: bash resolve_rhel_version.sh --product-context RHOAI [--base-rhel-version rhel10]
# Emits BASE_RHEL_VERSION (rhel9/rhel10) and IMAGE_REPO_SUFFIX (-rhel9/-rhel10).
# ODH emits empty values and must not supply an OS. Legacy RHOAI defaults to rhel9.
set -euo pipefail
PRODUCT_CONTEXT=""
BASE_RHEL_VERSION=""
OS_PROVIDED=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    --base-rhel-version) BASE_RHEL_VERSION="$2"; OS_PROVIDED=true; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done
case "$PRODUCT_CONTEXT" in
  RHOAI)
    if [[ "$OS_PROVIDED" == false ]]; then BASE_RHEL_VERSION=rhel9; fi
    case "$BASE_RHEL_VERSION" in
      rhel9|rhel10) IMAGE_REPO_SUFFIX="-${BASE_RHEL_VERSION}" ;;
      *) echo "ERROR: base_rhel_version must be rhel9 or rhel10" >&2; exit 1 ;;
    esac ;;
  ODH)
    if [[ "$OS_PROVIDED" == true ]]; then
      echo "ERROR: ODH must not set base_rhel_version" >&2; exit 1
    fi
    IMAGE_REPO_SUFFIX="" ;;
  *) echo "ERROR: product_context must be ODH or RHOAI" >&2; exit 1 ;;
esac
printf 'BASE_RHEL_VERSION=%q\n' "$BASE_RHEL_VERSION"
printf 'IMAGE_REPO_SUFFIX=%q\n' "$IMAGE_REPO_SUFFIX"
