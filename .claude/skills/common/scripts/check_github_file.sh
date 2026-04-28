#!/usr/bin/env bash
# Usage: check_github_file.sh --repo-path "org/repo" --file-path "path/to/file" --ref <ref> [--output <file>]
# Exit 0: file exists; Exit 1: file not found (404); Exit 2: API or auth error.
# Optionally writes the decoded file content to --output.
set -euo pipefail

REPO_PATH=""
FILE_PATH=""
REF="main"
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-path)  REPO_PATH="$2";  shift 2 ;;
    --file-path)  FILE_PATH="$2";  shift 2 ;;
    --ref)        REF="$2";        shift 2 ;;
    --output)     OUTPUT="$2";     shift 2 ;;
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
if [[ -n "$GITHUB_TOKEN" ]]; then
  AUTH_HEADER="Authorization: Bearer ${GITHUB_TOKEN}"
fi

ENCODED_PATH=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${FILE_PATH}', safe='/'))")
API_URL="https://api.github.com/repos/${REPO_PATH}/contents/${ENCODED_PATH}?ref=${REF}"

HTTP_CODE=$(curl -s -o /tmp/gh_file_response.json -w "%{http_code}" \
  ${AUTH_HEADER:+-H "$AUTH_HEADER"} \
  -H "Accept: application/vnd.github.v3+json" \
  "$API_URL")

if [[ "$HTTP_CODE" == "200" ]]; then
  if [[ -n "$OUTPUT" ]]; then
    python3 -c "
import json, base64, sys
with open('/tmp/gh_file_response.json') as f:
    data = json.load(f)
content = base64.b64decode(data['content']).decode('utf-8')
with open('$OUTPUT', 'w') as out:
    out.write(content)
"
  fi
  exit 0
elif [[ "$HTTP_CODE" == "404" ]]; then
  exit 1
else
  echo "ERROR: GitHub API returned HTTP $HTTP_CODE for $API_URL" >&2
  cat /tmp/gh_file_response.json >&2
  exit 2
fi
