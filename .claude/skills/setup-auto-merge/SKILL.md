---
name: setup-auto-merge
description: Configures auto-merge for a new component repo by adding entries to
  rhods-devops-infra's upstream-source-map.yaml and main-release-source-map.yaml,
  registering the repo in both auto-merge GitHub Actions workflows, and raising a
  GitHub PR targeting main. Part of the ODH/RHOAI component onboarding pipeline.
allowed-tools: Bash, Read, Edit, Write
user-invocable: true
---

# Setup Auto-Merge

Configures auto-merge for a new component repository by updating four files in the
`rhods-devops-infra` repo and raising a GitHub PR targeting `main`:

1. Adding an entry to `src/config/upstream-source-map.yaml`
2. Adding an entry to `src/config/main-release-source-map.yaml`
3. Registering the repo in `.github/workflows/upstream-auto-merge.yaml`
4. Registering the repo in `.github/workflows/main-release-auto-merge.yaml`

> **CRITICAL — `RDI_URL` is the single source of truth for every Git and GitHub
> operation in this skill.**
> Resolved once in Step 0 from `RHODS_DEVOPS_INFRA_REPO_URL` (if set) or defaulting to
> `https://github.com/red-hat-data-services/rhods-devops-infra.git`.
> Every clone, push, and PR call (`--src-url`, `--dest-url`) **must** use `$RDI_URL`
> — never a hardcoded URL. `RDI_PATH` is derived from `$RDI_URL` in Step 0.
> This rule applies for the entire skill execution even if the URL resolves to a fork.

## Usage

```
/setup-auto-merge [<jira-url>]
```

Examples:
```
/setup-auto-merge https://redhat.atlassian.net/browse/RHOAIENG-1234
/setup-auto-merge
```

## Prerequisites

