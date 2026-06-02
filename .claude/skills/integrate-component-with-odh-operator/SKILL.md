---
name: integrate-component-with-odh-operator
description: Updates the operator repository (opendatahub-io/opendatahub-operator for ODH, red-hat-data-services/rhods-operator for RHOAI) to include a new operator component in build/manifests-config.yaml and raises a GitHub PR. Exits cleanly (no-op) when is_operator=false. Automates Step 9 of the ODH/RHOAI component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Integrate Component with ODH Operator

Adds a new operator component to the operator repository (`opendatahub-operator` for ODH,
`rhods-operator` for RHOAI) by:
1. Reading the component's onboarding YAML from the Jira ticket.
2. Exiting cleanly if `is_operator: false` — nothing to do.
3. Adding a new entry to `build/manifests-config.yaml` in the operator repo.
4. Raising a GitHub PR for the change.

> **CRITICAL — `ODH_OPERATOR_URL` is the single source of truth for every Git and GitHub
> operation in this skill.**
> It is resolved in Step 3d by `resolve_operator_url.sh`, which checks the
> `ODH_OPERATOR_REPO_URL` env var first (override) and falls back to the product-context
> default (ODH → `opendatahub-io/opendatahub-operator`;
> RHOAI → `red-hat-data-services/rhods-operator`).
> **Never set `ODH_OPERATOR_URL` or `ODH_OPERATOR_PATH` manually.** Always use the values
> produced by the script. Every clone, push, and PR call (`--src-url`, `--dest-url`) **must**
> use `$ODH_OPERATOR_URL` — never a hardcoded URL. `ODH_OPERATOR_PATH` (also set by the
> script) must be used for all GitHub API calls.
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
- Optional: `ODH_OPERATOR_REPO_URL` — overrides the target operator repo. If not set, the
  default is derived from `product_context`:
  - `ODH` → `https://github.com/opendatahub-io/opendatahub-operator.git`
  - `RHOAI` → `https://github.com/red-hat-data-services/rhods-operator.git`
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**Jira attachment:** The Jira issue must have `component_onboarding_details.yaml` attached
(created by `/create-component-onboarding-jira`).

## Implementation

If invoked with `--existing-pr-url <url>`: print 'PR already raised: <url>' and exit 0. The orchestrator passes this when the URL is already recorded in pipeline_state.json.

---

## Step 0: Parse Inputs

1. Extract `<jira-url>` (the first positional argument).
   Extract `<jira-id>` as the last path segment (e.g., `RHODS-14226`).

   If the argument cannot be parsed as a Jira URL (no `/browse/` segment), stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHODS-14226

2. `ODH_OPERATOR_URL` and `ODH_OPERATOR_PATH` will be resolved in Step 3d by the
   `resolve_operator_url.sh` script. Do **not** set `ODH_OPERATOR_URL` or
   `ODH_OPERATOR_PATH` manually in any step — the script handles the
   `ODH_OPERATOR_REPO_URL` env-var override and product-context defaults.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "scripts/check_prerequisites.sh" \
  --env "GITHUB_USER GITHUB_TOKEN JIRA_USER_EMAIL JIRA_API_TOKEN" \
  --tools "uv git"
```

---

## Step 2: Set Up Working Directory

```bash
eval "$(bash "scripts/init_workdir.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
```

---

## Step 3: Fetch Jira Details and Component YAML

This step ensures both `component_onboarding_details.json` (full Jira issue) and
`component_onboarding_details.yaml` (component parameters) exist in `$WORKDIR`.

**3a. Fetch Jira issue details** (skip if `$WORKDIR/component_onboarding_details.json` already exists):

```bash
if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  cd "$WORKDIR"
  uv run --script scripts/fetch_jira_details.py <jira-url>
