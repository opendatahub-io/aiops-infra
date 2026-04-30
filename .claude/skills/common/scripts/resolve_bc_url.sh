#!/usr/bin/env bash
# Usage: eval "$(bash resolve_bc_url.sh --product-context <ODH|RHOAI> [--override <URL>])"
# Resolves the build-config repo URL (BC_URL) and derives BC_PATH.
#
# Resolution order:
#   1. --override URL  (e.g. from BUILD_CONFIG_REPO_URL env var)
#   2. Default derived from --product-context:
#        ODH   → https://github.com/opendatahub-io/ODH-Build-Config.git
#        RHOAI → https://github.com/red-hat-data-services/RHOAI-Build-Config.git
#
# Outputs (via eval): BC_URL, BC_PATH
set -euo pipefail

PRODUCT_CONTEXT=""
OVERRIDE_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --product-context) PRODUCT_CONTEXT="${2^^}"; shift 2 ;;
    --override)        OVERRIDE_URL="$2";        shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -n "$OVERRIDE_URL" ]]; then
  BC_URL="$OVERRIDE_URL"
  echo "[resolve_bc_url] Using override: $BC_URL" >&2
else
  [[ -z "$PRODUCT_CONTEXT" ]] && { echo "ERROR: --product-context is required when --override is not set" >&2; exit 1; }
  case "$PRODUCT_CONTEXT" in
    ODH)   BC_URL="https://github.com/opendatahub-io/ODH-Build-Config.git" ;;
    RHOAI) BC_URL="https://github.com/red-hat-data-services/RHOAI-Build-Config.git" ;;
    *) echo "ERROR: Unknown product_context '$PRODUCT_CONTEXT'. Expected 'ODH' or 'RHOAI'." >&2; exit 1 ;;
  esac
  echo "[resolve_bc_url] Derived from product_context ($PRODUCT_CONTEXT): $BC_URL" >&2
fi

BC_PATH=$(echo "$BC_URL" | sed 's|https://github.com/||;s|\.git$||')

printf 'BC_URL=%q\n'  "$BC_URL"
printf 'BC_PATH=%q\n' "$BC_PATH"
