#!/usr/bin/env bash
# Wrapper for the update-rhoai-product-listing step (RHOAI only).
#
# Appends the component's registry path to product-listings/rhoai/rhoai.yaml
# in pyxis-repo-configs and raises a GitLab MR.
#
# Exit codes:
#   0  MR raised — prints MR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  Entry already exists — writes pipeline_state.json (status=done)
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

EXISTING_URL=$(jq -r '.steps.product_listing.mr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "MR already recorded in state: $EXISTING_URL"
  echo "MR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
[[ -z "$COMPONENT_NAME" ]] && {
  echo "ERROR: component_name missing from YAML." >&2; exit 1
}

RELEASE_CATEGORY=$(grep -m1 'release_category:' "$YAML_FILE" \
  | sed 's/^[[:space:]]*release_category:[[:space:]]*//' | tr -d '"' || true)
[[ -z "$RELEASE_CATEGORY" ]] && RELEASE_CATEGORY="Generally Available"

# DevPreview (Beta) components use the rhoai-beta product line in Pyxis.
# Appending -beta to the image name is rejected by cicada validation.
PRODUCT_LINE="rhoai"
[[ "$RELEASE_CATEGORY" == "Beta" ]] && PRODUCT_LINE="rhoai-beta"

PRODUCT_LISTING_ENTRY="registry.access.redhat.com/${PRODUCT_LINE}/${COMPONENT_NAME}-rhel9"

PYXIS_URL="${PYXIS_REPO_CONFIGS_REPO_URL:-https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git}"
PYXIS_PATH=$(echo "$PYXIS_URL" | sed 's|https://gitlab.cee.redhat.com/||;s|\.git$||')
PYXIS_PATH_ENCODED=$(echo "$PYXIS_PATH" | sed 's|/|%2F|g')

echo "COMPONENT_NAME        : $COMPONENT_NAME"
echo "PRODUCT_LISTING_ENTRY : $PRODUCT_LISTING_ENTRY"
echo "PYXIS_URL             : $PYXIS_URL"

# Fast-path: check if entry already exists
RHOAI_YAML_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -sk -w "%{http_code}" \
  -H "Authorization: Bearer $GITLAB_TOKEN" \
  "https://gitlab.cee.redhat.com/api/v4/projects/${PYXIS_PATH_ENCODED}/repository/files/product-listings%2Frhoai%2Frhoai.yaml/raw?ref=main" \
  -o "$RHOAI_YAML_TMPFILE" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
  if grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML_TMPFILE"; then
    rm -f "$RHOAI_YAML_TMPFILE"
    echo "Product listing entry '$PRODUCT_LISTING_ENTRY' already exists."
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "product-listing-exists" \
      --comment "Product listing entry '${PRODUCT_LISTING_ENTRY}' already exists in pyxis-repo-configs. No MR needed." || true
    bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
      --state "$PIPELINE_STATE" --step product_listing --status done
    exit 2
  fi
fi
rm -f "$RHOAI_YAML_TMPFILE"

# Clone
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
  --src-url  "$PYXIS_URL" \
  --dest-url "$PYXIS_URL" \
  --src-branch main \
  --dest-branch "$JIRA_ID" \
  --sparse-files "product-listings/rhoai/rhoai.yaml") || {
  echo "ERROR: Playpen setup for pyxis-repo-configs (product-listing) failed. Check VPN." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

RHOAI_YAML="$CLONE_DIR/product-listings/rhoai/rhoai.yaml"
[[ ! -f "$RHOAI_YAML" ]] && {
  echo "ERROR: product-listings/rhoai/rhoai.yaml not found in $CLONE_DIR." >&2; exit 1
}

# Append entry
if grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML" 2>/dev/null; then
  echo "Entry already present in YAML — skipping append."
else
  uv run --script "$SCRIPTS_DIR/append_yaml_list_entry.py" "$RHOAI_YAML" \
    --list-key "repositories" \
    --value "$PRODUCT_LISTING_ENTRY" || {
    echo "ERROR: Could not append to product-listings/rhoai/rhoai.yaml." >&2; exit 1
  }
fi

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "product-listings/rhoai/rhoai.yaml" \
  --message   "Add ${COMPONENT_NAME} to RHOAI product listing

Appends ${PRODUCT_LISTING_ENTRY} to the
repositories list in product-listings/rhoai/rhoai.yaml.

Related: ${JIRA_ID}" \
  --branch        "$DEST_BRANCH" \
  --target-branch "main" \
  --jira-url      "$JIRA_URL"

# Raise MR (up to 3 attempts)
MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$PYXIS_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$PYXIS_URL" \
    --dest-branch main \
    --title       "Add ${COMPONENT_NAME} to RHOAI product listing" \
    --description "Adds \`${PRODUCT_LISTING_ENTRY}\` to \`product-listings/rhoai/rhoai.yaml\`.

Component: ${COMPONENT_NAME}
Jira: ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "product-listing-mr-raised" \
  --comment "[step:product_listing] GitLab MR raised to add '${COMPONENT_NAME}' to RHOAI product listing.

MR URL: ${MR_URL}
Entry: ${PRODUCT_LISTING_ENTRY}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step product_listing \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
