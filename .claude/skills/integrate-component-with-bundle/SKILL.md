---
name: integrate-component-with-bundle
description: Updates the build-config repository (ODH-Build-Config for ODH, RHOAI-Build-Config for RHOAI) with a new component's relatedImages entry (bundle/bundle-patch.yaml) and optionally config/build-config.yaml (RHOAI only), then raises a GitHub PR. Automates Step 8 of the ODH/RHOAI component onboarding pipeline.
allowed-tools: Bash, Read, Edit, Write
user-invocable: true
---

# Integrate Component with Bundle

Updates the build-config repository (`ODH-Build-Config` for ODH, `RHOAI-Build-Config` for RHOAI)
for a new component by:
1. Adding a `relatedImages` entry to `bundle/bundle-patch.yaml`.
2. (RHOAI only) Adding an entry to `config/build-config.yaml`.
3. Raising a GitHub PR for the change(s).

> **CRITICAL — `BC_URL` is the single source of truth for every Git and GitHub
> operation in this skill.**
> It is resolved in Step 0 if `BUILD_CONFIG_REPO_URL` is explicitly set; otherwise it is
> derived in Step 3d from `product_context`
>   (ODH → `opendatahub-io/ODH-Build-Config`; RHOAI → `red-hat-data-services/RHOAI-Build-Config`).
> Every clone, push, and PR call (`--src-url`, `--dest-url`) **must** use `$BC_URL`
> — never a hardcoded URL. `BC_PATH` is derived from `BC_URL` in Step 3d.
> This rule applies for the entire skill execution even if the URL resolves to a fork.

## Usage

```
/integrate-component-with-bundle <jira-url>
```

Examples:
```
/integrate-component-with-bundle https://redhat.atlassian.net/browse/RHODS-14226
```

## Prerequisites

- `GITHUB_USER` — GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — personal access token with `repo` scope and push access to the build-config repo
- `JIRA_USER_EMAIL` — your Atlassian account email
- `JIRA_API_TOKEN` — Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `git`
- Optional: `BUILD_CONFIG_REPO_URL` — overrides the target build-config repo. If not set,
  the default is derived from `product_context`:
  - `ODH`  → `https://github.com/opendatahub-io/ODH-Build-Config.git`
  - `RHOAI` → `https://github.com/red-hat-data-services/RHOAI-Build-Config.git`
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**Jira attachment:** The Jira issue must have `component_onboarding_details.yaml` attached
(created by `/create-component-onboarding-jira`).

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.
---

## Step 0: Parse Inputs

1. Extract `<jira-url>` (the first positional argument).
   Extract `<jira-id>` as the last path segment (e.g., `RHODS-14226`).

   If the argument cannot be parsed as a Jira URL (no `/browse/` segment), stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHODS-14226

2. Resolve `BC_URL` — only if `BUILD_CONFIG_REPO_URL` is explicitly set. If not set, the
   default will be derived from `product_context` in Step 3d. Execute this exact block;
   do NOT skip the `echo`:

   ```bash
   if [[ -n "${BUILD_CONFIG_REPO_URL:-}" ]]; then
     BC_URL="$BUILD_CONFIG_REPO_URL"
     echo "BUILD_CONFIG_REPO_URL is set; BC_URL resolved to: $BC_URL"
   else
     BC_URL=""
     echo "BUILD_CONFIG_REPO_URL is not set — will derive default from product_context in Step 3d."
   fi
   ```

   **Never override or re-derive `BC_URL` after Step 3d.** `BC_PATH` is derived in Step 3d
   once `BC_URL` is finalised.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
if [[ -z "${GITHUB_USER:-}" ]]; then
  echo "ERROR: GITHUB_USER is not set. export GITHUB_USER=yourusername"; exit 1
fi
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERROR: GITHUB_TOKEN is not set. export GITHUB_TOKEN=yourtoken"; exit 1
fi
if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  echo "ERROR: JIRA_USER_EMAIL is not set. export JIRA_USER_EMAIL=you@example.com"; exit 1
fi
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: JIRA_API_TOKEN is not set. export JIRA_API_TOKEN=your-api-token"; exit 1
fi
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1
fi
if ! command -v git &>/dev/null; then
  echo "ERROR: git is not installed."; exit 1
