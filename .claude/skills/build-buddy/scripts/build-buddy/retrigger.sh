#!/usr/bin/env bash
# retrigger.sh — Retrigger a Konflux PipelineRun via PaC comment or annotation
#
# Primary:  PaC comment (/retest on PR or /retest branch:<branch> on push)
# Fallback: Annotation on the PipelineRun resource
#
# Usage:
#   source retrigger.sh
#   retrigger_pipeline <pipelinerun-name> <namespace> [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
[[ -z "${BB_PP_IMAGE:-}" ]] && source "${SCRIPT_DIR}/config.sh"

# ── extract_pac_metadata ────────────────────────────────────────────────────
# Extract PaC annotations from a PipelineRun to determine retrigger method.
# Sets: PAC_REPO_URL, PAC_PR_NUMBER, PAC_BRANCH, PAC_SHA, PAC_EVENT_TYPE
extract_pac_metadata() {
  local pr_name="$1"
  local namespace="$2"

  local annotations
  annotations=$(oc get pipelinerun "$pr_name" -n "$namespace" \
    -o jsonpath='{.metadata.annotations}' 2>/dev/null) || {
    echo "ERROR: Cannot fetch PipelineRun '$pr_name' in namespace '$namespace'." >&2
    return 1
  }

  PAC_REPO_URL=$(echo "$annotations" | jq -r '.["pipelinesascode.tekton.dev/url-repository"] // empty' 2>/dev/null || true)
  PAC_PR_NUMBER=$(echo "$annotations" | jq -r '.["pipelinesascode.tekton.dev/pull-request"] // empty' 2>/dev/null || true)
  PAC_BRANCH=$(echo "$annotations" | jq -r '.["pipelinesascode.tekton.dev/branch"] // empty' 2>/dev/null || true)
  PAC_SHA=$(echo "$annotations" | jq -r '.["pipelinesascode.tekton.dev/sha"] // empty' 2>/dev/null || true)
  PAC_EVENT_TYPE=$(echo "$annotations" | jq -r '.["pipelinesascode.tekton.dev/event-type"] // empty' 2>/dev/null || true)

  if [[ -z "$PAC_REPO_URL" ]]; then
    echo "WARN: No PaC annotations found on PipelineRun '$pr_name'." >&2
    return 1
  fi

  echo "PaC metadata extracted:"
  echo "  Repo:       $PAC_REPO_URL"
  echo "  PR#:        ${PAC_PR_NUMBER:-N/A}"
  echo "  Branch:     ${PAC_BRANCH:-N/A}"
  echo "  SHA:        ${PAC_SHA:-N/A}"
  echo "  Event type: ${PAC_EVENT_TYPE:-N/A}"
}

# ── extract_github_owner_repo ───────────────────────────────────────────────
# Extract owner/repo from a GitHub URL
# Returns: "owner/repo" on stdout
extract_github_owner_repo() {
  local url="$1"
  echo "$url" | sed -E 's|https?://github\.com/||; s|\.git$||; s|/$||'
}

# ── retrigger_via_pac_comment ───────────────────────────────────────────────
# Post a /retest comment via GitHub API (primary retrigger method)
# For PR builds: gh pr comment
# For push builds: GitHub API commit comment
retrigger_via_pac_comment() {
  local pr_name="$1"
  local namespace="$2"
  local dry_run="${3:-false}"

  if ! command -v gh &>/dev/null && [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "WARN: Neither 'gh' CLI nor GITHUB_TOKEN available for PaC comment." >&2
    return 1
  fi

  if ! extract_pac_metadata "$pr_name" "$namespace"; then
    return 1
  fi

  local owner_repo
  owner_repo=$(extract_github_owner_repo "$PAC_REPO_URL")

  # PR builds: comment on the PR
  if [[ -n "$PAC_PR_NUMBER" && "$PAC_PR_NUMBER" != "0" ]]; then
    echo "Retriggering via PR comment: /retest on PR #${PAC_PR_NUMBER}"
    if [[ "$dry_run" == "true" ]]; then
      echo "[DRY RUN] Would post '/retest' on ${owner_repo}#${PAC_PR_NUMBER}"
      return 0
    fi

    if command -v gh &>/dev/null; then
      gh pr comment "$PAC_PR_NUMBER" --repo "$owner_repo" --body "/retest"
    else
      curl -s -X POST \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/repos/${owner_repo}/issues/${PAC_PR_NUMBER}/comments" \
        -d '{"body": "/retest"}'
    fi
    echo "Retrigger comment posted on PR #${PAC_PR_NUMBER}."
    return 0
  fi

  # Push builds: commit comment with /retest branch:<branch>
  if [[ -n "$PAC_SHA" && -n "$PAC_BRANCH" ]]; then
    echo "Retriggering via commit comment: /retest branch:${PAC_BRANCH}"
    if [[ "$dry_run" == "true" ]]; then
      echo "[DRY RUN] Would post '/retest branch:${PAC_BRANCH}' on commit ${PAC_SHA}"
      return 0
    fi

    if [[ -z "${GITHUB_TOKEN:-}" ]]; then
      echo "ERROR: GITHUB_TOKEN required for commit comment retrigger." >&2
      return 1
    fi

    curl -s -X POST \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/${owner_repo}/commits/${PAC_SHA}/comments" \
      -d "{\"body\": \"/retest branch:${PAC_BRANCH}\"}"
    echo "Retrigger comment posted on commit ${PAC_SHA}."
    return 0
  fi

  echo "ERROR: Cannot determine retrigger method — no PR# or SHA+branch." >&2
  return 1
}

# ── retrigger_via_annotation ────────────────────────────────────────────────
# Fallback: annotate the PipelineRun to trigger a rebuild
retrigger_via_annotation() {
  local pr_name="$1"
  local namespace="$2"
  local dry_run="${3:-false}"

  echo "Retriggering via annotation on PipelineRun '$pr_name'..."
  if [[ "$dry_run" == "true" ]]; then
    echo "[DRY RUN] Would annotate PipelineRun '$pr_name' in '$namespace'"
    return 0
  fi

  oc annotate pipelinerun "$pr_name" -n "$namespace" \
    "build.appstudio.openshift.io/request=trigger-pac-build" \
    --overwrite 2>&1 || {
    echo "ERROR: Failed to annotate PipelineRun '$pr_name'." >&2
    return 1
  }
  echo "Annotation applied successfully."
  return 0
}

# ── retrigger_pipeline ──────────────────────────────────────────────────────
# Main entry point: try PaC comment first, fall back to annotation.
# Usage: retrigger_pipeline <pr-name> <namespace> [--dry-run]
retrigger_pipeline() {
  local pr_name="$1"
  local namespace="$2"
  local dry_run="false"
  [[ "${3:-}" == "--dry-run" ]] && dry_run="true"

  echo ""
  echo "=== Retrigger: $pr_name (ns: $namespace) ==="

  # Primary: PaC comment
  if retrigger_via_pac_comment "$pr_name" "$namespace" "$dry_run"; then
    echo "Retrigger: SUCCESS (PaC comment)"
    return 0
  fi

  echo "PaC comment retrigger failed. Trying annotation fallback..."

  # Fallback: annotation
  if retrigger_via_annotation "$pr_name" "$namespace" "$dry_run"; then
    echo "Retrigger: SUCCESS (annotation fallback)"
    return 0
  fi

  echo "ERROR: All retrigger methods failed for '$pr_name'." >&2
  return 1
}