- `GITHUB_USER` — GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — personal access token with `repo` scope and push access to rhods-devops-infra
- `JIRA_USER_EMAIL` — Atlassian account email (required when jira-url provided)
- `JIRA_API_TOKEN` — Atlassian API token (required when jira-url provided)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `git`, `curl`
- Optional: `RHODS_DEVOPS_INFRA_REPO_URL` — overrides target repo URL
  (default: `https://github.com/red-hat-data-services/rhods-devops-infra.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**If invoked from a parent orchestrator:** `component_onboarding_details.yaml` may already
be placed in the working directory. Otherwise it will be downloaded from Jira.

## Entry Templates

**upstream-source-map.yaml** entry:
```yaml
- name: <repo_name>
  automerge: 'yes'
  src:
    url: <upstream_repo_url>.git
    branch: main
  dest:
    url: <repo_url>.git
    branch: main
```

**main-release-source-map.yaml** entry:
```yaml
- name: <repo_name>
  automerge: 'yes'
  repo-url: <repo_url>.git
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse Inputs

1. Extract `<jira-url>` from first positional argument (optional).

   If provided but does not contain `/browse/`, stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

2. Set:
   - `JIRA_URL` — full URL if provided, else empty string
   - `JIRA_ID` — last path segment (e.g. `RHOAIENG-1234`), else empty string

3. Resolve `RDI_URL` — execute this exact block; do NOT skip the `echo`:

   ```bash
   RDI_URL="${RHODS_DEVOPS_INFRA_REPO_URL:-https://github.com/red-hat-data-services/rhods-devops-infra.git}"
   echo "RHODS_DEVOPS_INFRA_REPO_URL=${RHODS_DEVOPS_INFRA_REPO_URL:-(not set, using default)}"
   echo "RDI_URL resolved to: $RDI_URL"
   ```

   **Never override or re-derive `RDI_URL` in later steps.**

4. Derive `RDI_PATH`:

   ```bash
   RDI_PATH=$(echo "$RDI_URL" | sed 's|https://github.com/||;s|\.git$||')
   echo "RDI_PATH: $RDI_PATH"
   ```

5. Echo all resolved values:
   ```
   JIRA_URL  : ${JIRA_URL:-(not provided)}
   JIRA_ID   : ${JIRA_ID:-(not provided)}
   RDI_URL   : $RDI_URL
   RDI_PATH  : $RDI_PATH
   ```

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
if [[ -z "${GITHUB_USER:-}" ]]; then
  echo "ERROR: GITHUB_USER is not set. export GITHUB_USER=yourusername"; exit 1
fi
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERROR: GITHUB_TOKEN is not set. export GITHUB_TOKEN=yourtoken (needs repo scope)"; exit 1
fi
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1
fi
if ! command -v git &>/dev/null; then
  echo "ERROR: git is not installed."; exit 1
fi
if ! command -v curl &>/dev/null; then
  echo "ERROR: curl is not installed."; exit 1
fi
```

When `JIRA_URL` is non-empty, also check:
```bash
if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  echo "ERROR: JIRA_USER_EMAIL is not set. export JIRA_USER_EMAIL=you@example.com"; exit 1
fi
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: JIRA_API_TOKEN is not set. export JIRA_API_TOKEN=your-api-token"; exit 1
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

Skip if `$WORKDIR/component_onboarding_details.json` already exists.
Only when `JIRA_URL` is non-empty:
```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py "$JIRA_URL"
```
On exit 1, display stderr and stop:
```
ERROR in Step 3d (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

### 3e. Parse YAML

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.yaml`.

Extract `inputs.repo_url` into `REPO_URL`. If missing, stop:
```
ERROR in Step 3e: Missing required field 'inputs.repo_url' in component_onboarding_details.yaml.
  Re-generate the YAML with /create-component-onboarding-jira <jira-url>.
```

### 3f. Derive Global Variables

```bash
# repo_name: last path segment without .git
REPO_NAME="${REPO_URL##*/}"
REPO_NAME="${REPO_NAME%.git}"

# Repo slug for GitHub API calls (owner/repo, no .git)
REPO_SLUG=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')

# Find upstream (parent) repo via GitHub API
GH_REPO_INFO=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/${REPO_SLUG}")

IS_FORK=$(echo "$GH_REPO_INFO" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(str(d.get('fork',False)).lower())" 2>/dev/null \
  || echo "false")

if [[ "$IS_FORK" == "true" ]]; then
  UPSTREAM_REPO_URL=$(echo "$GH_REPO_INFO" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d['parent']['html_url'])" 2>/dev/null)
  echo "  Repo is a fork — upstream: $UPSTREAM_REPO_URL"
else
  UPSTREAM_REPO_URL="${REPO_URL%.git}"
  echo "  Repo is not a fork — using repo_url as upstream."
fi

echo "REPO_NAME        : $REPO_NAME"
echo "REPO_URL         : $REPO_URL"
echo "UPSTREAM_REPO_URL: $UPSTREAM_REPO_URL"
```

---

## Step 4: Fast-Path Check — Are Entries Already in Both Config Files?

> **Reminder:** Use `$RDI_PATH` (derived in Step 0) for the GitHub API URL.

Fetch both config files from the `main` branch of `$RDI_PATH` via GitHub API:

```bash
fetch_file_content() {
  local path="$1"
  curl -s \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${RDI_PATH}/contents/${path}?ref=main" \
    | python3 -c \
      "import sys,json,base64; d=json.load(sys.stdin); print(base64.b64decode(d['content']).decode())" \
      2>/dev/null
}

USM_CONTENT=$(fetch_file_content "src/config/upstream-source-map.yaml")
MRSM_CONTENT=$(fetch_file_content "src/config/main-release-source-map.yaml")

USM_HAS_ENTRY=false
MRSM_HAS_ENTRY=false
[[ -n "$USM_CONTENT" ]] && echo "$USM_CONTENT" | grep -qF "name: ${REPO_NAME}" && USM_HAS_ENTRY=true
[[ -n "$MRSM_CONTENT" ]] && echo "$MRSM_CONTENT" | grep -qF "name: ${REPO_NAME}" && MRSM_HAS_ENTRY=true
```

If both `USM_HAS_ENTRY=true` AND `MRSM_HAS_ENTRY=true`:
```bash
echo "Entry '${REPO_NAME}' already exists in both config files. Nothing to do."
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "auto-merge-setup-done" \
    --comment "Auto-merge config for '${REPO_NAME}' already exists in ${RDI_PATH} (both source maps). No action needed."
fi
exit 0
```

If `USM_CONTENT` or `MRSM_CONTENT` is empty (API error or network issue), warn and continue —
do not fail hard:
```
WARN: Could not fetch config files from GitHub API. Proceeding to check via local clone.
```

---

## Step 5: Check for Existing Open PR in Jira Comments

Skip entirely if `$WORKDIR/component_onboarding_details.json` does not exist.

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.json`.

```bash
RDI_REPO_NAME="${RDI_PATH##*/}"
# e.g. "rhods-devops-infra"
```

Search `fields.comment.comments[].body` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/${RDI_REPO_NAME}/pull/\d+
```

For each URL found:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "<found-url>" --check-only
```

Parse stdout:
- If `state=open` and the `title=` line contains `REPO_NAME`:
  ```bash
  PR_URL="<found-url>"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --comment "Found existing open GitHub PR for auto-merge setup of '${REPO_NAME}': ${PR_URL}
Resuming monitoring of this PR."
  fi
  echo "Found existing open PR: $PR_URL. Jumping to Step 10 to monitor."
  ```
  **Set `PR_URL` and jump directly to Step 10** (Monitor PR).

- If `state=merged`: update Jira with `auto-merge-setup-done` label and a merged comment. **Stop exit 0.**
- If `state=closed`: note it and continue searching.

If no matching open PR found, continue to Step 6.

---

## Step 6: Set Up Playpen (Clone main branch)

> **NOTE:** Clone from `main`. Pass `--dest-branch` only when `JIRA_ID` is available.
> Sparse checkout the two directories containing all 4 target files.

```bash
cd "$WORKDIR"

PLAYPEN_ARGS=(
  --src-url "$RDI_URL"
  --src-branch "main"
  --sparse-files "src/config .github/workflows"
)
[[ -n "$JIRA_ID" ]] && PLAYPEN_ARGS+=(--dest-branch "$JIRA_ID")

PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_github_playpen.sh "${PLAYPEN_ARGS[@]}")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
```

On exit 1, display stderr and stop:
```
ERROR in Step 6 (Playpen setup): Clone or push failed. See details above.
  Check network connectivity and GITHUB_TOKEN (needs push access to $RDI_PATH).
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 7: Edit the Four Target Files

