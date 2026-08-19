#!/usr/bin/env bash
# Offboarding: remove stale PipelineRun files from the component repo's .tekton/ directory.
#
# The sync-pipelineruns workflow only copies (cp -rf) from konflux-central to
# the component repo — it never deletes.  After the OKC/pull-pipeline PRs
# merge, the removed PipelineRun files remain in the component repo's .tekton/.
# This step raises PR(s) to the component repo to delete them.
#
# RHOAI:
#   push file  → lives on the release branch (e.g. rhoai-3.6-ea.1) → PR 1
#   pull file  → lives on main (only if remove_pull_pipelines is done) → PR 2
# ODH:
#   both files → live on main → single PR
#
# Exit codes:
#   0  PR(s) raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Files not found (already removed) — writes pipeline_state.json (status=done)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$JIRA_URL" ]] && { echo "ERROR: --jira-url is required" >&2; exit 1; }

JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN_PREFIX=""
if [[ "${OFFBOARD_DRY_RUN:-false}" == "true" ]]; then
  DRY_RUN_PREFIX="[DRY RUN] "
fi

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.sync_component_tekton.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null | tr -d '"' || echo "")

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
REPO_ORG_PATH=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')

echo "COMPONENT_NAME : $COMPONENT_NAME"
echo "REPO_URL       : $REPO_URL"
echo "REPO_NAME      : $REPO_NAME"

PR_URLS_RAISED=""

if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  [[ -z "$TARGET_RHOAI_VERSION" ]] && {
    echo "ERROR: target_rhoai_version required for RHOAI." >&2; exit 1
  }
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"

  PUSH_FILE="${COMPONENT_NAME}-${VERSION_VAR}-push.yaml"
  PULL_FILE="${COMPONENT_NAME}-pull-request.yaml"
  PUSH_BRANCH="$BRANCH_NAME"

  # --- Push PipelineRun (version branch) ---
  echo "Checking for push PipelineRun on branch '$PUSH_BRANCH': .tekton/$PUSH_FILE"
  API_URL="https://api.github.com/repos/${REPO_ORG_PATH}/contents/.tekton/${PUSH_FILE}?ref=${PUSH_BRANCH}"
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "$API_URL" 2>/dev/null || echo "000")

  if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "Found push PipelineRun — raising cleanup PR to '$PUSH_BRANCH'"
    cd "$WORKDIR"
    PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
      --src-url     "$REPO_URL" \
      --src-branch  "$PUSH_BRANCH" \
      --dest-branch "${JIRA_ID}-tekton-cleanup" \
      --sparse-files ".tekton") || {
      echo "ERROR: Playpen setup failed for push PipelineRun cleanup." >&2; exit 1
    }
    CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
    DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

    TARGET_PATH="$CLONE_DIR/.tekton/$PUSH_FILE"
    if [[ -f "$TARGET_PATH" ]]; then
      rm "$TARGET_PATH"
      cd "$CLONE_DIR"
      git add -A
      git commit -m "${DRY_RUN_PREFIX}Remove stale ${PUSH_FILE} from .tekton/ (offboarding)

The sync-pipelineruns workflow does not delete files removed from
konflux-central. This commit cleans up the stale PipelineRun.

Related: ${JIRA_ID}"
      git push origin "$DEST_BRANCH" || {
        git fetch --unshallow origin 2>/dev/null || true
        git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed." >&2; exit 1; }
      }

      PUSH_PR_URL=""
      for attempt in 1 2 3; do
        PUSH_PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
          --src-url     "$REPO_URL" \
          --src-branch  "$DEST_BRANCH" \
          --dest-url    "$REPO_URL" \
          --dest-branch "$PUSH_BRANCH" \
          --title       "${DRY_RUN_PREFIX}Remove stale ${PUSH_FILE} from .tekton/ (offboarding)" \
          --description "Removes stale push PipelineRun \`${PUSH_FILE}\` from \`.tekton/\`.

The sync-pipelineruns workflow copies PipelineRuns from konflux-central but does not delete files that were removed upstream. This cleans up after offboarding.

