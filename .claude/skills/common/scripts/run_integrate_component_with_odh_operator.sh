#!/usr/bin/env bash
# Main script for the integrate-component-with-odh-operator skill.
# Adds a new component entry to build/manifests-config.yaml in opendatahub-operator
# and raises a GitHub PR. Exits cleanly if is_operator=false.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Step 0: Parse Inputs ---
JIRA_URL=""
WORKDIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) WORKDIR_OVERRIDE="$2"; shift 2 ;;
    http*)     JIRA_URL="$1"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$JIRA_URL" || "$JIRA_URL" != *"/browse/"* ]]; then
  echo "Usage: $(basename "$0") <jira-url> [--workdir <path>]" >&2
  echo "  Example: $(basename "$0") https://redhat.atlassian.net/browse/RHODS-14226" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL##*/}"

ODH_OPERATOR_URL="${ODH_OPERATOR_REPO_URL:-https://github.com/opendatahub-io/opendatahub-operator.git}"
echo "ODH_OPERATOR_REPO_URL=${ODH_OPERATOR_REPO_URL:-(not set, using default)}"
echo "ODH_OPERATOR_URL resolved to: $ODH_OPERATOR_URL"

ODH_OPERATOR_PATH=$(echo "$ODH_OPERATOR_URL" | sed 's|https://github.com/||;s|\.git$||')

# --- Step 1: Check Prerequisites ---
bash "$SCRIPTS_DIR/check_prerequisites.sh" \
  --env   "GITHUB_USER GITHUB_TOKEN JIRA_USER_EMAIL JIRA_API_TOKEN" \
  --tools "uv git"

# --- Step 2: Set Up Working Directory ---
if [[ -n "$WORKDIR_OVERRIDE" ]]; then
  WORKDIR="$WORKDIR_OVERRIDE"
else
  WORKDIR="$(pwd)/${JIRA_ID}"
fi
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"

# --- Step 3: Fetch Jira Details and Component YAML ---
if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$JIRA_URL"); then
    echo "ERROR in Step 3a (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting." >&2
    exit 1
  fi
fi

YAML_PATH="$WORKDIR/component_onboarding_details.yaml"
if [[ ! -f "$YAML_PATH" ]]; then
  if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/download_jira_attachment.py" \
      "$JIRA_URL" component_onboarding_details.yaml); then
    echo "ERROR in Step 3b (Download YAML): Could not download 'component_onboarding_details.yaml' from Jira." >&2
    echo "  Ensure the attachment exists on the Jira issue before running this skill." >&2
    echo "  Run /create-component-onboarding-jira $JIRA_URL first." >&2
    exit 1
  fi
fi

_parse() {
  python3 -c "
import yaml, sys
with open('$YAML_PATH') as f:
    d = yaml.safe_load(f)
inp = d.get('inputs', {})
val = inp.get('$1', '')
print(str(val).lower() if isinstance(val, bool) else (val or ''))
" 2>/dev/null
}
COMPONENT_NAME="$(_parse component_name)"
PRODUCT_CONTEXT="$(_parse product_context)"
IS_OPERATOR="$(_parse is_operator)"
REPO_URL="$(_parse repo_url)"
REPO_BRANCH="$(_parse repo_branch)"
OPERATOR_MANIFEST_SRC_PATH="$(_parse operator_manifest_src_path)"
OPERATOR_MANIFEST_DEST_PATH="$(_parse operator_manifest_dest_path)"

for field_check in "COMPONENT_NAME:component_name" "PRODUCT_CONTEXT:product_context" "IS_OPERATOR:is_operator" "REPO_URL:repo_url" "REPO_BRANCH:repo_branch"; do
  var="${field_check%%:*}"
  key="${field_check##*:}"
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR in Step 3c: Missing required field '${key}' in component_onboarding_details.yaml. Aborting." >&2
    exit 1
  fi
done

