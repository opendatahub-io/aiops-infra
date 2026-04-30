#!/usr/bin/env bash
# check_quay_repo.sh — Check whether a Quay repository exists using skopeo.
#
# Usage:
#   check_quay_repo.sh <quay-repo>
#
# Arguments:
#   <quay-repo>   Repository in one of these formats:
#                   quay.io/<org>/<repo>
#                   <org>/<repo>
#
# Exit codes:
#   0  Repository exists (public with tags, or private/unauthorized — both count as "exists")
#   1  Repository does not exist
#   2  Tool error (skopeo not installed, network error, unexpected failure)
#
# All informational output goes to stderr. Stdout is empty.
#
# Examples:
#   check_quay_repo.sh quay.io/opendatahub/odh-dashboard
#   check_quay_repo.sh rhoai/rhoai-data-science-pipelines-operator-controller

set -euo pipefail

# ── Helpers ────────────────────────────────────────────────────────────────────
info()  { echo "[INFO]  $*" >&2; }
warn()  { echo "[WARN]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }

# ── Argument validation ────────────────────────────────────────────────────────
if [[ $# -ne 1 ]]; then
  error "Usage: $0 <quay-repo>"
  error "  <quay-repo> must be in the format: quay.io/<org>/<repo> or <org>/<repo>"
  exit 2
fi

RAW_REPO="$1"

# ── Normalize input ────────────────────────────────────────────────────────────
# Strip leading "quay.io/" if present, then rebuild as quay.io/<org>/<repo>
REPO="${RAW_REPO#quay.io/}"

# Validate that we still have at least two path segments (org/repo)
SEGMENT_COUNT=$(echo "$REPO" | tr -cd '/' | wc -c)
if [[ "$SEGMENT_COUNT" -lt 1 ]]; then
  error "Invalid repository format: '${RAW_REPO}'"
  error "  Expected: quay.io/<org>/<repo> or <org>/<repo>"
  exit 2
fi

FULL_REPO="quay.io/${REPO}"
info "Checking: ${FULL_REPO}"

# ── Prerequisite check ─────────────────────────────────────────────────────────
if ! command -v skopeo &>/dev/null; then
  error "skopeo is not installed."
  error "  macOS:        brew install skopeo"
  error "  RHEL/Fedora:  sudo dnf install skopeo"
  error "  Ubuntu/Debian: sudo apt-get install skopeo"
  exit 2
fi

# ── Run skopeo ─────────────────────────────────────────────────────────────────
# Capture both stdout and stderr; do NOT let set -e abort on non-zero exit here.
SKOPEO_STDERR=$(mktemp)
SKOPEO_STDOUT=$(mktemp)
trap 'rm -f "$SKOPEO_STDERR" "$SKOPEO_STDOUT"' EXIT

set +e
skopeo list-tags "docker://${FULL_REPO}" >"$SKOPEO_STDOUT" 2>"$SKOPEO_STDERR"
SKOPEO_EXIT=$?
set -e

STDERR_CONTENT=$(cat "$SKOPEO_STDERR")
STDOUT_CONTENT=$(cat "$SKOPEO_STDOUT")

# ── Interpret result ───────────────────────────────────────────────────────────
if [[ "$SKOPEO_EXIT" -eq 0 ]]; then
  # skopeo succeeded → repo exists and is publicly accessible
  info "${FULL_REPO} exists (public)."
  exit 0
fi

# skopeo failed — inspect stderr to distinguish cases
STDERR_LOWER=$(echo "$STDERR_CONTENT" | tr '[:upper:]' '[:lower:]')

# Auth error from skopeo — Quay.io returns 401 for BOTH non-existent repos AND
# private repos, so skopeo's "unauthorized" alone cannot confirm existence.
# Use the Quay REST API as a tie-breaker: only HTTP 200 is a definitive "exists".
# 401/404 from the API are both treated as "does not exist" because:
#   - public repos that exist → 200
#   - non-existent repos     → 401 (Quay hides existence) or 404
#   - private repos          → 401 (ambiguous, but false-negative is safe here
#     since the Step 8 YAML idempotency check prevents actual duplicates)
if echo "$STDERR_LOWER" | grep -qE 'unauthorized|authentication required|access denied|403'; then
  ORG=$(echo "$REPO" | cut -d/ -f1)
  REPO_NAME=$(echo "$REPO" | cut -d/ -f2)
  QUAY_API_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://quay.io/api/v1/repository/${ORG}/${REPO_NAME}" 2>/dev/null || echo "000")

  if [[ "$QUAY_API_STATUS" == "200" ]]; then
    info "${FULL_REPO} exists (confirmed via Quay API)."
    exit 0
  else
    info "${FULL_REPO} not confirmed via Quay API (status=${QUAY_API_STATUS}) — treating as does not exist."
    exit 1
  fi
fi

# Repo does not exist
if echo "$STDERR_LOWER" | grep -qE 'not found|manifest unknown|does not exist|404|repository does not exist|name unknown'; then
  info "${FULL_REPO} does not exist."
  exit 1
fi

# Network / DNS / connection error
if echo "$STDERR_LOWER" | grep -qE 'no such host|connection refused|timeout|network|dial tcp|tls'; then
  error "Network error checking ${FULL_REPO}:"
  error "  ${STDERR_CONTENT}"
  error "  Check your network connection."
  exit 2
fi

# Fallback: unknown error
error "Unexpected error from skopeo (exit ${SKOPEO_EXIT}):"
error "  ${STDERR_CONTENT}"
exit 2
