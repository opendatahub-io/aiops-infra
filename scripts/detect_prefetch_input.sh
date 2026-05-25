#!/usr/bin/env bash
# Detect Konflux prefetch-input type by inspecting a GitHub repo root for dependency files.
#
# Usage:
#   eval "$(bash detect_prefetch_input.sh \
#     --repo-url "https://github.com/owner/repo.git" \
#     [--context-path "."] \
#     [--github-token "$GITHUB_TOKEN"])"
#
# Exports (via eval): PREFETCH_INPUT (JSON array string)
# Falls back to "[]" when the repo cannot be fetched or no known files are found.
# Summary is printed to stderr.

set -euo pipefail

REPO_URL=""
CONTEXT_PATH="."
GH_TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)     REPO_URL="$2";      shift 2 ;;
    --context-path) CONTEXT_PATH="$2";  shift 2 ;;
    --github-token) GH_TOKEN="$2";      shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$REPO_URL" ]] && { echo "ERROR: --repo-url is required" >&2; exit 1; }

GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

# Normalize context path
if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CTX_PATH="."
else
  CTX_PATH="$CONTEXT_PATH"
fi

PREFETCH_INPUT="[]"

if [[ -n "$GH_TOKEN" ]]; then
  REPO_SLUG=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')
  ROOT_CONTENTS=$(curl -s \
    -H "Authorization: token $GH_TOKEN" \
    "https://api.github.com/repos/${REPO_SLUG}/contents/" 2>/dev/null || echo "")

  if [[ -n "$ROOT_CONTENTS" ]]; then
    FILE_NAMES=$(echo "$ROOT_CONTENTS" | python3 -c \
      "import sys,json; [print(f['name']) for f in json.load(sys.stdin) if f.get('type')=='file']" \
      2>/dev/null || echo "")

    if echo "$FILE_NAMES" | grep -qx "go.mod"; then
      PREFETCH_INPUT="[{\"type\": \"gomod\", \"path\": \"${CTX_PATH}\"}]"
    elif echo "$FILE_NAMES" | grep -qx "requirements.txt"; then
      PREFETCH_INPUT="[{\"type\": \"pip\", \"path\": \"requirements.txt\"}]"
    elif echo "$FILE_NAMES" | grep -qx "package.json"; then
      PREFETCH_INPUT="[{\"type\": \"npm\", \"path\": \"${CTX_PATH}\"}]"
    elif echo "$FILE_NAMES" | grep -qx "Gemfile"; then
      PREFETCH_INPUT="[{\"type\": \"bundler\", \"path\": \"${CTX_PATH}\"}]"
    fi
  else
    echo "[detect_prefetch_input] WARN: Could not fetch repo contents via GitHub API." >&2
  fi
else
  echo "[detect_prefetch_input] WARN: GITHUB_TOKEN not set — using empty prefetch-input." >&2
fi

echo "[detect_prefetch_input] PREFETCH_INPUT=${PREFETCH_INPUT}" >&2
printf 'PREFETCH_INPUT=%q\n' "$PREFETCH_INPUT"