Jira: ${JIRA_URL}" 2>/dev/null) && break
        [[ "$attempt" -eq 3 ]] && {
          echo "ERROR: Could not create push cleanup PR after 3 attempts." >&2; exit 1
        }
        sleep 5
      done
      PR_URLS_RAISED="$PUSH_PR_URL"
      echo "Push cleanup PR: $PUSH_PR_URL"
    fi
  else
    echo "Push PipelineRun '$PUSH_FILE' not found on '$PUSH_BRANCH' — already clean."
  fi

  # --- Pull-request PipelineRun (main branch) ---
  PULL_STEP_STATUS=$(jq -r '.steps.remove_pull_pipelines.status // "pending"' "$PIPELINE_STATE")
  if [[ "$PULL_STEP_STATUS" == "done" || "$PULL_STEP_STATUS" == "merged" ]]; then
    echo "Checking for pull-request PipelineRun on 'main': .tekton/$PULL_FILE"
    API_URL="https://api.github.com/repos/${REPO_ORG_PATH}/contents/.tekton/${PULL_FILE}?ref=main"
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      -H "Authorization: token $GITHUB_TOKEN" \
      -H "Accept: application/vnd.github.v3+json" \
      "$API_URL" 2>/dev/null || echo "000")

    if [[ "$HTTP_STATUS" == "200" ]]; then
      echo "Found pull-request PipelineRun — raising cleanup PR to 'main'"
      cd "$WORKDIR"
      PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
        --src-url     "$REPO_URL" \
        --src-branch  "main" \
        --dest-branch "${JIRA_ID}-tekton-cleanup-pull" \
        --sparse-files ".tekton") || {
        echo "ERROR: Playpen setup failed for pull-request PipelineRun cleanup." >&2; exit 1
      }
      CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
      DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

      TARGET_PATH="$CLONE_DIR/.tekton/$PULL_FILE"
      if [[ -f "$TARGET_PATH" ]]; then
        rm "$TARGET_PATH"
        cd "$CLONE_DIR"
        git add -A
        git commit -m "${DRY_RUN_PREFIX}Remove stale ${PULL_FILE} from .tekton/ (offboarding)

The sync-pipelineruns workflow does not delete files removed from
konflux-central. This commit cleans up the stale PipelineRun.

Related: ${JIRA_ID}"
        git push origin "$DEST_BRANCH" || {
          git fetch --unshallow origin 2>/dev/null || true
          git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed." >&2; exit 1; }
        }

        PULL_PR_URL=""
        for attempt in 1 2 3; do
          PULL_PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
            --src-url     "$REPO_URL" \
            --src-branch  "$DEST_BRANCH" \
            --dest-url    "$REPO_URL" \
            --dest-branch "main" \
            --title       "${DRY_RUN_PREFIX}Remove stale ${PULL_FILE} from .tekton/ (offboarding)" \
            --description "Removes stale pull-request PipelineRun \`${PULL_FILE}\` from \`.tekton/\`.

The sync-pipelineruns workflow copies PipelineRuns from konflux-central but does not delete files that were removed upstream. This cleans up after offboarding.

Jira: ${JIRA_URL}" 2>/dev/null) && break
          [[ "$attempt" -eq 3 ]] && {
            echo "ERROR: Could not create pull cleanup PR after 3 attempts." >&2; exit 1
          }
          sleep 5
        done
        if [[ -n "$PR_URLS_RAISED" ]]; then
          PR_URLS_RAISED="$PR_URLS_RAISED $PULL_PR_URL"
        else
          PR_URLS_RAISED="$PULL_PR_URL"
        fi
        echo "Pull cleanup PR: $PULL_PR_URL"
      fi
    else
      echo "Pull-request PipelineRun '$PULL_FILE' not found on 'main' — already clean."
    fi
  else
    echo "remove_pull_pipelines step not done — skipping pull-request PipelineRun cleanup on main."
  fi