fi
```

---

## Step 2: Set Up Working Directory

```bash
WORKDIR="$(pwd)/<jira-id>"
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"
cd "$WORKDIR"
```

---

## Step 3: Fetch Jira Details and Component YAML

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
  Ensure the attachment exists on the Jira issue. Run /create-component-onboarding-jira first.
```

**3c. Parse the YAML** using the `Read` tool to read `$WORKDIR/component_onboarding_details.yaml`.

Extract and store these values (all under `inputs:`):

| Variable | YAML field | Required | Example |
|----------|-----------|----------|---------|
| `COMPONENT_NAME` | `inputs.component_name` | Yes | `odh-ai-first-demo` |
| `PRODUCT_CONTEXT` | `inputs.product_context` | Yes | `ODH` |
| `REPO_URL` | `inputs.repo_url` | Yes | `https://github.com/rhoai-rhtap/odh-ai-first-demo` |
| `REPO_BRANCH` | `inputs.repo_branch` | Yes | `main` |
| `TARGET_RHOAI_VERSION` | `inputs.target_rhoai_version` | When RHOAI | `2.16` or `2.16-ea-1` |

If any of COMPONENT_NAME, PRODUCT_CONTEXT, REPO_URL, REPO_BRANCH is missing, stop with:
```
ERROR in Step 3c: Missing required field '<field>' in component_onboarding_details.yaml. Aborting.
```

If `product_context=RHOAI` and `target_rhoai_version` is missing, stop with:
```
ERROR in Step 3c: Missing required field 'target_rhoai_version' in component_onboarding_details.yaml
  (required when product_context=RHOAI). Aborting.
```

**3d. Derive computed variables:**

```bash
# 3d-1: Finalise BC_URL and derive BC_PATH
if [[ -z "${BC_URL:-}" ]]; then
  if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
    BC_URL="https://github.com/opendatahub-io/ODH-Build-Config.git"
  elif [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
    BC_URL="https://github.com/red-hat-data-services/RHOAI-Build-Config.git"
  fi
  echo "BC_URL derived from product_context (${PRODUCT_CONTEXT}): $BC_URL"
fi

BC_PATH=$(echo "$BC_URL" | sed 's|https://github.com/||;s|\.git$||')
echo "BC_PATH: $BC_PATH"

# 3d-2: Parse target_rhoai_version and derive version/branch variables (RHOAI only)
if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  if [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)-ea-([0-9]+)$ ]]; then
    x="${BASH_REMATCH[1]}"; y="${BASH_REMATCH[2]}"; n="${BASH_REMATCH[3]}"
    version_var="v${x}-${y}-ea-${n}"
    branch_var="v${x}.${y}-ea.${n}"
  elif [[ "$TARGET_RHOAI_VERSION" =~ ^([0-9]+)\.([0-9]+)$ ]]; then
    x="${BASH_REMATCH[1]}"; y="${BASH_REMATCH[2]}"
    version_var="v${x}-${y}"
    branch_var="v${x}.${y}"
  else
    echo "ERROR in Step 3d: Invalid target_rhoai_version '${TARGET_RHOAI_VERSION}'. Expected x.y or x.y-ea-n."
    exit 1
  fi
  branch_name="rhoai-${branch_var}"
  echo "version_var  : $version_var"
  echo "branch_var   : $branch_var"
  echo "branch_name  : $branch_name"
fi

# 3d-3: Quay organisation based on product context
if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
  QUAY_ORG="opendatahub"
elif [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  QUAY_ORG="rhoai"
else
  echo "ERROR in Step 3d: Unknown PRODUCT_CONTEXT '$PRODUCT_CONTEXT'. Expected 'ODH' or 'RHOAI'."
  exit 1
fi

# relatedImages entry name: uppercase component name with hyphens → underscores
RELATED_IMAGE_NAME="RELATED_IMAGE_$(echo "$COMPONENT_NAME" | tr '[:lower:]-' '[:upper:]_')_IMAGE"
# e.g. odh-ai-first-demo → RELATED_IMAGE_ODH_AI_FIRST_DEMO_IMAGE

# relatedImages entry value — try to fetch the real SHA256 digest from Quay first
STABLE_IMAGE="quay.io/${QUAY_ORG}/${COMPONENT_NAME}:odh-stable"
REAL_DIGEST=$(skopeo inspect --no-creds "docker://${STABLE_IMAGE}" 2>/dev/null \
  | jq -r '.Digest // ""' 2>/dev/null || echo "")

if [[ -n "$REAL_DIGEST" && "$REAL_DIGEST" == sha256:* ]]; then
  RELATED_IMAGE_VALUE="quay.io/${QUAY_ORG}/${COMPONENT_NAME}@${REAL_DIGEST}"
  USING_PLACEHOLDER=false
  echo "  Fetched real digest from Quay: $REAL_DIGEST"
else
  RELATED_IMAGE_VALUE="quay.io/${QUAY_ORG}/${COMPONENT_NAME}@sha256:$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  USING_PLACEHOLDER=true
  echo "  WARNING: Image not yet published to Quay — using placeholder digest."
  echo "  Update bundle-patch.yaml with the real digest before merging the PR."
fi
```

