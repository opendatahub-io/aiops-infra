#!/usr/bin/env bash
# Main script for the integrate-component-with-bundle skill.
# Updates bundle/bundle-patch.yaml in ODH-Build-Config and raises a GitHub PR.
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

OBC_URL="${OBC_REPO_URL:-https://github.com/opendatahub-io/ODH-Build-Config.git}"
echo "OBC_REPO_URL=${OBC_REPO_URL:-(not set, using default)}"
echo "OBC_URL resolved to: $OBC_URL"

OBC_PATH=$(echo "$OBC_URL" | sed 's|https://github.com/||;s|\.git$||')

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
    echo "  Ensure the attachment exists on the Jira issue. Run /create-component-onboarding-jira first." >&2
    exit 1
  fi
fi

_parse() {
  python3 -c "
import yaml, sys
with open('$YAML_PATH') as f:
    d = yaml.safe_load(f)
inp = d.get('inputs', {})
print(inp.get('$1', ''))
" 2>/dev/null
}
COMPONENT_NAME="$(_parse component_name)"
PRODUCT_CONTEXT="$(_parse product_context)"
REPO_URL="$(_parse repo_url)"
REPO_BRANCH="$(_parse repo_branch)"

for field_check in "COMPONENT_NAME:component_name" "PRODUCT_CONTEXT:product_context" "REPO_URL:repo_url" "REPO_BRANCH:repo_branch"; do
  var="${field_check%%:*}"
  key="${field_check##*:}"
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR in Step 3c: Missing required field '${key}' in component_onboarding_details.yaml. Aborting." >&2
    exit 1
  fi
done

eval "$(bash "$SCRIPTS_DIR/derive_bundle_vars.sh" \
  --component-name  "$COMPONENT_NAME" \
  --product-context "$PRODUCT_CONTEXT")"

DIGEST_LINE=$(bash "$SCRIPTS_DIR/resolve_image_digest.sh" --image "$STABLE_IMAGE" 2>/dev/null || true)
RESOLVE_EXIT=$?
DIGEST="${DIGEST_LINE#digest=}"

if [[ $RESOLVE_EXIT -eq 0 && -n "$DIGEST" ]]; then
  RELATED_IMAGE_VALUE="quay.io/${QUAY_ORG}/${COMPONENT_NAME}@${DIGEST}"
  USING_PLACEHOLDER=false
  echo "  Fetched real digest from Quay: $DIGEST"
else
  DIGEST="${DIGEST:-sha256:0000000000000000000000000000000000000000000000000000000000000000}"
  RELATED_IMAGE_VALUE="quay.io/${QUAY_ORG}/${COMPONENT_NAME}@${DIGEST}"
  USING_PLACEHOLDER=true
  echo "  WARNING: Image not yet published to Quay — using placeholder digest."
  echo "  Update bundle-patch.yaml with the real digest before merging the PR."
fi

echo ""
echo "Component: $COMPONENT_NAME"
echo "Product context: $PRODUCT_CONTEXT → QUAY_ORG=$QUAY_ORG"
echo "Related image name: $RELATED_IMAGE_NAME"
echo "Related image value: $RELATED_IMAGE_VALUE"
echo "Repo: $OBC_URL"

# --- Step 4: Check If Component Already Exists in bundle-patch.yaml ---
BUNDLE_TMPFILE=$(mktemp)
FILE_EXIT=0
bash "$SCRIPTS_DIR/check_github_file.sh" \
  --repo-path "$OBC_PATH" \
  --file-path "bundle/bundle-patch.yaml" \
  --ref       main \
  --output    "$BUNDLE_TMPFILE" || FILE_EXIT=$?

if [[ "$FILE_EXIT" -eq 1 ]]; then
  echo "WARN in Step 4: bundle/bundle-patch.yaml not found on main branch (HTTP 404). Continuing."
  rm -f "$BUNDLE_TMPFILE"
elif [[ "$FILE_EXIT" -eq 2 ]]; then
  echo "WARN in Step 4: Could not fetch bundle/bundle-patch.yaml (API error). Continuing."
  rm -f "$BUNDLE_TMPFILE"
