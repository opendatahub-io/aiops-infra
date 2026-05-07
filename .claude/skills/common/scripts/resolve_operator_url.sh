#!/usr/bin/env bash
# Resolve ODH_OPERATOR_URL and ODH_OPERATOR_PATH.
#
# Priority: ODH_OPERATOR_REPO_URL (env override) > product-context default.
#
# Usage:
#   eval "$(bash resolve_operator_url.sh --product-context <ODH|RHOAI>)"
#
# Env var:
#   ODH_OPERATOR_REPO_URL  – if set, takes priority over the product-context default.
#
# Exports (via eval):
#   ODH_OPERATOR_URL   – full clone URL (e.g. https://github.com/…/opendatahub-operator.git)
#   ODH_OPERATOR_PATH  – owner/repo slug for GitHub API calls

set -euo pipefail

PRODUCT_CONTEXT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PRODUCT_CONTEXT" ]] && {
  echo "ERROR: --product-context is required (ODH or RHOAI)" >&2; exit 1
}

if [[ -n "${ODH_OPERATOR_REPO_URL:-}" ]]; then
  ODH_OPERATOR_URL="$ODH_OPERATOR_REPO_URL"
  echo "ODH_OPERATOR_REPO_URL override detected: $ODH_OPERATOR_URL" >&2
elif [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  ODH_OPERATOR_URL="https://github.com/opendatahub-io/opendatahub-operator.git"
  echo "ODH_OPERATOR_URL derived from product_context (ODH): $ODH_OPERATOR_URL" >&2
elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  ODH_OPERATOR_URL="https://github.com/red-hat-data-services/rhods-operator.git"
  echo "ODH_OPERATOR_URL derived from product_context (RHOAI): $ODH_OPERATOR_URL" >&2
else
  echo "ERROR: Unrecognised product_context '$PRODUCT_CONTEXT'. Expected 'ODH' or 'RHOAI'." >&2
  exit 1
fi

ODH_OPERATOR_PATH=$(echo "$ODH_OPERATOR_URL" | sed 's|https://github.com/||;s|\.git$||')
echo "ODH_OPERATOR_PATH: $ODH_OPERATOR_PATH" >&2

printf 'ODH_OPERATOR_URL=%q\n'  "$ODH_OPERATOR_URL"
printf 'ODH_OPERATOR_PATH=%q\n' "$ODH_OPERATOR_PATH"