Print a summary:
```
Component: $COMPONENT_NAME
Product context: $PRODUCT_CONTEXT → QUAY_ORG=$QUAY_ORG
Related image name: $RELATED_IMAGE_NAME
Related image value: $RELATED_IMAGE_VALUE
Repo: $BC_URL
```

---

## Step 4: Check If Component Already Exists in bundle-patch.yaml

Before cloning, check whether `$RELATED_IMAGE_NAME` already has an entry in
`bundle/bundle-patch.yaml` on the **`main` branch** of `$BC_URL`.

> **Reminder:** Use `$BC_PATH` (derived from `$BC_URL` in Step 3d) for the GitHub API URL.
> Do NOT substitute the hardcoded upstream path.

```bash
BUNDLE_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/${BC_PATH}/contents/bundle/bundle-patch.yaml?ref=main" \
  -o "$BUNDLE_TMPFILE")
```

**If `HTTP_STATUS` is not `200`:**
- `404` — file not found. Warn and continue to Step 5:
  ```
  WARN in Step 4: bundle/bundle-patch.yaml not found on main branch (HTTP 404).
    Verify BC_URL points to the correct repo. Continuing.
  ```
- Any other non-200 — Warn and continue to Step 5:
  ```
  WARN in Step 4: Could not fetch bundle/bundle-patch.yaml (HTTP $HTTP_STATUS). Continuing.
  ```
- Do NOT abort — the API check is a fast-path optimisation; proceed with the full flow if inconclusive.

**If `HTTP_STATUS` is `200`:**

```bash
if grep -q "${RELATED_IMAGE_NAME}" "$BUNDLE_TMPFILE"; then
  ENTRY_EXISTS=true
else
  ENTRY_EXISTS=false
fi
rm -f "$BUNDLE_TMPFILE"
```

If `ENTRY_EXISTS=true`:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "obc-changes-done" \
  --comment "'$COMPONENT_NAME' ($RELATED_IMAGE_NAME) is already present in bundle/bundle-patch.yaml on the main branch of ${BC_PATH}.

No changes are needed. The build-config integration for this component is already complete."
```

Print:
```
$RELATED_IMAGE_NAME already exists in bundle/bundle-patch.yaml (main branch).
Jira updated with label 'obc-changes-done'. No action needed.
```

**Stop with exit 0.**

If `ENTRY_EXISTS=false`: clean up temp file and continue to Step 5.
```bash
rm -f "$BUNDLE_TMPFILE"
```

---

## Step 5: Check for Existing Open PR in Jira Comments

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.json`.

```bash
BC_REPO_NAME="${BC_PATH##*/}"
# e.g. "ODH-Build-Config" or "RHOAI-Build-Config"
```

Search the array at `fields.comment.comments[].body` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/${BC_REPO_NAME}/pull/\d+
```

For each URL found, run:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url <found-url> --check-only
```

Parse stdout:

- If `state=open` **and** `title=` contains `$COMPONENT_NAME`:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "Existing open GitHub PR found for '$COMPONENT_NAME' in ${BC_PATH}: <found-url>.

No new PR will be raised. Review and merge the existing PR to complete this step."
  ```
  Print:
  ```
  Found existing open PR for $COMPONENT_NAME: <found-url>
  Jira updated. No new PR raised — review and merge the existing PR.
  ```
  **Stop with exit 0.**

- If `state=merged`:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "obc-changes-done" \
    --comment "${BC_PATH} PR for '$COMPONENT_NAME' was already merged: <found-url>. No action needed.

Step 8 (Integrate with Bundle) is complete."
  ```
  Print: `PR already merged. Step 8 (integrate-with-bundle) is complete.`
  **Stop with exit 0.**

