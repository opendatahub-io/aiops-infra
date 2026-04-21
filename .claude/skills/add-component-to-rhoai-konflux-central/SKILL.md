---
name: add-component-to-rhoai-konflux-central
description: Adds a Tekton PipelineRun YAML to the rhoai-konflux-central GitHub repository for a new RHOAI component, then raises and monitors a GitHub PR targeting the version-specific branch.
allowed-tools: Bash, Read, Edit, Write, WebFetch
user-invocable: true
---

# Add Component to RHOAI-Konflux-Central

Creates a Tekton `PipelineRun` resource for a new RHOAI component by:
1. Generating a push PipelineRun YAML under `pipelineruns/<repo_name>/.tekton/`.
2. Raising a pull request to the version-specific branch of `rhoai-konflux-central`.
3. Monitoring the PR until it merges. When merged, Konflux CI will start building the component.

> **CRITICAL — `RHOAI_KONFLUX_CENTRAL_REPO_URL` overrides the default repo for every step.**
> This env var is resolved once in Step 0 into `RKC_URL` and `RKC_PATH`.
> Every subsequent Git clone, push, GitHub API call, and PR operation **must** use
> `$RKC_URL` / `$RKC_PATH` — never the hardcoded upstream URL.
> The PR target branch is **`$BRANCH_NAME`** (a version-specific branch), NOT `main`.

## Usage

```
/add-component-to-rhoai-konflux-central [<jira-url>]
```

Examples:
```
/add-component-to-rhoai-konflux-central https://redhat.atlassian.net/browse/RHOAIENG-1234
/add-component-to-rhoai-konflux-central
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

Check in order. Stop with a remediation message if any check fails.

```bash
# 1. GITHUB_USER
if [[ -z "${GITHUB_USER:-}" ]]; then
  echo "ERROR: GITHUB_USER is not set. export GITHUB_USER=yourusername"
  exit 1
fi

# 2. GITHUB_TOKEN
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERROR: GITHUB_TOKEN is not set. export GITHUB_TOKEN=yourtoken (needs repo scope)"
  exit 1
fi

# 3. uv
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# 4. git
if ! command -v git &>/dev/null; then
  echo "ERROR: git is not installed."
  exit 1
fi

# 5. curl
if ! command -v curl &>/dev/null; then
  echo "ERROR: curl is not installed."
  exit 1
fi
```

When `JIRA_URL` is non-empty, also check:
```bash
if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  echo "ERROR: JIRA_USER_EMAIL is not set. export JIRA_USER_EMAIL=you@example.com"
  exit 1
fi
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: JIRA_API_TOKEN is not set. export JIRA_API_TOKEN=your-api-token"
  exit 1
fi
```

---

## Step 2: Set Up Working Directory

```bash
if [[ -n "$JIRA_ID" ]]; then
  WORKDIR="$(pwd)/${JIRA_ID}"
else
  WORKDIR="$(pwd)"
fi
mkdir -p "$WORKDIR"
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

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.yaml`.

Extract (all under `inputs:`):

| Variable | YAML field | Required |
|----------|-----------|----------|
| `COMPONENT_NAME` | `inputs.component_name` | Yes |
| `REPO_URL` | `inputs.repo_url` | Yes |
| `CONTEXT_PATH` | `inputs.context_path` | Yes |
| `DOCKERFILE_PATH` | `inputs.dockerfile_path` | Yes |
| `ARCHITECTURES` | `inputs.architectures` | Yes (array) |
| `TARGET_RHOAI_VERSION` | `inputs.target_rhoai_version` | Yes |

If any required field is missing, stop:
```
ERROR in Step 3e: Missing required field '<field>' in component_onboarding_details.yaml.
  Re-generate the YAML with /create-component-onboarding-jira <jira-url>.
```

### 3f. Derive all global variables

Parse `TARGET_RHOAI_VERSION` (canonical form: `x.y` or `x.y-ea-n`):

```bash
if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"
  VERSION_Y="${BASH_REMATCH[2]}"
  VERSION_N="${BASH_REMATCH[3]}"
  VERSION_VAR="v${VERSION_X}-${VERSION_Y}-ea-${VERSION_N}"        # e.g. v3-4-ea-2
  BRANCH_VAR="v${VERSION_X}.${VERSION_Y}-ea.${VERSION_N}"        # e.g. v3.4-ea.2
  RHOAI_MINOR_VERSION="${VERSION_X}.${VERSION_Y}.0-ea.${VERSION_N}" # e.g. 3.4.0-ea.2
elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
  VERSION_X="${BASH_REMATCH[1]}"
  VERSION_Y="${BASH_REMATCH[2]}"
  VERSION_N=""
  VERSION_VAR="v${VERSION_X}-${VERSION_Y}"         # e.g. v3-4
  BRANCH_VAR="v${VERSION_X}.${VERSION_Y}"          # e.g. v3.4
  RHOAI_MINOR_VERSION="${VERSION_X}.${VERSION_Y}.0" # e.g. 3.4.0
else
  echo "ERROR: Cannot parse target_rhoai_version '${TARGET_RHOAI_VERSION}'."
  echo "  Expected canonical form: x.y  OR  x.y-ea-n  (e.g. 3.4 or 3.4-ea-2)"
  exit 1
fi

BRANCH_NAME="rhoai-${BRANCH_VAR}"     # e.g. rhoai-v3.4-ea.2

# Repo name from repo_url (strip owner prefix, strip .git suffix)
REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"

# PipelineRun file name
PIPELINERUN_FILE="${COMPONENT_NAME}-${VERSION_VAR}-push.yaml"

# Context path normalization
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
COMPONENT_NAME        : $COMPONENT_NAME
REPO_URL              : $REPO_URL
TARGET_RHOAI_VERSION  : $TARGET_RHOAI_VERSION
VERSION_VAR           : $VERSION_VAR
BRANCH_VAR            : $BRANCH_VAR
BRANCH_NAME           : $BRANCH_NAME
RHOAI_MINOR_VERSION   : $RHOAI_MINOR_VERSION
REPO_NAME             : $REPO_NAME
PIPELINERUN_FILE      : $PIPELINERUN_FILE
CONTEXT_PATH_NORMALIZED: $CONTEXT_PATH_NORMALIZED
PLATFORMS             : ${PLATFORMS[*]}
```

---

## Step 4: Fast-Path Check — Does PipelineRun Already Exist?

Check via GitHub API whether the pipelinerun file already exists in the `$BRANCH_NAME` branch:

```bash
PIPELINE_API_URL="https://api.github.com/repos/${RKC_PATH}/contents/pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}?ref=${BRANCH_NAME}"

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$PIPELINE_API_URL")
```

**`HTTP_STATUS == 200`** (file exists): update Jira and stop:
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "rkc-changes-done" \
    --comment "PipelineRun '${PIPELINERUN_FILE}' already exists in rhoai-konflux-central at branch '${BRANCH_NAME}'. No action needed."
fi
echo "PipelineRun already exists in RKC branch '${BRANCH_NAME}'. Nothing to do."
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

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.json`.

Search `fields.comment.comments[].body` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/[^/\s]+/pull/\d+
```

For each URL found, run:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "<found-url>" --check-only
```

Parse stdout:
- If `state=open` **and** the `title=` line contains `COMPONENT_NAME` or `VERSION_VAR`:
  - This is the open PR for the same component + version. Resume monitoring.
  ```bash
  PR_URL="<found-url>"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --comment "Found existing open GitHub PR for '${COMPONENT_NAME}-${VERSION_VAR}': ${PR_URL}
Resuming monitoring of this PR."
  fi
  echo "Found existing open PR: $PR_URL. Skipping PR creation and jumping to monitor."
  ```
  **Set `PR_URL` and jump directly to Step 11** (Monitor PR).

- If `state=merged`: update Jira with `rkc-changes-done` label and merged comment. **Stop exit 0.**
- If `state=closed`: note it and continue searching.

If no matching open PR found, continue to Step 6.

---

## Step 6: Set Up Playpen (Clone)

> **CRITICAL:** Clone from `$BRANCH_NAME`, NOT from `main`. The version-specific branch
> already exists in the RKC repo. The `--src-branch` must be `$BRANCH_NAME`.

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_github_playpen.sh \
  --src-url "$RKC_URL" \
  --src-branch "$BRANCH_NAME" \
  ${JIRA_ID:+--dest-branch "$JIRA_ID"} \
  --sparse-files "pipelineruns/$REPO_NAME")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
