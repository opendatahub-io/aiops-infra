---
name: create-quay-repo
description: Creates a Quay repository via a GitOps MR to app-interface. Handles fork setup, sparse YAML editing, MR creation, and optional Jira tracking. Automates Step 2 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Create Quay Repo

Creates a new Quay repository for an ODH component by raising a merge request to the
`app-interface` GitLab repository (GitOps-driven). The Quay repo is automatically
created when the MR is merged.

## Usage

```
/create-quay-repo quay.io/<org>/<repo> [--jira-url <url>] [--visibility public|private]
/create-quay-repo <org>/<repo>         [--jira-url <url>] [--visibility public|private]
```

Examples:
```
/create-quay-repo quay.io/opendatahub/my-new-component
/create-quay-repo rhoai/rhoai-data-science-pipelines --jira-url https://redhat.atlassian.net/browse/RHOAIENG-1234
/create-quay-repo opendatahub/odh-ai-first-demo --jira-url https://redhat.atlassian.net/browse/RHOAIENG-5678 --visibility public
```

## Prerequisites

- `GITLAB_USER` environment variable must be set to your GitLab username
  - Set: `export GITLAB_USER=yourusername`
- `GITLAB_TOKEN` environment variable must be set to a GitLab personal access token
  - Needs scopes: `api`, `write_repository`
  - Set: `export GITLAB_TOKEN=yourtoken`
- `uv` must be installed and in PATH
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `skopeo` must be installed and in PATH
  - macOS:       `brew install skopeo`
  - RHEL/Fedora: `sudo dnf install skopeo`
- Optional: `APP_INTERFACE_REPO_URL` (default: `https://gitlab.cee.redhat.com/service/app-interface`)
- If `--jira-url` provided:
  - `JIRA_USER_EMAIL` must be set
  - `JIRA_API_TOKEN` must be set
  - Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**Network:** The `app-interface` repository is on Red Hat's internal GitLab. Ensure
**VPN is active** before running this skill.

## Implementation

---

## Idempotency: --existing-mr-url fast-path

If the skill is invoked with `--existing-mr-url <url>`, print:
```
MR already raised: <url>
```
and exit 0 immediately. The orchestrator passes this argument when the MR URL is already
recorded in `pipeline_state.json`, meaning this step was completed in a prior run.

---

## Step 0: Parse Inputs

Parse the arguments provided by the user:

1. Extract `<quay-repo>` (the first positional argument). Strip the `quay.io/` prefix if present.
   Split on `/` to extract `<org>` and `<repo>`.

   Valid formats:
   - `quay.io/<org>/<repo>` → strip prefix → `<org>/<repo>`
   - `<org>/<repo>` → use as-is

   If the input cannot be parsed into exactly `<org>/<repo>`, stop with:
   > ERROR: Invalid quay repo format. Expected `quay.io/<org>/<repo>` or `<org>/<repo>`.

2. Determine `<visibility>`:
   - If `--visibility` was explicitly provided: use that value (`public` or `private`)
   - If `<org>` is `rhoai` and `--visibility` was NOT provided: set `visibility=private`
   - Otherwise: set `visibility=public`

3. Extract `<jira-url>` from `--jira-url` if provided. Extract `<jira-id>` as the last
   path segment of the URL (e.g., `RHOAIENG-1234`).

4. Resolve `APP_INTERFACE_URL` — execute this exact block; do NOT skip the `echo`:

   ```bash
   APP_INTERFACE_URL="${APP_INTERFACE_REPO_URL:-https://gitlab.cee.redhat.com/service/app-interface}"
   echo "APP_INTERFACE_REPO_URL=${APP_INTERFACE_REPO_URL:-(not set, using default)}"
   echo "APP_INTERFACE_URL resolved to: $APP_INTERFACE_URL"
   ```

   **Never override or re-derive `APP_INTERFACE_URL` in later steps.** If any step appears
   to use a different URL, that is a bug — stop and correct it.

> **IMPORTANT — `APP_INTERFACE_URL` is the single source of truth for all Git and GitLab
> operations in this skill.**
> Use `$APP_INTERFACE_URL` for every operation: fork setup (`--gitlab-repo-url`),
> playpen clone (`--src-url`), and MR destination (`--dest-url`).
> **Never substitute the upstream URL in place of `$APP_INTERFACE_URL`**, even if it
> appears to point to a personal fork. The user configured it intentionally.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "scripts/check_prerequisites.sh" \
  --env "GITLAB_USER GITLAB_TOKEN" \
  --tools "uv skopeo"
