---
name: create-pull-pipelines-in-rhoai-konflux-central
description: Adds a pull-request Tekton PipelineRun YAML to the rhoai-konflux-central GitHub repository for a new RHOAI component, then raises and monitors a GitHub PR targeting the main branch.
allowed-tools: Bash
user-invocable: true
---

# Create Pull Pipelines in RHOAI-Konflux-Central

Creates a Tekton `PipelineRun` resource for pull-request builds of a new RHOAI component by:
1. Generating a pull-request PipelineRun YAML under `pipelineruns/<repo_name>/.tekton/`.
2. Raising a pull request to the `main` branch of `rhoai-konflux-central`.
3. Monitoring the PR until it merges.

> **CRITICAL — `RHOAI_KONFLUX_CENTRAL_REPO_URL` overrides the default repo for every step.**
> This env var is resolved once in Step 0 into `RKC_URL` and `RKC_PATH`.
> Every subsequent Git clone, push, GitHub API call, and PR operation **must** use
> `$RKC_URL` / `$RKC_PATH` — never the hardcoded upstream URL.
> The PR target branch is **`main`** (not a version-specific branch).

## Usage

```
/create-pull-pipelines-in-rhoai-konflux-central [<jira-url>]
```

Examples:
```
/create-pull-pipelines-in-rhoai-konflux-central https://redhat.atlassian.net/browse/RHOAIENG-1234
/create-pull-pipelines-in-rhoai-konflux-central
```

## Prerequisites

