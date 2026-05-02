---
name: sync-rhoai-renovate-configs
description: Triggers the sync-renovate-configs GitHub Actions workflow in rhoai-konflux-central to push renovate config updates to all registered component repos. Monitors the run and updates Jira on completion.
allowed-tools: Bash
user-invocable: true
---

# Sync RHOAI Renovate Configs

Triggers the `sync-renovate-configs.yml` GitHub Actions workflow in
`red-hat-data-services/konflux-central` (the RKC repo) to propagate the central Renovate
configuration to all registered component repositories. Monitors the run to completion and
optionally updates a Jira issue with progress labels and comments.

Run this skill after merging a PR that adds a new component repo to `config.yaml` via
`/enable-renovate-on-rhoai-component-repo`.

> **CRITICAL — `RHOAI_KONFLUX_CENTRAL_REPO_URL` overrides the default repo for every step.**
> Resolved once in Step 0 into `RKC_URL` and `RKC_PATH`.
> Every GitHub API call, workflow trigger, and monitor operation must use `$RKC_URL`.
> Never re-derive or hardcode after Step 0.

## Usage

```
/sync-rhoai-renovate-configs [<jira-url>]
```

Examples:
```
/sync-rhoai-renovate-configs https://redhat.atlassian.net/browse/RHOAIENG-1234
/sync-rhoai-renovate-configs
```

## Prerequisites

- `GITHUB_USER` — your GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — GitHub PAT with `repo` + `actions:write` scope (or `workflow` scope on classic PATs)
- `JIRA_USER_EMAIL` — Atlassian account email (required only when jira-url provided)
- `JIRA_API_TOKEN` — Atlassian API token (required only when jira-url provided)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Optional: `RHOAI_KONFLUX_CENTRAL_REPO_URL` (default: `https://github.com/red-hat-data-services/konflux-central.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

## Workflow Details

| Field | Value |
|-------|-------|
| File | `.github/workflows/sync-renovate-configs.yml` |
| Ref | `main` |
| Trigger | `workflow_dispatch` only |
| Input `dry_run` | boolean — `false` (default; syncs for real) |
| Input `renovate-config` | choice — `all` (default; syncs all distributions) |

The workflow commits `"sync config with renovate-central"` to each registered repo's
`main` branch. No PRs are created — changes are pushed directly.

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse Inputs and Resolve URLs

1. Extract optional `<jira-url>` from the first positional argument (may be empty/omitted).

   If provided but does not contain `/browse/`, stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

2. Set:
   - `JIRA_URL` — full URL if provided, else empty string
   - `JIRA_ID` — last path segment (e.g. `RHOAIENG-1234`), else empty string

3. Resolve `RKC_URL` — the single source of truth for all GitHub operations. Execute this
   exact block; do NOT skip the `echo`:

   ```bash
   RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
   echo "RHOAI_KONFLUX_CENTRAL_REPO_URL=${RHOAI_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
   echo "RKC_URL resolved to: $RKC_URL"
   ```

   **Never override or re-derive `RKC_URL` in later steps.**

4. Derive `RKC_PATH` and set workflow constants:

   ```bash
   RKC_PATH=$(echo "$RKC_URL" | sed 's|https://github.com/||;s|\.git$||')
   # e.g. "red-hat-data-services/konflux-central"

   WORKFLOW_FILE=".github/workflows/sync-renovate-configs.yml"
   WORKFLOW_REF="main"
   ```

5. Echo all resolved values:
   ```
   JIRA_URL      : ${JIRA_URL:-(not provided)}
   JIRA_ID       : ${JIRA_ID:-(not provided)}
   RKC_URL       : $RKC_URL
   RKC_PATH      : $RKC_PATH
   WORKFLOW_FILE : $WORKFLOW_FILE
   WORKFLOW_REF  : $WORKFLOW_REF
   ```

---

## Step 1: Check Prerequisites

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITHUB_USER GITHUB_TOKEN" \
  --tools "uv"

if [[ -n "$JIRA_URL" ]]; then
  bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
    --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi
```

Note: `GITHUB_TOKEN` needs `repo` scope + `actions:write` scope (or `workflow` scope on classic PATs).

---

## Step 2: Trigger the Workflow

Print a summary of what will be triggered:
```
Triggering workflow: $WORKFLOW_FILE
  Repo  : $RKC_URL
  Ref   : $WORKFLOW_REF
  Input : dry_run=false
  Input : renovate-config=all
  Jira  : ${JIRA_URL:-(not provided)}
```

Trigger (up to 3 attempts):

```bash
RUN_ID=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py trigger \
  --repo-url "$RKC_URL" \
  --workflow "$WORKFLOW_FILE" \
  --ref "$WORKFLOW_REF" \
  --input "dry_run=false" \
  --input "renovate-config=all")
```

On exit 1, check stderr content:

- Contains `403` → stop immediately (no retry):
  ```
  ERROR in Step 2 (Trigger): Permission denied (HTTP 403).
    GITHUB_TOKEN needs 'actions:write' scope (or 'workflow' scope on classic PATs).
    Regenerate your token with the required scopes and re-run.
  ```
- Contains `404` → stop immediately (no retry):
  ```
  ERROR in Step 2 (Trigger): Workflow or repo not found (HTTP 404).
    Verify RKC_URL is correct: $RKC_URL
    Verify the workflow file exists at: $WORKFLOW_FILE
  ```
- Any other error → retry (up to 3 total attempts, 10 s between retries).
  After 3 failures, stop:
  ```
  ERROR in Step 2 (Trigger): Could not dispatch workflow after 3 attempts. See above. Aborting.
  ```

On success, `RUN_ID` is set to the numeric run ID. Print:
```
Workflow run triggered.
  Run ID  : $RUN_ID
  Run URL : https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
```

Update Jira (only when `JIRA_URL` non-empty):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "renovate-sync-triggered" \
  --comment "sync-renovate-configs workflow triggered (Run #${RUN_ID}).

Inputs:
  dry_run        : false
  renovate-config: all

Workflow run: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}

