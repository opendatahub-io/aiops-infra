#!/usr/bin/env bash
# Usage: git_commit_push.sh --clone-dir <dir> --files "<f1> <f2>" --message "<msg>" --branch <branch>
#                           [--remote <remote>] [--target-branch <branch>] [--jira-url <url>]
#
# Stages files, commits, and pushes. On non-fast-forward failure (another job merged
# first), uses resolve_union_conflicts.sh to auto-resolve via the union merge driver.
set -euo pipefail

# Required for gitlab.cee.redhat.com which uses an internal CA not trusted by default
export GIT_SSL_NO_VERIFY=true

CLONE_DIR=""
FILES=()
MESSAGE=""
BRANCH=""
REMOTE="origin"
TARGET_BRANCH=""
JIRA_URL=""

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --clone-dir)     CLONE_DIR="$2";             shift 2 ;;
    --files)         read -ra FILES <<< "$2";    shift 2 ;;
    --message)       MESSAGE="$2";               shift 2 ;;
    --branch)        BRANCH="$2";                shift 2 ;;
    --remote)        REMOTE="$2";                shift 2 ;;
    --target-branch) TARGET_BRANCH="$2";         shift 2 ;;
    --jira-url)      JIRA_URL="$2";              shift 2 ;;
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

# Ensure git identity is set; CI runners often have no global config
git config --get user.email &>/dev/null || git config user.email "ci-bot@redhat.com"
git config --get user.name  &>/dev/null || git config user.name  "CI Bot"

git commit -m "$MESSAGE"

# If target-branch is known, proactively sync with the latest target before pushing.
# This sets up the union merge driver for shared YAML files and incorporates any
# changes merged by concurrent onboarding jobs — ensuring the PR is always
# conflict-free when raised, not just when a push fails.
if [[ -n "$TARGET_BRANCH" ]]; then
  bash "$SCRIPTS_DIR/resolve_union_conflicts.sh" \
    --clone-dir     "$CLONE_DIR" \
    --target-branch "$TARGET_BRANCH" \
    ${JIRA_URL:+--jira-url "$JIRA_URL"} || exit 1
fi

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
