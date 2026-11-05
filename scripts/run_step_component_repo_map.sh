#!/usr/bin/env bash
# Final RHOAI onboarding action: register source-repository/component/image links.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
VERIFY_MERGED=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    --verify-merged) VERIFY_MERGED=true; shift ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done
[[ -z "$JIRA_URL" ]] && { echo "ERROR: --jira-url is required" >&2; exit 1; }
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_MAP=""

report_failure() {
  local status=$?
  [[ -n "$TMP_MAP" ]] && rm -f "$TMP_MAP"
  if [[ "$status" -ne 0 && "$status" -ne 2 && -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "[step:component_repo_map] Mapping registration did not complete (exit ${status}). Review the onboarding run output; this action remains incomplete until the map PR is merged and verified on main." || true
  fi
}
trap report_failure EXIT

JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"
YAML_FILE="${WORKDIR}/component_onboarding_details.yaml"
MAP_PATH="config/component_repo_map.json"
RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
RKC_PATH="${RKC_URL#https://github.com/}"; RKC_PATH="${RKC_PATH%.git}"
MAP_URL="https://raw.githubusercontent.com/${RKC_PATH}/main/${MAP_PATH}"

[[ -f "$PIPELINE_STATE" ]] || { echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1; }
[[ -f "$YAML_FILE" ]] || { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }
[[ "$(jq -r '.product_context // ""' "$PIPELINE_STATE")" == "RHOAI" ]] || {
  echo "ERROR: component_repo_map is only applicable to RHOAI onboarding." >&2; exit 1;
}

fetch_map() {
  local dest="$1"
  [[ -n "${GITHUB_TOKEN:-}" ]] || { echo "ERROR: GITHUB_TOKEN is required." >&2; return 1; }
  curl -fsSL \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "$MAP_URL" -o "$dest" || {
      echo "ERROR: Could not fetch ${MAP_PATH} from ${RKC_PATH}:main." >&2
      return 1
    }
}

mark_done() {
  local comment="$1"
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step component_repo_map --status done
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "component-repo-map-verified" \
    --remove-label "component-repo-map-pr-raised" \
    --comment "$comment" || true
}

TMP_MAP=$(mktemp)
fetch_map "$TMP_MAP"

if [[ "$VERIFY_MERGED" == true ]]; then
  [[ "$(jq -r '.steps.component_repo_map.status // ""' "$PIPELINE_STATE")" == "merged" ]] || {
    echo "ERROR: component_repo_map is not in merged state; refusing verification." >&2; exit 1;
  }
  uv run --script "$SCRIPTS_DIR/component_repo_map.py" \
    --details "$YAML_FILE" --map-file "$TMP_MAP" --verify
  mark_done "[step:component_repo_map] The component/image associations are verified in ${MAP_PATH} on konflux-central main. Onboarding may complete."
  exit 0
fi

EXISTING_URL=$(jq -r '.steps.component_repo_map.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

if uv run --script "$SCRIPTS_DIR/component_repo_map.py" \
  --details "$YAML_FILE" --map-file "$TMP_MAP" --verify >/dev/null 2>&1; then
  mark_done "[step:component_repo_map] The requested component/image associations already exist in ${MAP_PATH} on konflux-central main. No PR was needed."
  echo "Mapping already correct on main; no PR needed."
  exit 2
fi

cd "$WORKDIR"
PLAYPEN_OUTPUT=$(bash "$SCRIPTS_DIR/setup_github_playpen.sh" \
  --src-url "$RKC_URL" \
  --src-branch main \
  --dest-branch "${JIRA_ID}-component-repo-map" \
  --sparse-files "$MAP_PATH") || {
  echo "ERROR: Playpen setup failed for konflux-central component map." >&2; exit 1;
}
CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
CLONE_MAP="$CLONE_DIR/$MAP_PATH"
[[ -f "$CLONE_MAP" ]] || { echo "ERROR: $MAP_PATH not found in cloned konflux-central." >&2; exit 1; }

RESULT=$(uv run --script "$SCRIPTS_DIR/component_repo_map.py" \
  --details "$YAML_FILE" --map-file "$CLONE_MAP") || exit 1
if [[ "$RESULT" == "already-correct" ]]; then
  mark_done "[step:component_repo_map] The requested component/image associations are already present in ${MAP_PATH} on konflux-central main. No PR was needed."
  echo "Mapping already correct on main; no PR needed."
  exit 2
fi

bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files "$MAP_PATH" \
  --message "Register RHOAI component images for GAP gating" \
  --branch "$DEST_BRANCH"

PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
  --src-url "$RKC_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$RKC_URL" \
  --dest-branch main \
  --title "Register RHOAI component images for GAP gating" \
  --description "Register the RHOAI component-to-image delivery repository mappings required by GAP build gating.

Jira: ${JIRA_URL}") || {
  echo "ERROR: Could not create component map PR." >&2; exit 1;
}

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "component-repo-map-pr-raised" \
  --comment "[step:component_repo_map] GitHub PR raised to register the component/image associations in ${MAP_PATH}. The onboarding will remain incomplete until it is merged and the entries are verified on main.

PR URL: ${PR_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step component_repo_map \
  --status pr_raised --url "$PR_URL" --url-field pr_url

echo "PR_URL=${PR_URL}"
