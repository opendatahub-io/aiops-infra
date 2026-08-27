#!/usr/bin/env bash
# Wrapper for the setup-auto-merge step (RHOAI only).
#
# Updates four files in rhods-devops-infra (upstream-source-map.yaml,
# main-release-source-map.yaml, upstream-auto-merge.yaml,
# main-release-auto-merge.yaml) and raises a GitHub PR.
#
# Exit codes:
#   0  PR raised — prints PR_URL=<url>; writes pipeline_state.json
#   1  Unexpected failure; pipeline_state.json NOT written
#   2  All entries already present — writes pipeline_state.json (status=done)
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

EXISTING_URL=$(jq -r '.steps.auto_merge.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

REPO_URL=$(grep -m1 'repo_url:' "$YAML_FILE" | awk '{print $2}')
[[ -z "$REPO_URL" ]] && {
  echo "ERROR: repo_url missing from YAML." >&2; exit 1
}

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"

eval "$(bash "$SCRIPTS_DIR/detect_repo_upstream.sh" --repo-url "$REPO_URL" 2>/dev/null)" || {
  UPSTREAM_REPO_URL="$REPO_URL"
}

RDI_URL="${RHODS_DEVOPS_INFRA_REPO_URL:-https://github.com/red-hat-data-services/rhods-devops-infra.git}"
echo "RHODS_DEVOPS_INFRA_REPO_URL=${RHODS_DEVOPS_INFRA_REPO_URL:-(not set, using default)}"
echo "RDI_URL resolved to: $RDI_URL"
RDI_PATH=$(echo "$RDI_URL" | sed 's|https://github.com/||;s|\.git$||')

echo "REPO_NAME        : $REPO_NAME"
echo "REPO_URL         : $REPO_URL"
echo "UPSTREAM_REPO_URL: $UPSTREAM_REPO_URL"

# Fast-path: check if entries already exist in both config files via API
fetch_file_content() {
  local path="$1"
  curl -s \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${RDI_PATH}/contents/${path}?ref=main" \
    | python3 -c \
      "import sys,json,base64; d=json.load(sys.stdin); print(base64.b64decode(d['content']).decode())" \
      2>/dev/null || echo ""
}

USM_CONTENT=$(fetch_file_content "src/config/upstream-source-map.yaml" 2>/dev/null || echo "")
MRSM_CONTENT=$(fetch_file_content "src/config/main-release-source-map.yaml" 2>/dev/null || echo "")

USM_HAS_ENTRY=false; MRSM_HAS_ENTRY=false
[[ -n "$USM_CONTENT" ]]  && echo "$USM_CONTENT"  | grep -qF "name: ${REPO_NAME}" && USM_HAS_ENTRY=true
[[ -n "$MRSM_CONTENT" ]] && echo "$MRSM_CONTENT" | grep -qF "name: ${REPO_NAME}" && MRSM_HAS_ENTRY=true

if [[ "$USM_HAS_ENTRY" == "true" && "$MRSM_HAS_ENTRY" == "true" ]]; then
  echo "Auto-merge entries for '${REPO_NAME}' already exist in both config files."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "auto-merge-setup-done" \
    --comment "Auto-merge config for '${REPO_NAME}' already exists in ${RDI_PATH} (both source maps). No action needed." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step auto_merge --status done
  exit 2
fi

# Clone (sparse)
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url     "$RDI_URL" \
  --src-branch  "main" \
  --dest-branch "$JIRA_ID" \
  --sparse-files "src/config .github/workflows") || {
  echo "ERROR: Playpen setup for rhods-devops-infra failed." >&2; exit 1
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

# Edit upstream-source-map.yaml
USM_FILE="$CLONE_DIR/src/config/upstream-source-map.yaml"
[[ ! -f "$USM_FILE" ]] && { echo "ERROR: src/config/upstream-source-map.yaml not found." >&2; exit 1; }
if ! grep -qF "name: ${REPO_NAME}" "$USM_FILE"; then
  cat >> "$USM_FILE" <<EOF
- name: ${REPO_NAME}
  automerge: 'yes'
  ignore-files: .tekton/*
  src:
    url: ${UPSTREAM_REPO_URL}.git
    branch: main
  dest:
    url: ${REPO_URL}.git
    branch: main
EOF
  grep -qF "name: ${REPO_NAME}" "$USM_FILE" || {
    echo "ERROR: Verification failed for upstream-source-map.yaml." >&2; exit 1
  }
fi

# Edit main-release-source-map.yaml
MRSM_FILE="$CLONE_DIR/src/config/main-release-source-map.yaml"
[[ ! -f "$MRSM_FILE" ]] && { echo "ERROR: src/config/main-release-source-map.yaml not found." >&2; exit 1; }
if ! grep -qF "name: ${REPO_NAME}" "$MRSM_FILE"; then
  cat >> "$MRSM_FILE" <<EOF
- name: ${REPO_NAME}
  automerge: 'yes'
  repo-url: ${REPO_URL}.git
  ignore-files: .tekton/*
EOF
  grep -qF "name: ${REPO_NAME}" "$MRSM_FILE" || {
    echo "ERROR: Verification failed for main-release-source-map.yaml." >&2; exit 1
  }
fi

# Edit upstream-auto-merge.yaml (add to repositories options list)
add_to_workflow_options() {
  local file="$1" entry="$2"
  [[ ! -f "$file" ]] && { echo "ERROR: $file not found." >&2; exit 1; }
  if grep -qF "$entry" "$file" 2>/dev/null; then
    echo "$entry already in $(basename "$file") — skipping."
    return 0
  fi
  OPTIONS_LINE=$(grep -n 'repositories:' "$file" | head -1 | cut -d: -f1)
  OPTIONS_START=$(awk -v start="$OPTIONS_LINE" 'NR>start && /options:/{print NR; exit}' "$file")
  INDENT=$(awk -v start="$OPTIONS_START" 'NR>start && /^\s*- /{match($0,/^[[:space:]]*/); print substr($0,1,RLENGTH); exit}' "$file")
  LAST_OPT=$(awk -v start="$OPTIONS_START" -v indent="$INDENT" \
    'NR>start { if ($0 ~ "^" indent "- ") last=NR; else if (last) { print last; found=1; exit } } END { if (last && !found) print last }' "$file")
  awk -v line="$LAST_OPT" -v new_entry="${INDENT}- ${entry}" \
    'NR==line{print; print new_entry; next}1' "$file" > "${file}.tmp" && mv "${file}.tmp" "$file"
  grep -qF "$entry" "$file" || {
    echo "ERROR: Verification failed for $(basename "$file")." >&2; exit 1
  }
  echo "$entry added to $(basename "$file")."
}

