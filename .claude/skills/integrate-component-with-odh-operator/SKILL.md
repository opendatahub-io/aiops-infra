---
name: integrate-component-with-odh-operator
description: Updates the opendatahub-operator repository to include a new operator component in build/manifests-config.yaml and raises a GitHub PR. Exits cleanly (no-op) when is_operator=false. Automates Step 9 of the ODH component onboarding pipeline.
allowed-tools: Bash, Read, Edit, Write
user-invocable: true
---

# Integrate Component with ODH Operator

Adds a new operator component to `opendatahub-operator` by:
1. Reading the component's onboarding YAML from the Jira ticket.
2. Exiting cleanly if `is_operator: false` — nothing to do.
3. Adding a new entry to `build/manifests-config.yaml` in the operator repo.
4. Raising a GitHub PR for the change.

> **CRITICAL — `ODH_OPERATOR_URL` is the single source of truth for every Git and GitHub
> operation in this skill.**
> It is resolved once in Step 0 from `ODH_OPERATOR_REPO_URL` (or the default).
> Every clone, push, and PR call (`--src-url`, `--dest-url`) **must** use `$ODH_OPERATOR_URL`
> — never the hardcoded upstream URL `https://github.com/opendatahub-io/opendatahub-operator.git`.
> This rule applies for the entire skill execution even if the URL resolves to a fork.

## Usage

```
/integrate-component-with-odh-operator <jira-url>
```

Examples:
```
/integrate-component-with-odh-operator https://redhat.atlassian.net/browse/RHODS-14226
```

## Prerequisites

- `GITHUB_USER` — GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — personal access token with `repo` scope and push access to the operator repo
- `JIRA_USER_EMAIL` — your Atlassian account email
- `JIRA_API_TOKEN` — Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `git`
- Optional: `ODH_OPERATOR_REPO_URL` (default: `https://github.com/opendatahub-io/opendatahub-operator.git`)
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

2. Resolve `ODH_OPERATOR_URL`. Execute this exact block; do NOT skip the `echo`:

   ```bash
   ODH_OPERATOR_URL="${ODH_OPERATOR_REPO_URL:-https://github.com/opendatahub-io/opendatahub-operator.git}"
   echo "ODH_OPERATOR_REPO_URL=${ODH_OPERATOR_REPO_URL:-(not set, using default)}"
   echo "ODH_OPERATOR_URL resolved to: $ODH_OPERATOR_URL"
   ```

   The `echo` output confirms which repo is active for the entire skill run.
   **Never override or re-derive `ODH_OPERATOR_URL` in later steps.** If any step appears
   to use a different URL, that is a bug — stop and correct it.

3. Parse `ODH_OPERATOR_URL` to extract owner and repo path for GitHub API calls:
   ```bash
   ODH_OPERATOR_PATH=$(echo "$ODH_OPERATOR_URL" | sed 's|https://github.com/||;s|\.git$||')
   # e.g. "opendatahub-io/opendatahub-operator"
   ```

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env   "GITHUB_USER GITHUB_TOKEN JIRA_USER_EMAIL JIRA_API_TOKEN" \
  --tools "uv git"
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
  Run /create-component-onboarding-jira <jira-url> first.
```

**3c. Parse the YAML** using the `Read` tool to read `$WORKDIR/component_onboarding_details.yaml`.

Extract and store these values (all under the `inputs:` key):

| Variable | YAML field | Required | Example |
|----------|-----------|----------|---------|
| `COMPONENT_NAME` | `inputs.component_name` | Yes | `odh-ai-first-demo` |
| `PRODUCT_CONTEXT` | `inputs.product_context` | Yes | `ODH` |
| `IS_OPERATOR` | `inputs.is_operator` | Yes | `true` |
| `OPERATOR_MANIFEST_SRC_PATH` | `inputs.operator_manifest_src_path` | When is_operator=true | `config/manifests` |
| `OPERATOR_MANIFEST_DEST_PATH` | `inputs.operator_manifest_dest_path` | When is_operator=true | `opt/manifests/odh-ai-first-demo` |
| `REPO_URL` | `inputs.repo_url` | Yes | `https://github.com/rhoai-rhtap/odh-ai-first-demo` |
| `REPO_BRANCH` | `inputs.repo_branch` | Yes | `main` |

If any of COMPONENT_NAME, PRODUCT_CONTEXT, IS_OPERATOR, REPO_URL, REPO_BRANCH is missing, stop with:
```
ERROR in Step 3c: Missing required field '<field>' in component_onboarding_details.yaml. Aborting.
```

---

## Step 4: Check is_operator Gate

**4a. If `IS_OPERATOR` is `false`:**

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "operator-changes-not-needed" \
  --comment "Skipping odh-operator integration for '$COMPONENT_NAME'.

