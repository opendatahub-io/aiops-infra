#!/usr/bin/env bash
# Check if a GitHub branch exists; create it from main if missing.
#
# Usage:
#   bash ensure_github_branch.sh \
#     --repo-path "owner/repo" \
#     --branch-name "rhoai-3.4" \
#     [--github-token "$GITHUB_TOKEN"]
#
# Uses GITHUB_TOKEN env var if --github-token is not provided.
# Exit 0: branch exists (or was created). Exit 1: error.

set -euo pipefail

REPO_PATH=""
BRANCH_NAME=""
GH_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-path)    REPO_PATH="$2";    shift 2 ;;
    --branch-name)  BRANCH_NAME="$2";  shift 2 ;;
    --github-token) GH_TOKEN="$2";     shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$REPO_PATH" ]]   && { echo "ERROR: --repo-path is required" >&2; exit 1; }
[[ -z "$BRANCH_NAME" ]] && { echo "ERROR: --branch-name is required" >&2; exit 1; }

GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
[[ -z "$GH_TOKEN" ]] && { echo "ERROR: GITHUB_TOKEN is not set" >&2; exit 1; }

BRANCH_CHECK_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO_PATH}/branches/${BRANCH_NAME}")

if [[ "$BRANCH_CHECK_STATUS" == "200" ]]; then
  echo "Branch '$BRANCH_NAME' already exists in $REPO_PATH."
  exit 0
fi

if [[ "$BRANCH_CHECK_STATUS" != "404" ]]; then
  echo "WARN: Unexpected HTTP $BRANCH_CHECK_STATUS checking branch '$BRANCH_NAME'. Proceeding with creation attempt."
fi

echo "Branch '$BRANCH_NAME' not found. Creating from main..."

MAIN_SHA=$(curl -s \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO_PATH}/git/refs/heads/main" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['object']['sha'])" 2>/dev/null || echo "")

if [[ -z "$MAIN_SHA" ]]; then
  echo "ERROR: Could not resolve SHA for 'main' in $REPO_PATH. Check GITHUB_TOKEN and repo access." >&2
  exit 1
fi

CREATE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO_PATH}/git/refs" \
  -d "{\"ref\": \"refs/heads/${BRANCH_NAME}\", \"sha\": \"${MAIN_SHA}\"}")

if [[ "$CREATE_STATUS" == "201" ]]; then
  echo "Branch '$BRANCH_NAME' created from main (SHA: $MAIN_SHA)."
else
  echo "ERROR: Failed to create branch '$BRANCH_NAME' (HTTP $CREATE_STATUS)." >&2
  exit 1
fi
