---
name: update-component-using-odh-konflux-central
description: Onboards a new ODH/RHOAI component onto the Konflux CI platform by adding PipelineRun YAMLs and updating the onboarder workflow in the odh-konflux-central GitHub repository and raising a pull request. Automates Step 4 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Update Component Using ODH-Konflux-Central

Creates Tekton `PipelineRun` resources for a new ODH/RHOAI component by:
1. Generating push and pull-request PipelineRun YAMLs from the OKC templates.
2. Adding the component's GitHub repo to the onboarder workflow's component list.
3. Raising a pull request to `odh-konflux-central`. When merged, Konflux CI will
   start building the component.

> **CRITICAL — `ODH_KONFLUX_CENTRAL_REPO_URL` overrides the default repo for every step.**
> This env var is resolved once in Step 0 into `OKC_URL` and `OKC_PATH`.
> Every subsequent Git clone, push, GitHub API call, and PR operation **must** use
> `$OKC_URL` / `$OKC_PATH` — never the hardcoded upstream URL
> `https://github.com/opendatahub-io/odh-konflux-central.git`.
> This rule holds for the entire skill execution, even if the URL resolves to a personal fork.

## Usage

```
/update-component-using-odh-konflux-central <jira-url>
```

Examples:
```
/update-component-using-odh-konflux-central https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Prerequisites

- `GITHUB_USER` — your GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — GitHub personal access token with `repo` scope
- `JIRA_USER_EMAIL` — your Atlassian account email
- `JIRA_API_TOKEN` — Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Optional: `ODH_KONFLUX_CENTRAL_REPO_URL` (default: `https://github.com/opendatahub-io/odh-konflux-central.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**Jira attachment:** The Jira issue must have `component_onboarding_details.yaml` attached.
This YAML is the source of truth for all component parameters.

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.


---

## Step 0: Parse Inputs

1. Extract `<jira-url>` (the first positional argument). It must be a full Jira URL.
   Extract `<jira-id>` as the last path segment (e.g., `RHOAIENG-1234`, `RHODS-5678`).

   If the argument cannot be parsed as a Jira URL (no `/browse/` segment), stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

2. Resolve `OKC_URL` — the single source of truth for all Git and GitHub operations in
   this skill. Execute this exact block; do NOT skip the `echo`:

   ```bash
   OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
   echo "ODH_KONFLUX_CENTRAL_REPO_URL=${ODH_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
   echo "OKC_URL resolved to: $OKC_URL"
   ```

   The `echo` output confirms which repo is active for the entire skill run.
   **Never override or re-derive `OKC_URL` in later steps.** If any step appears to use
   a different URL, that is a bug — stop and correct it.

> **IMPORTANT — `OKC_URL` is the single source of truth for all Git operations.**
> Use `$OKC_URL` for every Git operation: clone (`--src-url`), push remote (`origin`),
> PR source URL (`--src-url`), and PR destination URL (`--dest-url`).
> **Never substitute the upstream URL in place of `$OKC_URL`**, even if it appears to
> point to a personal fork. The user configured it intentionally.

3. Parse `OKC_URL` to extract `OKC_OWNER` and `OKC_REPO_NAME` for GitHub API calls:
   ```bash
   OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
   # e.g. "opendatahub-io/odh-konflux-central"
   ```

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITHUB_USER GITHUB_TOKEN JIRA_USER_EMAIL JIRA_API_TOKEN" \
  --tools "uv git"
```

---

## Step 2: Set Up Working Directory

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_workdir.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
```

---

## Step 3: Fetch Jira Details and Component YAML

This step ensures both `component_onboarding_details.json` (full Jira issue) and
`component_onboarding_details.yaml` (component parameters) exist in `$WORKDIR`.

**3a. Fetch Jira issue details** (skip if `$WORKDIR/component_onboarding_details.json` already exists):

```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py <jira-url>
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3a (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

**3b. Download component YAML** (skip if `$WORKDIR/component_onboarding_details.yaml` already exists):

```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/download_jira_attachment.py \
  <jira-url> component_onboarding_details.yaml
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3b (Download YAML): Could not download 'component_onboarding_details.yaml' from Jira.
  Ensure the attachment exists on the Jira issue before running this skill.
