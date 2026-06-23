#!/usr/bin/env bash
# Wrapper for the enable-renovate-on-rhoai-component-repo step (RHOAI only).
#
# Adds the component's repo to the renovate config in rhoai-konflux-central
# (config.yaml on main) and raises a GitHub PR.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Entry already present — writes pipeline_state.json (status=done)
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

EXISTING_URL=$(jq -r '.steps.renovate.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

REPO_URL=$(grep -m1 'repo_url:' "$YAML_FILE" | awk '{print $2}')
[[ -z "$REPO_URL" ]] && { echo "ERROR: repo_url missing from YAML." >&2; exit 1; }

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
RENOVATE_ENTRY="red-hat-data-services/${REPO_NAME}"

RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')

echo "REPO_URL       : $REPO_URL"
echo "REPO_NAME      : $REPO_NAME"
echo "RENOVATE_ENTRY : $RENOVATE_ENTRY"
echo "RKC_URL        : $RKC_URL"

# Fast-path: check if entry already exists in config.yaml on main
CONFIG_CONTENT=$(curl -sf \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  "https://raw.githubusercontent.com/${RKC_PATH}/main/config.yaml" 2>/dev/null || echo "")

if [[ -n "$CONFIG_CONTENT" ]] && echo "$CONFIG_CONTENT" | grep -qF "${RENOVATE_ENTRY}"; then
  echo "Entry '${RENOVATE_ENTRY}' already exists in renovate config."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "renovate-changes-done" \
    --comment "Renovate config entry '${RENOVATE_ENTRY}' already exists in ${RKC_PATH} (config.yaml). No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step renovate --status done
  exit 2
fi

# Clone from main (sparse: config.yaml only)
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$RKC_URL" \
  --src-branch  "main" \
  --sparse-files "config.yaml") || {
  echo "ERROR: Playpen setup for rhoai-konflux-central (renovate) failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

# Check local clone for entry too (in case API was empty)
CONFIG_LOCAL="$CLONE_DIR/config.yaml"
if [[ -f "$CONFIG_LOCAL" ]] && grep -qF "${RENOVATE_ENTRY}" "$CONFIG_LOCAL" 2>/dev/null; then
  echo "Entry '${RENOVATE_ENTRY}' already in config.yaml (local clone check)."
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step renovate --status done
  exit 2
fi

# Edit config.yaml
uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-renovate-repo \
  "$CONFIG_LOCAL" \
  --renovate-config "renovate/default-renovate-distribution.json" \
  --name "$RENOVATE_ENTRY" || {
  echo "ERROR: Could not append renovate entry to config.yaml." >&2; exit 1
}
grep -qF "$RENOVATE_ENTRY" "$CONFIG_LOCAL" || {
  echo "ERROR: Verification failed — '${RENOVATE_ENTRY}' not found in config.yaml after edit." >&2; exit 1
}

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "config.yaml" \
  --message   "Enable Renovate for ${REPO_NAME}

Adds '${RENOVATE_ENTRY}' to the default Renovate distribution in config.yaml.

Related: ${JIRA_ID}" \
  --branch        "$DEST_BRANCH" \
  --target-branch "main" \
  --jira-url      "$JIRA_URL"

# Raise PR (up to 3 attempts)
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$RKC_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$RKC_URL" \
    --dest-branch "main" \
    --title       "Enable Renovate for ${REPO_NAME}" \
    --description "Adds '${RENOVATE_ENTRY}' to the default Renovate distribution in config.yaml.

| Field | Value |
|-------|-------|
| Component repo | \`${REPO_URL}\` |
| Renovate entry | \`${RENOVATE_ENTRY}\` |
| Distribution   | \`renovate/default-renovate-distribution.json\` |

**Jira:** ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "renovate-pr-raised" \
  --comment "[step:renovate] GitHub PR raised to enable Renovate for '${REPO_NAME}' in ${RKC_PATH}.

PR URL: ${PR_URL}
Entry added: ${RENOVATE_ENTRY}

Renovate will start managing dependencies in '${REPO_NAME}' once this PR is merged." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step renovate \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
