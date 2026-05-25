---
name: add-component-to-rhoai-konflux-central
description: Adds a Tekton PipelineRun YAML to the rhoai-konflux-central GitHub repository for a new RHOAI component, then raises a GitHub PR targeting the version-specific branch.
allowed-tools: Bash
user-invocable: true
---

# Add Component to RHOAI-Konflux-Central

Creates a Tekton `PipelineRun` resource for a new RHOAI component by:
1. Generating a push PipelineRun YAML under `pipelineruns/<repo_name>/.tekton/`.
2. Raising a pull request to the version-specific branch of `rhoai-konflux-central`.

When the PR is merged, Konflux CI will start building the component.

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

If invoked with `--existing-pr-url <url>`: print 'PR already raised: <url>' and exit 0. The orchestrator passes this when the URL is already recorded in pipeline_state.json.

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
bash "scripts/check_prerequisites.sh" \
  --env "GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git curl"

if [[ -n "$JIRA_URL" ]]; then
  bash "scripts/check_prerequisites.sh" \
    --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi
```

---

## Step 2: Set Up Working Directory

```bash
eval "$(bash "scripts/init_workdir.sh" --jira-url "${JIRA_URL:-}")"
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
uv run --script scripts/download_jira_attachment.py \
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

Only when `JIRA_URL` non-empty and `$WORKDIR/component_onboarding_details.json` does not already exist:
```bash
if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  cd "$WORKDIR"
  uv run --script scripts/fetch_jira_details.py "$JIRA_URL"
fi
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
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}')

# Parse architectures array (list items under 'architectures:' key)
ARCHITECTURES=($(awk '/^  architectures:/{found=1;next} found && /^  - /{print $2} found && /^  [a-z]/{exit}' "$YAML_FILE"))
[[ ${#ARCHITECTURES[@]} -eq 0 ]] && ARCHITECTURES=($(grep -A20 'architectures:' "$YAML_FILE" | grep '^ *- ' | awk '{print $2}'))

for _field in COMPONENT_NAME REPO_URL CONTEXT_PATH DOCKERFILE_PATH TARGET_RHOAI_VERSION; do
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
eval "$(bash "scripts/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
# Sets: VERSION_VAR, BRANCH_VAR, BRANCH_NAME, RHOAI_MINOR_VERSION, CONTENT_STREAM_TAG

REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"

PIPELINERUN_FILE="${COMPONENT_NAME}-${VERSION_VAR}-push.yaml"

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
  uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
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

## Step 5: Set Up Playpen (Clone)

> **CRITICAL:** Clone from `$BRANCH_NAME`, NOT from `main`. The `--src-branch` must be `$BRANCH_NAME`.

### 5a. Ensure the remote branch exists (create from `main` if missing)

```bash
bash "scripts/ensure_github_branch.sh" \
  --repo-path "$RKC_PATH" \
  --branch-name "$BRANCH_NAME" || {
  echo "ERROR in Step 5a: Failed to ensure branch '$BRANCH_NAME' exists in $RKC_PATH."
  echo "  Check GITHUB_TOKEN has repo scope."
  exit 1
}
```

### 5b. Clone the branch into a playpen

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash scripts/setup_github_playpen.sh \
  --src-url "$RKC_URL" \
  --src-branch "$BRANCH_NAME" \
  ${JIRA_ID:+--dest-branch "$JIRA_ID"} \
  --sparse-files "pipelineruns/$REPO_NAME")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
```

On exit 1: display stderr and stop:
```
ERROR in Step 5b (Playpen setup): Clone or push failed. See details above.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 6: Create PipelineRun Directory

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

## Step 7: Write PipelineRun YAML

### 7a. Determine prefetch-input

```bash
eval "$(bash "scripts/detect_prefetch_input.sh" \
  --repo-url "$REPO_URL" \
  --context-path "$CONTEXT_PATH_NORMALIZED")"
# Sets PREFETCH_INPUT (JSON array string, defaults to [] on error)
echo "PREFETCH_INPUT: $PREFETCH_INPUT"

# Build the prefetch-input param block — omit entirely when PREFETCH_INPUT is an empty array
if [[ "$PREFETCH_INPUT" == "[]" ]]; then
  PREFETCH_PARAM_BLOCK=""
  echo "PREFETCH_INPUT is empty — prefetch-input param will be omitted from PipelineRun."
else
  PREFETCH_PARAM_BLOCK="  - name: prefetch-input
    value: |
      ${PREFETCH_INPUT}"