```

**3c. Parse the YAML** using the `Read` tool to read `$WORKDIR/component_onboarding_details.yaml`.

Extract and store these values (all are under the `inputs:` key):

| Variable | YAML field | Example |
|----------|-----------|---------|
| `COMPONENT_NAME` | `inputs.component_name` | `odh-ai-first-demo` |
| `REPO_URL` | `inputs.repo_url` | `https://github.com/rhoai-rhtap/odh-ai-first-demo` |
| `REPO_BRANCH` | `inputs.repo_branch` | `main` |
| `CONTEXT_PATH` | `inputs.context_path` | `maas-controller` |
| `DOCKERFILE_PATH` | `inputs.dockerfile_path` | `Dockerfile` |
| `BUILD_TYPE` | `inputs.build_type` | `CI` or `RELEASE` |

Compute derived variables:

```bash
# Konflux component name (appended with -ci if not already present)
if [[ "$COMPONENT_NAME" == *-ci ]]; then
  KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"
else
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"
fi

# GitHub repo name from repo URL (last path segment, strip .git)
REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"

# PipelineRun resource names (used as 'name:' field in YAML)
PUSH_RUN_NAME="${COMPONENT_NAME}-on-push"
PR_RUN_NAME="${COMPONENT_NAME}-on-pull-request"

# Output file names (kebab-case, no 'on-' prefix in filename)
PUSH_YAML_FILE="${COMPONENT_NAME}-push.yaml"
PR_YAML_FILE="${COMPONENT_NAME}-pull-request.yaml"

# Service account name (uses Konflux component name, not base component name)
SERVICE_ACCOUNT_NAME="build-pipeline-${KONFLUX_COMPONENT_NAME}"

# Output image tags (push and pull-request use different tags for CI)
if [[ "${BUILD_TYPE^^}" == "CI" ]]; then
  PUSH_OUTPUT_IMAGE_TAG="odh-stable"
  PR_OUTPUT_IMAGE_TAG="odh-pr"
elif [[ "${BUILD_TYPE^^}" == "RELEASE" ]]; then
  # Use output_image_tag field if present; otherwise ask the user
  OUTPUT_IMAGE_TAG="${inputs_output_image_tag:-}"
  if [[ -z "$OUTPUT_IMAGE_TAG" ]]; then
    echo "ERROR in Step 3c: BUILD_TYPE is RELEASE but 'inputs.output_image_tag' is not set in component_onboarding_details.yaml."
    echo "  Please add 'output_image_tag: <tag>' under inputs: in the YAML and re-run."
    exit 1
  fi
  PUSH_OUTPUT_IMAGE_TAG="$OUTPUT_IMAGE_TAG"
  PR_OUTPUT_IMAGE_TAG="$OUTPUT_IMAGE_TAG"
else
  echo "ERROR in Step 3c: Unknown BUILD_TYPE '${BUILD_TYPE}'. Expected 'CI' or 'RELEASE'."
  exit 1
fi
```

If any required field (COMPONENT_NAME, REPO_URL, REPO_BRANCH, CONTEXT_PATH,
DOCKERFILE_PATH, BUILD_TYPE) is missing, stop with:
```
ERROR in Step 3c: Missing required field '<field>' in component_onboarding_details.yaml. Aborting.
```

---

## Step 4: Determine Product Context

Set `PRODUCT_CONTEXT` to `ODH` or `RHOAI` using the following rules in order:

1. **From `component_onboarding_details.yaml`** (already read in Step 3c): check `inputs.product_context`.
   If present and its value (case-insensitive) is `rhoai` → `RHOAI`; `odh` → `ODH`. Use this value directly.

2. **From Jira title** (in `component_onboarding_details.json` at `fields.summary`): if the title
   contains "RHOAI" (case-insensitive) → `RHOAI`; if it contains "ODH" → `ODH`.