is_operator=false in component_onboarding_details.yaml. No changes to opendatahub-operator are required for this component."
```

Print:
```
$COMPONENT_NAME is not an operator (is_operator=false). No odh-operator changes needed.
Jira updated with label 'operator-changes-not-needed'.
```

**Stop with exit 0** (this is not an error).

**4b. If `IS_OPERATOR` is `true`, validate operator-specific fields:**

If `OPERATOR_MANIFEST_SRC_PATH` or `OPERATOR_MANIFEST_DEST_PATH` is empty or missing, stop with:
```
ERROR in Step 4b: is_operator=true but operator_manifest_src_path or operator_manifest_dest_path
  is missing from component_onboarding_details.yaml.
  Add both fields and re-upload the YAML to the Jira ticket. Aborting.
```

Otherwise, print:
```
is_operator=true. Proceeding with odh-operator integration.
  component_name               : $COMPONENT_NAME
  operator_manifest_src_path   : $OPERATOR_MANIFEST_SRC_PATH
  operator_manifest_dest_path  : $OPERATOR_MANIFEST_DEST_PATH
  repo                         : $ODH_OPERATOR_URL
```

---

## Step 5: Check If Component Already Exists in manifests-config.yaml

Before cloning the repo, check whether `$COMPONENT_NAME` already has an entry in the
`map:` object of `build/manifests-config.yaml` on the **`main` branch** of `$ODH_OPERATOR_URL`.

> **Reminder:** Use `$ODH_OPERATOR_PATH` (derived from `$ODH_OPERATOR_URL` in Step 0) for
> the GitHub API URL. Do NOT substitute the hardcoded upstream path.

Fetch the raw file content from the GitHub API:

```bash
MANIFESTS_TMPFILE=$(mktemp)
bash "$COMMON_SCRIPTS_DIR/check_github_file.sh" \
  --repo-path "$ODH_OPERATOR_PATH" \
  --file-path "build/manifests-config.yaml" \
  --ref        main \
  --output     "$MANIFESTS_TMPFILE"
FILE_EXIT=$?
```

**If `FILE_EXIT` is not `0`:**
- `1` — file not found (HTTP 404). Warn and continue to Step 6:
  ```
  WARN in Step 5: build/manifests-config.yaml not found on main branch (HTTP 404).
    Verify ODH_OPERATOR_URL points to the correct repo. Continuing.
  ```
- `2` — GitHub API error. Warn and continue to Step 6:
  ```
  WARN in Step 5: Could not fetch build/manifests-config.yaml (API error). Continuing.
  ```
- Do NOT abort on API errors — the file check is a fast-path optimisation; proceed with the
  full clone-and-edit flow if the check is inconclusive.

**If `FILE_EXIT` is `0`:**

Check whether `$COMPONENT_NAME` is already present as a key under `map:`:

```bash
if grep -q "^  ${COMPONENT_NAME}:" "$MANIFESTS_TMPFILE"; then
  ENTRY_EXISTS=true
else
  ENTRY_EXISTS=false
fi
rm -f "$MANIFESTS_TMPFILE"
```

If `ENTRY_EXISTS=true`:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "odh-operator-pr-raised" \
  --comment "'$COMPONENT_NAME' is already present in build/manifests-config.yaml on the main branch of opendatahub-operator.

No changes are needed. The odh-operator integration for this component is already complete."
```

Print:
```
$COMPONENT_NAME already exists in build/manifests-config.yaml (main branch).
Jira updated with label 'odh-operator-pr-raised'. No action needed.
```

**Stop with exit 0.**

If `ENTRY_EXISTS=false`: clean up the temp file and continue to Step 6.

```bash
rm -f "$MANIFESTS_TMPFILE"
```

---

## Step 6: Check for Existing Open PR in Jira Comments

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.json`.

Search the array at `fields.comment.comments[].body` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/opendatahub-operator/pull/\d+
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
    --comment "Existing open GitHub PR found for '$COMPONENT_NAME' in opendatahub-operator: <found-url>.

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
    --add-label "odh-operator-changes-done" \
    --comment "odh-operator PR for '$COMPONENT_NAME' was already merged: <found-url>. No action needed.

Step 9 (Integrate with odh-operator) is complete."
  ```
  Print: `PR already merged. Step 9 (odh-operator integration) is complete.`
  **Stop with exit 0.**

If no matching PR is found, continue to Step 7.

---

## Step 7: Set Up Playpen (Clone)

> **Reminder:** Pass `--src-url "$ODH_OPERATOR_URL"` — the URL resolved in Step 0.
> Do NOT hardcode the upstream URL here.

Run from inside `$WORKDIR`:

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/run_github_playpen.sh" \
  --src-url      "$ODH_OPERATOR_URL" \
  --src-branch   main \
  --dest-branch  "<jira-id>" \
  --sparse-files "build" \
  --workdir      "$WORKDIR" \
  --scripts-dir  "$COMMON_SCRIPTS_DIR")"