fi
```

### 7b. Write the file

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
    pipelinesascode.tekton.dev/cancel-in-progress: "false"
    pipelinesascode.tekton.dev/max-keep-runs: "3"
    build.appstudio.openshift.io/build-nudge-files: "build/operator-nudging.yaml"
    pipelinesascode.tekton.dev/on-cel-expression: |
      event == "push"
      && target_branch == "${BRANCH_NAME}"
      && ( files.all.exists(p, !p.matches('^\\\\.tekton/')) || ".tekton/${COMPONENT_NAME}-${VERSION_VAR}-push.yaml".pathChanged() )
  labels:
    appstudio.openshift.io/application: rhoai-${VERSION_VAR}
    appstudio.openshift.io/component: ${COMPONENT_NAME}-${VERSION_VAR}
    pipelines.appstudio.openshift.io/type: build
  name: ${COMPONENT_NAME}-${VERSION_VAR}-on-push
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
    value: quay.io/rhoai/${COMPONENT_NAME}-rhel9:{{target_branch}}
  - name: rhoai-version
    value: "${RHOAI_MINOR_VERSION}"
  - name: dockerfile
    value: ${DOCKERFILE_PATH}
  - name: path-context
    value: ${CONTEXT_PATH_NORMALIZED}
  - name: hermetic
    value: true
${PREFETCH_PARAM_BLOCK}
  - name: build-source-image
    value: true
  - name: build-image-index
    value: true
  - name: build-platforms
    value:
${PLATFORM_LIST}
  - name: rhel-subscription-activation-key
    value: "rhel-subscription-activation-key-nonexistent"
  - name: additional-build-secret
    value: "rhel-ai-private-index-auth"
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
    serviceAccountName: build-pipeline-${COMPONENT_NAME}-${VERSION_VAR}
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

### 7c. Verify the written file

```bash
grep -q "name: ${COMPONENT_NAME}-${VERSION_VAR}-on-push" "$PIPELINERUN_PATH" || {
  echo "ERROR in Step 7c: name field not set correctly in $PIPELINERUN_PATH"; exit 1
}
grep -q "serviceAccountName: build-pipeline-${COMPONENT_NAME}-${VERSION_VAR}" "$PIPELINERUN_PATH" || {
  echo "ERROR in Step 7c: serviceAccountName not set correctly"; exit 1
}
grep -q '{{revision}}' "$PIPELINERUN_PATH" || {
  echo "ERROR in Step 7c: Tekton template variables missing from $PIPELINERUN_PATH"; exit 1
}
# Check no angle-bracket placeholders remain
grep -qE '<[A-Z_]+>' "$PIPELINERUN_PATH" && {
  echo "ERROR in Step 7c: Unreplaced placeholders remain in $PIPELINERUN_PATH"
  grep -E '<[A-Z_]+>' "$PIPELINERUN_PATH"
  exit 1
} || true
echo "Verification passed for $PIPELINERUN_PATH"
```

---

## Step 8: Commit and Push

```bash
bash "scripts/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE" \
  --message   "Add ${COMPONENT_NAME}-${VERSION_VAR} PipelineRun for ${REPO_NAME}

Adds Tekton PipelineRun for component '${COMPONENT_NAME}' targeting branch '${BRANCH_NAME}'.
File: pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}

Related: ${JIRA_ID:-no-jira}" \
  --branch    "$DEST_BRANCH"
```

On exit 1, display stderr and stop:
```
ERROR in Step 8 (Push): Could not push branch '$DEST_BRANCH' to $RKC_URL. See details above.
  Check GITHUB_TOKEN has 'repo' scope and write access to $RKC_PATH.
```

---

## Step 9: Raise PR (up to 3 attempts)

> **CRITICAL:** The PR target branch is `$BRANCH_NAME`, NOT `main`.
> Both `--src-url` and `--dest-url` must be `"$RKC_URL"`.

Before raising the PR, assert that `$BRANCH_NAME` is set and is not `main`:

```bash
if [[ -z "$BRANCH_NAME" || "$BRANCH_NAME" == "main" ]]; then
  echo "ERROR in Step 9: BRANCH_NAME is '${BRANCH_NAME:-<empty>}' — refusing to raise PR to main."
  echo "  BRANCH_NAME must be a version-specific branch (e.g. rhoai-3.5-ea.1)."
  echo "  Check that TARGET_RHOAI_VERSION was parsed correctly in Step 3f."
  exit 1
fi
echo "PR target branch: $BRANCH_NAME (confirmed not main)"
```

```bash
PR_URL=$(uv run --script scripts/raise_github_pr.py \
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
ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. Aborting.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

On success, update Jira (only when `JIRA_URL` non-empty):
```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "rkc-pr-raised" \
  --comment "[step:okc] GitHub PR raised to add Konflux PipelineRun for '${COMPONENT_NAME}' to rhoai-konflux-central.

PR URL: $PR_URL
Branch: ${BRANCH_NAME}
File: pipelineruns/${REPO_NAME}/.tekton/${PIPELINERUN_FILE}

CI builds will trigger for '${COMPONENT_NAME}' once this PR is merged."
```

---

## Step 10: Report Completion

```
Done.

  pipelineruns/$REPO_NAME/.tekton/$PIPELINERUN_FILE — created
  Branch              : $BRANCH_NAME
  GitHub PR           : $PR_URL
  Jira                : ${JIRA_ID:-(none)} — label: rkc-pr-raised

Review the prefetch-input array in the PR and update it if auto-detection
was incorrect or incomplete.
```

---

## Variable Summary

| Variable | ea example (`3.4-ea-2`) | non-ea example (`3.4`) |
|----------|------------------------|------------------------|
| `VERSION_VAR` | `v3-4-ea-2` | `v3-4` |
| `BRANCH_VAR` | `3.4-ea.2` | `3.4` |
| `BRANCH_NAME` | `rhoai-3.4-ea.2` | `rhoai-v3.4` |
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
| Branch `$BRANCH_NAME` not found in RKC | 5a | Auto-created from `main`; if creation fails check `GITHUB_TOKEN` `repo` scope |
| Push fails (shallow) | 5, 8 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PipelineRun already exists | 4 | Expected — exits 0; Jira labelled `rkc-changes-done` |
| PR creation fails 3× | 9 | Check GITHUB_TOKEN `repo` scope |
