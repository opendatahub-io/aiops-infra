---
name: enable-renovate-on-rhoai-component-repo
description: Enables Renovate dependency updates for a new RHOAI component repo by adding it to the renovate config in rhoai-konflux-central and raising a GitHub PR targeting main.
allowed-tools: Bash, Read, Edit, Write, WebFetch
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

Extract `inputs.repo_url`. If missing, stop:
```
ERROR in Step 3e: Missing required field 'inputs.repo_url' in component_onboarding_details.yaml.
  Re-generate the YAML with /create-component-onboarding-jira <jira-url>.
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

Fetch `config.yaml` from the `main` branch via GitHub API and search for the entry:

```bash
CONFIG_API_URL="https://api.github.com/repos/${RKC_PATH}/contents/config.yaml?ref=main"

CONFIG_RESPONSE=$(curl -s \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "$CONFIG_API_URL")

# Decode base64 content
CONFIG_CONTENT=$(echo "$CONFIG_RESPONSE" | python3 -c \
  "import sys,json,base64; d=json.load(sys.stdin); print(base64.b64decode(d['content']).decode())" \
  2>/dev/null)

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

## Step 5: Check for Existing Open PR in Jira Comments

Skip entirely if `$WORKDIR/component_onboarding_details.json` does not exist.

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.json`.

Search `fields.comment.comments[].body` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/[^/\s]+/pull/\d+
```

For each URL found:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "<found-url>" --check-only
```

Parse stdout:
- If `state=open` and the `title=` line contains `REPO_NAME` or `renovate`:
  ```bash
  PR_URL="<found-url>"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --comment "Found existing open GitHub PR for renovate config update: ${PR_URL}
Resuming monitoring of this PR."
  fi
  echo "Found existing open PR: $PR_URL. Jumping to Step 9 to monitor."
  ```
  **Set `PR_URL` and jump directly to Step 9** (Monitor PR).

- If `state=merged`: update Jira with `renovate-changes-done` label and a merged comment. **Stop exit 0.**
- If `state=closed`: note it and continue searching.

If no matching open PR found, continue to Step 6.

---

## Step 6: Set Up Playpen (Clone main branch)

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

## Step 7: Edit config.yaml

### 7a. Read the file

Use the `Read` tool to read `$CLONE_DIR/config.yaml`.

### 7b. Idempotency guard

If `${RENOVATE_ENTRY}` already appears in the file content, skip 7c–7d and continue to Step 8.

### 7c. Locate the insertion point

Find the last `- name:` entry within the `sync-repositories` array that belongs to the first
distribution group (`renovate-config: "renovate/default-renovate-distribution.json"`). This
is the last `- name: "red-hat-data-services/..."` line before the next
`- renovate-config: "renovate/custom-renovate-distribution.json"` block.

Use that last entry as the anchor context for the `Edit` tool.

### 7d. Insert the new entry

Use the `Edit` tool to append the new entry immediately after the last existing entry in the
target section. The indent must be exactly 2 spaces (matching all existing entries):

```
old_string: "  - name: \"red-hat-data-services/<LAST-ENTRY-REPO>\""
new_string:  "  - name: \"red-hat-data-services/<LAST-ENTRY-REPO>\"\n  - name: \"${RENOVATE_ENTRY}\""
```

### 7e. Verify

Use the `Read` tool on `$CLONE_DIR/config.yaml` and confirm:
- `${RENOVATE_ENTRY}` is present in the file
- The new entry appears **before** `- renovate-config: "renovate/custom-renovate-distribution.json"`
  (i.e., it is inside the default distribution section)
- The 2-space indent is consistent with surrounding entries
- No broken YAML indentation around the new entry

If any check fails, apply a corrective `Edit` call before continuing.

---

## Step 8: Commit and Push

```bash
cd "$CLONE_DIR"
git add config.yaml
git status   # confirm only config.yaml is staged
git commit -m "Enable Renovate for ${REPO_NAME}

Adds '${RENOVATE_ENTRY}' to the default Renovate distribution in config.yaml.

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
ERROR in Step 8 (Push): Could not push branch '$DEST_BRANCH' to $RKC_URL. See details above.
  Check GITHUB_TOKEN has 'repo' scope and write access to $RKC_PATH.
```

---

## Step 9: Raise PR (up to 3 attempts)

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
ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. Aborting.
  Check GITHUB_TOKEN has 'repo' scope and push access to $RKC_PATH.
```

On success, update Jira (only when `JIRA_URL` non-empty):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "renovate-pr-raised" \
  --comment "GitHub PR raised to enable Renovate for '${REPO_NAME}' in ${RKC_PATH}.

PR URL: $PR_URL
Entry added: ${RENOVATE_ENTRY}

Renovate will start managing dependencies in '${REPO_NAME}' once this PR is merged."
```

> **Proceed immediately to Step 10.** Do NOT stop here.

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
    --add-label "renovate-changes-done" \
    --remove-label "renovate-pr-raised" \
    --comment "GitHub PR merged: $PR_URL

Renovate is now enabled for '${REPO_NAME}' (${REPO_URL}).
Entry '${RENOVATE_ENTRY}' is active in the default Renovate distribution."
fi
```
Continue to Step 11.

**`closed` (exit 1):** PR closed without merging.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "GitHub PR was closed without merging: $PR_URL
Please review and re-run /enable-renovate-on-rhoai-component-repo ${JIRA_URL} to re-open."
fi
```
Stop with:
```
ERROR in Step 10 (Monitor PR): PR was closed without merging. Check: $PR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):** Attempt automated fix:
1. Use `Read` to examine `$CLONE_DIR/config.yaml` for YAML issues.
2. If fixable: apply `Edit`, then:
   ```bash
   cd "$CLONE_DIR"
   git add config.yaml
   git commit -m "Fix renovate config.yaml YAML syntax"
   git push origin "$DEST_BRANCH"
   ```
   Update Jira with fix attempt. **Jump back to Step 10** to re-monitor once.
3. If not fixable: update Jira with failure details and stop:
   ```
   ERROR in Step 10 (Monitor PR): CI checks failed and could not be auto-fixed.
   PR: $PR_URL — manual intervention required.
   ```

**`timeout` (exit 1):** PR still open after 60 minutes.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "PR monitoring timed out after 60 minutes: $PR_URL
Re-run /enable-renovate-on-rhoai-component-repo ${JIRA_URL:-} to resume."
fi
```
Print warning and continue to Step 11 (no hard stop).

---

## Step 11: Report Completion

```
Done.

  config.yaml — entry added: ${RENOVATE_ENTRY}
  GitHub PR   : $PR_URL — $RESULT
  Jira        : ${JIRA_ID:-(none)} — label: renovate-changes-done

Renovate will now manage dependencies in '${REPO_NAME}'.
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
| Open PR already found | 5 | Expected — jumps to Step 9 to monitor |
| Push fails (shallow) | 6, 8 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PR creation fails 3× | 9 | Check GITHUB_TOKEN `repo` scope |
| PR closed without merge | 10 | Review PR manually; re-run skill |
| Pipeline failed | 10 | Skill attempts auto-fix and retries monitor once |
| PR monitoring timeout | 10 | PR still open; re-run to resume monitoring |
