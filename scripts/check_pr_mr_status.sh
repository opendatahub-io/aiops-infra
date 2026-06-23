#!/usr/bin/env bash
# Check current PR/MR status for all steps in pr_raised/mr_raised state.
# Updates pipeline_state.json in place and prints newly-merged step keys to stdout.
#
# Usage:
#   NEWLY_MERGED=$(bash check_pr_mr_status.sh \
#     --state <pipeline_state.json> --scripts-dir <dir>)
#
# Stdout: newline-separated list of step keys that transitioned to "merged" this run.
# Stderr: progress messages.
# Side-effect: updates pipeline_state.json (status → "merged" or "closed").

set -euo pipefail

PIPELINE_STATE=""
SCRIPTS_DIR=""
JIRA_URL=""
WORKDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state)       PIPELINE_STATE="$2"; shift 2 ;;
    --scripts-dir) SCRIPTS_DIR="$2";    shift 2 ;;
    --jira-url)    JIRA_URL="$2";       shift 2 ;;
    --workdir)     WORKDIR="$2";        shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

for _arg in PIPELINE_STATE SCRIPTS_DIR; do
  [[ -z "${!_arg}" ]] && { echo "ERROR: --${_arg,,} is required (use underscores as hyphens)" >&2; exit 1; }
done

[[ -f "$PIPELINE_STATE" ]] || { echo "ERROR: $PIPELINE_STATE not found" >&2; exit 1; }

NEWLY_MERGED=()

# Iterate all steps that are in pr_raised or mr_raised status
STEP_KEYS=$(jq -r '.steps | to_entries[] | select(.value.status == "pr_raised" or .value.status == "mr_raised") | .key' "$PIPELINE_STATE")

for STEP_KEY in $STEP_KEYS; do
  # Get the URL (prefer pr_url, fall back to mr_url)
  URL=$(jq -r --arg k "$STEP_KEY" '.steps[$k].pr_url // .steps[$k].mr_url // ""' "$PIPELINE_STATE")

  if [[ -z "$URL" ]]; then
    echo "[check] $STEP_KEY: no URL recorded — skipping" >&2
    continue
  fi

  echo "[check] $STEP_KEY: checking $URL" >&2

  # Determine type from URL
  if [[ "$URL" == *"github.com"* ]]; then
    RESULT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
      --pr-url "$URL" --check-only 2>/dev/null || true)
  else
    RESULT=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/monitor_gitlab_mr.py" \
      --mr-url "$URL" --check-only 2>/dev/null || true)
  fi

  STATE=$(echo "$RESULT" | grep -oP 'state=\K\S+' || true)

  echo "[check] $STEP_KEY: state=$STATE" >&2

  if [[ "$STATE" == "merged" ]]; then
    TMP=$(mktemp)
    NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    jq --arg k "$STEP_KEY" --arg ts "$NOW" \
      '.steps[$k].status = "merged" | .last_status_change_at = $ts' \
      "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    NEWLY_MERGED+=("$STEP_KEY")
    echo "[check] $STEP_KEY: marked merged" >&2
  elif [[ "$STATE" == "closed" ]]; then
    TMP=$(mktemp)
    NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    jq --arg k "$STEP_KEY" --arg ts "$NOW" \
      '.steps[$k].status = "closed" | .last_status_change_at = $ts' \
      "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    echo "[check] $STEP_KEY: marked closed (PR/MR was closed without merging)" >&2
  elif [[ "$STATE" == "cannot_be_merged" || "$STATE" == "conflict" ]]; then
    echo "[check] $STEP_KEY: MR has conflicts — attempting union auto-resolve..." >&2
    # Extract source branch and target branch from MR/PR to clone and fix
    SOURCE_BRANCH=$(echo "$RESULT" | grep -oP 'source_branch=\K\S+' || true)
    TARGET_BRANCH=$(echo "$RESULT" | grep -oP 'target_branch=\K\S+' || true)
    SOURCE_URL=$(echo "$RESULT" | grep -oP 'source_url=\K\S+' || true)
    if [[ -n "$SOURCE_BRANCH" && -n "$TARGET_BRANCH" && -n "$SOURCE_URL" ]]; then
      CONFLICT_WORKDIR="${WORKDIR:-/tmp}/conflict-resolve-${STEP_KEY}"
      rm -rf "$CONFLICT_WORKDIR" && mkdir -p "$CONFLICT_WORKDIR"
      # Inject GitLab credentials into the clone URL
      AUTH_URL="$SOURCE_URL"
      if [[ "$SOURCE_URL" == *"gitlab.cee.redhat.com"* && -n "${GITLAB_TOKEN:-}" && -n "${GITLAB_USER:-}" ]]; then
        AUTH_URL="${SOURCE_URL/https:\/\//https://oauth2:${GITLAB_TOKEN}@}"
      fi
      if GIT_SSL_NO_VERIFY=true git clone \
          --branch "$SOURCE_BRANCH" --depth 20 --no-single-branch \
          "$AUTH_URL" "$CONFLICT_WORKDIR/repo" 2>/dev/null; then
        if GIT_SSL_NO_VERIFY=true bash "$SCRIPTS_DIR/resolve_union_conflicts.sh" \
            --clone-dir     "$CONFLICT_WORKDIR/repo" \
            --target-branch "$TARGET_BRANCH" \
            ${JIRA_URL:+--jira-url "$JIRA_URL"} 2>&1 | sed 's/^/  [union] /' >&2; then
          GIT_SSL_NO_VERIFY=true git -C "$CONFLICT_WORKDIR/repo" push origin "$SOURCE_BRANCH" 2>&1 | sed 's/^/  [push] /' >&2
          echo "[check] $STEP_KEY: conflicts auto-resolved and pushed" >&2
        else
          echo "[check] $STEP_KEY: union resolve failed — manual intervention required" >&2
        fi
      else
        echo "[check] $STEP_KEY: could not clone source branch to resolve — skipping" >&2
      fi
      rm -rf "$CONFLICT_WORKDIR"
    else
      echo "[check] $STEP_KEY: cannot extract branch info for auto-resolve" >&2
    fi
  else
    echo "[check] $STEP_KEY: still open/draft — no change" >&2
  fi
done

# Print newly merged steps to stdout for the orchestrator to consume
for KEY in "${NEWLY_MERGED[@]:-}"; do
  [[ -n "$KEY" ]] && echo "$KEY"
done
