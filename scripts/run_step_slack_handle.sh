#!/usr/bin/env bash
# Wrapper for the slack_handle step (both ODH and RHOAI).
#
# Upserts the component into src/config/team-slack-handles.yaml in the
# private red-hat-data-services/rhods-devops-infra repo and raises a GitHub
# PR. See RHOAIENG-85559 — this repo was chosen because it is already
# RH-employees-only (private GitHub org) and already the target of the
# `auto_merge` step's PRs, so no new infra/access is required.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Entry already exists, OR slack_team_handle missing from an older YAML
#      (skipped — see below); writes pipeline_state.json (status=done or skipped)
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

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.slack_handle.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
[[ -z "$COMPONENT_NAME" ]] && {
  echo "ERROR: component_name missing from YAML." >&2; exit 1
}

SLACK_TEAM_HANDLE=$(grep -m1 'slack_team_handle:' "$YAML_FILE" | awk '{print $2}' || true)
SLACK_TEAM_CHANNEL=$(grep -m1 'slack_team_channel:' "$YAML_FILE" | awk '{print $2}' || true)

# Gate: skip (not a hard failure) when slack_team_handle is absent. This field
# is required by /create-component-onboarding-jira going forward, but the
# schema does NOT require it (RHOAIENG-85559 was added after many components
# were already onboarded/in-flight) — hard-failing here would halt the ENTIRE
# orchestrator run for every older ticket missing it, per the orchestrator's
# exit-1 contract. Skipping lets the rest of the pipeline proceed normally;
# re-running create-component-onboarding-jira later can backfill the field.
if [[ -z "$SLACK_TEAM_HANDLE" ]]; then
  echo "slack_team_handle not present in component_onboarding_details.yaml — skipping slack_handle step."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "slack-routing-not-provided" \
    --comment "[step:slack_handle] Skipping Slack routing for '${COMPONENT_NAME}' — no slack_team_handle in component_onboarding_details.yaml (this field was added after this ticket started, see RHOAIENG-85559). This step is now marked 'skipped' and will not retry automatically; if you'd like it added later, re-run /create-component-onboarding-jira to collect the handle, then ask a DevOps guardian to reset the slack_handle step to 'pending' in pipeline_state.json." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step slack_handle --status skipped
  exit 2
fi

RDI_URL="${RHODS_DEVOPS_INFRA_REPO_URL:-https://github.com/red-hat-data-services/rhods-devops-infra.git}"
echo "RHODS_DEVOPS_INFRA_REPO_URL=${RHODS_DEVOPS_INFRA_REPO_URL:-(not set, using default)}"
echo "RDI_URL resolved to: $RDI_URL"
RDI_PATH=$(echo "$RDI_URL" | sed 's|https://github.com/||;s|\.git$||')
ROUTING_FILE="src/config/team-slack-handles.yaml"

echo "COMPONENT_NAME     : $COMPONENT_NAME"
echo "SLACK_TEAM_HANDLE  : $SLACK_TEAM_HANDLE"
echo "SLACK_TEAM_CHANNEL : ${SLACK_TEAM_CHANNEL:-"(none)"}"
echo "RDI_URL            : $RDI_URL"

# Fast-path: check via API whether the entry already exists, before cloning.
EXISTING_CONTENT=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.raw" \
  "https://api.github.com/repos/${RDI_PATH}/contents/${ROUTING_FILE}?ref=main" 2>/dev/null || echo "")

if [[ -n "$EXISTING_CONTENT" ]] && echo "$EXISTING_CONTENT" | grep -qF "  ${COMPONENT_NAME}:"; then
  echo "Slack routing for '${COMPONENT_NAME}' already present in ${ROUTING_FILE}."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "slack-routing-exists" \
    --comment "[step:slack_handle] Slack routing for '${COMPONENT_NAME}' already exists in ${RDI_PATH}/${ROUTING_FILE}. No PR needed.

Handle: @${SLACK_TEAM_HANDLE}" || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step slack_handle --status done
  exit 2
fi

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$RDI_URL" \
  --src-branch  "main" \
  --dest-branch "$JIRA_ID" \
  --sparse-files "src/config") || {
  echo "ERROR: Playpen setup for rhods-devops-infra failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

ROUTING_YAML="$CLONE_DIR/$ROUTING_FILE"
if [[ ! -f "$ROUTING_YAML" ]]; then
  mkdir -p "$(dirname "$ROUTING_YAML")"
  cat > "$ROUTING_YAML" <<'HEADER'
# Component -> Slack team handle mapping (RHOAIENG-85559).
# Auto-maintained by the component-onboarding pipeline (slack_handle step).
# Manual edits are fine; keep entries alphabetically sorted by component name.
components:
HEADER
  echo "Created new ${ROUTING_FILE} (did not exist yet)."
fi

UPSERT_ARGS=(
  "$ROUTING_YAML"
  --component-name "$COMPONENT_NAME"
  --slack-team-handle "$SLACK_TEAM_HANDLE"
)
[[ -n "${SLACK_TEAM_CHANNEL:-}" ]] && UPSERT_ARGS+=(--slack-team-channel "$SLACK_TEAM_CHANNEL")

set +e
UPSERT_JSON=$(uv run --script "$SCRIPTS_DIR/upsert_team_slack_handle.py" "${UPSERT_ARGS[@]}" 2>&1)
UPSERT_RC=$?
set -e

if [[ "$UPSERT_RC" -eq 1 ]]; then
  echo "ERROR: Could not upsert Slack routing for '${COMPONENT_NAME}'." >&2
  echo "$UPSERT_JSON" >&2
  exit 1
fi

if [[ "$UPSERT_RC" -eq 2 ]]; then
  echo "Slack routing for '${COMPONENT_NAME}' already present in $ROUTING_FILE."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "slack-routing-exists" \
    --comment "[step:slack_handle] Slack routing for '${COMPONENT_NAME}' already exists in ${RDI_PATH}/${ROUTING_FILE}. No PR needed.

Handle: @${SLACK_TEAM_HANDLE}" || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step slack_handle --status done
  exit 2
fi

CHANNEL_LINE=""
[[ -n "${SLACK_TEAM_CHANNEL:-}" ]] && CHANNEL_LINE="
Channel: #${SLACK_TEAM_CHANNEL}"

bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$ROUTING_FILE" \
  --message   "Add ${COMPONENT_NAME} Slack routing

Routes ${COMPONENT_NAME} to @${SLACK_TEAM_HANDLE} in ${ROUTING_FILE}.

Related: ${JIRA_ID}" \
  --branch "$DEST_BRANCH"

PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$RDI_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$RDI_URL" \
    --dest-branch "main" \
    --title       "Add ${COMPONENT_NAME} Slack routing" \
    --description "Adds Slack routing for \`${COMPONENT_NAME}\` to \`${ROUTING_FILE}\`.

Handle: @${SLACK_TEAM_HANDLE}${CHANNEL_LINE}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "slack-routing-pr-raised" \
  --comment "[step:slack_handle] GitHub PR raised to add '${COMPONENT_NAME}' Slack routing to ${RDI_PATH}.

PR URL: ${PR_URL}
Handle: @${SLACK_TEAM_HANDLE}${CHANNEL_LINE}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step slack_handle \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