If no matching PR is found, continue to Step 6.

---

## Step 6: Set Up Playpen (Clone)

> **Reminder:** Pass `--src-url "$BC_URL"` — finalised in Step 3d (or Step 0 if
> `BUILD_CONFIG_REPO_URL` was explicitly set). Do NOT hardcode the upstream URL here.

Determine the source branch and sparse-file set based on `product_context`:

```bash
if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
  SRC_BRANCH="main"
  SPARSE_FILES="bundle"
else
  SRC_BRANCH="$branch_name"   # e.g. "rhoai-v2.16" or "rhoai-v2.16-ea.1"
  SPARSE_FILES="bundle config"
fi

cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_github_playpen.sh \
  --src-url "$BC_URL" \
  --src-branch "$SRC_BRANCH" \
  --dest-branch "<jira-id>" \
  --sparse-files "$SPARSE_FILES")
```

Parse `PLAYPEN_OUTPUT` from stdout:
- Line 1 → `CLONE_DIR` (absolute path, e.g. `$WORKDIR/ODH-Build-Config-playpen`)
- Line 2 → `DEST_BRANCH` (e.g. `RHODS-14226`)

On exit 1: display stderr and stop with:
```
ERROR in Step 6 (Playpen setup): Clone or push failed. See details above.
  Check network connectivity and GITHUB_TOKEN (needs push access to $BC_PATH).
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "<jira-id>"
```

---

## Step 7: Update bundle/bundle-patch.yaml

Use the `Read` tool to read `$CLONE_DIR/bundle/bundle-patch.yaml`.

If the file does not exist, stop with:
```
ERROR in Step 7: bundle/bundle-patch.yaml not found in $CLONE_DIR.
  Verify that $BC_URL points to the correct build-config repository.
```

Locate the `patch.relatedImages:` array. It will contain existing entries like:
```yaml
patch:
  relatedImages:
    - name: RELATED_IMAGE_EXISTING_COMPONENT_IMAGE
      value: quay.io/opendatahub/existing-component@sha256:abc123...
      component: existing-component
    - name: RELATED_IMAGE_ANOTHER_COMPONENT_IMAGE
      value: quay.io/opendatahub/another-component@sha256:def456...
      component: another-component
```

**Check if `$RELATED_IMAGE_NAME` already appears in the file:**
- **Already present**: Print `$RELATED_IMAGE_NAME already in bundle-patch.yaml — skipping edit.`
- **Not present**: Use the `Edit` tool to append the new entry at the **end of the
  `relatedImages` array**, before any sibling key (or at end of file if it is the last key).
  Match the indentation of existing entries (4 spaces for `- name:`, 6 spaces for `value:`).

  **ODH** (include `component:` field):
  ```yaml
      - name: $RELATED_IMAGE_NAME
        value: $RELATED_IMAGE_VALUE
        component: $COMPONENT_NAME
  ```

  **RHOAI** (omit `component:` field):
  ```yaml
      - name: $RELATED_IMAGE_NAME
        value: $RELATED_IMAGE_VALUE
  ```

After editing, verify with the `Read` tool that:
- `name: $RELATED_IMAGE_NAME` is present under `patch.relatedImages`
- `value: $RELATED_IMAGE_VALUE` is present and on the line immediately following
- Surrounding entries are undisturbed

If verification fails, fix with another `Edit` call before continuing.

---

## Step 8: Update config/build-config.yaml (RHOAI only)

> **Execute this step only when `product_context=RHOAI`. Skip entirely for ODH.**

**8a. Read the file**

Use the `Read` tool to read `$CLONE_DIR/config/build-config.yaml`.

If the file does not exist, stop with:
```
ERROR in Step 8: config/build-config.yaml not found in $CLONE_DIR.
  Verify that $BC_URL points to the correct RHOAI-Build-Config repository.
```

**8b. Idempotency check**

Check if `rhoai/${COMPONENT_NAME}-rhel9:` already appears under
`config.replacements[0].repo_mappings`. If present:
```
rhoai/${COMPONENT_NAME}-rhel9 already in config.replacements[0].repo_mappings — skipping.
```
Continue to Step 9.