elif [[ "$FILE_EXIT" -eq 0 ]]; then
  if grep -q "${RELATED_IMAGE_NAME}" "$BUNDLE_TMPFILE" 2>/dev/null; then
    rm -f "$BUNDLE_TMPFILE"
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "obc-changes-done" \
      --comment "'$COMPONENT_NAME' ($RELATED_IMAGE_NAME) is already present in bundle/bundle-patch.yaml on the main branch of ODH-Build-Config.

No changes are needed. The ODH-Build-Config integration for this component is already complete." || true
    echo "$RELATED_IMAGE_NAME already exists in bundle/bundle-patch.yaml (main branch)."
    echo "Jira updated with label 'obc-changes-done'. No action needed."
    exit 0
  fi
  rm -f "$BUNDLE_TMPFILE"
fi

# --- Step 5: Check for Existing Open PR in Jira Comments ---
PR_URL=""
EXISTING_PRS=$(python3 -c "
import json, re
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
comments = d.get('fields', {}).get('comment', {}).get('comments', [])
pattern = re.compile(r'https://github\.com/[^/\s]+/ODH-Build-Config/pull/\d+')
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
      --comment "Existing open GitHub PR found for '$COMPONENT_NAME' in ODH-Build-Config: $pr_url.

No new PR will be raised. Review and merge the existing PR to complete this step." || true
    echo "Found existing open PR for $COMPONENT_NAME: $pr_url"
    echo "Jira updated. No new PR raised — review and merge the existing PR."
    exit 0
  elif [[ "$STATE" == "merged" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "obc-changes-done" \
      --comment "ODH-Build-Config PR for '$COMPONENT_NAME' was already merged: $pr_url. No action needed.

Step 8 (Integrate with Bundle) is complete." || true
    echo "PR already merged. Step 8 (integrate-with-bundle) is complete."
    exit 0
  fi
done <<< "$EXISTING_PRS"

# --- Step 6: Set Up Playpen (Clone) ---
eval "$(bash "$SCRIPTS_DIR/run_github_playpen.sh" \
  --src-url      "$OBC_URL" \
  --src-branch   main \
  --dest-branch  "${JIRA_ID}" \
  --sparse-files "bundle" \
  --workdir      "$WORKDIR" \
  --scripts-dir  "$SCRIPTS_DIR")" || {
  echo "ERROR in Step 6 (Playpen setup): Clone or push failed. See details above." >&2
  echo "  Check network connectivity and GITHUB_TOKEN (needs push access to $OBC_PATH)." >&2
  exit 1
}

# --- Step 7: Update bundle/bundle-patch.yaml ---
BUNDLE_FILE="$CLONE_DIR/bundle/bundle-patch.yaml"
if [[ ! -f "$BUNDLE_FILE" ]]; then
  echo "ERROR in Step 7: bundle/bundle-patch.yaml not found in $CLONE_DIR." >&2
  echo "  Verify that $OBC_URL points to the correct ODH-Build-Config repository." >&2
  exit 1
fi

uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-array-entry \
  "$BUNDLE_FILE" \
  --array-key "patch.relatedImages" \
  --name  "$RELATED_IMAGE_NAME" \
  --value "$RELATED_IMAGE_VALUE"

# --- Step 8: Commit and Push ---
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "bundle/bundle-patch.yaml" \
  --message   "Add $COMPONENT_NAME to bundle-patch.yaml" \
  --branch    "$DEST_BRANCH" || {
  echo "ERROR in Step 8 (Push): Could not push branch '$DEST_BRANCH' to origin. See details above." >&2
  exit 1
}

# --- Step 9: Raise PR (up to 3 attempts) ---
if [[ "${USING_PLACEHOLDER}" == "true" ]]; then
  PLACEHOLDER_NOTE="> **NOTE:** The SHA256 digest for \`$RELATED_IMAGE_NAME\` is a **placeholder** — the image has not yet been built by Konflux.
> Before merging this PR, replace the digest with the real value:
> \`\`\`
> skopeo inspect --no-creds docker://quay.io/${QUAY_ORG}/${COMPONENT_NAME}:odh-stable | jq -r '.Digest'
> \`\`\`"
else
  PLACEHOLDER_NOTE=""
fi

PR_ATTEMPTS=0
PR_URL=""
while [[ $PR_ATTEMPTS -lt 3 && -z "$PR_URL" ]]; do
  PR_ATTEMPTS=$((PR_ATTEMPTS + 1))
  PR_ERR=$(mktemp)
  PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
    --src-url "$OBC_URL" \
    --src-branch "$DEST_BRANCH" \
    --dest-url "$OBC_URL" \
    --dest-branch main \
    --title "Add $COMPONENT_NAME to bundle-patch.yaml" \
    --description "Adds '$COMPONENT_NAME' to the ODH-Build-Config bundle relatedImages.

Component: $COMPONENT_NAME
Product context: $PRODUCT_CONTEXT
Quay org: $QUAY_ORG
Upstream repo: $REPO_URL @ $REPO_BRANCH
Jira: $JIRA_URL

**File changed:**
- \`bundle/bundle-patch.yaml\` — added \`$RELATED_IMAGE_NAME\` to \`patch.relatedImages\`

${PLACEHOLDER_NOTE}" 2>"$PR_ERR") || {
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
  echo "ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting." >&2
  exit 1
fi

echo "PR raised: $PR_URL"
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "obc-changes-done" \
  --comment "GitHub PR raised to add '$COMPONENT_NAME' to ODH-Build-Config.

PR URL: $PR_URL

File changed:
- bundle/bundle-patch.yaml: $RELATED_IMAGE_NAME added to patch.relatedImages" || true

# Write PR URL for parent orchestrator
echo "$PR_URL" > "$WORKDIR/bundle_pr_url"

# --- Step 10: Monitor the PR ---
MONITOR_RESULT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
  --pr-url "$PR_URL" \
  --timeout 60 2>/dev/null || echo "timeout")

case "$MONITOR_RESULT" in
  *merged*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --remove-label "obc-changes-done" \
      --add-label "obc-pr-merged" \
      --comment "ODH-Build-Config PR merged: $PR_URL

bundle/bundle-patch.yaml for '$COMPONENT_NAME' is now live on main.

Step 8 (Integrate with Bundle) is complete." || true
    ;;
  *closed*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "ODH-Build-Config PR was closed without merging: $PR_URL

Please review and re-trigger if needed." || true
    echo "ERROR in Step 10: PR was closed without merging." >&2
    echo "PR: $PR_URL" >&2
    exit 1
    ;;
  *pipeline_failed*|*pipeline_canceled*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "CI checks failed on ODH-Build-Config PR: $PR_URL

Please review the PR checks and push a fix, then re-run this skill to resume monitoring." || true
    echo "ERROR in Step 10: CI checks failed on PR $PR_URL." >&2
    echo "Manual intervention required — review the PR and push a fix, then re-run." >&2
    exit 1
    ;;
  *)
    # timeout
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "PR monitoring timed out after 60 minutes. PR is still open: $PR_URL

Re-run /integrate-component-with-bundle to resume — at Step 5 it will detect the
existing PR and jump straight to monitoring." || true
    echo "WARNING: PR monitoring timed out after 60 minutes."
    echo "PR is still open: $PR_URL"
    echo "Re-run this skill to resume monitoring (Step 5 will skip raising a new PR)."
    exit 1
    ;;
esac

# --- Step 11: Report Completion ---
echo ""
echo "Done."
echo ""
echo "  bundle/bundle-patch.yaml    — $RELATED_IMAGE_NAME added to patch.relatedImages"
echo "  GitHub PR                   — merged: $PR_URL"
echo "  Jira                        — updated (label: obc-pr-merged)"
echo ""
echo "  component_name              : $COMPONENT_NAME"
echo "  product_context             : $PRODUCT_CONTEXT"
echo "  quay_org                    : $QUAY_ORG"
echo "  related_image_name          : $RELATED_IMAGE_NAME"
echo "  repo                        : $OBC_URL"
echo ""
echo "Step 8 (Integrate with Bundle) is complete."
