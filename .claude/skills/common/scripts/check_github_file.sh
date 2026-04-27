#!/usr/bin/env bash
# check_github_file.sh — checks if a file exists in a GitHub repository via
# the Contents API. Downloads the file content to --output if found.
# Exit 0: file found (HTTP 200); Exit 1: not found (HTTP 404); Exit 2: auth/other error.
# Stdout: the HTTP status code.
set -euo pipefail

REPO_PATH=""
FILE_PATH=""
REF="main"
OUTPUT_FILE=""

usage() {
  echo "Usage: $0 --repo-path ORG/REPO --file-path path/to/file --ref REF --output /tmp/file.yaml"
  echo "  Environment: GITHUB_TOKEN (required)"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-path) REPO_PATH="$2"; shift 2 ;;
    --file-path) FILE_PATH="$2"; shift 2 ;;
    --ref)       REF="$2";       shift 2 ;;
    --output)    OUTPUT_FILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$REPO_PATH" || -z "$FILE_PATH" || -z "$OUTPUT_FILE" ]] && usage
[[ -z "${GITHUB_TOKEN:-}" ]] && { echo "ERROR: GITHUB_TOKEN is not set." >&2; exit 2; }

HTTP_STATUS=$(curl -s -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/${REPO_PATH}/contents/${FILE_PATH}?ref=${REF}" \
  -o "$OUTPUT_FILE")

echo "$HTTP_STATUS"

if [[ "$HTTP_STATUS" == "200" ]]; then
  exit 0
elif [[ "$HTTP_STATUS" == "404" ]]; then
  exit 1
else
  echo "ERROR: Unexpected HTTP status $HTTP_STATUS from GitHub API." >&2
  exit 2
fi