```

On exit 1: display stderr and stop:
```
ERROR in Step 6 (Playpen setup): Clone or push failed. See details above.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
  Verify branch '$BRANCH_NAME' exists in the RKC repo.
  (If the branch is missing, sprint-onboarding for this RHOAI version may be pending.)
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

If other pipelinerun files already exist in the `.tekton` directory, use the `Read` tool to
examine one of them. Note any structural differences from the template — this can catch
environment-specific patterns not covered by the spec.

Set the target file path:
```bash
PIPELINERUN_PATH="$TEKTON_DIR/$PIPELINERUN_FILE"
```

---

## Step 8: Write PipelineRun YAML

### 8a. Determine prefetch-input

Try to fetch the Konflux prefetch-input documentation:
```
WebFetch: https://konflux.pages.redhat.com/docs/users/building/prefetching-dependencies.html#generic
```
If unreachable, continue — this is advisory only.

Then inspect the component repo's root for known dependency file names via the GitHub API:
```bash
REPO_PATH=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')
curl -s -H "Authorization: token $GITHUB_TOKEN" \
  "https://api.github.com/repos/${REPO_PATH}/contents/"
```

Determine `PREFETCH_INPUT` based on what is found:

| Detected file | `prefetch-input` value |
|--------------|----------------------|
| `go.mod` | `[{"type": "gomod", "path": "."}]` |
| `requirements.txt` | `[{"type": "pip", "path": "requirements.txt"}]` |
| `package.json` | `[{"type": "npm", "path": "."}]` |
| `Gemfile` | `[{"type": "bundler", "path": "."}]` |
| Nothing detected / fetch fails | `[]` |

If `CONTEXT_PATH_NORMALIZED != "."`, adjust the `path` field to use `$CONTEXT_PATH_NORMALIZED`.

### 8b. Write the file

> **CRITICAL — `{{...}}` and `{{ ... }}` are Tekton/PAC templating variables.**
> Write them **verbatim** — do NOT substitute their content with actual values.

Use the `Write` tool to create `$PIPELINERUN_PATH` with the following content, substituting
all `<...>` placeholders with actual variable values, and leaving all `{{...}}` untouched:

```yaml
apiVersion: tekton.dev/v1
kind: PipelineRun
metadata:
  annotations:
    build.appstudio.openshift.io/repo: <REPO_URL>?rev={{revision}}
    build.appstudio.redhat.com/commit_sha: '{{revision}}'
    build.appstudio.redhat.com/target_branch: '{{target_branch}}'
    pipelinesascode.tekton.dev/cancel-in-progress: "false"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    build.appstudio.openshift.io/build-nudge-files: "build/operator-nudging.yaml"
    pipelinesascode.tekton.dev/on-cel-expression: |
      event == "push"
      && target_branch == "<BRANCH_NAME>"
      && ( files.all.exists(p, !p.matches('^\\.tekton/')) || ".tekton/<COMPONENT_NAME>-<VERSION_VAR>-push.yaml".pathChanged() )
  labels:
    appstudio.openshift.io/application: rhoai-<VERSION_VAR>
    appstudio.openshift.io/component: <COMPONENT_NAME>-<VERSION_VAR>
    pipelines.appstudio.openshift.io/type: build
  name: <COMPONENT_NAME>-<VERSION_VAR>-on-push
  namespace: rhoai-tenant
spec:
  params:
  - name: git-url
    value: '{{source_url}}'
  - name: revision
    value: '{{revision}}'
  - name: additional-tags
    value:
    - '{{target_branch}}-{{revision}}'
  - name: output-image
    value: quay.io/rhoai/<COMPONENT_NAME>-rhel9:{{target_branch}}
  - name: rhoai-version
    value: "<RHOAI_MINOR_VERSION>"
  - name: dockerfile
    value: <DOCKERFILE_PATH>
  - name: path-context
    value: <CONTEXT_PATH_NORMALIZED>
  - name: hermetic
    value: true
  - name: prefetch-input
    value: |
      <PREFETCH_INPUT_JSON>
  - name: build-source-image
    value: true
  - name: build-image-index
    value: true
  - name: build-platforms
    value:
    <PLATFORM_LIST>
  - name: rhel-subscription-activation-key
    value: "rhel-subscription-activation-key-nonexistent"
  pipelineRef:
    resolver: git
    params:
    - name: url
      value: <RKC_URL>
    - name: revision
      value: '{{ target_branch }}'
    - name: pathInRepo
      value: pipelines/multi-arch-container-build.yaml
  taskRunTemplate:
    serviceAccountName: build-pipeline-<COMPONENT_NAME>-<VERSION_VAR>
  workspaces:
  - name: git-auth
    secret:
      secretName: '{{ git_auth_secret }}'
status: {}
```