3. **Fallback**: Ask the user:
   > I could not determine the product context (ODH or RHOAI) from the YAML or the Jira title.
   > Is this onboarding for ODH or RHOAI?

Based on `PRODUCT_CONTEXT`, set these variables:

| Variable | ODH | RHOAI |
|----------|-----|-------|
| `NAMESPACE` | `open-data-hub-tenant` | `rhoai-tenant` |
| `APPLICATION` | `opendatahub-builds` | `rhoai-builds` |
| `QUAY_ORG` | `opendatahub` | `rhoai` |

> **Note on RHOAI:** If the RHOAI namespace or application name above differs from your
> environment, pause and ask the user to confirm before proceeding.

---

## Step 5: Check If PipelineRuns Already Exist in OKC Repo

> **Reminder:** Use `$OKC_PATH` (derived from `$OKC_URL` in Step 0) for all GitHub API calls.
> Do NOT substitute the hardcoded upstream path `opendatahub-io/odh-konflux-central`.

Check via the GitHub API whether both PipelineRun files already exist in the OKC repo
(`pipelineruns/<REPO_NAME>/<PUSH_YAML_FILE>` and `pipelineruns/<REPO_NAME>/<PR_YAML_FILE>`):

```bash
PUSH_API_URL="https://api.github.com/repos/${OKC_PATH}/contents/pipelineruns/${REPO_NAME}/${PUSH_YAML_FILE}"
PR_API_URL="https://api.github.com/repos/${OKC_PATH}/contents/pipelineruns/${REPO_NAME}/${PR_YAML_FILE}"

PUSH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PUSH_API_URL")

PR_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PR_API_URL")
```

- **Both return 200** (files exist): Update Jira and stop:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "okc-changes-done" \
    --comment "PipelineRun files for '$COMPONENT_NAME' already exist in OKC repo at 'pipelineruns/$REPO_NAME/'. No action needed."
  ```
  Print: `PipelineRuns already exist in OKC. Nothing to do.` and **stop**.

- **Either returns non-200**: Continue to Step 6.

- **curl fails entirely** (network error): Display error and stop with:
  ```
  ERROR in Step 5: Could not reach GitHub API. Check network connectivity and GITHUB_TOKEN.
  ```

---

## Step 6: Check for Existing Open PR in Jira Comments

Extract existing GitHub PR URLs from the Jira comments:

```bash
EXISTING_PR_URLS=$(jq -r '.fields.comment.comments[].body' \
  "$WORKDIR/component_onboarding_details.json" 2>/dev/null \
  | grep -oE 'https://github\.com/[^/[:space:]]+/[^/[:space:]]+/pull/[0-9]+' \
  | sort -u || true)
```

Search `$EXISTING_PR_URLS` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/[^/\s]+/pull/\d+
```

For each URL found, run:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url <found-url> --check-only
```

Parse stdout:
- If `state=open` **and** `title=` line contains `COMPONENT_NAME` or `KONFLUX_COMPONENT_NAME`:
  - This is an existing open PR for the same component.
  - Update Jira:
    ```bash
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
      --comment "Found existing open GitHub PR for $COMPONENT_NAME: <found-url>. Monitoring it."
    ```
  - Print: `Found existing open PR: <found-url>. Skipping PR creation and jumping to monitor.`
  - Set `PR_URL=<found-url>` and **jump directly to Step 10** (Monitor PR).

If no matching open PR is found, continue to Step 7.

---

## Step 7: Set Up Playpen (Clone)

> **Reminder:** Pass `--src-url "$OKC_URL"` to `setup_github_playpen.sh`. This sets `origin`
> to `$OKC_URL` (the repo from `ODH_KONFLUX_CENTRAL_REPO_URL`, or the default). Do NOT
> hardcode the upstream URL here.

Run from inside `$WORKDIR`. Sparse checkout only the paths needed:
- `pipelineruns/template` — source template YAML files
- `pipelineruns/$REPO_NAME` — target directory for new PipelineRuns (may be empty/missing)
- `.github/workflows` — for the onboarder workflow update

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_github_playpen.sh \
  --src-url "$OKC_URL" \
  --src-branch main \
  --dest-branch "<jira-id>" \
  --sparse-files "pipelineruns/template pipelineruns/$REPO_NAME .github/workflows")
```