```

If `--jira-url` was provided, also check:
```bash
bash "scripts/check_prerequisites.sh" --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
```

---

## Step 2: Create Working Directory

```bash
if [[ -n "${JIRA_URL:-}" ]]; then
  eval "$(bash "scripts/init_workdir.sh" --jira-url "$JIRA_URL")"
else
  WORKDIR="$(pwd)/quay-<org>-<repo>"
  mkdir -p "$WORKDIR"
fi
echo "Working directory: $WORKDIR"
```

---

## Step 3: Check If Quay Repo Already Exists

```bash
bash scripts/check_quay_repo.sh quay.io/<org>/<repo>
```

- **Exit 0** (repo exists): If `--jira-url` was provided, run:
  ```bash
  uv run --script scripts/update_jira_issue.py <jira-url> \
    --add-label "quay-repo-created" \
    --comment "Quay repo quay.io/<org>/<repo> already exists. No action needed."
  ```
  Then print:
  ```
  Quay repo quay.io/<org>/<repo> already exists. Nothing to do.
  ```
  And **stop**.

- **Exit 1** (does not exist): Continue to Step 5.

- **Exit 2** (tool error): Display the error output and stop.

---

## Step 5: Fork app-interface

```bash
FORK_URL=$(uv run --script scripts/setup_gitlab_fork.py \
  --gitlab-repo-url "$APP_INTERFACE_URL")
```

On exit 1: display the script's stderr output and stop with:
```
ERROR in Step 5 (Fork app-interface): Could not fork the repository. See details above. Aborting.
```

On success, `FORK_URL` holds the HTTPS URL of the fork (e.g.,
`https://gitlab.cee.redhat.com/<GITLAB_USER>/app-interface`).

---

## Step 6: Determine YAML File Path and Branch Name

Map `<org>` to the YAML file path inside app-interface:

| `<org>` | YAML file path |
|---------|----------------|
| `opendatahub` | `data/services/rhoai/quay/opendatahub.yml` |
| `rhoai`       | `data/services/rhoai/quay/rhoai.yml`       |
| `modh`        | `data/services/rhoai/quay/modh.yml`        |
| Other         | Ask the user (see below)                   |

For any other `<org>`, pause and ask:
> I need the path to the quay config YAML within app-interface for the org `<org>`.
> This is typically under `data/services/rhoai/quay/<org>.yml`.
> What is the correct path?

Set `YAML_FILE=<path>`.

Determine `DEST_BRANCH`:
- If `<jira-id>` is available: `DEST_BRANCH=component-onboarding-<jira-id>` (e.g. `component-onboarding-RHOAIENG-1234`)
- Otherwise: leave `DEST_BRANCH` unset (the playpen script will auto-generate one)

---

## Step 7: Set Up Playpen (Full Clone)

Run from inside `$WORKDIR`. The clone is wrapped with a **45-minute timeout** (`timeout 2700`)
because `app-interface` is a large repository that can take a long time to fetch.

```bash
cd "$WORKDIR"

if [[ -n "$DEST_BRANCH" ]]; then
  PLAYPEN_OUTPUT=$(timeout 2700 bash scripts/setup_gitlab_playpen.sh \
    --src-url "$APP_INTERFACE_URL" \
    --dest-url "$FORK_URL" \
    --src-branch master \
    --dest-branch "$DEST_BRANCH")
else
  PLAYPEN_OUTPUT=$(timeout 2700 bash scripts/setup_gitlab_playpen.sh \
    --src-url "$APP_INTERFACE_URL" \
    --dest-url "$FORK_URL" \
    --src-branch master)
fi
```

Parse `PLAYPEN_OUTPUT`:
- Line 1 → `CLONE_DIR` (absolute path to the `app-interface-playpen` directory)
- Line 2 → `DEST_BRANCH` (the branch that was created and pushed)

On exit 124 (timeout): stop with:
```
ERROR in Step 7 (Playpen setup): Clone timed out after 45 minutes. Check VPN connectivity and retry. Aborting.
```

