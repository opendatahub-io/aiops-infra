#!/usr/bin/env bash
# Offboarding: remove component from RHOAI product listing in pyxis-repo-configs (RHOAI only).
#
# Removes the component's registry path from product-listings/rhoai/rhoai.yaml
# and raises a GitLab MR.
#
# Exit codes:
#   0  MR raised — prints MR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Entry not found (already removed) — writes pipeline_state.json (status=done)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"
export GIT_SSL_NO_VERIFY=true

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

EXISTING_URL=$(jq -r '.steps.remove_product_listing.mr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "MR already recorded in state: $EXISTING_URL"
  echo "MR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_offboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "$SCRIPTS_DIR")"

if [[ "$FULLY_DEPRECATED" != "true" ]]; then
  echo "fully_deprecated is not set — skipping product listing removal."
  echo "Product listing is shared across all supported versions. Only remove when the component is not needed in any version."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-product-listing-skipped" \
    --comment "${DRY_RUN_PREFIX}Skipping product listing removal for '$COMPONENT_NAME' — fully_deprecated is not set. Product listing entries are shared across all supported versions." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_product_listing --status skipped
  exit 2
fi

# Product listing entries use the rhoai registry path
PRODUCT_LISTING_ENTRY="registry.access.redhat.com/rhoai/${COMPONENT_NAME}-rhel9"
# Also check for beta variant
PRODUCT_LISTING_ENTRY_BETA="registry.access.redhat.com/rhoai-beta/${COMPONENT_NAME}-rhel9"

PYXIS_URL="${PYXIS_REPO_CONFIGS_REPO_URL:-https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git}"
PYXIS_PATH=$(echo "$PYXIS_URL" | sed 's|https://gitlab.cee.redhat.com/||;s|\.git$||')
PYXIS_PATH_ENCODED=$(echo "$PYXIS_PATH" | sed 's|/|%2F|g')

echo "COMPONENT_NAME        : $COMPONENT_NAME"
echo "PRODUCT_LISTING_ENTRY : $PRODUCT_LISTING_ENTRY"
echo "PYXIS_URL             : $PYXIS_URL"

# Fast-path: check if entry exists
RHOAI_YAML_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -sk -w "%{http_code}" \
  -H "Authorization: Bearer $GITLAB_TOKEN" \
  "https://gitlab.cee.redhat.com/api/v4/projects/${PYXIS_PATH_ENCODED}/repository/files/product-listings%2Frhoai%2Frhoai.yaml/raw?ref=main" \
  -o "$RHOAI_YAML_TMPFILE" 2>/dev/null || echo "000")

ENTRY_TO_REMOVE=""
if [[ "$HTTP_STATUS" == "200" ]]; then
  if grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML_TMPFILE"; then
    ENTRY_TO_REMOVE="$PRODUCT_LISTING_ENTRY"
  elif grep -qF "$PRODUCT_LISTING_ENTRY_BETA" "$RHOAI_YAML_TMPFILE"; then
    ENTRY_TO_REMOVE="$PRODUCT_LISTING_ENTRY_BETA"
  fi
fi
rm -f "$RHOAI_YAML_TMPFILE"

if [[ -z "$ENTRY_TO_REMOVE" ]]; then
  echo "Product listing entry for '${COMPONENT_NAME}' not found in pyxis-repo-configs — already removed."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "offboard-product-listing-done" \
    --comment "${DRY_RUN_PREFIX}Product listing entry for '${COMPONENT_NAME}' already absent from pyxis-repo-configs. No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step remove_product_listing --status done
  exit 2
fi

# Clone
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
  --src-url  "$PYXIS_URL" \
  --dest-url "$PYXIS_URL" \
  --src-branch main \
  --dest-branch "${JIRA_ID}-offboard" \
  --sparse-files "product-listings/rhoai/rhoai.yaml") || {
  echo "ERROR: Playpen setup for pyxis-repo-configs failed. Check VPN." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

RHOAI_YAML="$CLONE_DIR/product-listings/rhoai/rhoai.yaml"
[[ ! -f "$RHOAI_YAML" ]] && {
  echo "ERROR: product-listings/rhoai/rhoai.yaml not found." >&2; exit 1
}

# Remove entry
uv run --script "$SCRIPTS_DIR/edit_yaml.py" remove-list-item \
  "$RHOAI_YAML" \
  --list-key "repositories" \
  --value "$ENTRY_TO_REMOVE" || {
  echo "ERROR: Could not remove entry from product-listings/rhoai/rhoai.yaml." >&2; exit 1
}

bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "product-listings/rhoai/rhoai.yaml" \
  --message   "Remove ${COMPONENT_NAME} from RHOAI product listing (offboarding)

Removes ${ENTRY_TO_REMOVE} from the
repositories list in product-listings/rhoai/rhoai.yaml.

Related: ${JIRA_ID}" \
  --branch "$DEST_BRANCH"

MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$PYXIS_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$PYXIS_URL" \
    --dest-branch main \
    --title       "${DRY_RUN_PREFIX}Remove ${COMPONENT_NAME} from RHOAI product listing (offboarding)" \
    --description "Removes \`${ENTRY_TO_REMOVE}\` from \`product-listings/rhoai/rhoai.yaml\`.

Component: ${COMPONENT_NAME}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboard-product-listing-mr-raised" \
  --comment "${DRY_RUN_PREFIX}[step:remove_product_listing] GitLab MR raised to remove '${COMPONENT_NAME}' from RHOAI product listing.

MR URL: ${MR_URL}
Entry: ${ENTRY_TO_REMOVE}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step remove_product_listing \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
