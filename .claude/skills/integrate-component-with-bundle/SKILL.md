---
name: integrate-component-with-bundle
description: Updates the build-config repository (ODH-Build-Config for ODH, RHOAI-Build-Config for RHOAI) with a new component's relatedImages entry (bundle/bundle-patch.yaml) and optionally config/build-config.yaml (RHOAI only), then raises a GitHub PR. Automates Step 8 of the ODH/RHOAI component onboarding pipeline.
allowed-tools: Bash
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

1. Parse and validate the Jira URL:

   ```bash
   eval "$(bash "$COMMON_SCRIPTS_DIR/parse_jira_url.sh" "${1:-}")"
   echo "JIRA_URL : ${JIRA_URL:-(not provided)}"
   echo "JIRA_ID  : ${JIRA_ID:-(not provided)}"
   ```

2. Note whether `BUILD_CONFIG_REPO_URL` is set — it will be passed to `resolve_bc_url.sh`
   in Step 3d once `product_context` is known:

   ```bash
   echo "BUILD_CONFIG_REPO_URL : ${BUILD_CONFIG_REPO_URL:-(not set, will derive from product_context in Step 3d)}"
   ```

   **`BC_URL` and `BC_PATH` are resolved in Step 3d.** Never set or override them before that.

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

**3c. Parse the YAML** from `$WORKDIR/component_onboarding_details.yaml`:

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/parse_component_details.sh" \
  --workdir    "$WORKDIR" \
  --jira-id    "$JIRA_ID" \
  --scripts-dir "$COMMON_SCRIPTS_DIR")"
# Sets: COMPONENT_NAME, REPO_URL, REPO_BRANCH, PRODUCT_CONTEXT,
#       QUAY_ORG, QUAY_VISIBILITY, QUAY_REPO_URI, IS_OPERATOR

# Also extract TARGET_RHOAI_VERSION (optional field, required when PRODUCT_CONTEXT=RHOAI)
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$WORKDIR/component_onboarding_details.yaml" | awk '{print $2}')
```

| Variable | YAML field | Required | Example |
|----------|-----------|----------|---------|
| `COMPONENT_NAME` | `inputs.component_name` | Yes | `odh-ai-first-demo` |
| `PRODUCT_CONTEXT` | `inputs.product_context` | Yes | `ODH` |
| `REPO_URL` | `inputs.repo_url` | Yes | `https://github.com/rhoai-rhtap/odh-ai-first-demo` |
| `REPO_BRANCH` | `inputs.repo_branch` | Yes | `main` |
| `TARGET_RHOAI_VERSION` | `inputs.target_rhoai_version` | When RHOAI | `2.16` or `2.16-ea-1` |

If `product_context=RHOAI` and `target_rhoai_version` is missing, stop with:
```
ERROR in Step 3c: Missing required field 'target_rhoai_version' in component_onboarding_details.yaml
  (required when product_context=RHOAI). Aborting.
```

**3d. Derive computed variables:**

```bash
# 3d-1: Resolve BC_URL and BC_PATH from product_context (with optional override)
eval "$(bash "$COMMON_SCRIPTS_DIR/resolve_bc_url.sh" \
  --product-context "$PRODUCT_CONTEXT" \
  ${BUILD_CONFIG_REPO_URL:+--override "$BUILD_CONFIG_REPO_URL"})"
# Sets: BC_URL, BC_PATH
echo "BC_URL : $BC_URL"
echo "BC_PATH: $BC_PATH"

# 3d-2: Parse target_rhoai_version into version/branch variables (RHOAI only)
if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  eval "$(bash "$COMMON_SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION")"
  # Sets: VERSION_VAR, BRANCH_VAR, BRANCH_NAME, RHOAI_MINOR_VERSION, CONTENT_STREAM_TAG
fi

# 3d-3: Resolve RELATED_IMAGE_NAME, RELATED_IMAGE_VALUE, USING_PLACEHOLDER
eval "$(bash "$COMMON_SCRIPTS_DIR/resolve_bundle_image.sh" \
  --component-name "$COMPONENT_NAME" \
  --quay-org       "$QUAY_ORG")"
# Sets: RELATED_IMAGE_NAME, RELATED_IMAGE_VALUE, USING_PLACEHOLDER
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
check_result=0
bash "$COMMON_SCRIPTS_DIR/check_github_file.sh" \
  --repo-path "$BC_PATH" \
  --file-path "bundle/bundle-patch.yaml" \
  --ref       "main" \
  --grep      "$RELATED_IMAGE_NAME" || check_result=$?
# check_result: 0=found, 1=not found or 404, 2=API error
```

- `check_result=2` (API error) — warn and continue to Step 5:
  ```
  WARN in Step 4: Could not fetch bundle/bundle-patch.yaml via GitHub API. Continuing.
  ```
