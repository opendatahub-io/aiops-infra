#!/usr/bin/env bash
# Wrapper for the create-rhoai-delivery-repo onboarding step (RHOAI only).
#
# Raises a GitLab MR to pyxis-repo-configs that adds the component's delivery repo entry.
#
# Exit codes:
#   0  MR raised — prints MR_URL=<url> as last line; writes pipeline_state.json
#   1  Unexpected failure — stderr contains error; pipeline_state.json NOT written
#   2  Delivery repo already exists — writes pipeline_state.json (status=done)
#
# Known failure modes encoded here:
#   - Shallow push rejected: unshallow + retry
#   - MR transient failure: retried up to 3 times
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

EXISTING_URL=$(jq -r '.steps.delivery_repo.mr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "MR already recorded in state: $EXISTING_URL"
  echo "MR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}' | tr -d '"')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' | tr -d '"')
SHORT_DESCRIPTION=$(grep -m1 'short_description:' "$YAML_FILE" \
  | sed 's/^[[:space:]]*short_description:[[:space:]]*//')
LONG_DESCRIPTION=$(grep -m1 'long_description:' "$YAML_FILE" \
  | sed 's/^[[:space:]]*long_description:[[:space:]]*//')
RELEASE_CATEGORY=$(grep -m1 'release_category:' "$YAML_FILE" \
  | sed 's/^[[:space:]]*release_category:[[:space:]]*//' | tr -d '"')

[[ -z "$COMPONENT_NAME" ]] && {
  echo "ERROR: component_name missing from $YAML_FILE" >&2; exit 1
}
[[ -z "$TARGET_RHOAI_VERSION" ]] && {
  echo "ERROR: target_rhoai_version missing from $YAML_FILE" >&2; exit 1
}
[[ -z "$SHORT_DESCRIPTION" ]] && SHORT_DESCRIPTION="$COMPONENT_NAME"
[[ -z "$LONG_DESCRIPTION" ]]  && LONG_DESCRIPTION="$COMPONENT_NAME"
[[ -z "$RELEASE_CATEGORY" ]]  && RELEASE_CATEGORY="Generally Available"

eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" \
  --version          "$TARGET_RHOAI_VERSION" \
  --component        "$COMPONENT_NAME" \
  --release-category "$RELEASE_CATEGORY")"
# Sets: CONTENT_STREAM_TAG, REPOSITORY_NAME (rhoai-beta/ prefix for Beta), and other version vars

DISPLAY_NAME=$(echo "$COMPONENT_NAME" | tr '-' ' ' \
  | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1' \
  | sed -E 's/\bOdh\b/ODH/g; s/\bRhoai\b/RHOAI/g; s/\bAi\b/AI/g; s/\bCli\b/CLI/g; s/\bApi\b/API/g')

PYXIS_URL="${PYXIS_REPO_CONFIGS_REPO_URL:-https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git}"
echo "PYXIS_REPO_CONFIGS_REPO_URL=${PYXIS_REPO_CONFIGS_REPO_URL:-(not set, using default)}"
echo "PYXIS_URL resolved to: $PYXIS_URL"

PYXIS_PATH=$(echo "$PYXIS_URL" | sed 's|https://gitlab.cee.redhat.com/||;s|\.git$||')
PYXIS_PATH_ENCODED=$(echo "$PYXIS_PATH" | sed 's|/|%2F|g')

# All release categories (GA, Tech Preview, Beta) use the same product YAML.
# The release_category distinction is encoded *inside* the YAML entry (via
# release_categories and the rhoai-beta/ repository name prefix), not via
# separate directory trees.
PRODUCT_YAML_PATH="products/rhoai/rhoai.yaml"
PRODUCT_YAML_PATH_ENCODED=$(echo "$PRODUCT_YAML_PATH" | sed 's|/|%2F|g')

# Fast-path: check if repo already exists via GitLab API
RHOAI_YAML_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -sk -w "%{http_code}" \
  -H "Authorization: Bearer $GITLAB_TOKEN" \
  "https://gitlab.cee.redhat.com/api/v4/projects/${PYXIS_PATH_ENCODED}/repository/files/${PRODUCT_YAML_PATH_ENCODED}/raw?ref=main" \
  -o "$RHOAI_YAML_TMPFILE" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
  if grep -qF "repository: ${REPOSITORY_NAME}" "$RHOAI_YAML_TMPFILE"; then
    rm -f "$RHOAI_YAML_TMPFILE"
    echo "Delivery repository '${REPOSITORY_NAME}' already exists in pyxis-repo-configs."
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "delivery-repo-exists" \
      --comment "Delivery repository '${REPOSITORY_NAME}' already exists in pyxis-repo-configs. No MR needed." || true
    bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
      --state "$PIPELINE_STATE" --step delivery_repo --status done
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
  --sparse-files "$PRODUCT_YAML_PATH") || {
  echo "ERROR: Playpen setup for pyxis-repo-configs failed. Check VPN and GITLAB_TOKEN scope." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

# Modify YAML
RHOAI_YAML="$CLONE_DIR/${PRODUCT_YAML_PATH}"
[[ ! -f "$RHOAI_YAML" ]] && {
  echo "ERROR: ${PRODUCT_YAML_PATH} not found in $CLONE_DIR" >&2; exit 1
}

RESULT=$(uv run --script "$SCRIPTS_DIR/append_delivery_repo_entry.py" \
  --yaml-file           "$RHOAI_YAML" \
  --repository-name     "$REPOSITORY_NAME" \
  --content-stream-tag  "$CONTENT_STREAM_TAG" \
  --release-category    "$RELEASE_CATEGORY" \
  --display-name        "$DISPLAY_NAME" \
  --short-description   "$SHORT_DESCRIPTION" \
  --long-description    "$LONG_DESCRIPTION")
echo "$RESULT"

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$PRODUCT_YAML_PATH" \
  --message   "Add ${REPOSITORY_NAME} delivery repository for ${COMPONENT_NAME}

Adds a new repository entry to ${PRODUCT_YAML_PATH}:
  repository: ${REPOSITORY_NAME}
  content_stream_tags: ['${CONTENT_STREAM_TAG}']

Related: ${JIRA_ID}" \
  --branch "$DEST_BRANCH"

# Raise MR (up to 3 attempts)
MR_URL=""
for attempt in 1 2 3; do
  MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
    --src-url     "$PYXIS_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$PYXIS_URL" \
    --dest-branch main \
    --title       "Add ${REPOSITORY_NAME} delivery repository for ${COMPONENT_NAME}" \
    --description "Adds a new delivery repository entry to \`${PRODUCT_YAML_PATH}\`.

| Field | Value |
|-------|-------|
| \`repository\` | \`${REPOSITORY_NAME}\` |
| \`content_stream_tags\` | \`['${CONTENT_STREAM_TAG}']\` |
| \`component_name\` | \`${COMPONENT_NAME}\` |
| \`target_rhoai_version\` | \`${TARGET_RHOAI_VERSION}\` |

**File changed:** \`${PRODUCT_YAML_PATH}\`
**Jira:** ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create MR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "delivery-repo-mr-raised" \
  --comment "[step:delivery_repo] GitLab MR raised to create RHOAI delivery repository '${REPOSITORY_NAME}'.

MR URL: ${MR_URL}

File changed: ${PRODUCT_YAML_PATH}
Repository: ${REPOSITORY_NAME}
Content stream tag: ${CONTENT_STREAM_TAG}

The delivery repository will be provisioned automatically once the MR is merged." || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step delivery_repo \
  --status mr_raised --url "$MR_URL" --url-field mr_url

echo "MR_URL=${MR_URL}"
