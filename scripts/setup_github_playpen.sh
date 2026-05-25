#!/usr/bin/env bash
# setup_github_playpen.sh — Clone a GitHub repo, create a new branch, and push it.
#
# Usage:
#   setup_github_playpen.sh \
#     --src-url <url>           # mandatory: source GitHub repo to clone
#     [--dest-url <url>]        # optional: remote to push branch to (default: same as src)
#     [--src-branch <name>]     # optional: branch to clone (default: main)
#     [--dest-branch <name>]    # optional: new branch to create (default: $GITHUB_USER-<timestamp>)
#     [--sparse-files <paths>]  # optional: space-separated list of files/dirs for sparse checkout
#     [--clone-dir <name>]      # optional: clone directory name (default: <repo-name>-playpen)
#
# Environment:
#   GITHUB_TOKEN  — required; used for git authentication via x-access-token
#   GITHUB_USER   — required; used in default dest-branch name and git config
#
# Output (stdout):
#   Line 1: absolute path to the clone directory
#   Line 2: dest-branch name that was created and pushed
#
# Exit codes:
#   0  Success
#   1  Error

set -euo pipefail

# ── Helpers ────────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*" >&2; }
warn()  { echo "[WARN]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }
die()   { error "$*"; exit 1; }

# ── Parse arguments ────────────────────────────────────────────────────────────
SRC_URL=""
DEST_URL=""
SRC_BRANCH="main"
DEST_BRANCH=""
SPARSE_FILES=""
CLONE_DIR_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-url)        SRC_URL="${2:?--src-url requires a value}";       shift 2 ;;
    --dest-url)       DEST_URL="${2:?--dest-url requires a value}";     shift 2 ;;
    --src-branch)     SRC_BRANCH="${2:?--src-branch requires a value}"; shift 2 ;;
    --dest-branch)    DEST_BRANCH="${2:?--dest-branch requires a value}"; shift 2 ;;
    --sparse-files)   SPARSE_FILES="${2:?--sparse-files requires a value}"; shift 2 ;;
    --clone-dir)      CLONE_DIR_NAME="${2:?--clone-dir requires a value}"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "Unknown argument: $1. Run '$0 --help' for usage." ;;
  esac
done

# ── Validate required arguments ────────────────────────────────────────────────
[[ -z "$SRC_URL" ]] && die "--src-url is required."

# Derive clone directory name from repo name if not explicitly provided
if [[ -z "$CLONE_DIR_NAME" ]]; then
  REPO_NAME="${SRC_URL##*/}"       # last path segment
  REPO_NAME="${REPO_NAME%.git}"    # strip .git suffix
  CLONE_DIR_NAME="${REPO_NAME}-playpen"
fi

# ── Validate environment variables ─────────────────────────────────────────────
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_USER="${GITHUB_USER:-}"

[[ -z "$GITHUB_TOKEN" ]] && die "GITHUB_TOKEN is not set. Export it before running this script."
[[ -z "$GITHUB_USER" ]]  && die "GITHUB_USER is not set. Export it before running this script."

# ── Defaults ───────────────────────────────────────────────────────────────────
if [[ -z "$DEST_URL" ]]; then
  DEST_URL="$SRC_URL"
fi

if [[ -z "$DEST_BRANCH" ]]; then
  TIMESTAMP=$(date +%Y%m%d%H%M%S)
  DEST_BRANCH="${GITHUB_USER}-${TIMESTAMP}"
fi

# ── Inject token into remote URLs ──────────────────────────────────────────────
# Converts https://github.com/<path> → https://x-access-token:<token>@github.com/<path>
# The token is masked in all log output.
inject_auth() {
  local url="$1"
  local scheme host_path
  scheme="${url%%://*}"
  host_path="${url#*://}"
  echo "${scheme}://x-access-token:${GITHUB_TOKEN}@${host_path}"
}

mask_url() {
  local url="$1"
  echo "$url" | sed "s/${GITHUB_TOKEN}/***REDACTED***/g"
}

