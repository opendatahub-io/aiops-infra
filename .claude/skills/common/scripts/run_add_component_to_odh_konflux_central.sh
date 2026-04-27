#!/usr/bin/env bash
# Main script for the add-component-to-odh-konflux-central skill.
# Generates PipelineRun YAMLs from templates, updates the onboarder workflow,
# and raises a GitHub PR to odh-konflux-central.
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
  echo "  Example: $(basename "$0") https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL##*/}"

OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
echo "ODH_KONFLUX_CENTRAL_REPO_URL=${ODH_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
echo "OKC_URL resolved to: $OKC_URL"

OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')

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
    exit 1
  fi
fi

_parse() {
  python3 -c "
import yaml, sys
with open('$YAML_PATH') as f:
    d = yaml.safe_load(f)
inp = d.get('inputs', {})
print(inp.get('$1', '') or '')
" 2>/dev/null
}
COMPONENT_NAME="$(_parse component_name)"
REPO_URL="$(_parse repo_url)"
REPO_BRANCH="$(_parse repo_branch)"
CONTEXT_PATH="$(_parse context_path)"
DOCKERFILE_PATH="$(_parse dockerfile_path)"
BUILD_TYPE="$(_parse build_type)"
INPUTS_OUTPUT_IMAGE_TAG="$(_parse output_image_tag)"
PRODUCT_CONTEXT_YAML="$(_parse product_context)"

for field_check in "COMPONENT_NAME:component_name" "REPO_URL:repo_url" "REPO_BRANCH:repo_branch" "CONTEXT_PATH:context_path" "DOCKERFILE_PATH:dockerfile_path" "BUILD_TYPE:build_type"; do
  var="${field_check%%:*}"
  key="${field_check##*:}"
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR in Step 3c: Missing required field '${key}' in component_onboarding_details.yaml. Aborting." >&2
    exit 1
  fi
done

eval "$(bash "$SCRIPTS_DIR/derive_okc_pipeline_vars.sh" \
  --component-name   "$COMPONENT_NAME" \
  --repo-url         "$REPO_URL" \
  --build-type       "$BUILD_TYPE" \
  --output-image-tag "${INPUTS_OUTPUT_IMAGE_TAG:-}")"

# --- Step 4: Determine Product Context ---
PRODUCT_CONTEXT=""

if [[ -n "${PRODUCT_CONTEXT_YAML:-}" ]]; then
  case "${PRODUCT_CONTEXT_YAML^^}" in
    RHOAI) PRODUCT_CONTEXT="RHOAI" ;;
    ODH)   PRODUCT_CONTEXT="ODH" ;;
  esac
fi

if [[ -z "$PRODUCT_CONTEXT" && -f "$WORKDIR/component_onboarding_details.json" ]]; then
  JIRA_SUMMARY=$(python3 -c "
import json
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
print(d.get('fields', {}).get('summary', ''))
" 2>/dev/null || true)
  if echo "$JIRA_SUMMARY" | grep -qi "RHOAI"; then
    PRODUCT_CONTEXT="RHOAI"
  elif echo "$JIRA_SUMMARY" | grep -qi "ODH"; then
    PRODUCT_CONTEXT="ODH"
  fi
fi

if [[ -z "$PRODUCT_CONTEXT" ]]; then
  while true; do
    printf "I could not determine the product context from the YAML or the Jira title.\nIs this onboarding for ODH or RHOAI? (ODH/RHOAI): "
    read -r PRODUCT_CONTEXT
    PRODUCT_CONTEXT="${PRODUCT_CONTEXT^^}"
    case "$PRODUCT_CONTEXT" in
      ODH|RHOAI) break ;;
      *) echo "  Invalid. Must be ODH or RHOAI." ;;
    esac
  done
fi

case "${PRODUCT_CONTEXT^^}" in
  ODH)
    NAMESPACE="open-data-hub-tenant"
    APPLICATION="opendatahub-builds"
    QUAY_ORG="opendatahub"
    ;;
  RHOAI)
    NAMESPACE="rhoai-tenant"
    APPLICATION="rhoai-builds"
    QUAY_ORG="rhoai"
    ;;
  *)
    echo "ERROR in Step 4: Unknown PRODUCT_CONTEXT '${PRODUCT_CONTEXT}'. Expected ODH or RHOAI." >&2
    exit 1
    ;;