Placeholder substitution table:

| Placeholder | Replace with |
|------------|-------------|
| `<REPO_URL>` | `$REPO_URL` |
| `<BRANCH_NAME>` | `$BRANCH_NAME` |
| `<COMPONENT_NAME>` | `$COMPONENT_NAME` |
| `<VERSION_VAR>` | `$VERSION_VAR` |
| `<RHOAI_MINOR_VERSION>` | `$RHOAI_MINOR_VERSION` |
| `<DOCKERFILE_PATH>` | `$DOCKERFILE_PATH` |
| `<CONTEXT_PATH_NORMALIZED>` | `$CONTEXT_PATH_NORMALIZED` |
| `<PREFETCH_INPUT_JSON>` | The JSON array determined in 8a (e.g. `[]`) |
| `<PLATFORM_LIST>` | Indented YAML list items for each platform, e.g.:<br>`    - linux/x86_64`<br>`    - linux-m2xlarge/arm64` |
| `<RKC_URL>` | `$RKC_URL` (the pipeline definition repo — follows `RHOAI_KONFLUX_CENTRAL_REPO_URL` override) |

> **Consistency note:** `pipelineRef.params[url]` uses `$RKC_URL` so that overriding
> `RHOAI_KONFLUX_CENTRAL_REPO_URL` (e.g. to a fork for testing) is respected everywhere.
> The default value is `https://github.com/red-hat-data-services/konflux-central.git`.

### 8c. Verify the written file

Use the `Read` tool to read `$PIPELINERUN_PATH` and verify:
- No `<...>` placeholder (angle-bracket token) remains in the file
- `name: ${COMPONENT_NAME}-${VERSION_VAR}-on-push` is present
- `serviceAccountName: build-pipeline-${COMPONENT_NAME}-${VERSION_VAR}` is present
- Platform list matches the requested architectures exactly
- `{{revision}}`, `{{target_branch}}`, `{{source_url}}`, `{{ git_auth_secret }}` are present verbatim
- YAML is syntactically consistent (no mixed indentation, no unclosed strings)

If any verification check fails, apply corrective `Edit` calls before continuing.

---

## Step 9: Commit and Push

```bash
cd "$CLONE_DIR"
git add "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE"
git status   # confirm only the expected file is staged
git commit -m "Add ${COMPONENT_NAME}-${VERSION_VAR} PipelineRun for ${REPO_NAME}

Adds Tekton PipelineRun for component '${COMPONENT_NAME}' targeting branch '${BRANCH_NAME}'.
File: pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}

Related: ${JIRA_ID:-no-jira}"
git push origin "$DEST_BRANCH"
```

If push fails with "shallow update not allowed":
```bash
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

On any other push failure, display stderr and stop:
```
ERROR in Step 9 (Push): Could not push branch '$DEST_BRANCH' to $RKC_URL. See details above.
  Check GITHUB_TOKEN has 'repo' scope and write access to $RKC_PATH.
```

---

## Step 10: Raise PR (up to 3 attempts)

> **CRITICAL:** The PR target branch is `$BRANCH_NAME`, NOT `main`.
> Both `--src-url` and `--dest-url` must be `"$RKC_URL"`.

```bash
PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
  --src-url "$RKC_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$RKC_URL" \
  --dest-branch "$BRANCH_NAME" \
  --title "Add ${COMPONENT_NAME}-${VERSION_VAR} PipelineRun for ${REPO_NAME}" \
  --description "Adds Tekton PipelineRun YAML for component '${COMPONENT_NAME}'.

## Details

