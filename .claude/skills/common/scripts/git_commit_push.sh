#!/usr/bin/env bash
# Usage: git_commit_push.sh --clone-dir <dir> --files "<f1> <f2>" --message "<msg>" --branch <branch> [--remote <remote>]
# Stages files, commits, and pushes. Handles shallow-clone and non-fast-forward retries.
set -euo pipefail

CLONE_DIR=""
FILES=()
MESSAGE=""
BRANCH=""
REMOTE="origin"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clone-dir) CLONE_DIR="$2";             shift 2 ;;
    --files)     read -ra FILES <<< "$2";    shift 2 ;;
    --message)   MESSAGE="$2";               shift 2 ;;
    --branch)    BRANCH="$2";                shift 2 ;;
    --remote)    REMOTE="$2";                shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for required in CLONE_DIR MESSAGE BRANCH; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 1
  fi
done

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "ERROR: --files is required" >&2
  exit 1
fi

cd "$CLONE_DIR"

# Ensure we're on the right branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH"
fi

# Stage specified files
for f in "${FILES[@]}"; do
  git add "$f"
done

# Commit (skip if nothing staged)
if git diff --cached --quiet; then
  echo "Nothing to commit — working tree clean."
  exit 0
fi

git commit -m "$MESSAGE"

# Push with retry logic
_push() {
  git push "$REMOTE" "$BRANCH" "$@"
}

if ! _push 2>/tmp/git_push_err; then
  err=$(<"/tmp/git_push_err")

  if echo "$err" | grep -q "shallow"; then
    echo "Shallow clone detected — fetching full history..." >&2
    git fetch --unshallow
    _push
  elif echo "$err" | grep -qE "non-fast-forward|rejected"; then
    echo "Non-fast-forward detected — retrying with --force-with-lease..." >&2
    _push --force-with-lease
  else
    echo "$err" >&2
    exit 1
  fi
fi

echo "Pushed branch '$BRANCH' to '$REMOTE'."
