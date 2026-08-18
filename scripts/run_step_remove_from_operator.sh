#!/usr/bin/env bash
# Offboarding: remove component from operator manifests config.
#
# Exit 2 immediately when is_operator=false (no-op).
# Otherwise removes the entry from build/manifests-config.yaml and raises a PR.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  is_operator=false (skipped) OR entry not found (already removed);
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

EXISTING_URL=$(jq -r '.steps.remove_operator.pr_url // ""' "$PIPELINE_STATE")
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

if [[ "$IS_OPERATOR" != "true" ]]; then
  echo "is_operator=false — skipping operator manifest removal."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-operator-not-needed" \
    --comment "Skipping operator manifest removal for '$COMPONENT_NAME' (is_operator=false)." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_operator --status skipped
  exit 2
fi

eval "$(bash "$SCRIPTS_DIR/resolve_operator_url.sh" \
  --product-context "$PRODUCT_CONTEXT")"
echo "ODH_OPERATOR_URL  : $ODH_OPERATOR_URL"

if [[ "$PRODUCT_CONTEXT" == "RHOAI" && -n "$TARGET_RHOAI_VERSION" ]]; then
  eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
  OPERATOR_TARGET_BRANCH="$BRANCH_NAME"
else
  OPERATOR_TARGET_BRANCH="main"
fi

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$ODH_OPERATOR_URL" \
  --src-branch  "$OPERATOR_TARGET_BRANCH" \
  --dest-branch "${JIRA_ID}-offboard" \
  --sparse-files "build/manifests-config.yaml") || {
  echo "ERROR: Playpen setup for operator repo failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

MANIFESTS_CONFIG="$CLONE_DIR/build/manifests-config.yaml"
[[ ! -f "$MANIFESTS_CONFIG" ]] && {
  echo "ERROR: build/manifests-config.yaml not found." >&2; exit 1
}

if ! grep -qF "$COMPONENT_NAME" "$MANIFESTS_CONFIG" 2>/dev/null; then
  echo "Entry '${COMPONENT_NAME}' not found in manifests-config.yaml — already removed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-operator-pr-merged" \
    --comment "Operator manifests entry '${COMPONENT_NAME}' already absent from ${ODH_OPERATOR_PATH}. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_operator --status done
  exit 2
fi

uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-map-key \
  "$MANIFESTS_CONFIG" \
  --map-key "map" \
  --name "$COMPONENT_NAME" || {
  echo "ERROR: Could not remove '$COMPONENT_NAME' from manifests-config.yaml." >&2; exit 1
}

bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "build/manifests-config.yaml" \
  --message   "Remove ${COMPONENT_NAME} from operator manifests (offboarding)" \
  --branch    "$DEST_BRANCH"

PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$ODH_OPERATOR_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$ODH_OPERATOR_URL" \
    --dest-branch "$OPERATOR_TARGET_BRANCH" \
    --title       "Remove ${COMPONENT_NAME} from operator manifests (offboarding)" \
    --description "Removes '${COMPONENT_NAME}' entry from build/manifests-config.yaml.

Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-operator-pr-raised" \
  --comment "[step:remove_operator] GitHub PR raised to remove '${COMPONENT_NAME}' from operator manifests.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_operator \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