- `GITHUB_USER` — your GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — GitHub personal access token with `repo` scope
- `JIRA_USER_EMAIL` — Atlassian account email (required when jira-url provided)
- `JIRA_API_TOKEN` — Atlassian API token (required when jira-url provided)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `git`, `curl`
- Optional: `RHOAI_KONFLUX_CENTRAL_REPO_URL` (default: `https://github.com/red-hat-data-services/konflux-central.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**If invoked from a parent orchestrator:** `component_onboarding_details.yaml` may already
be placed in the working directory. Otherwise the Jira attachment will be downloaded.

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Substitution Rules

The following substitutions are applied to the pull-request pipeline template. The
template reference is `pipelineruns/odh-dashboard/.tekton/odh-dashboard-pull-request.yaml`
on the `main` branch of `red-hat-data-services/konflux-central`.

### Substituted fields

| Template value | Replaced with | Source |
|----------------|---------------|--------|
| `odh-dashboard` in `metadata.name` | `${COMPONENT_NAME}` | YAML `component_name` |
| `odh-dashboard` in `appstudio.openshift.io/component:` | `${COMPONENT_NAME}` | YAML `component_name` |
| `odh-dashboard` in `pipelinesascode.tekton.dev/on-label:` | `${COMPONENT_NAME}` | YAML `component_name` |
| `odh-dashboard` in `io.openshift.tags=` | `${COMPONENT_NAME}` | YAML `component_name` |
| `odh-dashboard` in `output-image:` | `${COMPONENT_NAME}` | YAML `component_name` |
| `https://github.com/red-hat-data-services/odh-dashboard` in repo annotation | `${REPO_URL}` | YAML `repo_url` |
| `51094` (hardcoded PR number suffix in `name:`) | `{{pull_request_number}}` | PAC template variable |
| `Dockerfile.konflux` in `dockerfile:` | `${DOCKERFILE_PATH}` | YAML `dockerfile_path` |
| `.` in `path-context:` | `${CONTEXT_PATH_NORMALIZED}` | YAML `context_path` |
| `[{"type": "npm", "path": "."}]` in `prefetch-input:` | `${PREFETCH_INPUT}` | `detect_prefetch_input.sh` |
| All 4 hardcoded `build-platforms` entries | `${PLATFORMS[@]}` | YAML `architectures` |
| `https://github.com/red-hat-data-services/konflux-central.git` in `pipelineRef.url` | `${RKC_URL}` | env var / default |

### Fields kept unchanged from the template

| Field | Value | Reason |
|-------|-------|--------|
| `appstudio.openshift.io/application:` | `automation` | Shared label across all PR pipelines |
| `pipelinesascode.tekton.dev/on-event:` | `[pull_request]` | Fixed trigger type |
| `pipelinesascode.tekton.dev/on-comment:` | `^/build-konflux` | Fixed comment trigger |
| `pipelinesascode.tekton.dev/on-target-branch:` | `[{{target_branch}}]` | PAC variable |
| `pipelinesascode.tekton.dev/cancel-in-progress:` | `"true"` | Cancel stale PR builds |
| `pipelinesascode.tekton.dev/max-keep-runs:` | `"3"` | Standard retention |
| `serviceAccountName:` | `build-pipeline-pull-request-pipelines` | Shared SA for all PR pipelines |
| `timeouts.pipeline:` | `8h` | Standard PR build timeout |
| `image-expires-after:` | `5d` | PR images are temporary |
| `enable-slack-failure-notification:` | `"false"` | PR builds do not page |
| `pipelineRef.pathInRepo:` | `pipelines/multi-arch-container-build.yaml` | Fixed pipeline definition |
| `pipelineRef.revision:` | `{{ target_branch }}` | PAC variable |
| `git_auth_secret:` | `{{ git_auth_secret }}` | PAC variable |

---

## Step 0: Parse Inputs

1. Extract `<jira-url>` from the first positional argument (may be empty/omitted).

   If provided but does not contain `/browse/`, stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

2. Set:
   - `JIRA_URL` — the full URL if provided, else empty string
   - `JIRA_ID` — last path segment (e.g. `RHOAIENG-1234`), or empty string

3. Resolve `RKC_URL` — the single source of truth for all Git and GitHub operations:

   ```bash
   RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
   echo "RHOAI_KONFLUX_CENTRAL_REPO_URL=${RHOAI_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
   echo "RKC_URL resolved to: $RKC_URL"
   ```

   **Never override or re-derive `RKC_URL` in later steps.**

4. Derive `RKC_PATH` for GitHub API calls:

   ```bash
   RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')
   # e.g. "red-hat-data-services/konflux-central"
   ```

5. Echo resolved values:
   ```
   JIRA_URL : ${JIRA_URL:-(not provided)}
   JIRA_ID  : ${JIRA_ID:-(not provided)}
   RKC_URL  : $RKC_URL
   RKC_PATH : $RKC_PATH
   ```

---

## Step 1: Check Prerequisites

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git curl"

if [[ -n "$JIRA_URL" ]]; then
  bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
    --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi
```

---

## Step 2: Set Up Working Directory

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_workdir.sh" --jira-url "${JIRA_URL:-}")"
echo "Working directory: $WORKDIR"
```

---

## Step 3: Get Component YAML and Derive Variables

### 3a. Pipeline-state check

If `$WORKDIR/component_onboarding_details.yaml` already exists (placed by parent orchestrator), skip 3b:
```bash
if [[ -f "$WORKDIR/component_onboarding_details.yaml" ]]; then
  echo "Using existing component_onboarding_details.yaml from pipeline state."
fi
```

### 3b. Download from Jira

Only when file does not exist and `JIRA_URL` is non-empty:
```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/download_jira_attachment.py \
  "$JIRA_URL" component_onboarding_details.yaml
```

On exit 1: display stderr and stop:
```
ERROR in Step 3b: Could not download 'component_onboarding_details.yaml'.
  Ensure the attachment exists on the Jira issue.
  Run /create-component-onboarding-jira <jira-url> first.
```

### 3c. Guard

If file is still missing and no JIRA_URL, stop:
```
ERROR in Step 3: No component_onboarding_details.yaml found and no Jira URL provided.
```

### 3d. Fetch Jira details

Skip if `$WORKDIR/component_onboarding_details.json` already exists. Only when `JIRA_URL` non-empty:
```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py "$JIRA_URL"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3d (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

### 3e. Parse YAML

```bash
YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
REPO_URL=$(grep -m1 'repo_url:' "$YAML_FILE" | awk '{print $2}')
CONTEXT_PATH=$(grep -m1 'context_path:' "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}')

# Parse architectures array (list items under 'architectures:' key)
ARCHITECTURES=($(awk '/^  architectures:/{found=1;next} found && /^  - /{print $2} found && /^  [a-z]/{exit}' "$YAML_FILE"))
[[ ${#ARCHITECTURES[@]} -eq 0 ]] && ARCHITECTURES=($(grep -A20 'architectures:' "$YAML_FILE" | grep '^ *- ' | awk '{print $2}'))

for _field in COMPONENT_NAME REPO_URL CONTEXT_PATH DOCKERFILE_PATH; do
  [[ -z "${!_field}" ]] && {
    echo "ERROR in Step 3e: Missing required field '${_field}' in component_onboarding_details.yaml."
    echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
    exit 1
  }
done
[[ ${#ARCHITECTURES[@]} -eq 0 ]] && {
  echo "ERROR in Step 3e: Missing required field 'architectures' in component_onboarding_details.yaml."
  exit 1
}
```

### 3f. Derive all global variables

```bash
REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"

PIPELINERUN_FILE="${COMPONENT_NAME}-pull-request.yaml"

if [[ "$CONTEXT_PATH" == "./" || "$CONTEXT_PATH" == "." ]]; then
  CONTEXT_PATH_NORMALIZED="."
else
  CONTEXT_PATH_NORMALIZED="$CONTEXT_PATH"
fi
```

Build the platform list from `ARCHITECTURES`:
```bash
PLATFORMS=()
for arch in "${ARCHITECTURES[@]}"; do
  case "$arch" in
    x86_64)  PLATFORMS+=("linux/x86_64") ;;
    arm64)   PLATFORMS+=("linux-m2xlarge/arm64") ;;
    ppc64le) PLATFORMS+=("linux/ppc64le") ;;
    s390x)   PLATFORMS+=("linux/s390x") ;;
    *) echo "WARN: Unknown architecture '$arch' — skipping" ;;
  esac
done
```

If `PLATFORMS` is empty after processing, stop:
```
ERROR in Step 3f: No valid architectures found in 'architectures' field.
  Expected one or more of: x86_64, arm64, ppc64le, s390x
```

Print all resolved values:
```
COMPONENT_NAME          : $COMPONENT_NAME
REPO_URL                : $REPO_URL
REPO_NAME               : $REPO_NAME
PIPELINERUN_FILE        : $PIPELINERUN_FILE
CONTEXT_PATH_NORMALIZED : $CONTEXT_PATH_NORMALIZED
DOCKERFILE_PATH         : $DOCKERFILE_PATH
PLATFORMS               : ${PLATFORMS[*]}
```

---

## Step 4: Fast-Path Check — Does PipelineRun Already Exist?

Check via GitHub API whether the pipelinerun file already exists on the `main` branch:

```bash
PIPELINE_API_URL="https://api.github.com/repos/${RKC_PATH}/contents/pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}?ref=main"

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PIPELINE_API_URL")
```

**`HTTP_STATUS == 200`** (file exists): update Jira and stop:
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "rkc-pull-changes-done" \
    --comment "Pull-request PipelineRun '${PIPELINERUN_FILE}' already exists in rhoai-konflux-central on 'main'. No action needed."
fi
echo "PipelineRun already exists in RKC main branch. Nothing to do."
exit 0
```

**`HTTP_STATUS == 404`**: continue to Step 5.

**Any other status** (e.g. 401, 403, 5xx): warn and continue — do not fail hard on transient connectivity issues:
```
WARN: GitHub API returned HTTP $HTTP_STATUS for fast-path check. Proceeding anyway.
```

---

## Step 5: Check for Existing Open PR in Jira Comments

Skip this step entirely if `$WORKDIR/component_onboarding_details.json` does not exist.

Extract PR URLs from `$WORKDIR/component_onboarding_details.json`:
```bash
EXISTING_PR_URLS=$(jq -r '.fields.comment.comments[].body' \
  "$WORKDIR/component_onboarding_details.json" 2>/dev/null \
  | grep -oE 'https://github\.com/[^/[:space:]]+/[^/[:space:]]+/pull/[0-9]+' \
  | sort -u || true)
```

For each URL found, run:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "<found-url>" --check-only
```

Parse stdout:
- If `state=open` **and** the `title=` line contains `COMPONENT_NAME` and `pull-request`:
  - This is the open PR for the same component. Resume monitoring.
  ```bash
  PR_URL="<found-url>"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --comment "Found existing open GitHub PR for '${COMPONENT_NAME}' pull-request pipeline: ${PR_URL}
Resuming monitoring of this PR."
  fi
  echo "Found existing open PR: $PR_URL. Skipping PR creation and jumping to monitor."
  ```
  **Set `PR_URL` and jump directly to Step 11** (Monitor PR).

- If `state=merged`: update Jira with `rkc-pull-changes-done` label and a merged comment. **Stop exit 0.**
- If `state=closed`: note it and continue searching.

If no matching open PR found, continue to Step 6.

---

## Step 6: Set Up Playpen (Clone)

> **CRITICAL:** Clone from `main`. The `--src-branch` must be `main`.

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_github_playpen.sh \
  --src-url "$RKC_URL" \
  --src-branch "main" \
  ${JIRA_ID:+--dest-branch "$JIRA_ID"} \
  --sparse-files "pipelineruns/$REPO_NAME")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
```

On exit 1: display stderr and stop:
```
ERROR in Step 6 (Playpen setup): Clone or push failed. See details above.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 7: Create PipelineRun Directory

Check case-insensitively whether the `.tekton` directory already exists:
```bash
TEKTON_DIR=$(find "$CLONE_DIR/pipelineruns/$REPO_NAME" -maxdepth 1 -iname ".tekton" -type d 2>/dev/null | head -1)
if [[ -z "$TEKTON_DIR" ]]; then
  TEKTON_DIR="$CLONE_DIR/pipelineruns/$REPO_NAME/.tekton"
  mkdir -p "$TEKTON_DIR"
fi
```

If other pipelinerun files already exist in the `.tekton` directory, list them to note any
structural differences from the template:
```bash
ls "$TEKTON_DIR" 2>/dev/null && cat "$TEKTON_DIR/"*.yaml 2>/dev/null | head -30 || true
```

Set the target file path:
```bash
PIPELINERUN_PATH="$TEKTON_DIR/$PIPELINERUN_FILE"
```

---

## Step 8: Write Pull-Request PipelineRun YAML

### 8a. Determine prefetch-input

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/detect_prefetch_input.sh" \
  --repo-url "$REPO_URL" \
  --context-path "$CONTEXT_PATH_NORMALIZED")"
# Sets PREFETCH_INPUT (JSON array string, defaults to [] on error)
echo "PREFETCH_INPUT: $PREFETCH_INPUT"
```

### 8b. Write the file

> **CRITICAL — `{{...}}` and `{{ ... }}` are Tekton/PAC templating variables.**
> Write them **verbatim** — do NOT substitute their content with actual values.

Build the platform list YAML and write `$PIPELINERUN_PATH`:

```bash
# Build YAML platform list (4-space indented)
PLATFORM_LIST=""
for p in "${PLATFORMS[@]}"; do
  PLATFORM_LIST+="    - ${p}"$'\n'
done
PLATFORM_LIST="${PLATFORM_LIST%$'\n'}"

cat > "$PIPELINERUN_PATH" <<PIPELINERUN_EOF

apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  annotations:
    build.appstudio.openshift.io/repo: ${REPO_URL}?rev={{revision}}
    build.appstudio.redhat.com/commit_sha: '{{revision}}'
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    build.appstudio.redhat.com/pull_request_number: "{{pull_request_number}}"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    pipelinesascode.tekton.dev/on-comment: "^/build-konflux"
    pipelinesascode.tekton.dev/on-label: "[kfbuild-all, kfbuild-${COMPONENT_NAME}]"
    pipelinesascode.tekton.dev/on-target-branch: "[{{target_branch}}]"
    pipelinesascode.tekton.dev/on-event: "[pull_request]"
    pipelinesascode.tekton.dev/cancel-in-progress: "true"
  labels:
    appstudio.openshift.io/application: automation
    appstudio.openshift.io/component: pull-request-pipelines-${COMPONENT_NAME}
    pipelines.appstudio.openshift.io/type: build
  name: ${COMPONENT_NAME}-on-pull-request-{{pull_request_number}}
  namespace: rhoai-tenant
spec:
  timeouts:
    pipeline: 8h
  params:
  - name: git-url
    value: '{{source_url}}'
  - name: revision
    value: '{{revision}}'
  - name: additional-tags
    value:
    - 'pr-{{pull_request_number}}-into-{{target_branch}}'
  - name: additional-labels
    value:
    - version=on-pr-{{revision}}
    - io.openshift.tags=${COMPONENT_NAME}
  - name: output-image
    value: quay.io/rhoai/pull-request-pipelines:${COMPONENT_NAME}-{{revision}}
  - name: build-platforms
    value:
${PLATFORM_LIST}
  - name: image-expires-after
    value: 5d
  - name: dockerfile
    value: ${DOCKERFILE_PATH}
  - name: path-context
    value: ${CONTEXT_PATH_NORMALIZED}
  - name: hermetic
    value: true
  - name: prefetch-input
    value: |
      ${PREFETCH_INPUT}
  - name: build-image-index
    value: true
  - name: enable-slack-failure-notification
    value: "false"
  pipelineRef:
    resolver: git
    params:
    - name: url
      value: ${RKC_URL}
    - name: revision
      value: '{{ target_branch }}'
    - name: pathInRepo
      value: pipelines/multi-arch-container-build.yaml
  taskRunTemplate:
    serviceAccountName: build-pipeline-pull-request-pipelines
  workspaces:
  - name: git-auth
    secret:
      secretName: '{{ git_auth_secret }}'
status: {}
PIPELINERUN_EOF
echo "PipelineRun written to $PIPELINERUN_PATH"
```

> **Note:** `pipelineRef.params[url]` uses `$RKC_URL` so that overriding
> `RHOAI_KONFLUX_CENTRAL_REPO_URL` (e.g. to a fork for testing) is respected everywhere.

### 8c. Verify the written file

```bash
grep -q "name: ${COMPONENT_NAME}-on-pull-request" "$PIPELINERUN_PATH" || {
  echo "ERROR in Step 8c: name field not set correctly in $PIPELINERUN_PATH"; exit 1
}
grep -q "pull-request-pipelines-${COMPONENT_NAME}" "$PIPELINERUN_PATH" || {
  echo "ERROR in Step 8c: component label not set correctly"; exit 1
}
grep -q '{{pull_request_number}}' "$PIPELINERUN_PATH" || {
  echo "ERROR in Step 8c: PAC template variables missing from $PIPELINERUN_PATH"; exit 1
}
# Check no angle-bracket placeholders remain
grep -qE '<[A-Z_]+>' "$PIPELINERUN_PATH" && {
  echo "ERROR in Step 8c: Unreplaced placeholders remain in $PIPELINERUN_PATH"
  grep -E '<[A-Z_]+>' "$PIPELINERUN_PATH"
  exit 1
} || true
echo "Verification passed for $PIPELINERUN_PATH"
```

---

## Step 9: Commit and Push

```bash
bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE" \
  --message   "Add ${COMPONENT_NAME} pull-request PipelineRun for ${REPO_NAME}

Adds Tekton pull-request PipelineRun for component '${COMPONENT_NAME}'.
File: pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}

Related: ${JIRA_ID:-no-jira}" \
  --branch    "$DEST_BRANCH"
```

On exit 1, display stderr and stop:
```
ERROR in Step 9 (Push): Could not push branch '$DEST_BRANCH' to $RKC_URL. See details above.
  Check GITHUB_TOKEN has 'repo' scope and write access to $RKC_PATH.
```

---

## Step 10: Raise PR (up to 3 attempts)

> **CRITICAL:** The PR target branch is `main`.
> Both `--src-url` and `--dest-url` must be `"$RKC_URL"`.

```bash
PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
  --src-url "$RKC_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$RKC_URL" \
  --dest-branch "main" \
  --title "Add ${COMPONENT_NAME} pull-request PipelineRun for ${REPO_NAME}" \
  --description "Adds Tekton pull-request PipelineRun YAML for component '${COMPONENT_NAME}'.

## Details

| Field | Value |
|-------|-------|
| Component | \`${COMPONENT_NAME}\` |
| Source repo | \`${REPO_URL}\` |
| File | \`pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}\` |
| Platforms | ${PLATFORMS[*]} |
| Output image | \`quay.io/rhoai/pull-request-pipelines:${COMPONENT_NAME}-{{revision}}\` |

**Jira:** ${JIRA_URL:-(none)}")
```

On failure:
- "Branch not found" → re-push `$DEST_BRANCH` to origin and retry.
- "Connection error" → inform user of network issue, retry.
- Any other error → retry.

After 3 failures, stop:
```
ERROR in Step 10 (Raise PR): Could not create PR after 3 attempts. Aborting.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

On success, update Jira (only when `JIRA_URL` non-empty):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "rkc-pull-pr-raised" \
  --comment "GitHub PR raised to add pull-request PipelineRun for '${COMPONENT_NAME}' to rhoai-konflux-central.

PR URL: $PR_URL
Target branch: main
File: pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}

PR builds will trigger for '${COMPONENT_NAME}' once this PR is merged."
```

> **CRITICAL: Proceed immediately to Step 11.** Do NOT stop here.

---

## Step 11: Monitor PR

```bash
RESULT=$(uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "$PR_URL" \
  --timeout 60)
```

The script polls every 60 seconds and writes progress to stderr.

**`merged` (exit 0):**
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "rkc-pull-changes-done" \
    --remove-label "rkc-pull-pr-raised" \
    --comment "GitHub PR merged: $PR_URL

Pull-request Konflux CI is now configured for '${COMPONENT_NAME}'.
Builds will trigger on pull requests to ${REPO_URL}."
fi
```
Continue to Step 12.

**`closed` (exit 1):** PR closed without merging.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "GitHub PR was closed without merging: $PR_URL
Please review and re-run /create-pull-pipelines-in-rhoai-konflux-central ${JIRA_URL} to re-open."
fi
```
Stop with:
```
ERROR in Step 11 (Monitor PR): PR was closed without merging. Check: $PR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):** Attempt automated fix:
1. Inspect `$PIPELINERUN_PATH` for YAML validity:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('$PIPELINERUN_PATH'))" 2>&1
   ```
2. If YAML is invalid, check for common indentation issues:
   ```bash
   grep -n 'value:' "$PIPELINERUN_PATH" | tail -10
   grep -n 'params:' "$PIPELINERUN_PATH" | head -5
   ```
3. If fixable, re-write the file with corrected content (re-run the heredoc from Step 8b with the same variables), then commit and push the fix:
   ```bash
   bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
     --clone-dir "$CLONE_DIR" \
     --files     "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE" \
     --message   "Fix ${COMPONENT_NAME} pull-request PipelineRun YAML definition" \
     --branch    "$DEST_BRANCH"
   ```
   Update Jira with fix attempt. **Jump back to Step 11** to re-monitor once.
4. If not fixable: update Jira with failure details and stop:
   ```
   ERROR in Step 11 (Monitor PR): CI checks failed and could not be auto-fixed.
   PR: $PR_URL — manual intervention required.
   ```

**`timeout` (exit 1):** PR still open after 60 minutes.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "PR monitoring timed out after 60 minutes: $PR_URL
The PR is still open. Re-run /create-pull-pipelines-in-rhoai-konflux-central ${JIRA_URL:-} to resume."
fi
```
Print warning and continue to Step 12 (no hard stop).

---

## Step 12: Report Completion

```
Done.

  pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE — created
  Target branch       : main
  GitHub PR           : $PR_URL — $RESULT
  Jira                : ${JIRA_ID:-(none)} — label: rkc-pull-changes-done

Pull-request Konflux CI builds will trigger for '$COMPONENT_NAME' on PRs
in repository: $REPO_URL

Note: Review the prefetch-input array in the PR and update it if auto-detection
was incorrect or incomplete.
```

---

## Architecture Mapping

| `architectures` value | `build-platforms` entry |
|-----------------------|------------------------|
| `x86_64` | `linux/x86_64` |
| `arm64` | `linux-m2xlarge/arm64` |
| `ppc64le` | `linux/ppc64le` |
| `s390x` | `linux/s390x` |

---

## Error Reference

| Error | Step | Action |
|-------|------|--------|
| `GITHUB_USER` not set | 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | 1 | `export GITHUB_TOKEN=yourtoken` (needs `repo` scope) |
| `JIRA_USER_EMAIL`/`JIRA_API_TOKEN` not set | 1 | Export both env vars |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| YAML attachment missing | 3b | Run `/create-component-onboarding-jira <jira-url>` first |
| `architectures` missing | 3e | Add `architectures: [x86_64, arm64]` etc. to YAML |
| Push fails (shallow) | 6, 9 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PipelineRun already exists | 4 | Expected — exits 0; Jira labelled `rkc-pull-changes-done` |
| Open PR already found | 5 | Expected — jumps to Step 11 to monitor |
| PR creation fails 3× | 10 | Check GITHUB_TOKEN `repo` scope |
| PR closed without merge | 11 | Review PR manually; re-run skill |
| Pipeline failed | 11 | Skill attempts auto-fix and retries monitor once |
| PR monitoring timeout | 11 | PR still open; re-run to resume monitoring |