else
  # ODH: both files on main
  PUSH_FILE="${COMPONENT_NAME}-push.yaml"
  PULL_FILE="${COMPONENT_NAME}-pull-request.yaml"

  echo "Checking for PipelineRun files on 'main': .tekton/$PUSH_FILE, .tekton/$PULL_FILE"

  FILES_TO_REMOVE=""
  for F in "$PUSH_FILE" "$PULL_FILE"; do
    API_URL="https://api.github.com/repos/${REPO_ORG_PATH}/contents/.tekton/${F}?ref=main"
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
      -H "Authorization: token $GITHUB_TOKEN" \
      -H "Accept: application/vnd.github.v3+json" \
      "$API_URL" 2>/dev/null || echo "000")
    if [[ "$HTTP_STATUS" == "200" ]]; then
      FILES_TO_REMOVE="$FILES_TO_REMOVE $F"
    else
      echo "'$F' not found on 'main' — already clean."
    fi
  done

  FILES_TO_REMOVE=$(echo "$FILES_TO_REMOVE" | xargs)
  if [[ -n "$FILES_TO_REMOVE" ]]; then
    echo "Found stale files: $FILES_TO_REMOVE — raising cleanup PR"
    cd "$WORKDIR"
    PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
      --src-url     "$REPO_URL" \
      --src-branch  "main" \
      --dest-branch "${JIRA_ID}-tekton-cleanup" \
      --sparse-files ".tekton") || {
      echo "ERROR: Playpen setup failed." >&2; exit 1
    }
    CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
    DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

    DELETED=""
    for F in $FILES_TO_REMOVE; do
      TARGET_PATH="$CLONE_DIR/.tekton/$F"
      if [[ -f "$TARGET_PATH" ]]; then
        rm "$TARGET_PATH"
        DELETED="$DELETED $F"
      fi
    done
    DELETED=$(echo "$DELETED" | xargs)

    if [[ -n "$DELETED" ]]; then
      cd "$CLONE_DIR"
      git add -A
      git commit -m "${DRY_RUN_PREFIX}Remove stale PipelineRun files from .tekton/ (offboarding)

Removes: ${DELETED}

The sync-pipelineruns workflow does not delete files removed from
konflux-central. This commit cleans up the stale PipelineRuns.

Related: ${JIRA_ID}"
      git push origin "$DEST_BRANCH" || {
        git fetch --unshallow origin 2>/dev/null || true
        git push origin "$DEST_BRANCH" || { echo "ERROR: Push failed." >&2; exit 1; }
      }

      PR_URL=""
      for attempt in 1 2 3; do
        PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
          --src-url     "$REPO_URL" \
          --src-branch  "$DEST_BRANCH" \
          --dest-url    "$REPO_URL" \
          --dest-branch "main" \
          --title       "${DRY_RUN_PREFIX}Remove stale PipelineRun files from .tekton/ (offboarding)" \
          --description "Removes stale PipelineRun files from \`.tekton/\`: ${DELETED}

The sync-pipelineruns workflow copies PipelineRuns from konflux-central but does not delete files that were removed upstream. This cleans up after offboarding.

Jira: ${JIRA_URL}" 2>/dev/null) && break
        [[ "$attempt" -eq 3 ]] && {
          echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
        }
        sleep 5
      done
      PR_URLS_RAISED="$PR_URL"
      echo "Cleanup PR: $PR_URL"
    fi
  fi
fi

# If no PRs were raised, everything is already clean
if [[ -z "$PR_URLS_RAISED" ]]; then
  echo "No stale PipelineRun files found in component repo — already clean."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-sync-tekton-done" \
    --comment "${DRY_RUN_PREFIX}Component repo .tekton/ is already clean — no stale PipelineRun files found for '${COMPONENT_NAME}'. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step sync_component_tekton --status done
  exit 2
fi

# Record first PR URL in state; put all URLs in the Jira comment
FIRST_PR_URL=$(echo "$PR_URLS_RAISED" | awk '{print $1}')

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-sync-tekton-pr-raised" \
  --comment "${DRY_RUN_PREFIX}[step:sync_component_tekton] PR(s) raised to remove stale PipelineRun files from component repo .tekton/:

$(for U in $PR_URLS_RAISED; do echo "- $U"; done)" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step sync_component_tekton \
  --status pr_raised --url "$FIRST_PR_URL" --url-field pr_url

echo "PR_URL=${FIRST_PR_URL}"