```

`$CLONE_DIR` and `$DEST_BRANCH` are set in the caller's environment via eval.

On exit 1: display stderr and stop with:
```
ERROR in Step 7 (Playpen setup): Clone or push failed. See details above.
  Check network connectivity and GITHUB_TOKEN (needs push access to $ODH_OPERATOR_PATH).
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "<jira-id>"
```

---

## Step 8: Update manifests-config.yaml

Use the `Read` tool to read `$CLONE_DIR/build/manifests-config.yaml`.

If the file does not exist, stop with:
```
ERROR in Step 8: build/manifests-config.yaml not found in $CLONE_DIR.
  Verify that $ODH_OPERATOR_URL points to the correct opendatahub-operator repository.
```

Locate the `map:` key. It will contain existing entries like:
```yaml
map:
  existing-component:
    src: path/to/manifests
    dest: opt/manifests/existing-component
  another-component:
    src: config/manifests
    dest: opt/manifests/another-component
```

**Check if `$COMPONENT_NAME` already exists under `map:`:**

- **Already present**: Print `$COMPONENT_NAME already in manifests-config.yaml — skipping edit.`
  Continue to Step 9 (commit and push are still needed so the branch has a commit for the PR).

- **Not present**: Use the `Edit` tool to insert the new entry under `map:` in **alphabetical
  order** among existing component keys. The entry format is:
  ```yaml
    <COMPONENT_NAME>:
      src: <OPERATOR_MANIFEST_SRC_PATH>
      dest: <OPERATOR_MANIFEST_DEST_PATH>
  ```
  Match the indentation of surrounding entries (2 spaces for the component key under `map:`,
  4 spaces for `src:` and `dest:`).

After editing, verify with the `Read` tool that:
- `$COMPONENT_NAME:` is present under `map:`
- `src: $OPERATOR_MANIFEST_SRC_PATH` is present and correctly indented
- `dest: $OPERATOR_MANIFEST_DEST_PATH` is present and correctly indented
- No surrounding entries have been disturbed

If verification fails, fix with another `Edit` call before continuing.

---

## Step 9: Commit and Push

> **Reminder:** `origin` was set to `$ODH_OPERATOR_URL` by `setup_github_playpen.sh` in Step 7.
> Pushing to `origin` is correct — do NOT change the remote URL here.

```bash
cd "$CLONE_DIR"
git add build/manifests-config.yaml
git status   # verify only the expected file is staged
git commit -m "Add $COMPONENT_NAME to manifests-config.yaml"
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

> **Reminder:** Both `--src-url` and `--dest-url` must be `"$ODH_OPERATOR_URL"`. Do NOT
> replace either with the hardcoded upstream URL, even if `$ODH_OPERATOR_URL` resolves to
> a personal fork.

```bash
PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
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
Jira: <jira-url>

**File changed:**
- \`build/manifests-config.yaml\` — added \`$COMPONENT_NAME\` entry under \`map:\`")
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
  --add-label "odh-operator-pr-raised" \
  --comment "GitHub PR raised to add '$COMPONENT_NAME' to opendatahub-operator manifests config.

PR URL: $PR_URL

Changes will take effect once this PR is reviewed and merged.
File changed: build/manifests-config.yaml (map entry added for $COMPONENT_NAME)."
```

---

## Step 11: Report Completion

Print:
```
Done.

  build/manifests-config.yaml  — $COMPONENT_NAME entry added under map:
  GitHub PR                    — raised: $PR_URL
  Jira                         — updated (label: odh-operator-pr-raised)

  component_name               : $COMPONENT_NAME
  operator_manifest_src_path   : $OPERATOR_MANIFEST_SRC_PATH
  operator_manifest_dest_path  : $OPERATOR_MANIFEST_DEST_PATH
  repo                         : $ODH_OPERATOR_URL

Next step: review and merge the PR, then mark Step 9 complete in Jira.
```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITHUB_USER` not set | Step 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | Step 1 | `export GITHUB_TOKEN=yourtoken` (needs push access to operator repo) |
| `JIRA_USER_EMAIL` not set | Step 1 | `export JIRA_USER_EMAIL=you@example.com` |
| `JIRA_API_TOKEN` not set | Step 1 | `export JIRA_API_TOKEN=your-token` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `component_onboarding_details.yaml` missing | Step 3b | Run `/create-component-onboarding-jira <jira-url>` first |
| `is_operator=false` | Step 4a | Expected — no operator changes needed; skill exits 0 |
| Operator manifest fields missing | Step 4b | Add `operator_manifest_src_path` and `operator_manifest_dest_path` to YAML and re-upload |
| Component already in manifests-config.yaml (main) | Step 5 | Expected — Jira updated; skill exits 0 cleanly |
| Existing open PR found | Step 6 | Expected — Jira updated; merge the existing PR |
| PR already merged | Step 6 | Expected — skill exits 0 cleanly |
| `build/manifests-config.yaml` not found in clone | Step 8 | Check `ODH_OPERATOR_URL` points to the correct repo |
| Clone or push fails | Step 7 | Check GITHUB_TOKEN push scope on `$ODH_OPERATOR_PATH` |
| Shallow push rejected | Steps 7, 9 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PR creation fails 3× | Step 10 | Check GITHUB_TOKEN; verify branch was pushed; fix manually |
