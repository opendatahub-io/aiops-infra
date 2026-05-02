---
name: enable-renovate-on-rhoai-component-repo
description: Enables Renovate dependency updates for a new RHOAI component repo by adding it to the renovate config in rhoai-konflux-central and raising a GitHub PR targeting main.
allowed-tools: Bash
user-invocable: true
---

# Enable Renovate on RHOAI Component Repo

Registers a new RHOAI component repository in the Renovate configuration maintained in
`rhoai-konflux-central` (`config.yaml` on `main`) so that Renovate bot keeps its dependencies
up to date. Raises a PR and monitors it to completion.

> **CRITICAL — `RHOAI_KONFLUX_CENTRAL_REPO_URL` overrides the default repo for every step.**
> Resolved once in Step 0 into `RKC_URL`. Every Git clone, push, GitHub API call, and PR
> operation must use `$RKC_URL` / `$RKC_PATH`. The PR target branch is **`main`**.

## Usage

```
/enable-renovate-on-rhoai-component-repo [<jira-url>]
```

Examples:
```
/enable-renovate-on-rhoai-component-repo https://redhat.atlassian.net/browse/RHOAIENG-1234
/enable-renovate-on-rhoai-component-repo
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

## Renovate config.yaml Structure

The file is a top-level YAML array with three distribution groups. Entries are added to the
`sync-repositories` array of the **first** group:

```yaml
- renovate-config: "renovate/default-renovate-distribution.json"
  sync-repositories:
  - name: "red-hat-data-services/rhods-operator"
  - name: "red-hat-data-services/codeflare-operator"
  ...
- renovate-config: "renovate/custom-renovate-distribution.json"
  ...
```

New entry format (2-space indent, matching all existing entries):
```yaml
  - name: "red-hat-data-services/<REPO_NAME>"
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

**Idempotency fast-path:** If invoked with `--existing-pr-url <url>`, print
`PR already raised: <url>` and exit 0. The orchestrator passes this when the URL is already
recorded in `pipeline_state.json`.

---

## Step 0: Parse Inputs

1. Extract `<jira-url>` from the first positional argument (may be empty/omitted).

   If provided but does not contain `/browse/`, stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

2. Set:
   - `JIRA_URL` — full URL if provided, else empty string
   - `JIRA_ID` — last path segment (e.g. `RHOAIENG-1234`), else empty string

3. Resolve `RKC_URL` — single source of truth for all Git and GitHub operations:
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

If `$WORKDIR/component_onboarding_details.yaml` already exists (placed by parent orchestrator),
skip 3b:
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
On exit 1, display stderr and stop:
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

Only when `JIRA_URL` is non-empty:
```bash
if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  cd "$WORKDIR"
  uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py "$JIRA_URL"
fi
```
On exit 1, display stderr and stop:
```
ERROR in Step 3d (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

### 3e. Parse YAML

```bash
REPO_URL=$(grep -m1 'repo_url:' "$WORKDIR/component_onboarding_details.yaml" | awk '{print $2}')
[[ -z "$REPO_URL" ]] && {
  echo "ERROR in Step 3e: Missing required field 'inputs.repo_url' in component_onboarding_details.yaml."
  echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
  exit 1
}
```

### 3f. Derive variables

```bash
REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"
RENOVATE_ENTRY="red-hat-data-services/${REPO_NAME}"
```

Print:
```
REPO_URL       : $REPO_URL
REPO_NAME      : $REPO_NAME
RENOVATE_ENTRY : $RENOVATE_ENTRY
```

---

## Step 4: Fast-Path Check — Is Entry Already in Renovate Config?

Fetch `config.yaml` from the `main` branch via raw GitHub URL and search for the entry:

```bash
# Use raw.githubusercontent.com to avoid base64 decoding the /contents API response
CONFIG_CONTENT=$(curl -sf \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  "https://raw.githubusercontent.com/${RKC_PATH}/main/config.yaml" 2>/dev/null || echo "")

if [[ -n "$CONFIG_CONTENT" ]] && echo "$CONFIG_CONTENT" | grep -qF "${RENOVATE_ENTRY}"; then
  echo "Entry '${RENOVATE_ENTRY}' already exists in renovate config. Nothing to do."
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --add-label "renovate-changes-done" \
      --comment "Renovate config entry '${RENOVATE_ENTRY}' already exists in ${RKC_PATH} (config.yaml). No action needed."
  fi
  exit 0