fi
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3a (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

**3b. Download component YAML** (skip if `$WORKDIR/component_onboarding_details.yaml` already exists):

```bash
cd "$WORKDIR"
uv run --script scripts/download_jira_attachment.py \
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

**3d. Resolve `ODH_OPERATOR_URL` and `ODH_OPERATOR_PATH`:**

Run the `resolve_operator_url.sh` script. This script checks the `ODH_OPERATOR_REPO_URL`
env var first (override), then falls back to the product-context default. You **must** use
`eval` so the exported variables are available in subsequent steps.

```bash
eval "$(bash "scripts/resolve_operator_url.sh" \
  --product-context "$PRODUCT_CONTEXT")"
echo "ODH_OPERATOR_URL:  $ODH_OPERATOR_URL"
echo "ODH_OPERATOR_PATH: $ODH_OPERATOR_PATH"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3d: Could not resolve operator URL. See details above.
```

**`ODH_OPERATOR_URL` and `ODH_OPERATOR_PATH` are now fixed for the remainder of the skill.
Never hardcode a URL — always use `$ODH_OPERATOR_URL` and `$ODH_OPERATOR_PATH`.**

**3e. Resolve `OPERATOR_TARGET_BRANCH`:**

Set the target branch for cloning and raising PRs based on product context:
- **ODH** — targets `main`
- **RHOAI** — targets `$REPO_BRANCH` (the component's branch from the onboarding YAML, e.g. `rhoai-2.20`)

```bash
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  OPERATOR_TARGET_BRANCH="$REPO_BRANCH"
else
  OPERATOR_TARGET_BRANCH="main"
fi
echo "OPERATOR_TARGET_BRANCH: $OPERATOR_TARGET_BRANCH"
```

**`OPERATOR_TARGET_BRANCH` is now fixed for the remainder of the skill.** Use it wherever
the target branch is needed (clone, API checks, PR destination). Never hardcode `main`.

---

## Step 4: Check is_operator Gate

**4a. If `IS_OPERATOR` is `false`:**

```bash
uv run --script scripts/update_jira_issue.py <jira-url> \
  --add-label "operator-changes-not-needed" \
  --comment "Skipping odh-operator integration for '$COMPONENT_NAME'.

is_operator=false in component_onboarding_details.yaml. No changes to the operator repo (${ODH_OPERATOR_PATH}) are required for this component."
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
`map:` object of `build/manifests-config.yaml` on the **`$OPERATOR_TARGET_BRANCH` branch** of `$ODH_OPERATOR_URL`.

> **Reminder:** Use `$ODH_OPERATOR_PATH` (derived from `$ODH_OPERATOR_URL` in Step 3d) for
> the GitHub API URL. Do NOT substitute the hardcoded upstream path.

Fetch the raw file content from the GitHub API:

```bash
MANIFESTS_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/${ODH_OPERATOR_PATH}/contents/build/manifests-config.yaml?ref=${OPERATOR_TARGET_BRANCH}" \
  -o "$MANIFESTS_TMPFILE")
```

**If `HTTP_STATUS` is not `200`:**
- `404` — file not found in the repo. Warn and continue to Step 6:
  ```
  WARN in Step 5: build/manifests-config.yaml not found on $OPERATOR_TARGET_BRANCH branch (HTTP 404).
    Verify ODH_OPERATOR_URL points to the correct repo. Continuing.
  ```
- Any other non-200 — GitHub API error. Warn and continue to Step 6:
  ```
  WARN in Step 5: Could not fetch build/manifests-config.yaml (HTTP $HTTP_STATUS). Continuing.
  ```
- Do NOT abort on API errors — the file check is a fast-path optimisation; proceed with the
  full clone-and-edit flow if the check is inconclusive.

**If `HTTP_STATUS` is `200`:**

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
uv run --script scripts/update_jira_issue.py <jira-url> \
  --add-label "odh-operator-pr-raised" \
  --comment "'$COMPONENT_NAME' is already present in build/manifests-config.yaml on the ${OPERATOR_TARGET_BRANCH} branch of ${ODH_OPERATOR_PATH}.

No changes are needed. The odh-operator integration for this component is already complete."
```

Print:
```
$COMPONENT_NAME already exists in build/manifests-config.yaml ($OPERATOR_TARGET_BRANCH branch).
Jira updated with label 'odh-operator-pr-raised'. No action needed.
```

**Stop with exit 0.**

If `ENTRY_EXISTS=false`: clean up the temp file and continue to Step 6.

```bash
rm -f "$MANIFESTS_TMPFILE"
```

---

## Step 6: Set Up Playpen (Clone)

> **Reminder:** Pass `--src-url "$ODH_OPERATOR_URL"` — the URL finalised in Step 3d
> (or Step 0 if `ODH_OPERATOR_REPO_URL` was explicitly set). Do NOT hardcode the URL here.

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash scripts/setup_github_playpen.sh \
  --src-url "$ODH_OPERATOR_URL" \
  --src-branch "$OPERATOR_TARGET_BRANCH" \
  --dest-branch "component-onboarding-<jira-id>" \
  --sparse-files "build")
```

Parse `PLAYPEN_OUTPUT` from stdout:
- Line 1 → `CLONE_DIR` (absolute path, e.g. `$WORKDIR/opendatahub-operator-playpen`)
- Line 2 → `DEST_BRANCH` (the branch created and pushed, e.g. `RHODS-14226`)

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

## Step 7: Update manifests-config.yaml

Check the file exists:

```bash
[[ -f "$CLONE_DIR/build/manifests-config.yaml" ]] || {
  echo "ERROR in Step 8: build/manifests-config.yaml not found in $CLONE_DIR."
  echo "  Verify that $ODH_OPERATOR_URL points to the correct operator repository."
  exit 1
}
```

**Check if `$COMPONENT_NAME` already exists under `map:` and insert if not:**

```bash
if grep -q "^  ${COMPONENT_NAME}:" "$CLONE_DIR/build/manifests-config.yaml" 2>/dev/null; then
  echo "$COMPONENT_NAME already in manifests-config.yaml — skipping edit."
  # Continue to Step 9 (commit and push are still needed for the PR branch)
else
  uv run --script "scripts/edit_yaml.py" insert-map-key \
    "$CLONE_DIR/build/manifests-config.yaml" \
    --map-key "map" \
    --name "$COMPONENT_NAME" \
    --src  "$OPERATOR_MANIFEST_SRC_PATH" \
    --dest "$OPERATOR_MANIFEST_DEST_PATH"
fi
```

On exit 1 from `edit_yaml.py`: display stderr and stop with:
```
ERROR in Step 8 (Update manifests-config.yaml): Could not insert component entry. See details above. Aborting.
```

Verify the entry was written:

```bash
grep -q "^  ${COMPONENT_NAME}:" "$CLONE_DIR/build/manifests-config.yaml" \
  || { echo "ERROR: $COMPONENT_NAME not found in manifests-config.yaml after insert."; exit 1; }
```

---

## Step 8: Commit and Push

> **Reminder:** `origin` was set to `$ODH_OPERATOR_URL` by `setup_github_playpen.sh` in Step 7.

```bash
bash "scripts/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "build/manifests-config.yaml" \
  --message   "Add $COMPONENT_NAME to manifests-config.yaml" \
  --branch    "$DEST_BRANCH"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 9 (Commit/Push): Could not commit or push changes. See details above. Aborting.
```

---

## Step 9: Raise PR (up to 3 attempts)

> **Reminder:** Both `--src-url` and `--dest-url` must be `"$ODH_OPERATOR_URL"`. Do NOT
> replace either with the hardcoded upstream URL, even if `$ODH_OPERATOR_URL` resolves to
> a personal fork.

```bash
PR_URL=$(uv run --script scripts/raise_github_pr.py \
  --src-url "$ODH_OPERATOR_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$ODH_OPERATOR_URL" \
  --dest-branch "$OPERATOR_TARGET_BRANCH" \
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
ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting.
```

After a successful PR creation, update Jira:
```bash
uv run --script scripts/update_jira_issue.py <jira-url> \
  --add-label "operator-pr-raised" \
  --comment "GitHub PR raised to add '$COMPONENT_NAME' to ${ODH_OPERATOR_PATH} manifests config.

PR URL: $PR_URL

Changes will take effect once this PR is reviewed and merged.
File changed: build/manifests-config.yaml (map entry added for $COMPONENT_NAME)."
```

---

## Step 10: Report Completion

Print:
```
Done.

  build/manifests-config.yaml  — $COMPONENT_NAME entry added under map:
  GitHub PR                    — raised: $PR_URL
  Jira                         — updated (label: operator-pr-raised)

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
| `build/manifests-config.yaml` not found in clone | Step 7 | Check `ODH_OPERATOR_URL` points to the correct repo |
| Clone or push fails | Step 6 | Check GITHUB_TOKEN push scope on `$ODH_OPERATOR_PATH` |
| Shallow push rejected | Steps 6, 8 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PR creation fails 3× | Step 9 | Check GITHUB_TOKEN; verify branch was pushed; fix manually |