| Field | Value |
|-------|-------|
| Component | \`${COMPONENT_NAME}\` |
| Version | \`${TARGET_RHOAI_VERSION}\` |
| Branch | \`${BRANCH_NAME}\` |
| Source repo | \`${REPO_URL}\` |
| File | \`pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}\` |
| Platforms | ${PLATFORMS[*]} |

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
  --add-label "rkc-pr-raised" \
  --comment "GitHub PR raised to add Konflux PipelineRun for '${COMPONENT_NAME}' to rhoai-konflux-central.

PR URL: $PR_URL
Branch: ${BRANCH_NAME}
File: pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}

CI builds will trigger for '${COMPONENT_NAME}' once this PR is merged."
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
    --add-label "rkc-changes-done" \
    --remove-label "rkc-pr-raised" \
    --comment "GitHub PR merged: $PR_URL

Konflux CI is now configured for '${COMPONENT_NAME}'.
Builds will trigger on pushes to branch '${BRANCH_NAME}' of ${REPO_URL}."
fi
```
Continue to Step 12.

**`closed` (exit 1):** PR closed without merging.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "GitHub PR was closed without merging: $PR_URL
Please review and re-run /add-component-to-rhoai-konflux-central ${JIRA_URL} to re-open."
fi
```
Stop with:
```
ERROR in Step 11 (Monitor PR): PR was closed without merging. Check: $PR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):** Attempt automated fix:
1. Use `Read` to re-examine `$PIPELINERUN_PATH` for YAML issues.
2. If fixable: apply `Edit` corrections, then:
   ```bash
   cd "$CLONE_DIR"
   git add "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE"
   git commit -m "Fix ${COMPONENT_NAME}-${VERSION_VAR} PipelineRun definition"
   git push origin "$DEST_BRANCH"
   ```
   Update Jira with fix attempt. **Jump back to Step 11** to re-monitor once.
3. If not fixable: update Jira with failure details and stop:
   ```
   ERROR in Step 11 (Monitor PR): CI checks failed and could not be auto-fixed.
   PR: $PR_URL — manual intervention required.
   ```

**`timeout` (exit 1):** PR still open after 60 minutes.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "PR monitoring timed out after 60 minutes: $PR_URL
The PR is still open. Re-run /add-component-to-rhoai-konflux-central ${JIRA_URL:-} to resume."
fi
```
Print warning and continue to Step 12 (no hard stop).

---

## Step 12: Report Completion

```
Done.

  pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE — created
  Branch              : $BRANCH_NAME
  GitHub PR           : $PR_URL — $RESULT
  Jira                : ${JIRA_ID:-(none)} — label: rkc-changes-done

Konflux CI builds will trigger for '$COMPONENT_NAME' on pushes to '$BRANCH_NAME'
in repository: $REPO_URL

Note: Review the prefetch-input array in the PR and update it if auto-detection
was incorrect or incomplete.
```

---

## Variable Summary

| Variable | ea example (`3.4-ea-2`) | non-ea example (`3.4`) |
|----------|------------------------|------------------------|
| `VERSION_VAR` | `v3-4-ea-2` | `v3-4` |
| `BRANCH_VAR` | `v3.4-ea.2` | `v3.4` |
| `BRANCH_NAME` | `rhoai-v3.4-ea.2` | `rhoai-v3.4` |
| `RHOAI_MINOR_VERSION` | `3.4.0-ea.2` | `3.4.0` |
| `PIPELINERUN_FILE` | `<comp>-v3-4-ea-2-push.yaml` | `<comp>-v3-4-push.yaml` |

Architecture mapping:

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
| `target_rhoai_version` missing/invalid | 3f | Fix field; expected `x.y` or `x.y-ea-n` |
| `architectures` missing | 3e | Add `architectures: [x86_64, arm64]` etc. to YAML |
| Branch `$BRANCH_NAME` not found in RKC | 6 | Sprint-onboarding for this version may be pending |
| Push fails (shallow) | 6, 9 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PipelineRun already exists | 4 | Expected — exits 0; Jira labelled `rkc-changes-done` |
| Open PR already found | 5 | Expected — jumps to Step 11 to monitor |
| PR creation fails 3× | 10 | Check GITHUB_TOKEN `repo` scope |
| PR closed without merge | 11 | Review PR manually; re-run skill |
| Pipeline failed | 11 | Skill attempts auto-fix and retries monitor once |
| PR monitoring timeout | 11 | PR still open; re-run to resume monitoring |