On exit 1: display stderr and stop with:
```
ERROR in Step 7 (Playpen setup): Clone or push failed. See details above. Aborting.
```

---

## Step 8: Modify YAML File

**Resolve description:** If `product_context == RHOAI`, use `short_description` from the
collected inputs; otherwise use `"<org> <repo> container image"`.

**Idempotency check:** Check whether `<repo>` already exists in the YAML:

```bash
if grep -q "^  name: <repo>$" "$CLONE_DIR/$YAML_FILE" 2>/dev/null || \
   grep -q "^- name: <repo>$" "$CLONE_DIR/$YAML_FILE" 2>/dev/null; then
  echo "Entry for '<repo>' already exists in the YAML — skipping append."
  # Continue to Step 9
else
  if [[ "$visibility" == "public" ]]; then
    VIS_FLAG="--public"
  else
    VIS_FLAG="--no-public"
  fi
  uv run --script "scripts/edit_yaml.py" append-items-array \
    "$CLONE_DIR/$YAML_FILE" \
    --name "<repo>" \
    --description "'<short_description if product_context==RHOAI, else '<org> <repo> container image'>'" \
    $VIS_FLAG
fi
```

On exit 1 from `edit_yaml.py`: display stderr and stop with:
```
ERROR in Step 8 (Modify YAML): Could not append entry to $YAML_FILE. See details above. Aborting.
```

---

## Step 9: Commit and Raise MR (up to 3 attempts)

Commit and push the change:

```bash
DEST_REMOTE="dest"
[[ "$FORK_URL" == "$APP_INTERFACE_URL" ]] && DEST_REMOTE="origin"

bash "scripts/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$YAML_FILE" \
  --message   "Add <repo> to quay <org> config" \
  --branch    "$DEST_BRANCH" \
  --remote    "$DEST_REMOTE"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 9 (Commit/Push): Could not commit or push changes. See details above. Aborting.
```

Now raise the MR. Attempt up to **3 times**:

**Attempt 1:**
```bash
MR_URL=$(uv run --script scripts/raise_gitlab_mr.py \
  --src-url "$FORK_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$APP_INTERFACE_URL" \
  --dest-branch master \
  --title "Add <repo> quay repository for <org>" \
  --description "Add quay.io/<org>/<repo> to app-interface GitOps config.

Visibility: <visibility>
Jira: <jira-url or N/A>")
```

On success (exit 0): `MR_URL` is set. Continue to Jira update below.

On failure (exit 1): Read the error from stderr. Common fixable errors:
- "Branch not found on fork" → the push may have failed silently. Re-run the `git push` command and retry.
- "Connection error / VPN" → tell the user to check VPN and retry.
- Any other error → retry bare (Attempt 2, then Attempt 3).

After 3 failures, stop with:
```
ERROR in Step 9 (Raise MR): Could not create merge request after 3 attempts. See errors above. Aborting.
```

After a successful MR creation, if `--jira-url` was provided:
```bash
uv run --script scripts/update_jira_issue.py <jira-url> \
  --add-label "quay-mr-raised" \
  --comment "GitLab MR raised to create quay.io/<org>/<repo>.

MR URL: $MR_URL

The Quay repo will be created automatically once this MR is merged."
```

Print the MR URL and stop:
```
MR raised: $MR_URL
```

The skill is complete. The orchestrator will monitor the MR separately.

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITLAB_USER` not set | Step 1 | `export GITLAB_USER=yourusername` |
| `GITLAB_TOKEN` not set | Step 1 | `export GITLAB_TOKEN=yourtoken` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `skopeo` not installed | Step 1 | `brew install skopeo` / `sudo dnf install skopeo` |
| VPN not active | Steps 5, 7, 9 | Activate VPN and re-run |
| Fork creation fails | Step 5 | Check GITLAB_TOKEN permissions (needs `api` scope) |
| Clone fails | Step 7 | Check VPN and GITLAB_TOKEN `write_repository` scope |
| Clone timed out (45 min) | Step 7 | Check VPN; retry once connectivity is stable |
| Push fails | Step 9 | Check GITLAB_TOKEN `write_repository` scope |
| MR creation fails 3x | Step 9 | Check VPN; inspect stderr; manual fallback |