Parse `PLAYPEN_OUTPUT`:
- Line 1 → `CLONE_DIR` (absolute path, e.g. `$WORKDIR/odh-konflux-central-playpen`)
- Line 2 → `DEST_BRANCH` (the branch created and pushed)

On exit 1: display stderr and stop with:
```
ERROR in Step 7 (Playpen setup): Clone or push failed. See details above.
  Check network connectivity and GITHUB_TOKEN repo scope.
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "<jira-id>"
```

---

## Step 8: Generate PipelineRun Files and Update Workflow

### 8a. Verify template files exist

```bash
[[ -f "$CLONE_DIR/pipelineruns/template/odh-component-push.yaml" ]] || \
  { echo "ERROR: Push template not found in $CLONE_DIR"; exit 1; }
[[ -f "$CLONE_DIR/pipelineruns/template/odh-component-pull-request.yaml" ]] || \
  { echo "ERROR: PR template not found in $CLONE_DIR"; exit 1; }
```

### 8b. Create repo directory if needed

```bash
mkdir -p "$CLONE_DIR/pipelineruns/$REPO_NAME"
```

### 8c. Generate push PipelineRun

Copy the push template to the target location:
```bash
cp "$CLONE_DIR/pipelineruns/template/odh-component-push.yaml" \
   "$CLONE_DIR/pipelineruns/$REPO_NAME/$PUSH_YAML_FILE"
```

Apply all substitutions to the push PipelineRun using `sed`:

```bash
PUSH_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PUSH_YAML_FILE"
sed -i '' \
  -e "s|component-git-url|${REPO_URL}|g" \
  -e "s|\$\$TARGET_BRANCH\$\$|${REPO_BRANCH}|g" \
  -e "s|odh-component-name-ci|${KONFLUX_COMPONENT_NAME}|g" \
  -e "s|odh-file-name-on-push|${PUSH_RUN_NAME}|g" \
  -e "s|quay.io/opendatahub/quayurl|quay.io/${QUAY_ORG}/${COMPONENT_NAME}|g" \
  -e "s|\$\$OUTPUT_IMAGE_TAG\$\$|${PUSH_OUTPUT_IMAGE_TAG}|g" \
  -e "s|dockerfilepath|${DOCKERFILE_PATH}|g" \
  -e "s|    value: \\.  |    value: ${CONTEXT_PATH}|g" \
  -e "s|build-pipeline-sa-namw|${SERVICE_ACCOUNT_NAME}|g" \
  -e "s|open-data-hub-tenant|${NAMESPACE}|g" \
  -e "s|opendatahub-builds|${APPLICATION}|g" \
  "$PUSH_FILE"
```

Verify the substitutions were applied:

```bash
grep -q "name: $PUSH_RUN_NAME" "$PUSH_FILE" \
  || { echo "ERROR: PUSH_RUN_NAME not found after substitution."; exit 1; }
grep -q "serviceAccountName: $SERVICE_ACCOUNT_NAME" "$PUSH_FILE" \
  || { echo "ERROR: SERVICE_ACCOUNT_NAME not found after substitution."; exit 1; }
grep -q '\$\$TARGET_BRANCH\$\$\|quayurl' "$PUSH_FILE" \
  && { echo "ERROR: Unreplaced placeholders found in push YAML."; exit 1; } || true
```

### 8d. Generate pull-request PipelineRun

Copy the PR template to the target location:
```bash
cp "$CLONE_DIR/pipelineruns/template/odh-component-pull-request.yaml" \
   "$CLONE_DIR/pipelineruns/$REPO_NAME/$PR_YAML_FILE"
```

Apply all substitutions to the PR PipelineRun using `sed`. Note: the PR template uses YAML
comments (`#`) as placeholders — the sed commands remove them as part of substitution:

```bash
PR_FILE="$CLONE_DIR/pipelineruns/$REPO_NAME/$PR_YAML_FILE"
sed -i '' \
  -e "s|build.appstudio.openshift.io/repo: #component-git-url?rev={{revision}}|build.appstudio.openshift.io/repo: ${REPO_URL}?rev={{revision}}|g" \
  -e "s|\$\$TARGET_BRANCH\$\$|${REPO_BRANCH}|g" \
  -e "s|odh-component-name-ci|${KONFLUX_COMPONENT_NAME}|g" \
  -e "s|  name: #odh-file-name-on-pull-request|  name: ${PR_RUN_NAME}|g" \
  -e "s|quay.io/opendatahub/quayurl|quay.io/${QUAY_ORG}/${COMPONENT_NAME}|g" \
  -e "s|\$\$OUTPUT_IMAGE_TAG\$\$|${PR_OUTPUT_IMAGE_TAG}|g" \
  -e "s|dockerfilepath|${DOCKERFILE_PATH}|g" \
  -e "s|    value: \.  |    value: ${CONTEXT_PATH}|g" \
  -e "s|    serviceAccountName: #build-pipeline-sa-name|    serviceAccountName: ${SERVICE_ACCOUNT_NAME}|g" \
  -e "s|  #add these additional params|  # additional params|g" \
  -e "s|open-data-hub-tenant|${NAMESPACE}|g" \
  -e "s|opendatahub-builds|${APPLICATION}|g" \
  "$PR_FILE"
```

Verify the substitutions were applied:

```bash
grep -q "name: $PR_RUN_NAME" "$PR_FILE" \
  || { echo "ERROR: PR_RUN_NAME not found after substitution."; exit 1; }
grep -q "serviceAccountName: $SERVICE_ACCOUNT_NAME" "$PR_FILE" \
  || { echo "ERROR: SERVICE_ACCOUNT_NAME not found after substitution."; exit 1; }
grep -q '\$\$TARGET_BRANCH\$\$\|#component-git-url\|#odh-file-name' "$PR_FILE" \
  && { echo "ERROR: Unreplaced placeholders found in PR YAML."; exit 1; } || true
```

### 8e. Update the onboarder workflow

Check if `$REPO_NAME` is already in the workflow's `options:` list:

```bash
WORKFLOW_FILE="$CLONE_DIR/.github/workflows/odh-konflux-onboarder.yml"
if grep -q "          - ${REPO_NAME}$" "$WORKFLOW_FILE" 2>/dev/null; then
  echo "$REPO_NAME already in onboarder workflow component list — skipping."
else
  uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" insert-list-item \
    "$WORKFLOW_FILE" \
    --list-key "on.workflow_dispatch.inputs.components.options" \
    --value "$REPO_NAME"
fi
```

On exit 1 from `edit_yaml.py`: display stderr and stop with:
```
ERROR in Step 8e: Could not insert $REPO_NAME into workflow options. See details above. Aborting.
```

### 8f–8g. Commit and push all changes

> **Reminder:** `origin` was set to `$OKC_URL` by `setup_github_playpen.sh` in Step 7.

```bash
bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "." \
  --message   "Add $KONFLUX_COMPONENT_NAME PipelineRuns for $REPO_NAME" \
  --branch    "$DEST_BRANCH"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 8f–8g (Commit/Push): Could not commit or push changes. See details above. Aborting.
```

---

## Step 9: Raise PR (up to 3 attempts)

> **Reminder:** Both `--src-url` and `--dest-url` must be `"$OKC_URL"`. Do NOT replace
> either with the hardcoded upstream URL, even if `$OKC_URL` resolves to a personal fork.

Step 8 committed and pushed all changes. Proceed directly to raising the PR.

**Raise PR** — attempt up to 3 times:

```bash
PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
  --src-url "$OKC_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$OKC_URL" \
  --dest-branch main \
  --title "Add $KONFLUX_COMPONENT_NAME PipelineRuns for $COMPONENT_NAME" \
  --description "Add Konflux CI PipelineRuns for '$COMPONENT_NAME' from repo '$REPO_NAME'.

Product: $PRODUCT_CONTEXT
Application: $APPLICATION
Output image: quay.io/$QUAY_ORG/$COMPONENT_NAME:$OUTPUT_IMAGE_TAG
Source repo: $REPO_URL @ $REPO_BRANCH
Jira: <jira-url>

**Files changed:**
- \`pipelineruns/$REPO_NAME/$PUSH_YAML_FILE\` (new)
- \`pipelineruns/$REPO_NAME/$PR_YAML_FILE\` (new)
- \`.github/workflows/odh-konflux-onboarder.yml\` (updated: added $REPO_NAME to components list)")
```

On success: `PR_URL` is set.

On failure:
- "Branch not found" → re-push and retry
- "Connection error" → tell user to check network and retry
- Any other error → retry (up to 3 times total)

After 3 failures, stop with:
```
ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting.
```

After a successful PR creation, update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "okc-pr-raised" \
  --comment "GitHub PR raised to add Konflux PipelineRuns for '$COMPONENT_NAME' to odh-konflux-central.

PR URL: $PR_URL

CI builds will start for '$COMPONENT_NAME' once this PR is merged."
```

> **CRITICAL: Proceed immediately to Step 10.** Do NOT stop here. Steps 10 and 11 are
> mandatory follow-through after every successful PR creation.

---

## Step 10: Monitor PR

```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "$PR_URL" \
  --timeout 60
```

The script polls every 60 seconds and writes progress to stderr.

Read the **stdout** result:

- **`merged`** (exit 0): PR merged.
  Update Jira:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --remove-label "okc-pr-raised" \
    --comment "PR merged: $PR_URL

Konflux CI is now configured for '$COMPONENT_NAME'. Builds will trigger on pushes and
pull requests to '$REPO_BRANCH' branch of $REPO_URL.

Step 4 (odh-konflux-central update) is complete."
  ```
  Print: `PR merged. Step 4 (odh-konflux-central update) complete.`
  **Continue to Step 11.**

- **`closed`** (exit 1): PR closed without merging.
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "GitHub PR was closed without merging: $PR_URL

Please review the PR and re-run /update-component-using-odh-konflux-central if needed."
  ```
  Stop with:
  ```
  ERROR in Step 10 (Monitor PR): PR was closed without merging. Check the PR: $PR_URL
  ```

- **`pipeline_failed`** or **`pipeline_canceled`** (exit 1): CI checks failed.
  Attempt to diagnose the failure from the PR's check annotations, fix the generated YAML
  in `$CLONE_DIR/pipelineruns/$REPO_NAME/`, recommit, and push to update the PR:
  ```bash
  cd "$CLONE_DIR"
  # Inspect the generated YAML via bash (cat / sed / python3 one-liner) and fix it, then:
  git add -A
  git commit -m "Fix $KONFLUX_COMPONENT_NAME PipelineRun definition"
  git push origin "$DEST_BRANCH"
  ```
  Update Jira:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "CI checks failed on PR $PR_URL. Attempted automated fix and pushed update.

Please review the PR checks and re-run if the issue persists."
  ```
  **Jump back to Step 10** to re-monitor (once). If checks fail again, stop with:
  ```
  ERROR in Step 10 (Monitor PR): CI checks failed after fix attempt. Manual intervention needed.
  PR: $PR_URL
  ```

- **`timeout`** (exit 1): PR still open after 60 minutes.
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "PR monitoring timed out after 60 minutes. PR is still open: $PR_URL

Please check the PR status manually. Re-run /update-component-using-odh-konflux-central
to resume — it will detect the existing open PR at Step 6 and jump straight to monitoring."
  ```
  Print:
  ```
  WARNING: PR monitoring timed out after 60 minutes.
  The PR is still open: $PR_URL
  Re-run this skill when the PR is merged (it will short-circuit at Step 6).
  ```

---

## Step 11: Final Jira Update

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "okc-changes-done" \
  --comment "odh-konflux-central update complete.

Component: $COMPONENT_NAME ($KONFLUX_COMPONENT_NAME)
Repo: $REPO_URL @ $REPO_BRANCH
Output image: quay.io/$QUAY_ORG/$COMPONENT_NAME:$OUTPUT_IMAGE_TAG
PipelineRuns added:
  - pipelineruns/$REPO_NAME/$PUSH_YAML_FILE
  - pipelineruns/$REPO_NAME/$PR_YAML_FILE
Workflow updated: .github/workflows/odh-konflux-onboarder.yml

PR: $PR_URL (merged)

Step 4 (Add to odh-konflux-central) is complete."
```