Monitoring in progress (max 30 minutes)..."
```

---

## Step 3: Monitor the Workflow (30 minutes max)

```bash
MONITOR_OUTPUT=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py monitor \
  --repo-url "$RKC_URL" \
  --run-id "$RUN_ID" \
  --timeout 30 \
  --poll-interval 60)
WORKFLOW_STATUS="${MONITOR_OUTPUT#status=}"
```

The script polls every 60 seconds and writes progress to stderr.

**`success`:** Print and continue to Step 4:
```
Workflow run $RUN_ID completed successfully.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
```

**`failure`:** Attempt automated diagnosis by fetching step logs, then retry once:

```bash
FAILURE_LOGS=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py get-step-logs \
  --repo-url "$RKC_URL" \
  --run-id "$RUN_ID" \
  --step "Sync" 2>/dev/null) || true
```

Display to the user:
```
Workflow run $RUN_ID FAILED.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}

Log excerpt:
<first 50 lines of FAILURE_LOGS, or "(could not fetch logs)" if empty>

Retrying automatically...
```

**Retry once** by returning to Step 2 (re-trigger with the same inputs). If the second run
also fails, update Jira and stop:
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "renovate-sync-failed" \
    --remove-label "renovate-sync-triggered" \
    --comment "sync-renovate-configs workflow failed on second attempt.

Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}

Please inspect the run logs and re-run /sync-rhoai-renovate-configs to retry."
fi
```
Stop with:
```
ERROR in Step 3: Workflow failed on second attempt. Manual investigation required.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
```

**`cancelled`:**
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --remove-label "renovate-sync-triggered" \
    --comment "sync-renovate-configs workflow run #${RUN_ID} was cancelled.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
Re-run /sync-rhoai-renovate-configs to retry."
fi
```
Stop:
```
ERROR in Step 3: Workflow run $RUN_ID was cancelled.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
```

**`timeout`:** Workflow still running after 30 minutes.
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "sync-renovate-configs workflow run #${RUN_ID} monitoring timed out after 30 minutes.
The run may still be completing.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
Re-run /sync-rhoai-renovate-configs to re-trigger when ready."
fi
```
Stop (no hard failure — workflow may still complete in GitHub Actions):
```
WARNING: Workflow run $RUN_ID has not completed after 30 minutes.
Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
The run may still be in progress. Re-run /sync-rhoai-renovate-configs to re-trigger.
```

---

## Step 4: Update Jira on Success

Only when `JIRA_URL` is non-empty:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "renovate-sync-done" \
  --remove-label "renovate-sync-triggered" \
  --comment "[step:renovate_sync] sync-renovate-configs workflow completed successfully.

Run URL: https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}

Renovate config has been synced to all registered component repositories.
The Renovate bot will now manage dependencies across those repos."
```

---

## Step 5: Report Completion

```
Done.

  Workflow : $WORKFLOW_FILE
  Repo     : $RKC_URL
  Run ID   : $RUN_ID
  Status   : success
  Run URL  : https://github.com/${RKC_PATH}/actions/runs/${RUN_ID}
  Jira     : ${JIRA_ID:-(none)} — label: renovate-sync-done

Renovate config is now synced to all registered component repositories.
```

---

## Error Reference

| Error | Step | Action |
|-------|------|--------|
| `GITHUB_USER` not set | 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | 1 | `export GITHUB_TOKEN=yourtoken` (needs `repo` + `actions:write` scope) |
| `JIRA_USER_EMAIL`/`JIRA_API_TOKEN` not set | 1 | Export both env vars |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| HTTP 403 on trigger | 2 | Regenerate GITHUB_TOKEN with `actions:write` (or `workflow`) scope |
| HTTP 404 on trigger | 2 | Verify `RKC_URL` and that `WORKFLOW_FILE` exists at that path |
| Trigger fails 3× | 2 | Check token, repo URL, and workflow file path; inspect stderr |
| Workflow run fails | 3 | Auto-retried once; check logs at Run URL if second attempt fails |
| Workflow cancelled | 3 | Re-run skill to re-trigger |
| Monitor timeout (30 min) | 3 | Run may still complete; check GitHub Actions UI; re-run |