UAM_FILE="$CLONE_DIR/.github/workflows/upstream-auto-merge.yaml"
MRAM_FILE="$CLONE_DIR/.github/workflows/main-release-auto-merge.yaml"
add_to_workflow_options "$UAM_FILE"  "$REPO_NAME"
add_to_workflow_options "$MRAM_FILE" "$REPO_NAME"

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "src/config/upstream-source-map.yaml src/config/main-release-source-map.yaml .github/workflows/upstream-auto-merge.yaml .github/workflows/main-release-auto-merge.yaml" \
  --message   "Configure auto-merge for ${REPO_NAME}

Adds '${REPO_NAME}' to upstream and main-release source maps
and registers it in both auto-merge workflows.

Related: ${JIRA_ID}" \
  --branch "$DEST_BRANCH"

# Raise PR (up to 3 attempts)
PR_URL=""
for attempt in 1 2 3; do
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url     "$RDI_URL" \
    --src-branch  "$DEST_BRANCH" \
    --dest-url    "$RDI_URL" \
    --dest-branch "main" \
    --title       "Configure auto-merge for ${REPO_NAME}" \
    --description "Sets up auto-merge for \`${REPO_NAME}\` in ${RDI_PATH}.

| Field | Value |
|-------|-------|
| Component repo  | \`${REPO_URL}\` |
| Upstream repo   | \`${UPSTREAM_REPO_URL}\` |
| Repo name       | \`${REPO_NAME}\` |

**Files changed:**
- \`src/config/upstream-source-map.yaml\`
- \`src/config/main-release-source-map.yaml\`
- \`.github/workflows/upstream-auto-merge.yaml\`
- \`.github/workflows/main-release-auto-merge.yaml\`

**Jira:** ${JIRA_URL}" 2>/dev/null) && break
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not create PR after 3 attempts." >&2; exit 1
  }
  sleep 5
done

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "auto-merge-pr-raised" \
  --comment "[step:auto_merge] GitHub PR raised to configure auto-merge for '${REPO_NAME}' in ${RDI_PATH}.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step auto_merge \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