AUTH_SRC_URL=$(inject_auth "$SRC_URL")
AUTH_DEST_URL=$(inject_auth "$DEST_URL")

info "Source: $(mask_url "$SRC_URL") (branch: ${SRC_BRANCH})"
info "Dest:   $(mask_url "$DEST_URL") (branch: ${DEST_BRANCH})"
[[ -n "$SPARSE_FILES" ]] && info "Sparse checkout: ${SPARSE_FILES}"

# ── Set up clone directory ─────────────────────────────────────────────────────
CLONE_DIR="$(pwd)/${CLONE_DIR_NAME}"

if [[ -d "$CLONE_DIR" ]]; then
  warn "Clone directory already exists — removing for a clean state: ${CLONE_DIR}"
  rm -rf "$CLONE_DIR"
fi

# ── Clone ──────────────────────────────────────────────────────────────────────
if [[ -n "$SPARSE_FILES" ]]; then
  info "Cloning with sparse checkout (--no-checkout --depth 1)..."

  if ! git clone --no-checkout --depth 1 --branch "$SRC_BRANCH" "$AUTH_SRC_URL" "$CLONE_DIR_NAME" 2>&1 | \
       sed "s/${GITHUB_TOKEN}/***REDACTED***/g" >&2; then
    die "git clone failed. Check network connectivity and GITHUB_TOKEN permissions."
  fi

  cd "$CLONE_DIR"

  git sparse-checkout init 2>&1 >&2

  # Split space-separated files into individual arguments
  # shellcheck disable=SC2086
  git sparse-checkout set $SPARSE_FILES 2>&1 >&2
  info "Sparse files set: ${SPARSE_FILES}"

  if ! git checkout "$SRC_BRANCH" 2>&1 >&2; then
    die "git checkout ${SRC_BRANCH} failed after sparse-checkout setup."
  fi
else
  info "Cloning (normal checkout, --depth 1)..."

  if ! git clone --depth 1 --branch "$SRC_BRANCH" "$AUTH_SRC_URL" "$CLONE_DIR_NAME" 2>&1 | \
       sed "s/${GITHUB_TOKEN}/***REDACTED***/g" >&2; then
    die "git clone failed. Check network connectivity and GITHUB_TOKEN permissions."
  fi

  cd "$CLONE_DIR"
fi

# Configure git identity for commits
git config user.email "${GITHUB_USER}@users.noreply.github.com" 2>&1 >&2
git config user.name  "${GITHUB_USER}" 2>&1 >&2

info "Clone complete: ${CLONE_DIR}"

# ── Register dest remote (if different from src) ───────────────────────────────
DEST_REMOTE="origin"

if [[ "$DEST_URL" != "$SRC_URL" ]]; then
  DEST_REMOTE="dest"
  info "Registering remote '${DEST_REMOTE}': $(mask_url "$DEST_URL")"
  git remote add "$DEST_REMOTE" "$AUTH_DEST_URL" 2>&1 | sed "s/${GITHUB_TOKEN}/***REDACTED***/g" >&2
fi

# ── Create and push new branch ─────────────────────────────────────────────────
info "Creating branch: ${DEST_BRANCH}"
git checkout -b "$DEST_BRANCH" 2>&1 >&2

info "Pushing branch '${DEST_BRANCH}' to remote '${DEST_REMOTE}'..."
if ! git push -u "$DEST_REMOTE" "$DEST_BRANCH" 2>&1 | sed "s/${GITHUB_TOKEN}/***REDACTED***/g" >&2; then
  die "git push failed. The branch may already exist on the remote, or GITHUB_TOKEN may lack write scope."
fi

info "Branch '${DEST_BRANCH}' pushed successfully."

# ── Output ─────────────────────────────────────────────────────────────────────
# Print clone dir and branch name to stdout (consumed by SKILL.md)
echo "$CLONE_DIR"
echo "$DEST_BRANCH"