esac

# --- Step 5: Check If PipelineRuns Already Exist ---
PUSH_EXIT=0
PR_EXIT=0
bash "$SCRIPTS_DIR/check_github_file.sh" \
  --repo-path "$OKC_PATH" \
  --file-path "pipelineruns/${REPO_NAME}/${PUSH_YAML_FILE}" \
  --ref       main \
  --output    /dev/null || PUSH_EXIT=$?

bash "$SCRIPTS_DIR/check_github_file.sh" \
  --repo-path "$OKC_PATH" \
  --file-path "pipelineruns/${REPO_NAME}/${PR_YAML_FILE}" \
  --ref       main \
  --output    /dev/null || PR_EXIT=$?

if [[ "$PUSH_EXIT" -eq 2 || "$PR_EXIT" -eq 2 ]]; then
  echo "ERROR in Step 5: Could not reach GitHub API. Check network connectivity and GITHUB_TOKEN." >&2
  exit 1
fi

if [[ "$PUSH_EXIT" -eq 0 && "$PR_EXIT" -eq 0 ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "okc-changes-done" \
    --comment "PipelineRun files for '$COMPONENT_NAME' already exist in OKC repo at 'pipelineruns/$REPO_NAME/'. No action needed." || true
  echo "PipelineRuns already exist in OKC. Nothing to do."
  exit 0
fi

# --- Step 6: Check for Existing Open PR in Jira Comments ---
OKC_PR_URL=""
EXISTING_PRS=$(python3 -c "
import json, re
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
comments = d.get('fields', {}).get('comment', {}).get('comments', [])
pattern = re.compile(r'https://github\.com/[^/\s]+/[^/\s]+/pull/\d+')
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
  if [[ "$STATE" == "open" ]] && \
     (echo "$TITLE" | grep -qF "$COMPONENT_NAME" || echo "$TITLE" | grep -qF "$KONFLUX_COMPONENT_NAME"); then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "Found existing open GitHub PR for $COMPONENT_NAME: $pr_url. Monitoring it." || true
    echo "Found existing open PR: $pr_url. Skipping PR creation and jumping to monitor."
    OKC_PR_URL="$pr_url"
    break
  fi
done <<< "$EXISTING_PRS"

# --- Steps 7–9: Clone, generate files, raise PR (skip if resuming existing PR) ---
if [[ -z "$OKC_PR_URL" ]]; then

  # --- Step 7: Set Up Playpen ---
  eval "$(bash "$SCRIPTS_DIR/run_github_playpen.sh" \
    --src-url      "$OKC_URL" \
    --src-branch   main \
    --dest-branch  "${JIRA_ID}" \
    --sparse-files "pipelineruns/template pipelineruns/$REPO_NAME .github/workflows" \
    --workdir      "$WORKDIR" \
    --scripts-dir  "$SCRIPTS_DIR")" || {
    echo "ERROR in Step 7 (Playpen setup): Clone or push failed. See details above." >&2
    echo "  Check network connectivity and GITHUB_TOKEN repo scope." >&2
    exit 1
  }

  # --- Step 8: Generate PipelineRun Files and Update Workflow ---

  # 8b. Create repo directory
  mkdir -p "$CLONE_DIR/pipelineruns/$REPO_NAME"

  # 8c. Generate push PipelineRun
  PUSH_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PUSH_YAML_FILE"
  cp "$CLONE_DIR/pipelineruns/template/odh-component-push.yaml" "$PUSH_FILE"

  REPO_URL="$REPO_URL" REPO_BRANCH="$REPO_BRANCH" \
  KONFLUX_COMPONENT_NAME="$KONFLUX_COMPONENT_NAME" \
  PUSH_RUN_NAME="$PUSH_RUN_NAME" QUAY_ORG="$QUAY_ORG" \
  COMPONENT_NAME="$COMPONENT_NAME" PUSH_OUTPUT_IMAGE_TAG="$PUSH_OUTPUT_IMAGE_TAG" \
  DOCKERFILE_PATH="$DOCKERFILE_PATH" CONTEXT_PATH="$CONTEXT_PATH" \
  SERVICE_ACCOUNT_NAME="$SERVICE_ACCOUNT_NAME" \
  NAMESPACE="$NAMESPACE" APPLICATION="$APPLICATION" \
  python3 - "$PUSH_FILE" << 'PYEOF'
import sys, os
f = sys.argv[1]
content = open(f).read()
E = os.environ
subs = [
    ('component-git-url', E['REPO_URL']),
    ('$$TARGET_BRANCH$$', E['REPO_BRANCH']),
    ('odh-component-name-ci', E['KONFLUX_COMPONENT_NAME']),
    ('odh-file-name-on-push', E['PUSH_RUN_NAME']),
    ('quay.io/opendatahub/quayurl', f"quay.io/{E['QUAY_ORG']}/{E['COMPONENT_NAME']}"),
    ('$$OUTPUT_IMAGE_TAG$$', E['PUSH_OUTPUT_IMAGE_TAG']),
    ('dockerfilepath', E['DOCKERFILE_PATH']),
    ('    value: .', f"    value: {E['CONTEXT_PATH']}"),
    ('build-pipeline-sa-namw', E['SERVICE_ACCOUNT_NAME']),
    ('open-data-hub-tenant', E['NAMESPACE']),
    ('opendatahub-builds', E['APPLICATION']),
]
for old, new in subs:
    content = content.replace(old, new)
open(f, 'w').write(content)
print(f"Generated push PipelineRun: {f}")
PYEOF

  # 8d. Generate pull-request PipelineRun
  PR_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PR_YAML_FILE"
  cp "$CLONE_DIR/pipelineruns/template/odh-component-pull-request.yaml" "$PR_FILE"

  REPO_URL="$REPO_URL" REPO_BRANCH="$REPO_BRANCH" \
  KONFLUX_COMPONENT_NAME="$KONFLUX_COMPONENT_NAME" \
  PR_RUN_NAME="$PR_RUN_NAME" QUAY_ORG="$QUAY_ORG" \
  COMPONENT_NAME="$COMPONENT_NAME" PR_OUTPUT_IMAGE_TAG="$PR_OUTPUT_IMAGE_TAG" \
  DOCKERFILE_PATH="$DOCKERFILE_PATH" CONTEXT_PATH="$CONTEXT_PATH" \
  SERVICE_ACCOUNT_NAME="$SERVICE_ACCOUNT_NAME" \
  NAMESPACE="$NAMESPACE" APPLICATION="$APPLICATION" \
  python3 - "$PR_FILE" << 'PYEOF'
import sys, os
f = sys.argv[1]
content = open(f).read()
E = os.environ
subs = [
    ('build.appstudio.openshift.io/repo: #component-git-url?rev={{revision}}',
     f"build.appstudio.openshift.io/repo: {E['REPO_URL']}?rev={{{{revision}}}}"),
    ('$$TARGET_BRANCH$$', E['REPO_BRANCH']),
    ('odh-component-name-ci', E['KONFLUX_COMPONENT_NAME']),
    ('  name: #odh-file-name-on-pull-request', f"  name: {E['PR_RUN_NAME']}"),
    ('quay.io/opendatahub/quayurl', f"quay.io/{E['QUAY_ORG']}/{E['COMPONENT_NAME']}"),
    ('$$OUTPUT_IMAGE_TAG$$', E['PR_OUTPUT_IMAGE_TAG']),
    ('dockerfilepath', E['DOCKERFILE_PATH']),
    ('    value: .', f"    value: {E['CONTEXT_PATH']}"),
    ('    serviceAccountName: #build-pipeline-sa-name', f"    serviceAccountName: {E['SERVICE_ACCOUNT_NAME']}"),
    ('  #add these additional params', '  # additional params'),
    ('open-data-hub-tenant', E['NAMESPACE']),
    ('opendatahub-builds', E['APPLICATION']),
]
for old, new in subs:
    content = content.replace(old, new)
open(f, 'w').write(content)
print(f"Generated PR PipelineRun: {f}")
PYEOF

  # 8e. Update the onboarder workflow
  WORKFLOW_FILE="$CLONE_DIR/.github/workflows/odh-konflux-onboarder.yml"
  if [[ ! -f "$WORKFLOW_FILE" ]]; then
    echo "WARNING in Step 8e: odh-konflux-onboarder.yml not found. Skipping workflow update." >&2
  else
    REPO_NAME="$REPO_NAME" python3 - "$WORKFLOW_FILE" << 'PYEOF'
import sys, os, re
workflow_file = sys.argv[1]
repo_name = os.environ['REPO_NAME']

with open(workflow_file) as f:
    lines = f.readlines()

in_options = False
insert_idx = None
indent = '          '
option_re = re.compile(r'^(\s+)- (.+)\s*$')
options_re = re.compile(r'^\s+options:\s*$')

for i, line in enumerate(lines):
    if options_re.match(line):
        in_options = True
        continue
    if in_options:
        m = option_re.match(line)
        if m:
            indent = m.group(1)
            name = m.group(2).strip()
            if name == repo_name:
                print(f"'{repo_name}' already in onboarder workflow component list — skipping.", file=sys.stderr)
                sys.exit(0)
            if name > repo_name and insert_idx is None:
                insert_idx = i
                break
            insert_idx = i + 1
        else:
            if insert_idx is None:
                insert_idx = i
            break

if insert_idx is None:
    print(f"ERROR: Could not find options: list in {workflow_file}", file=sys.stderr)
    sys.exit(1)

lines.insert(insert_idx, f"{indent}- {repo_name}\n")
with open(workflow_file, 'w') as f:
    f.writelines(lines)
print(f"Inserted '{repo_name}' into onboarder workflow options in alphabetical order.")
PYEOF
  fi

  # 8f. Commit all changes
  PUSH_ERR=$(mktemp)
  (cd "$CLONE_DIR" && git add -A && git commit -m "Add $KONFLUX_COMPONENT_NAME PipelineRuns for $REPO_NAME")

  # 8g. Push to remote
  if ! (cd "$CLONE_DIR" && git push origin "$DEST_BRANCH") 2>"$PUSH_ERR"; then
    if grep -q "shallow update not allowed" "$PUSH_ERR"; then
      (cd "$CLONE_DIR" && git fetch --unshallow origin && git push origin "$DEST_BRANCH")
    else
      cat "$PUSH_ERR" >&2
      rm -f "$PUSH_ERR"
      echo "ERROR in Step 8g: Could not push branch '$DEST_BRANCH' to origin." >&2
      exit 1
    fi
  fi
  rm -f "$PUSH_ERR"

  # --- Step 9: Raise PR (up to 3 attempts) ---
  PR_ATTEMPTS=0
  OKC_PR_URL=""
  while [[ $PR_ATTEMPTS -lt 3 && -z "$OKC_PR_URL" ]]; do
    PR_ATTEMPTS=$((PR_ATTEMPTS + 1))
    PR_ERR=$(mktemp)
    OKC_PR_URL=$(uv run --script "$SCRIPTS_DIR/raise_github_pr.py" \
      --src-url "$OKC_URL" \
      --src-branch "$DEST_BRANCH" \
      --dest-url "$OKC_URL" \
      --dest-branch main \
      --title "Add $KONFLUX_COMPONENT_NAME PipelineRuns for $COMPONENT_NAME" \
      --description "Add Konflux CI PipelineRuns for '$COMPONENT_NAME' from repo '$REPO_NAME'.

Product: $PRODUCT_CONTEXT
Application: $APPLICATION
Output image: quay.io/$QUAY_ORG/$COMPONENT_NAME:$PUSH_OUTPUT_IMAGE_TAG
Source repo: $REPO_URL @ $REPO_BRANCH
Jira: $JIRA_URL

**Files changed:**
- \`pipelineruns/$REPO_NAME/$PUSH_YAML_FILE\` (new)
- \`pipelineruns/$REPO_NAME/$PR_YAML_FILE\` (new)
- \`.github/workflows/odh-konflux-onboarder.yml\` (updated: added $REPO_NAME to components list)" 2>"$PR_ERR") || {
      cat "$PR_ERR" >&2
      rm -f "$PR_ERR"
      OKC_PR_URL=""
      if [[ $PR_ATTEMPTS -lt 3 ]]; then
        echo "PR creation attempt $PR_ATTEMPTS failed. Retrying..."
        sleep 5
      fi
      continue
    }
    rm -f "$PR_ERR"
  done

  if [[ -z "$OKC_PR_URL" ]]; then
    echo "ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting." >&2
    exit 1
  fi

  echo "PR raised: $OKC_PR_URL"
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "okc-pr-raised" \
    --comment "GitHub PR raised to add Konflux PipelineRuns for '$COMPONENT_NAME' to odh-konflux-central.

PR URL: $OKC_PR_URL

CI builds will start for '$COMPONENT_NAME' once this PR is merged." || true

  # Write PR URL for parent orchestrator
  echo "$OKC_PR_URL" > "$WORKDIR/okc_pr_url"

fi  # end of Steps 7–9

# --- Step 10: Monitor PR ---
MONITOR_RESULT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
  --pr-url "$OKC_PR_URL" \
  --timeout 60 2>/dev/null || echo "timeout")

case "$MONITOR_RESULT" in
  *merged*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --remove-label "okc-pr-raised" \
      --comment "PR merged: $OKC_PR_URL

Konflux CI is now configured for '$COMPONENT_NAME'. Builds will trigger on pushes and
pull requests to '$REPO_BRANCH' branch of $REPO_URL.

Step 4 (odh-konflux-central update) is complete." || true
    echo "PR merged. Step 4 (odh-konflux-central update) complete."
    ;;
  *closed*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "GitHub PR was closed without merging: $OKC_PR_URL

Please review the PR and re-run /update-component-using-odh-konflux-central if needed." || true
    echo "ERROR in Step 10 (Monitor PR): PR was closed without merging. Check the PR: $OKC_PR_URL" >&2
    exit 1
    ;;
  *pipeline_failed*|*pipeline_canceled*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "CI checks failed on PR $OKC_PR_URL.

Please review the PR checks and re-run /update-component-using-odh-konflux-central if the issue persists." || true
    echo "ERROR in Step 10 (Monitor PR): CI checks failed. Manual intervention needed." >&2
    echo "  PR: $OKC_PR_URL" >&2
    exit 1
    ;;
  *)
    # timeout
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "PR monitoring timed out after 60 minutes. PR is still open: $OKC_PR_URL

Please check the PR status manually. Re-run /update-component-using-odh-konflux-central
to resume — it will detect the existing open PR at Step 6 and jump straight to monitoring." || true
    echo "WARNING: PR monitoring timed out after 60 minutes."
    echo "The PR is still open: $OKC_PR_URL"
    echo "Re-run this skill when the PR is merged (it will short-circuit at Step 6)."
    exit 1
    ;;
esac

# --- Step 11: Final Jira Update ---
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "okc-changes-done" \
  --comment "odh-konflux-central update complete.

Component: $COMPONENT_NAME ($KONFLUX_COMPONENT_NAME)
Repo: $REPO_URL @ $REPO_BRANCH
Output image: quay.io/$QUAY_ORG/$COMPONENT_NAME:$PUSH_OUTPUT_IMAGE_TAG
PipelineRuns added:
  - pipelineruns/$REPO_NAME/$PUSH_YAML_FILE
  - pipelineruns/$REPO_NAME/$PR_YAML_FILE
Workflow updated: .github/workflows/odh-konflux-onboarder.yml

PR: $OKC_PR_URL (merged)

Step 4 (Add to odh-konflux-central) is complete." || true

echo "odh-konflux-central updated. '$COMPONENT_NAME' PipelineRuns are live."
echo "  Step 4 (Add to odh-konflux-central) complete."