> **Reminder:** `origin` was set to `$RDI_URL` by `setup_github_playpen.sh` in Step 6.
> All edits happen in `$CLONE_DIR`. Read each file first before editing.

### 7a. `src/config/upstream-source-map.yaml`

Use the `Read` tool to read `$CLONE_DIR/src/config/upstream-source-map.yaml`.

If the file does not exist, stop:
```
ERROR in Step 7a: src/config/upstream-source-map.yaml not found in $CLONE_DIR.
  Verify that $RDI_URL points to the correct rhods-devops-infra repository.
```

**Idempotency:** If `name: ${REPO_NAME}` already appears in the file, print:
```
${REPO_NAME} already in upstream-source-map.yaml — skipping edit.
```
Continue to 7b.

Otherwise, use the `Edit` tool to append the new entry after the last existing `- name:` entry
in the file. Match the indentation of surrounding entries (2-space for `- name:`, 4-space for
nested fields):

```yaml
- name: <REPO_NAME>
  automerge: 'yes'
  src:
    url: <UPSTREAM_REPO_URL>.git
    branch: main
  dest:
    url: <REPO_URL>.git
    branch: main
```

Verify with the `Read` tool that the new entry is present and surrounding entries are undisturbed.
If verification fails, apply a corrective `Edit` before continuing.

### 7b. `src/config/main-release-source-map.yaml`