**8c. Insert the new entry**

Use the `Edit` tool to append the new entry to `config.replacements[0].repo_mappings`,
matching the indentation of surrounding entries:
```yaml
    rhoai/<COMPONENT_NAME>-rhel9: rhoai/<COMPONENT_NAME>-rhel9
```

**8d. Verify**

Use the `Read` tool to confirm:
- `rhoai/${COMPONENT_NAME}-rhel9: rhoai/${COMPONENT_NAME}-rhel9` is present
- Surrounding entries are undisturbed

If verification fails, apply a corrective `Edit` before continuing.

---

## Step 9: Commit and Push

> **Reminder:** `origin` was set to `$BC_URL` by `setup_github_playpen.sh` in Step 6.
> Pushing to `origin` is correct — do NOT change the remote URL here.

```bash
cd "$CLONE_DIR"
git add bundle/bundle-patch.yaml
if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  git add config/build-config.yaml
fi
git status   # verify only the expected file(s) are staged
if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
  git commit -m "Add $COMPONENT_NAME to bundle-patch.yaml"
else
  git commit -m "Add $COMPONENT_NAME to bundle-patch.yaml and build-config.yaml"
fi
git push origin "$DEST_BRANCH"
```

If push fails with "shallow update not allowed":
```bash
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

On any other push failure, display stderr and stop with:
```
ERROR in Step 9 (Push): Could not push branch '$DEST_BRANCH' to origin. See details above.
```

---

## Step 10: Raise PR (up to 3 attempts)

> **Reminder:** Both `--src-url` and `--dest-url` must be `"$BC_URL"`. Do NOT replace
> either with the hardcoded upstream URL.

Build the PR description, including a placeholder warning when the real digest was not available:

```bash
if [[ "${USING_PLACEHOLDER:-true}" == "true" ]]; then
  PLACEHOLDER_NOTE="> **NOTE:** The SHA256 digest for \`$RELATED_IMAGE_NAME\` is a **placeholder** — the image has not yet been built by Konflux.
> Before merging this PR, replace the digest with the real value:
> \`\`\`
> skopeo inspect --no-creds docker://quay.io/${QUAY_ORG}/${COMPONENT_NAME}:odh-stable | jq -r '.Digest'
> \`\`\`"
else
  PLACEHOLDER_NOTE=""
fi

if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
  FILES_CHANGED="**File changed:**
- \`bundle/bundle-patch.yaml\` — added \`$RELATED_IMAGE_NAME\` to \`patch.relatedImages\`"
else
  FILES_CHANGED="**Files changed:**
- \`bundle/bundle-patch.yaml\` — added \`$RELATED_IMAGE_NAME\` to \`patch.relatedImages\`
- \`config/build-config.yaml\` — added \`rhoai/${COMPONENT_NAME}-rhel9\` to \`config.replacements[0].repo_mappings\` (RHOAI only)"
fi

PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
  --src-url "$BC_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$BC_URL" \
  --dest-branch main \
  --title "Add $COMPONENT_NAME to bundle-patch.yaml" \
  --description "Adds '$COMPONENT_NAME' to the ${BC_PATH} bundle relatedImages.

Component: $COMPONENT_NAME
Product context: $PRODUCT_CONTEXT
Quay org: $QUAY_ORG
Upstream repo: $REPO_URL @ $REPO_BRANCH
Jira: <jira-url>

${FILES_CHANGED}

${PLACEHOLDER_NOTE}")
```

On success: `PR_URL` contains the URL printed to stdout.

On failure:
- "Branch not found" → re-push the branch (`git push origin "$DEST_BRANCH"`) and retry.
- "Connection error" → notify user to check network and retry.
- Any other error → retry (up to 3 times total).

After 3 failures, stop with:
```
ERROR in Step 10 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting.
```

After a successful PR creation, update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "obc-changes-done" \
  --comment "GitHub PR raised to add '$COMPONENT_NAME' to ${BC_PATH}.

PR URL: $PR_URL

Files changed:
- bundle/bundle-patch.yaml: $RELATED_IMAGE_NAME added to patch.relatedImages
- config/build-config.yaml: rhoai/${COMPONENT_NAME}-rhel9 added to repo_mappings (RHOAI only)"
```

---

## Step 11: Monitor the PR

```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "$PR_URL" \
  --timeout 60