- Do NOT abort — this is a fast-path optimisation; proceed if inconclusive.

If `check_result=0` (entry already present):

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

Extract existing GitHub PR URLs from the Jira comments:

```bash
BC_REPO_NAME="${BC_PATH##*/}"
# e.g. "ODH-Build-Config" or "RHOAI-Build-Config"

EXISTING_PR_URLS=$(jq -r '.fields.comment.comments[].body' \
  "$WORKDIR/component_onboarding_details.json" 2>/dev/null \
  | grep -oE "https://github\.com/[^/[:space:]]+/${BC_REPO_NAME}/pull/[0-9]+" \
  | sort -u || true)
```

Search `$EXISTING_PR_URLS` for GitHub PR URLs matching:
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
  SRC_BRANCH="$branch_name"   # e.g. "rhoai-2.16" or "rhoai-2.16-ea.1"
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

```bash
[[ -f "$CLONE_DIR/bundle/bundle-patch.yaml" ]] || {
  echo "ERROR in Step 7: bundle/bundle-patch.yaml not found in $CLONE_DIR."
  echo "  Verify that $BC_URL points to the correct build-config repository."
  exit 1
}

if grep -qF "$RELATED_IMAGE_NAME" "$CLONE_DIR/bundle/bundle-patch.yaml"; then
  echo "$RELATED_IMAGE_NAME already in bundle-patch.yaml — skipping edit."
else
  COMPONENT_ARG=""
  [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]] && COMPONENT_ARG="--component $COMPONENT_NAME"

  uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" append-array-entry \
    "$CLONE_DIR/bundle/bundle-patch.yaml" \
    --array-key "patch.relatedImages" \
    --name      "$RELATED_IMAGE_NAME" \
    --value     "$RELATED_IMAGE_VALUE" \
    $COMPONENT_ARG || {
    echo "ERROR in Step 7 (Update bundle-patch.yaml): Could not append relatedImages entry. Aborting."
    exit 1
  }

  grep -qF "$RELATED_IMAGE_NAME" "$CLONE_DIR/bundle/bundle-patch.yaml" || {
    echo "ERROR: $RELATED_IMAGE_NAME not found in bundle-patch.yaml after insert."
    exit 1
  }
fi
```

---

## Step 8: Update config/build-config.yaml (RHOAI only)

> **Execute this step only when `product_context=RHOAI`. Skip entirely for ODH.**

**8a. Read the file**

```bash
[[ -f "$CLONE_DIR/config/build-config.yaml" ]] || {
  echo "ERROR in Step 8: config/build-config.yaml not found in $CLONE_DIR."
  echo "  Verify that $BC_URL points to the correct RHOAI-Build-Config repository."
  exit 1
}
```

**8b. Idempotency check**

Check if `rhoai/${COMPONENT_NAME}-rhel9:` already appears under
`config.replacements[0].repo_mappings`. If present, skip to Step 9.

**8c. Insert the new entry**

```bash
if grep -q "rhoai/${COMPONENT_NAME}-rhel9:" "$CLONE_DIR/config/build-config.yaml" 2>/dev/null; then
  echo "rhoai/${COMPONENT_NAME}-rhel9 already in config.replacements[0].repo_mappings — skipping."
else
  uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" insert-simple-map-entry \
    "$CLONE_DIR/config/build-config.yaml" \
    --map-key "config.replacements.0.repo_mappings" \
    --key     "rhoai/${COMPONENT_NAME}-rhel9" \
    --value   "rhoai/${COMPONENT_NAME}-rhel9"
fi
```

On exit 1 from `edit_yaml.py`: display stderr and stop with:
```
ERROR in Step 8c (Update build-config.yaml): Could not insert repo_mappings entry. See details above. Aborting.
```

**8d. Verify**

```bash
grep -q "rhoai/${COMPONENT_NAME}-rhel9:" "$CLONE_DIR/config/build-config.yaml" \
  || { echo "ERROR: rhoai/${COMPONENT_NAME}-rhel9 not found in build-config.yaml after insert."; exit 1; }
```

---

## Step 9: Commit and Push

> **Reminder:** `origin` was set to `$BC_URL` by `setup_github_playpen.sh` in Step 6.
> Pushing to `origin` is correct — do NOT change the remote URL here.

```bash
if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
  COMMIT_FILES="bundle/bundle-patch.yaml"
  COMMIT_MSG="Add $COMPONENT_NAME to bundle-patch.yaml"
else
  COMMIT_FILES="bundle/bundle-patch.yaml config/build-config.yaml"
  COMMIT_MSG="Add $COMPONENT_NAME to bundle-patch.yaml and build-config.yaml"
fi

bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$COMMIT_FILES" \
  --message   "$COMMIT_MSG" \
  --branch    "$DEST_BRANCH"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 9 (Commit/Push): Could not commit or push changes. See details above. Aborting.
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
