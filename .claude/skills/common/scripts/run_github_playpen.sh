#!/usr/bin/env bash
# run_github_playpen.sh — wrapper around setup_github_playpen.sh.
# Handles optional --dest-branch (skips the flag when empty) and outputs
# CLONE_DIR/DEST_BRANCH on stdout for eval by the caller.
# Exit 0: success; Exit 1: clone or push error.
set -euo pipefail

SRC_URL=""
SRC_BRANCH="main"
DEST_BRANCH=""
SPARSE_FILES=""
WORKDIR=""
COMMON_SCRIPTS_DIR=""

usage() {
  echo "Usage: $0 --src-url URL --sparse-files FILES --workdir PATH --scripts-dir PATH [--src-branch BRANCH] [--dest-branch BRANCH]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-url)      SRC_URL="$2";             shift 2 ;;
    --src-branch)   SRC_BRANCH="$2";          shift 2 ;;
    --dest-branch)  DEST_BRANCH="$2";         shift 2 ;;
    --sparse-files) SPARSE_FILES="$2";        shift 2 ;;
    --workdir)      WORKDIR="$2";             shift 2 ;;
    --scripts-dir)  COMMON_SCRIPTS_DIR="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$SRC_URL" || -z "$SPARSE_FILES" || -z "$WORKDIR" || -z "$COMMON_SCRIPTS_DIR" ]] && usage

cd "$WORKDIR"

PLAYPEN_ARGS=(
  --src-url      "$SRC_URL"
  --src-branch   "$SRC_BRANCH"
  --sparse-files "$SPARSE_FILES"
)
# Only pass --dest-branch when non-empty; setup_github_playpen.sh auto-generates one otherwise
[[ -n "$DEST_BRANCH" ]] && PLAYPEN_ARGS+=(--dest-branch "$DEST_BRANCH")

PLAYPEN_OUTPUT=$(bash "$COMMON_SCRIPTS_DIR/setup_github_playpen.sh" "${PLAYPEN_ARGS[@]}")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | sed -n '1p')
OUT_BRANCH=$(echo "$PLAYPEN_OUTPUT" | sed -n '2p')

echo "CLONE_DIR=${CLONE_DIR}"
echo "DEST_BRANCH=${OUT_BRANCH}"