Use the `Read` tool to read `$CLONE_DIR/src/config/main-release-source-map.yaml`.

If file does not exist, stop:
```
ERROR in Step 7b: src/config/main-release-source-map.yaml not found in $CLONE_DIR.
  Verify that $RDI_URL points to the correct rhods-devops-infra repository.
```

**Idempotency:** If `name: ${REPO_NAME}` already appears, skip.

Otherwise, append after the last existing `- name:` entry:
```yaml
- name: <REPO_NAME>
  automerge: 'yes'
  repo-url: <REPO_URL>.git
```

Verify with the `Read` tool. Apply a corrective `Edit` if verification fails.

### 7c. `.github/workflows/upstream-auto-merge.yaml`

Use the `Read` tool to read `$CLONE_DIR/.github/workflows/upstream-auto-merge.yaml`.

If file does not exist, stop:
```
ERROR in Step 7c: .github/workflows/upstream-auto-merge.yaml not found in $CLONE_DIR.
  Verify that $RDI_URL points to the correct rhods-devops-infra repository.
```

Locate the `repositories` input under `on.workflow_dispatch.inputs`. It has an `options:` list
where each entry is on its own line prefixed with `- ` (at the appropriate YAML indentation).

**Idempotency:** If `$REPO_NAME` already appears anywhere in the `options:` list, print:
```
${REPO_NAME} already in upstream-auto-merge.yaml repositories options — skipping edit.
```
Continue to 7d.

Otherwise, use the `Edit` tool to append a new `- <REPO_NAME>` option immediately after the
last existing option entry, matching the exact indentation of surrounding entries.

Verify with the `Read` tool that `$REPO_NAME` is now present in the options list.

### 7d. `.github/workflows/main-release-auto-merge.yaml`

Use the `Read` tool to read `$CLONE_DIR/.github/workflows/main-release-auto-merge.yaml`.

If file does not exist, stop:
```
ERROR in Step 7d: .github/workflows/main-release-auto-merge.yaml not found in $CLONE_DIR.
  Verify that $RDI_URL points to the correct rhods-devops-infra repository.
```

Apply the same idempotency check and edit logic as Step 7c for the `repositories` input's
`options:` list.

Verify with the `Read` tool.

---

## Step 8: Commit and Push

> **Reminder:** `origin` was set to `$RDI_URL` by `setup_github_playpen.sh` in Step 6.
> Pushing to `origin` is correct — do NOT change the remote URL here.

```bash
cd "$CLONE_DIR"
git add \
  src/config/upstream-source-map.yaml \
  src/config/main-release-source-map.yaml \
  .github/workflows/upstream-auto-merge.yaml \
  .github/workflows/main-release-auto-merge.yaml
git status   # verify only the expected files are staged
git commit -m "Configure auto-merge for ${REPO_NAME}

Adds '${REPO_NAME}' to upstream and main-release source maps
and registers it in both auto-merge workflows.

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
ERROR in Step 8 (Push): Could not push branch '$DEST_BRANCH' to origin. See details above.
  Check GITHUB_TOKEN has push access to $RDI_PATH.
```

---

## Step 9: Raise PR (up to 3 attempts)

> **Reminder:** Both `--src-url` and `--dest-url` must be `"$RDI_URL"`. Do NOT replace
> either with a hardcoded URL. The PR target branch is `main`.

```bash
PR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_github_pr.py \
  --src-url "$RDI_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$RDI_URL" \
  --dest-branch "main" \
  --title "Configure auto-merge for ${REPO_NAME}" \
  --description "Sets up auto-merge for \`${REPO_NAME}\` in ${RDI_PATH}.

## Details

| Field | Value |
|-------|-------|
| Component repo  | \`${REPO_URL}\` |
| Upstream repo   | \`${UPSTREAM_REPO_URL}\` |
| Repo name       | \`${REPO_NAME}\` |

**Files changed:**
- \`src/config/upstream-source-map.yaml\` — new entry added
- \`src/config/main-release-source-map.yaml\` — new entry added
- \`.github/workflows/upstream-auto-merge.yaml\` — \`${REPO_NAME}\` added to repositories options
- \`.github/workflows/main-release-auto-merge.yaml\` — \`${REPO_NAME}\` added to repositories options

**Jira:** ${JIRA_URL:-(none)}")
```