```

Read the stdout result:

**`merged` (exit 0):** PR merged.

Update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --remove-label "obc-changes-done" \
  --add-label "obc-pr-merged" \
  --comment "${BC_PATH} PR merged: $PR_URL

bundle/bundle-patch.yaml for '$COMPONENT_NAME' is now live on main.

Step 12 (Integrate with Bundle) is complete."
```

Continue to Step 12.

**`closed` (exit 1):** PR closed without merging.

Update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --comment "${BC_PATH} PR was closed without merging: $PR_URL

Please review and re-trigger if needed."
```

Stop with:
```
ERROR in Step 11: PR was closed without merging.
PR: $PR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):** CI checks failed on the PR.

Update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --comment "CI checks failed on ${BC_PATH} PR: $PR_URL

Please review the PR checks and push a fix, then re-run this skill to resume monitoring."
```

Stop with:
```
ERROR in Step 11: CI checks failed on PR $PR_URL.
Manual intervention required — review the PR and push a fix, then re-run.
```

**`timeout` (exit 1):** PR still open after 60 minutes.

Update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --comment "PR monitoring timed out after 60 minutes. PR is still open: $PR_URL

Re-run /integrate-component-with-bundle to resume — at Step 5 it will detect the
existing PR and jump straight to monitoring."
```

Print:
```
WARNING: PR monitoring timed out after 60 minutes.
PR is still open: $PR_URL
Re-run this skill to resume monitoring (Step 5 will skip raising a new PR).
```

---

## Step 12: Report Completion

Print:
```
Done.

  bundle/bundle-patch.yaml    — $RELATED_IMAGE_NAME added to patch.relatedImages
  config/build-config.yaml    — rhoai/${COMPONENT_NAME}-rhel9 added (RHOAI only)
  GitHub PR                   — merged: $PR_URL
  Jira                        — updated (label: obc-pr-merged)

  component_name              : $COMPONENT_NAME
  product_context             : $PRODUCT_CONTEXT
  quay_org                    : $QUAY_ORG
  related_image_name          : $RELATED_IMAGE_NAME
  repo                        : $BC_URL

Integrate with Bundle (pipeline step 8) is complete.
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_USER` not set | Step 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | Step 1 | `export GITHUB_TOKEN=yourtoken` (needs push access to build-config repo) |
| `JIRA_USER_EMAIL` not set | Step 1 | `export JIRA_USER_EMAIL=you@example.com` |
| `JIRA_API_TOKEN` not set | Step 1 | `export JIRA_API_TOKEN=your-token` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `component_onboarding_details.yaml` missing | Step 3b | Run `/create-component-onboarding-jira <jira-url>` first |
| `target_rhoai_version` missing (RHOAI) | Step 3c | Add field to YAML and re-upload to Jira |
| Invalid `target_rhoai_version` format | Step 3d | Expected format is `x.y` or `x.y-ea-n` (e.g. `2.16` or `2.16-ea-1`) |
| Unknown `PRODUCT_CONTEXT` | Step 3d | Set `product_context: ODH` or `product_context: RHOAI` in the YAML and re-upload |
| Component already in bundle-patch.yaml (main) | Step 4 | Expected — Jira updated; skill exits 0 cleanly |
| Existing open PR found | Step 5 | Expected — Jira updated; merge the existing PR |
| PR already merged | Step 5 | Expected — skill exits 0 cleanly |
| Clone or push fails | Step 6 | Check GITHUB_TOKEN push scope on `$BC_PATH` |
| Shallow push rejected | Steps 6, 9 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| `bundle/bundle-patch.yaml` not found in clone | Step 7 | Check `BC_URL` points to the correct build-config repo |
| `config/build-config.yaml` not found in clone | Step 8 | Check `BC_URL` points to the correct RHOAI-Build-Config repo |
| PR creation fails 3× | Step 10 | Check GITHUB_TOKEN; verify branch was pushed; fix manually |
| PR closed without merge | Step 11 | Review and re-run |
| PR CI checks failed | Step 11 | Review PR checks; push fix; re-run |
| PR monitoring timeout | Step 11 | Re-run skill — Step 5 detects existing PR and skips raising a new one |
