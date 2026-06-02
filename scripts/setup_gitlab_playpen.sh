#!/usr/bin/env bash
# setup_gitlab_playpen.sh — Sparse-clone a GitLab repo, create a new branch, and push it.
#
# Usage:
#   setup_gitlab_playpen.sh \
#     --src-url <url>           # mandatory: source GitLab repo to clone
#     [--dest-url <url>]        # optional: remote to push branch to (default: same as src)
#     [--src-branch <name>]     # optional: branch to clone (default: master)
#     [--dest-branch <name>]    # optional: new branch to create (default: $GITLAB_USER-<timestamp>)
#     [--sparse-files <paths>]  # optional: space-separated list of files/dirs for sparse checkout
#     [--clone-dir <name>]      # optional: clone directory name (default: <repo-name>-playpen)
#
# Environment:
#   GITLAB_TOKEN  — required; used for git authentication via oauth2
#   GITLAB_USER   — required; used in default dest-branch name
#
# Output (stdout):
#   Line 1: absolute path to the clone directory (<repo-name>-playpen inside CWD, or --clone-dir value)
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
SRC_BRANCH="master"
DEST_BRANCH=""
SPARSE_FILES=""
CLONE_DIR_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-url)        SRC_URL="${2:?--src-url requires a value}";      shift 2 ;;
    --dest-url)       DEST_URL="${2:?--dest-url requires a value}";    shift 2 ;;
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
GITLAB_TOKEN="${GITLAB_TOKEN:-}"
GITLAB_USER="${GITLAB_USER:-}"

[[ -z "$GITLAB_TOKEN" ]] && die "GITLAB_TOKEN is not set. Export it before running this script."
[[ -z "$GITLAB_USER" ]]  && die "GITLAB_USER is not set. Export it before running this script."

# ── Defaults ───────────────────────────────────────────────────────────────────
if [[ -z "$DEST_URL" ]]; then
  DEST_URL="$SRC_URL"
fi

if [[ -z "$DEST_BRANCH" ]]; then
  TIMESTAMP=$(date +%Y%m%d%H%M%S)
  DEST_BRANCH="component-onboarding-${GITLAB_USER}-${TIMESTAMP}"
fi

# ── Inject token into remote URLs ──────────────────────────────────────────────
inject_auth() {
  local url="$1"
  local scheme host_path
  scheme="${url%%://*}"
  host_path="${url#*://}"
  echo "${scheme}://oauth2:${GITLAB_TOKEN}@${host_path}"
}

mask_url() {
  local url="$1"
  echo "$url" | sed "s/${GITLAB_TOKEN}/***REDACTED***/g"
}

AUTH_SRC_URL=$(inject_auth "$SRC_URL")
AUTH_DEST_URL=$(inject_auth "$DEST_URL")

info "Source: $(mask_url "$SRC_URL") (branch: ${SRC_BRANCH})"
info "Dest:   $(mask_url "$DEST_URL") (branch: ${DEST_BRANCH})"
[[ -n "$SPARSE_FILES" ]] && info "Sparse checkout: ${SPARSE_FILES}"

# ── Set up clone directory ─────────────────────────────────────────────────────
CLONE_DIR="$(pwd)/${CLONE_DIR_NAME}"

if [[ -d "$CLONE_DIR" ]]; then
  warn "Clone directory already exists -- removing for a clean state: ${CLONE_DIR}"
  rm -rf "$CLONE_DIR"
fi

# ── Clone ──────────────────────────────────────────────────────────────────────
if [[ -n "$SPARSE_FILES" ]]; then
  info "Cloning with sparse checkout (--no-checkout --depth 1)..."

  if ! git clone --no-checkout --depth 1 --branch "$SRC_BRANCH" "$AUTH_SRC_URL" "$CLONE_DIR_NAME" 2>&1 | \
       sed "s/${GITLAB_TOKEN}/***REDACTED***/g" >&2; then
    die "git clone failed. Check VPN connectivity and GITLAB_TOKEN permissions."
  fi

  cd "$CLONE_DIR"

  git sparse-checkout init 2>&1 >&2

  # shellcheck disable=SC2086
  git sparse-checkout set $SPARSE_FILES 2>&1 >&2
  info "Sparse files set: ${SPARSE_FILES}"

  if ! git checkout "$SRC_BRANCH" 2>&1 >&2; then
    die "git checkout ${SRC_BRANCH} failed after sparse-checkout setup."
  fi
else
  info "Cloning (normal checkout, --depth 1)..."

  if ! git clone --depth 1 --branch "$SRC_BRANCH" "$AUTH_SRC_URL" "$CLONE_DIR_NAME" 2>&1 | \
       sed "s/${GITLAB_TOKEN}/***REDACTED***/g" >&2; then
    die "git clone failed. Check VPN connectivity and GITLAB_TOKEN permissions."
  fi

  cd "$CLONE_DIR"
fi

info "Clone complete: ${CLONE_DIR}"

# ── Register dest remote (if different from src) ───────────────────────────────
DEST_REMOTE="origin"

if [[ "$DEST_URL" != "$SRC_URL" ]]; then
  DEST_REMOTE="dest"
  info "Registering remote '${DEST_REMOTE}': $(mask_url "$DEST_URL")"
  git remote add "$DEST_REMOTE" "$AUTH_DEST_URL" 2>&1 | sed "s/${GITLAB_TOKEN}/***REDACTED***/g" >&2
fi

# ── Create and push new branch ─────────────────────────────────────────────────
# If the requested branch already exists on the remote, append a unique
# timestamp suffix so each run gets a clean branch without destroying
# prior work or existing MRs.
if git ls-remote --heads "$DEST_REMOTE" "$DEST_BRANCH" 2>/dev/null | grep -q "$DEST_BRANCH"; then
  ORIG_BRANCH="$DEST_BRANCH"
  DEST_BRANCH="${DEST_BRANCH}-$(date +%s)"
  info "Branch '${ORIG_BRANCH}' already exists on remote -- using '${DEST_BRANCH}' instead."
fi

info "Creating branch: ${DEST_BRANCH}"
git checkout -b "$DEST_BRANCH" 2>&1 >&2

info "Pushing branch '${DEST_BRANCH}' to remote '${DEST_REMOTE}'..."
if ! git push -u "$DEST_REMOTE" "$DEST_BRANCH" 2>&1 | sed "s/${GITLAB_TOKEN}/***REDACTED***/g" >&2; then
  die "git push failed. Check GITLAB_TOKEN write_repository scope and VPN connectivity."
fi

info "Branch '${DEST_BRANCH}' pushed successfully."

# ── Output ─────────────────────────────────────────────────────────────────────
echo "$CLONE_DIR"
echo "$DEST_BRANCH"
