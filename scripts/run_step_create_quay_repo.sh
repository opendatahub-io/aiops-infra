#!/usr/bin/env bash
# Wrapper for the create-quay-repo onboarding step.
#
# Raises a GitLab MR to app-interface that adds the component's Quay repo.
#
# Exit codes:
#   0  MR raised (or already existed in state) — prints MR_URL=<url> as last line
#      and writes pipeline_state.json (status=mr_raised, mr_url set, last_status_change_at updated)
#   1  Unexpected failure — stderr contains the error; pipeline_state.json is NOT written
#   2  Quay repo already exists upstream — prints nothing; writes pipeline_state.json
#      (status=done)
#
# Known failure modes encoded here (from CI log analysis):
#   - Clone timeout on app-interface (large repo): 45-minute timeout applied
#   - MR creation transient failure: retried up to 3 times
#   - Shallow push rejected: unshallow + retry
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

JIRA_ID="${JIRA_URL%/}"
JIRA_ID="${JIRA_ID##*/}"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

# Idempotency: if we already have a URL in state, re-emit it and exit 0
EXISTING_URL=$(jq -r '.steps.quay.mr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "MR already recorded in state: $EXISTING_URL"
  echo "MR_URL=$EXISTING_URL"
  exit 0
fi

# Load component details (placed by orchestrator before calling this script)
YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"
# Sets: COMPONENT_NAME PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI IS_OPERATOR

QUAY_REPO="${QUAY_REPO_URI##*/}"

APP_INTERFACE_URL="${APP_INTERFACE_REPO_URL:-https://gitlab.cee.redhat.com/service/app-interface}"
echo "APP_INTERFACE_REPO_URL=${APP_INTERFACE_REPO_URL:-(not set, using default)}"
echo "APP_INTERFACE_URL resolved to: $APP_INTERFACE_URL"

# Map org to YAML file path
case "$QUAY_ORG" in
  opendatahub) YAML_FILE_PATH="data/services/rhoai/quay/opendatahub.yml" ;;
  rhoai)       YAML_FILE_PATH="data/services/rhoai/quay/rhoai.yml"       ;;
  modh)        YAML_FILE_PATH="data/services/rhoai/quay/modh.yml"        ;;
  *)
    echo "ERROR: Unknown Quay org '$QUAY_ORG'. Cannot determine YAML path in app-interface." >&2
    exit 1
    ;;
esac

# Step: Check if Quay repo already exists upstream
set +e
bash "$SCRIPTS_DIR/check_quay_repo.sh" "quay.io/${QUAY_ORG}/${QUAY_REPO}"
CHECK_EXIT=$?
set -e
if [[ "$CHECK_EXIT" -eq 0 ]]; then
  echo "Quay repo quay.io/${QUAY_ORG}/${QUAY_REPO} already exists. Marking step done."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "quay-mr-merged" \
    --comment "Quay repo quay.io/${QUAY_ORG}/${QUAY_REPO} already exists. No MR needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step quay --status done
  exit 2
elif [[ "$CHECK_EXIT" -eq 2 ]]; then
  echo "ERROR: check_quay_repo.sh returned tool error" >&2; exit 1
fi

# Step: Fork app-interface (skip if APP_INTERFACE_URL is already in the user's namespace)
if [[ "$APP_INTERFACE_URL" == *"/${GITLAB_USER}/"* || "$APP_INTERFACE_URL" == *"/${GITLAB_USER}.git"* ]]; then
  echo "APP_INTERFACE_URL is already owned by ${GITLAB_USER} — using directly as fork."
  FORK_URL="$APP_INTERFACE_URL"
else
  FORK_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/setup_gitlab_fork.py" \
    --gitlab-repo-url "$APP_INTERFACE_URL") || {
    echo "ERROR: Could not fork app-interface. Check GITLAB_TOKEN api scope." >&2; exit 1
  }
fi

# Step: Clone (with 45-minute timeout for this large repo)
cd "$WORKDIR"
set +e
timeout 2700 env GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
    --src-url    "$APP_INTERFACE_URL" \
    --dest-url   "$FORK_URL" \
    --src-branch master \
    --dest-branch "$JIRA_ID" \
    --no-shallow > /tmp/playpen_quay.out 2>&1
rc=$?
set -e
if [[ $rc -eq 0 ]]; then
  CLONE_DIR=$(tail -2 /tmp/playpen_quay.out | head -1)
  DEST_BRANCH=$(tail -1 /tmp/playpen_quay.out)
elif [[ $rc -eq 124 ]]; then
  echo "ERROR: Clone of app-interface timed out after 45 minutes. Check VPN and retry." >&2; exit 1
