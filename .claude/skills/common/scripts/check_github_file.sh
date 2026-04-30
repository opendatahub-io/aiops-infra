#!/usr/bin/env bash
# Usage: check_github_file.sh --repo-path "org/repo" --file-path "path/to/file"
#                              [--ref <ref>] [--output <file>] [--grep <pattern>]
#
# Exit codes:
#   0  file exists (and pattern found, if --grep was given)
#   1  file not found (HTTP 404)  OR  file found but --grep pattern not matched
#   2  API or authentication error
#
# --grep PATTERN: fetch the file content and grep for PATTERN (fixed string).
#   Exit 0 if found, exit 1 if not found, exit 2 on API error.
set -euo pipefail

REPO_PATH=""
FILE_PATH=""
REF="main"
OUTPUT=""
GREP_PATTERN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-path)  REPO_PATH="$2";      shift 2 ;;
    --file-path)  FILE_PATH="$2";      shift 2 ;;
    --ref)        REF="$2";            shift 2 ;;
    --output)     OUTPUT="$2";         shift 2 ;;
    --grep)       GREP_PATTERN="$2";   shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for required in REPO_PATH FILE_PATH; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 2
  fi
done

GITHUB_TOKEN="${GITHUB_TOKEN:-}"
AUTH_HEADER=""
[[ -n "$GITHUB_TOKEN" ]] && AUTH_HEADER="Authorization: Bearer ${GITHUB_TOKEN}"

ENCODED_PATH=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${FILE_PATH}', safe='/'))")
API_URL="https://api.github.com/repos/${REPO_PATH}/contents/${ENCODED_PATH}?ref=${REF}"

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
  ${AUTH_HEADER:+-H "$AUTH_HEADER"} \
  -H "Accept: application/vnd.github.v3+json" \
  "$API_URL")

if [[ "$HTTP_CODE" == "404" ]]; then
  exit 1
elif [[ "$HTTP_CODE" != "200" ]]; then
  echo "ERROR: GitHub API returned HTTP $HTTP_CODE for $API_URL" >&2
  cat "$TMPFILE" >&2
  exit 2
fi

# Decode base64 content (GitHub API wraps file content in base64)
CONTENT=$(python3 -c "
import json, base64, sys
with open('$TMPFILE') as f:
    data = json.load(f)
print(base64.b64decode(data['content']).decode('utf-8'))
")

# Write to --output if requested
if [[ -n "$OUTPUT" ]]; then
  printf '%s' "$CONTENT" > "$OUTPUT"
fi

# Apply --grep if requested
if [[ -n "$GREP_PATTERN" ]]; then
  echo "$CONTENT" | grep -qF "$GREP_PATTERN" && exit 0 || exit 1
fi

exit 0
