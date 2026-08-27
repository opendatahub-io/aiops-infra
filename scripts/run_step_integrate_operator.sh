#!/usr/bin/env bash
# Wrapper for the integrate-component-with-odh-operator step.
#
# Exit 2 immediately when is_operator=false (no-op).
# Otherwise adds an entry to build/manifests-config.yaml in the operator repo
# and raises a GitHub PR.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  is_operator=false (skipped) OR entry already present;
#      writes pipeline_state.json (status=done or skipped)
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

EXISTING_URL=$(jq -r '.steps.operator.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

OPERATOR_MANIFEST_SRC_PATH=$(grep -m1  'operator_manifest_src_path:'  "$YAML_FILE" | awk '{print $2}' 2>/dev/null || echo "")
OPERATOR_MANIFEST_DEST_PATH=$(grep -m1 'operator_manifest_dest_path:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null || echo "")

# Gate: skip if is_operator=false
if [[ "$IS_OPERATOR" != "true" ]]; then
  echo "is_operator=false — skipping operator integration."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "operator-changes-not-needed" \
    --comment "Skipping odh-operator integration for '$COMPONENT_NAME' (is_operator=false)." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step operator --status skipped
  exit 2
fi

# Resolve operator URL
eval "$(bash "$SCRIPTS_DIR/resolve_operator_url.sh" \
  --product-context "$PRODUCT_CONTEXT")"
# Sets: ODH_OPERATOR_URL, ODH_OPERATOR_PATH
echo "ODH_OPERATOR_URL  : $ODH_OPERATOR_URL"
echo "ODH_OPERATOR_PATH : $ODH_OPERATOR_PATH"

# Determine target branch
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  OPERATOR_TARGET_BRANCH="$REPO_BRANCH"
else
  OPERATOR_TARGET_BRANCH="main"
fi

# Clone (sparse)
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$ODH_OPERATOR_URL" \
  --src-branch  "$OPERATOR_TARGET_BRANCH" \
  --dest-branch "$JIRA_ID" \
  --sparse-files "build/manifests-config.yaml") || {
  echo "ERROR: Playpen setup for operator repo failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

MANIFESTS_CONFIG="$CLONE_DIR/build/manifests-config.yaml"
[[ ! -f "$MANIFESTS_CONFIG" ]] && {
  echo "ERROR: build/manifests-config.yaml not found in operator repo clone." >&2; exit 1
}

# Idempotency
if grep -qF "$COMPONENT_NAME" "$MANIFESTS_CONFIG" 2>/dev/null; then
  echo "Entry '${COMPONENT_NAME}' already present in manifests-config.yaml."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "operator-pr-merged" \
    --comment "Operator manifests entry '${COMPONENT_NAME}' already present in ${ODH_OPERATOR_PATH}. No PR needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step operator --status done
  exit 2
fi

# Append manifests entry
uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-operator-component \
  "$MANIFESTS_CONFIG" \
  --component-name "$COMPONENT_NAME" \
  --src  "$OPERATOR_MANIFEST_SRC_PATH" \
  --dest "$OPERATOR_MANIFEST_DEST_PATH" || {
  echo "ERROR: Could not append to build/manifests-config.yaml." >&2; exit 1
}

# Verify the entry was written
grep -q "^  ${COMPONENT_NAME}:" "$MANIFESTS_CONFIG" || {
  echo "ERROR: $COMPONENT_NAME not found in manifests-config.yaml after insert." >&2; exit 1
}

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "build/manifests-config.yaml" \
  --message   "Add ${COMPONENT_NAME} to operator manifests config" \
  --branch    "$DEST_BRANCH"

# Raise PR
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$ODH_OPERATOR_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$ODH_OPERATOR_URL" \
    --dest-branch "$OPERATOR_TARGET_BRANCH" \
    --title       "Add ${COMPONENT_NAME} to operator manifests" \
    --description "Adds '${COMPONENT_NAME}' entry to build/manifests-config.yaml.

Repo: ${REPO_URL}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "operator-pr-raised" \
  --comment "[step:operator] GitHub PR raised to add '${COMPONENT_NAME}' to operator manifests in ${ODH_OPERATOR_PATH}.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step operator \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