# --- Step 4: Check is_operator Gate ---
if [[ "${IS_OPERATOR,,}" == "false" ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "operator-changes-not-needed" \
    --comment "Skipping odh-operator integration for '$COMPONENT_NAME'.

is_operator=false in component_onboarding_details.yaml. No changes to opendatahub-operator are required for this component." || true
  echo "$COMPONENT_NAME is not an operator (is_operator=false). No odh-operator changes needed."
  echo "Jira updated with label 'operator-changes-not-needed'."
  exit 0
fi

# is_operator=true — validate operator-specific fields
if [[ -z "${OPERATOR_MANIFEST_SRC_PATH:-}" || -z "${OPERATOR_MANIFEST_DEST_PATH:-}" ]]; then
  echo "ERROR in Step 4b: is_operator=true but operator_manifest_src_path or operator_manifest_dest_path" >&2
  echo "  is missing from component_onboarding_details.yaml." >&2
  echo "  Add both fields and re-upload the YAML to the Jira ticket. Aborting." >&2
  exit 1
fi

echo "is_operator=true. Proceeding with odh-operator integration."
echo "  component_name               : $COMPONENT_NAME"
echo "  operator_manifest_src_path   : $OPERATOR_MANIFEST_SRC_PATH"
echo "  operator_manifest_dest_path  : $OPERATOR_MANIFEST_DEST_PATH"
echo "  repo                         : $ODH_OPERATOR_URL"

# --- Step 5: Check If Component Already Exists in manifests-config.yaml ---
MANIFESTS_TMPFILE=$(mktemp)
FILE_EXIT=0
bash "$SCRIPTS_DIR/check_github_file.sh" \
  --repo-path "$ODH_OPERATOR_PATH" \
  --file-path "build/manifests-config.yaml" \
  --ref       main \
  --output    "$MANIFESTS_TMPFILE" || FILE_EXIT=$?

if [[ "$FILE_EXIT" -eq 1 ]]; then
  echo "WARN in Step 5: build/manifests-config.yaml not found on main branch (HTTP 404). Continuing."
  rm -f "$MANIFESTS_TMPFILE"
elif [[ "$FILE_EXIT" -eq 2 ]]; then
  echo "WARN in Step 5: Could not fetch build/manifests-config.yaml (API error). Continuing."
  rm -f "$MANIFESTS_TMPFILE"
elif [[ "$FILE_EXIT" -eq 0 ]]; then
  if grep -q "^  ${COMPONENT_NAME}:" "$MANIFESTS_TMPFILE" 2>/dev/null; then
    rm -f "$MANIFESTS_TMPFILE"
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "odh-operator-pr-raised" \
      --comment "'$COMPONENT_NAME' is already present in build/manifests-config.yaml on the main branch of opendatahub-operator.

No changes are needed. The odh-operator integration for this component is already complete." || true
    echo "$COMPONENT_NAME already exists in build/manifests-config.yaml (main branch)."
    echo "Jira updated with label 'odh-operator-pr-raised'. No action needed."
    exit 0
  fi
  rm -f "$MANIFESTS_TMPFILE"
fi

# --- Step 6: Check for Existing Open PR in Jira Comments ---
PR_URL=""
EXISTING_PRS=$(python3 -c "
import json, re
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
comments = d.get('fields', {}).get('comment', {}).get('comments', [])
pattern = re.compile(r'https://github\.com/[^/\s]+/opendatahub-operator/pull/\d+')
urls = []
for c in comments:
    urls.extend(pattern.findall(c.get('body', '')))
seen = set()
for u in urls:
    if u not in seen:
        seen.add(u)
        print(u)
" 2>/dev/null || true)

while IFS= read -r pr_url; do
  [[ -z "$pr_url" ]] && continue
  CHECK_OUT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
    --pr-url "$pr_url" --check-only 2>/dev/null || true)
  STATE=$(echo "$CHECK_OUT" | grep -o 'state=[a-z_]*' | cut -d= -f2 || true)
  TITLE=$(echo "$CHECK_OUT" | grep '^title=' | cut -d= -f2- || true)
  if [[ "$STATE" == "open" ]] && echo "$TITLE" | grep -qF "$COMPONENT_NAME"; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "Existing open GitHub PR found for '$COMPONENT_NAME' in opendatahub-operator: $pr_url.

No new PR will be raised. Review and merge the existing PR to complete this step." || true
    echo "Found existing open PR for $COMPONENT_NAME: $pr_url"
    echo "Jira updated. No new PR raised — review and merge the existing PR."
    exit 0
  elif [[ "$STATE" == "merged" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "odh-operator-changes-done" \
      --comment "odh-operator PR for '$COMPONENT_NAME' was already merged: $pr_url. No action needed.

Step 9 (Integrate with odh-operator) is complete." || true
    echo "PR already merged. Step 9 (odh-operator integration) is complete."
    exit 0
  fi
done <<< "$EXISTING_PRS"

# --- Step 7: Set Up Playpen (Clone) ---
eval "$(bash "$SCRIPTS_DIR/run_github_playpen.sh" \
  --src-url      "$ODH_OPERATOR_URL" \
  --src-branch   main \
  --dest-branch  "${JIRA_ID}" \
  --sparse-files "build" \
  --workdir      "$WORKDIR" \
  --scripts-dir  "$SCRIPTS_DIR")" || {
  echo "ERROR in Step 7 (Playpen setup): Clone or push failed. See details above." >&2
  echo "  Check network connectivity and GITHUB_TOKEN (needs push access to $ODH_OPERATOR_PATH)." >&2
  exit 1
}

# --- Step 8: Update build/manifests-config.yaml ---
MANIFESTS_FILE="$CLONE_DIR/build/manifests-config.yaml"
if [[ ! -f "$MANIFESTS_FILE" ]]; then
  echo "ERROR in Step 8: build/manifests-config.yaml not found in $CLONE_DIR." >&2
  echo "  Verify that $ODH_OPERATOR_URL points to the correct opendatahub-operator repository." >&2
  exit 1
fi

uv run --script "$SCRIPTS_DIR/edit_yaml.py" insert-map-key \
  "$MANIFESTS_FILE" \
  --map-key "map" \
  --name    "$COMPONENT_NAME" \
  --src     "$OPERATOR_MANIFEST_SRC_PATH" \
  --dest    "$OPERATOR_MANIFEST_DEST_PATH"

# --- Step 9: Commit and Push ---
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "build/manifests-config.yaml" \
  --message   "Add $COMPONENT_NAME to manifests-config.yaml" \
  --branch    "$DEST_BRANCH" || {
  echo "ERROR in Step 9 (Push): Could not push branch '$DEST_BRANCH' to origin. See details above." >&2
  exit 1
}

# --- Step 10: Raise PR (up to 3 attempts) ---
PR_ATTEMPTS=0
PR_URL=""
while [[ $PR_ATTEMPTS -lt 3 && -z "$PR_URL" ]]; do
  PR_ATTEMPTS=$((PR_ATTEMPTS + 1))
  PR_ERR=$(mktemp)
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url "$ODH_OPERATOR_URL" \
    --src-branch "$DEST_BRANCH" \
    --dest-url "$ODH_OPERATOR_URL" \
    --dest-branch main \
    --title "Add $COMPONENT_NAME to manifests-config.yaml" \
    --description "Adds '$COMPONENT_NAME' to the operator manifests config map.

Component: $COMPONENT_NAME
Manifest source path: $OPERATOR_MANIFEST_SRC_PATH
Manifest dest path:   $OPERATOR_MANIFEST_DEST_PATH
Upstream repo: $REPO_URL @ $REPO_BRANCH
Jira: $JIRA_URL

**File changed:**
- \`build/manifests-config.yaml\` — added \`$COMPONENT_NAME\` entry under \`map:\`" 2>"$PR_ERR") || {
    cat "$PR_ERR" >&2
    rm -f "$PR_ERR"
    PR_URL=""
    if [[ $PR_ATTEMPTS -lt 3 ]]; then
      echo "PR creation attempt $PR_ATTEMPTS failed. Retrying..."
      sleep 5
    fi
    continue
  }
  rm -f "$PR_ERR"
done

if [[ -z "$PR_URL" ]]; then
  echo "ERROR in Step 10 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting." >&2
  exit 1
fi

echo "PR raised: $PR_URL"
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "odh-operator-pr-raised" \
  --comment "GitHub PR raised to add '$COMPONENT_NAME' to opendatahub-operator manifests config.

PR URL: $PR_URL

Changes will take effect once this PR is reviewed and merged.
File changed: build/manifests-config.yaml (map entry added for $COMPONENT_NAME)." || true

# Write PR URL for parent orchestrator
echo "$PR_URL" > "$WORKDIR/operator_pr_url"

# --- Step 11: Report Completion ---
echo ""
echo "Done."
echo ""
echo "  build/manifests-config.yaml  — $COMPONENT_NAME entry added under map:"
echo "  GitHub PR                    — raised: $PR_URL"
echo "  Jira                         — updated (label: odh-operator-pr-raised)"
echo ""
echo "  component_name               : $COMPONENT_NAME"
echo "  operator_manifest_src_path   : $OPERATOR_MANIFEST_SRC_PATH"
echo "  operator_manifest_dest_path  : $OPERATOR_MANIFEST_DEST_PATH"
echo "  repo                         : $ODH_OPERATOR_URL"
echo ""
echo "Next step: review and merge the PR, then mark Step 9 complete in Jira."