else
  cat /tmp/playpen_quay.out >&2
  echo "ERROR: Playpen setup failed. Check VPN and GITLAB_TOKEN write_repository scope." >&2; exit 1
fi

# Step: Modify YAML
SHORT_DESC="${COMPONENT_NAME} container image"
[[ "$PRODUCT_CONTEXT" == "RHOAI" ]] && {
  SHORT_DESC=$(grep -m1 'short_description:' "$YAML_FILE" \
    | sed 's/^[[:space:]]*short_description:[[:space:]]*//' || echo "$COMPONENT_NAME")
}

if grep -qE "^[[:space:]]*(- )?name: ${QUAY_REPO}$" "${CLONE_DIR}/${YAML_FILE_PATH}" 2>/dev/null; then
  echo "Entry '${QUAY_REPO}' already present in YAML — skipping append."
  CHANGES_MADE=false
else
  VIS_FLAG="--public"
  [[ "$QUAY_VISIBILITY" == "private" ]] && VIS_FLAG="--no-public"
  uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-items-array \
    "${CLONE_DIR}/${YAML_FILE_PATH}" \
    --name "$QUAY_REPO" \
    --description "$SHORT_DESC" \
    $VIS_FLAG || {
    echo "ERROR: Could not append entry to ${YAML_FILE_PATH}." >&2; exit 1
  }
  CHANGES_MADE=true
fi

# Nothing to change means the entry is already on the target branch. Raising an MR
# in that case produces an empty, unmergeable MR (0 commits, base_sha == head_sha)
# that the pipeline then waits on forever — mark the step done instead.
_quay_already_configured() {
  local reason="$1"
  echo "${reason} — Quay repo already declared in app-interface. Marking step done."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "quay-mr-merged" \
    --comment "quay.io/${QUAY_ORG}/${QUAY_REPO} is already declared in ${YAML_FILE_PATH} on app-interface master. No MR needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step quay --status done
  exit 2
}

if [[ "$CHANGES_MADE" == "false" ]]; then
  _quay_already_configured "Entry '${QUAY_REPO}' already present in ${YAML_FILE_PATH}"
fi

# Step: Commit and push
DEST_REMOTE="dest"
[[ "$FORK_URL" == "$APP_INTERFACE_URL" ]] && DEST_REMOTE="origin"
set +e
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$YAML_FILE_PATH" \
  --message   "Add ${QUAY_REPO} to quay ${QUAY_ORG} config" \
  --branch    "$DEST_BRANCH" \
  --remote    "$DEST_REMOTE"
PUSH_RC=$?
set -e
if [[ "$PUSH_RC" -eq 3 ]]; then
  _quay_already_configured "Nothing to commit in ${YAML_FILE_PATH}"
elif [[ "$PUSH_RC" -ne 0 ]]; then
  echo "ERROR: Could not commit or push changes." >&2; exit 1
fi

# Guard against raising an MR that has no commits (e.g. the branch ends up equal to
# the target branch). An empty MR can never merge and blocks the pipeline.
COMMITS_AHEAD=$(git -C "$CLONE_DIR" rev-list --count "master..HEAD" 2>/dev/null || echo 0)
if [[ "${COMMITS_AHEAD:-0}" -lt 1 ]]; then
  _quay_already_configured "Branch '${DEST_BRANCH}' has no commits ahead of master"
fi

# Step: Raise MR (up to 3 attempts)
MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$FORK_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$APP_INTERFACE_URL" \
    --dest-branch master \
    --title       "Add ${QUAY_REPO} quay repository for ${QUAY_ORG}" \
    --description "Add quay.io/${QUAY_ORG}/${QUAY_REPO} to app-interface GitOps config.

Visibility: ${QUAY_VISIBILITY}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  STDERR_OUT=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url "$FORK_URL" --src-branch "$DEST_BRANCH" --dest-url "$APP_INTERFACE_URL" \
    --dest-branch master --title "Add ${QUAY_REPO} quay repository for ${QUAY_ORG}" \
    --description "Jira: ${JIRA_URL}" 2>&1 >/dev/null || true)
  if echo "$STDERR_OUT" | grep -qi "branch not found"; then
    cd "$CLONE_DIR"
    git push "$DEST_REMOTE" "$DEST_BRANCH" || true
    cd "$WORKDIR"
  fi
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

# Jira update
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "quay-mr-raised" \
  --comment "GitLab MR raised to create quay.io/${QUAY_ORG}/${QUAY_REPO}.

MR URL: ${MR_URL}

The Quay repo will be created automatically once this MR is merged." || true

# Update pipeline_state.json
bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step quay \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
