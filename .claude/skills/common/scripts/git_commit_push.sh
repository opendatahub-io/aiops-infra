#!/usr/bin/env bash
# Stages files, commits, and pushes to origin. Handles "shallow update not allowed" automatically.
# Usage: git_commit_push.sh --clone-dir <dir> --files <file> [--files <file>...] --message <msg> --branch <branch>
set -uo pipefail

CLONE_DIR=""
FILES=()
MESSAGE=""
BRANCH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clone-dir) CLONE_DIR="$2"; shift 2 ;;
    --files)     FILES+=("$2"); shift 2 ;;
    --message)   MESSAGE="$2"; shift 2 ;;
    --branch)    BRANCH="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$CLONE_DIR" || ${#FILES[@]} -eq 0 || -z "$MESSAGE" || -z "$BRANCH" ]]; then
  echo "Usage: git_commit_push.sh --clone-dir <dir> --files <file> [--files <file>...] --message <msg> --branch <branch>" >&2
  exit 1
fi

cd "$CLONE_DIR"

for FILE in "${FILES[@]}"; do
  git add "$FILE"
done

git status
git commit -m "$MESSAGE"

PUSH_ERR=$(mktemp)
if ! git push origin "$BRANCH" 2>"$PUSH_ERR"; then
  if grep -q "shallow update not allowed" "$PUSH_ERR"; then
    echo "Detected shallow clone — running git fetch --unshallow..." >&2
    rm -f "$PUSH_ERR"
    git fetch --unshallow origin
    git push origin "$BRANCH"
  else
    cat "$PUSH_ERR" >&2
    rm -f "$PUSH_ERR"
    echo "ERROR: Could not push branch '$BRANCH' to origin." >&2
    exit 1
  fi
fi

rm -f "$PUSH_ERR"
