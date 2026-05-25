#!/usr/bin/env bash
# Detect whether a GitHub repo is a fork and output the upstream (parent) URL.
#
# Usage:
#   eval "$(bash detect_repo_upstream.sh --repo-url "https://github.com/owner/repo.git" \
#     [--github-token "$GITHUB_TOKEN"])"
#
# Exports (via eval): UPSTREAM_REPO_URL
# If the repo is not a fork, UPSTREAM_REPO_URL equals the repo URL (without .git).
# Summary is printed to stderr.

set -euo pipefail

REPO_URL=""
GH_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)     REPO_URL="$2";  shift 2 ;;
    --github-token) GH_TOKEN="$2";  shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$REPO_URL" ]] && { echo "ERROR: --repo-url is required" >&2; exit 1; }

GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
[[ -z "$GH_TOKEN" ]] && { echo "ERROR: GITHUB_TOKEN is not set" >&2; exit 1; }

REPO_SLUG=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')

GH_REPO_INFO=$(curl -s \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO_SLUG}")

IS_FORK=$(echo "$GH_REPO_INFO" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(str(d.get('fork',False)).lower())" 2>/dev/null \
  || echo "false")

if [[ "$IS_FORK" == "true" ]]; then
  UPSTREAM_REPO_URL=$(echo "$GH_REPO_INFO" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d['parent']['html_url'])" 2>/dev/null || echo "")
  if [[ -z "$UPSTREAM_REPO_URL" ]]; then
    echo "WARN: Could not extract upstream URL — falling back to repo URL." >&2
    UPSTREAM_REPO_URL="${REPO_URL%.git}"
  else
    echo "  Repo is a fork — upstream: $UPSTREAM_REPO_URL" >&2
  fi
else
  UPSTREAM_REPO_URL="${REPO_URL%.git}"
  echo "  Repo is not a fork — using repo_url as upstream." >&2
fi

printf 'UPSTREAM_REPO_URL=%q\n' "$UPSTREAM_REPO_URL"