fi
```

If `CONFIG_CONTENT` is empty (API error or network issue), warn and continue — do not fail hard:
```
WARN: Could not fetch config.yaml from GitHub API. Proceeding to check via local clone.
```

---

## Step 5: Set Up Playpen (Clone main branch)

> **NOTE:** Clone from `main`. Do **NOT** pass `--dest-branch` (let the playpen script
> auto-generate a branch name). Sparse checkout only `config.yaml`.

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_github_playpen.sh \
  --src-url "$RKC_URL" \
  --src-branch "main" \
  --sparse-files "config.yaml")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
```

On exit 1, display stderr and stop:
```
ERROR in Step 5 (Playpen setup): Clone or push failed. See details above.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 6: Edit config.yaml

```bash
uv run --script "$COMMON_SCRIPTS_DIR/edit_yaml.py" append-renovate-repo \
  "$CLONE_DIR/config.yaml" \
  --renovate-config "renovate/default-renovate-distribution.json" \
  --name "$RENOVATE_ENTRY"

grep -qF "$RENOVATE_ENTRY" "$CLONE_DIR/config.yaml" || {
  echo "ERROR in Step 7: Failed to add '$RENOVATE_ENTRY' to config.yaml"; exit 1
}
echo "$RENOVATE_ENTRY added to sync-repositories in config.yaml."
```

---

## Step 7: Commit and Push

```bash
bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "config.yaml" \
  --message   "Enable Renovate for ${REPO_NAME}

Adds '${RENOVATE_ENTRY}' to the default Renovate distribution in config.yaml.

Related: ${JIRA_ID:-no-jira}" \
  --branch    "$DEST_BRANCH"
```

On exit 1, display stderr and stop:
```
ERROR in Step 7 (Push): Could not push branch '$DEST_BRANCH' to $RKC_URL. See details above.
  Check GITHUB_TOKEN has 'repo' scope and write access to $RKC_PATH.
```

---

## Step 8: Raise PR (up to 3 attempts)

> **PR target is `main`**, not a version-specific branch. Both `--src-url` and `--dest-url`
> must be `"$RKC_URL"`.

```bash
PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
  --src-url "$RKC_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$RKC_URL" \
  --dest-branch "main" \
  --title "Enable Renovate for ${REPO_NAME}" \
  --description "Adds '${RENOVATE_ENTRY}' to the default Renovate distribution in config.yaml.

## Details

| Field | Value |
|-------|-------|
| Component repo | \`${REPO_URL}\` |
| Renovate entry | \`${RENOVATE_ENTRY}\` |
| Distribution | \`renovate/default-renovate-distribution.json\` |

**Jira:** ${JIRA_URL:-(none)}")
```

On failure:
- "Branch not found" → re-push `$DEST_BRANCH` to origin and retry.
- "Connection error" → inform user, retry.
- Any other error → retry.

After 3 failures, stop:
```
ERROR in Step 8 (Raise PR): Could not create PR after 3 attempts. Aborting.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

On success, update Jira (only when `JIRA_URL` non-empty):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "renovate-pr-raised" \
  --comment "[step:renovate] GitHub PR raised to enable Renovate for '${REPO_NAME}' in ${RKC_PATH}.

PR URL: $PR_URL
Entry added: ${RENOVATE_ENTRY}

Renovate will start managing dependencies in '${REPO_NAME}' once this PR is merged."
```

Print the PR URL and exit 0.

---

## Step 9: Report Completion

```
Done.

  config.yaml — entry added: ${RENOVATE_ENTRY}
  GitHub PR   : $PR_URL
  Jira        : ${JIRA_ID:-(none)} — label: renovate-pr-raised

Renovate will now manage dependencies in '${REPO_NAME}' once the PR is merged.
Source: ${REPO_URL}
```

---

## Error Reference

| Error | Step | Action |
|-------|------|--------|
| `GITHUB_USER` not set | 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | 1 | `export GITHUB_TOKEN=yourtoken` (needs `repo` scope) |
| `JIRA_USER_EMAIL`/`JIRA_API_TOKEN` not set | 1 | Export both env vars |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| YAML attachment missing | 3b | Ensure `component_onboarding_details.yaml` is attached to Jira |
| `inputs.repo_url` missing | 3e | Add field to YAML; re-run `/create-component-onboarding-jira` |
| Entry already exists | 4 | Expected — exits 0; Jira labelled `renovate-changes-done` |
| Push fails (shallow) | 5, 7 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PR creation fails 3× | 8 | Check GITHUB_TOKEN `repo` scope |