Print:
```
✓ odh-konflux-central updated. '$COMPONENT_NAME' PipelineRuns are live.
  Step 4 (Add to odh-konflux-central) complete.
```

---

## Template Substitution Quick Reference

For reference, these are all the placeholder strings in the two template files and
their resolved values:

| Template placeholder | Resolved value | Notes |
|---------------------|---------------|-------|
| `component-git-url` | `$REPO_URL` | push template repo annotation |
| `#component-git-url` | `$REPO_URL` | PR template — remove `#` too |
| `$$TARGET_BRANCH$$` | `$REPO_BRANCH` | Both templates (replace_all) |
| `odh-component-name-ci` | `$KONFLUX_COMPONENT_NAME` | Both templates |
| `odh-file-name-on-push` | `$PUSH_RUN_NAME` | Push template `name:` field (`$COMPONENT_NAME-on-push`) |
| `#odh-file-name-on-pull-request` | `$PR_RUN_NAME` | PR template — remove `#` too (`$COMPONENT_NAME-on-pull-request`) |
| `quay.io/opendatahub/quayurl` | `quay.io/$QUAY_ORG/$COMPONENT_NAME` | Both templates |
| `$$OUTPUT_IMAGE_TAG$$` | `$PUSH_OUTPUT_IMAGE_TAG` (`odh-stable` for CI) | Push template only |
| `$$OUTPUT_IMAGE_TAG$$` | `$PR_OUTPUT_IMAGE_TAG` (`odh-pr` for CI) | PR template only |
| `dockerfilepath` | `$DOCKERFILE_PATH` | Both templates |
| `    value: .` | `    value: $CONTEXT_PATH` | path-context param, both templates |
| `build-pipeline-sa-namw` | `$SERVICE_ACCOUNT_NAME` | Push template — fix typo, set `build-pipeline-$KONFLUX_COMPONENT_NAME` |
| `#build-pipeline-sa-name` | `$SERVICE_ACCOUNT_NAME` | PR template — remove `#`, set `build-pipeline-$KONFLUX_COMPONENT_NAME` |
| `open-data-hub-tenant` | `$NAMESPACE` | Both templates |
| `opendatahub-builds` | `$APPLICATION` | Both templates |

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_USER` not set | Step 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | Step 1 | `export GITHUB_TOKEN=yourtoken` |
| `JIRA_USER_EMAIL` not set | Step 1 | `export JIRA_USER_EMAIL=you@redhat.com` |
| `JIRA_API_TOKEN` not set | Step 1 | `export JIRA_API_TOKEN=your-token` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `component_onboarding_details.yaml` missing from Jira | Step 3b | Upload the YAML to the Jira issue |
| Unknown `BUILD_TYPE` | Step 3c | Set `build_type: CI` or `build_type: RELEASE` in component_onboarding_details.yaml |
| `output_image_tag` missing for RELEASE build | Step 3c | Add `output_image_tag: <tag>` under `inputs:` in component_onboarding_details.yaml |
| GitHub API unreachable | Step 5 | Check network connectivity and GITHUB_TOKEN |
| Clone fails | Step 7 | Check GITHUB_TOKEN repo scope |
| Shallow push rejected | Steps 7, 8g | `git fetch --unshallow origin` then retry |
| PR creation fails 3× | Step 9 | Check GITHUB_TOKEN; inspect stderr; fix manually |
| PR CI checks fail | Step 10 | Automated fix attempted; check PR if it fails again |
| PR closed without merge | Step 10 | Review the PR; re-run after fixing |