On failure:
- "Branch not found" → re-push `$DEST_BRANCH` to origin and retry.
- "Connection error" → inform user, retry.
- Any other error → retry (up to 3 times total).

After 3 failures, stop:
```
ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. Aborting.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RDI_PATH.
```

On success, update Jira (only when `JIRA_URL` non-empty):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "auto-merge-pr-raised" \
  --comment "GitHub PR raised to configure auto-merge for '${REPO_NAME}' in ${RDI_PATH}.

PR URL: $PR_URL

Files changed:
- src/config/upstream-source-map.yaml: '${REPO_NAME}' entry added
- src/config/main-release-source-map.yaml: '${REPO_NAME}' entry added
- .github/workflows/upstream-auto-merge.yaml: '${REPO_NAME}' added to repositories
- .github/workflows/main-release-auto-merge.yaml: '${REPO_NAME}' added to repositories"
```

> **Proceed immediately to Step 10. Do NOT stop here.**

---

## Step 10: Monitor PR

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
    --add-label "auto-merge-setup-done" \
    --remove-label "auto-merge-pr-raised" \
    --comment "GitHub PR merged: $PR_URL

Auto-merge is now configured for '${REPO_NAME}' (${REPO_URL}) in ${RDI_PATH}."
fi
```
Continue to Step 11.

**`closed` (exit 1):** PR closed without merging.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "GitHub PR was closed without merging: $PR_URL
Please review and re-run /setup-auto-merge ${JIRA_URL} to re-open."
fi
```
Stop with:
```
ERROR in Step 10 (Monitor PR): PR was closed without merging.
PR: $PR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):** CI checks failed.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "CI checks failed on PR: $PR_URL
Please review the PR checks and re-run /setup-auto-merge ${JIRA_URL:-} to retry."
fi
```
Stop with:
```
ERROR in Step 10: CI checks failed on PR $PR_URL. Manual intervention required.
```

**`timeout` (exit 1):** PR still open after 60 minutes.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "PR monitoring timed out after 60 minutes: $PR_URL
Re-run /setup-auto-merge ${JIRA_URL:-} to resume."
fi
```
Print warning and continue to Step 11 (no hard stop).

---

## Step 11: Report Completion

```
Done.

  src/config/upstream-source-map.yaml            — ${REPO_NAME} entry added
  src/config/main-release-source-map.yaml        — ${REPO_NAME} entry added
  .github/workflows/upstream-auto-merge.yaml     — ${REPO_NAME} added to repositories
  .github/workflows/main-release-auto-merge.yaml — ${REPO_NAME} added to repositories
  GitHub PR                                      : $PR_URL — $RESULT
  Jira                                           : ${JIRA_ID:-(none)} — label: auto-merge-setup-done

  repo_name         : $REPO_NAME
  repo_url          : $REPO_URL
  upstream_repo_url : $UPSTREAM_REPO_URL
  target_repo       : $RDI_URL
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
| Both entries already exist | 4 | Expected — exits 0; Jira labelled `auto-merge-setup-done` |
| Open PR already found | 5 | Expected — jumps to Step 10 to monitor |
| Push fails (shallow) | 6, 8 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| Config file not found in clone | 7a/7b | Check `RDI_URL` points to correct rhods-devops-infra repo |
| Workflow file not found in clone | 7c/7d | Check `RDI_URL` points to correct rhods-devops-infra repo |
| PR creation fails 3× | 9 | Check GITHUB_TOKEN `repo` scope and push access to `$RDI_PATH` |
| PR closed without merge | 10 | Review PR manually; re-run skill |
| PR CI checks failed | 10 | Review PR checks; re-run skill |
| PR monitoring timeout | 10 | PR still open; re-run to resume monitoring |
