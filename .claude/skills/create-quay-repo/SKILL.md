---
name: create-quay-repo
description: Creates a Quay repository via a GitOps MR to app-interface. Handles fork setup, sparse YAML editing, MR creation, and optional Jira tracking. Automates Step 2 of the ODH component onboarding pipeline.
allowed-tools: Bash, Read, Edit
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

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

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

4. Set `APP_INTERFACE_URL` to `$APP_INTERFACE_REPO_URL` if set, else `https://gitlab.cee.redhat.com/service/app-interface`.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
# 1. GITLAB_USER
if [[ -z "${GITLAB_USER:-}" ]]; then
  echo "ERROR: GITLAB_USER is not set."
  echo "  export GITLAB_USER=yourusername"
  exit 1
fi

# 2. GITLAB_TOKEN
if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  echo "ERROR: GITLAB_TOKEN is not set."
  echo "  export GITLAB_TOKEN=yourtoken"
  exit 1
fi

# 3. uv
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed."
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# 4. skopeo
if ! command -v skopeo &>/dev/null; then
  echo "ERROR: skopeo is not installed."
  echo "  macOS:       brew install skopeo"
  echo "  RHEL/Fedora: sudo dnf install skopeo"
  exit 1
fi
```

If `--jira-url` was provided, also check:
```bash
if [[ -z "${JIRA_USER_EMAIL:-}" ]] || [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: --jira-url requires JIRA_USER_EMAIL and JIRA_API_TOKEN to be set."
  echo "  export JIRA_USER_EMAIL=you@example.com"
  echo "  export JIRA_API_TOKEN=your-api-token"
  exit 1
fi
```

---

## Step 2: Create Working Directory

```bash
if [[ -n "<jira-id>" ]]; then
  WORKDIR="$(pwd)/<jira-id>"
else
  WORKDIR="$(pwd)/quay-<org>-<repo>"
fi
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"
```

---

## Step 3: Check If Quay Repo Already Exists

```bash
bash <COMMON_SCRIPTS_DIR>/check_quay_repo.sh quay.io/<org>/<repo>
```

- **Exit 0** (repo exists): If `--jira-url` was provided, run:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "quay-repo-created" \
    --comment "Quay repo quay.io/<org>/<repo> already exists. No action needed."
  ```
  Then print:
  ```
  Quay repo quay.io/<org>/<repo> already exists. Nothing to do.
  ```
  And **stop**.

- **Exit 1** (does not exist): Continue to Step 4.

- **Exit 2** (tool error): Display the error output and stop.

---

## Step 4: Check for Existing Open MR in Jira Comments

This step only runs if `$WORKDIR/odh_component_details.json` exists (produced by the
`validate-component-onboarding-jira` skill).

Use the `Read` tool to read `$WORKDIR/odh_component_details.json`.

Search the array at `fields.comment.comments[].body` for GitLab MR URLs matching the
regular expression:
```
https://gitlab\.cee\.redhat\.com/[^/\s]+/[^/\s]+/-/merge_requests/\d+
```

For each URL found, run:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_gitlab_mr.py --mr-url <found-url> --check-only
```

Parse the stdout:
- If `state=opened` **and** the `title=` line contains `<repo>` (the quay repo name):
  - This is an existing open MR for the same quay repo.
  - If `--jira-url` provided:
    ```bash
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
      --comment "Found existing open GitLab MR for quay.io/<org>/<repo>: <found-url>. Monitoring it."
    ```
  - Print: `Found existing open MR: <found-url>. Skipping MR creation and jumping to monitor step.`
  - **Jump directly to Step 10** (Monitor MR) using `MR_URL=<found-url>`.

If no matching open MR is found, continue to Step 5.

---

## Step 5: Fork app-interface

```bash
FORK_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/setup_gitlab_fork.py \
  --gitlab-repo-url "$APP_INTERFACE_URL")
```

On exit 1: display the script's stderr output and stop with:
```
ERROR in Step 5 (Fork app-interface): Could not fork the repository. See details above. Aborting.
```

On success, `FORK_URL` holds the HTTPS URL of the fork (e.g.,
`https://gitlab.cee.redhat.com/<GITLAB_USER>/app-interface`).

---

## Step 6: Determine Sparse File Path and Branch Name

Map `<org>` to the YAML file path inside app-interface:

| `<org>` | Sparse file path |
|---------|-----------------|
| `opendatahub` | `data/services/rhoai/quay/opendatahub.yml` |
| `rhoai`       | `data/services/rhoai/quay/rhoai.yml`       |
| `modh`        | `data/services/rhoai/quay/modh.yml`        |
| Other         | Ask the user (see below)                   |

For any other `<org>`, pause and ask:
> I need the path to the quay config YAML within app-interface for the org `<org>`.
> This is typically under `data/services/rhoai/quay/<org>.yml`.
> What is the correct path?

Set `SPARSE_FILE=<path>`.

Determine `DEST_BRANCH`:
- If `<jira-id>` is available: `DEST_BRANCH=<jira-id>` (e.g. `RHOAIENG-1234`)
- Otherwise: leave `DEST_BRANCH` unset (the playpen script will auto-generate one)

---

## Step 7: Set Up Playpen (Sparse Clone)

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

if [[ -n "$DEST_BRANCH" ]]; then
  PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_gitlab_playpen.sh \
    --src-url "$APP_INTERFACE_URL" \
    --dest-url "$FORK_URL" \
    --src-branch master \
    --dest-branch "$DEST_BRANCH" \
    --sparse-files "$SPARSE_FILE")
else
  PLAYPEN_OUTPUT=$(bash <COMMON_SCRIPTS_DIR>/setup_gitlab_playpen.sh \
    --src-url "$APP_INTERFACE_URL" \
    --dest-url "$FORK_URL" \
    --src-branch master \
    --sparse-files "$SPARSE_FILE")
fi
```

Parse `PLAYPEN_OUTPUT`:
- Line 1 → `CLONE_DIR` (absolute path to the `app-interface-playpen` directory)
- Line 2 → `DEST_BRANCH` (the branch that was created and pushed)

On exit 1: display stderr and stop with:
```
ERROR in Step 7 (Playpen setup): Clone or push failed. See details above. Aborting.
```

---

## Step 8: Modify YAML File

Use the `Read` tool to read `$CLONE_DIR/$SPARSE_FILE`.

**Idempotency check:** Search the `items:` array for any entry where `name: <repo>` is already
present. If found:
- Print: `Entry for '<repo>' already exists in the YAML — skipping append.`
- Continue to Step 9.

If the entry does NOT exist, compose the YAML block to append:
```yaml
- name: <repo>
  description: "<org> <repo> container image"
  public: <true_or_false>
```
Where `public: true` if `visibility=public`, `public: false` if `visibility=private`.

Use the `Edit` tool to append this block to the `items:` array in `$CLONE_DIR/$SPARSE_FILE`.
Append after the last existing item in the array, maintaining consistent indentation (2 spaces).

After editing, use the `Read` tool to re-read the file and verify:
- The new `name: <repo>` entry is present
- The YAML structure looks syntactically correct (items array properly indented)

If the file looks malformed, fix it with another `Edit` call before proceeding.

---

## Step 9: Commit and Raise MR (up to 3 attempts)

First, commit the change:
```bash
cd "$CLONE_DIR"
git add "$SPARSE_FILE"
git commit -m "Add <repo> to quay <org> config"
```

If `FORK_URL != APP_INTERFACE_URL`, the remote is named `dest`; otherwise it is `origin`.
Determine the remote name (`DEST_REMOTE`) accordingly.

Push the commit:
```bash
git push "$DEST_REMOTE" "$DEST_BRANCH"
```

If the push fails (branch already has commits on remote), try `git push --force-with-lease "$DEST_REMOTE" "$DEST_BRANCH"` once.

Now raise the MR. Attempt up to **3 times**:

**Attempt 1:**
```bash
MR_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/raise_gitlab_mr.py \
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
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "quay-mr-raised" \
  --comment "GitLab MR raised to create quay.io/<org>/<repo>.

MR URL: $MR_URL

The Quay repo will be created automatically once this MR is merged."
```

---

## Step 10: Monitor MR

```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_gitlab_mr.py \
  --mr-url "$MR_URL" \
  --timeout 60
```

The script polls every 60 seconds and writes progress to stderr.

Read the **stdout** result:

- **`merged`** (exit 0): Quay repo is being created. If `--jira-url` provided:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "quay-repo-created" \
    --remove-label "quay-mr-raised" \
    --comment "MR merged: $MR_URL

quay.io/<org>/<repo> has been created (or will be created shortly by app-interface's GitOps reconciliation).

Step 2 (Create Quay Repo) is complete."
  ```
  Then print:
  ```
  ✓ quay.io/<org>/<repo> created successfully.
    MR merged: <MR_URL>
  ```

- **`closed`** (exit 1): MR was closed without merging. If `--jira-url` provided:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "GitLab MR was closed without merging: $MR_URL

Please review the MR and re-run /create-quay-repo if needed."
  ```
  Then stop with:
  ```
  ERROR in Step 10 (Monitor MR): MR was closed without merging. Check the MR: <MR_URL>. Aborting.
  ```

- **`pipeline_failed`** or **`pipeline_canceled`** (exit 1): Pipeline failed. The monitor
  script has already printed the failed job names and URLs to stderr. If `--jira-url` provided:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "Pipeline failed on GitLab MR: $MR_URL

Check the pipeline failures reported above and fix them, then re-run /create-quay-repo."
  ```
  Then stop with:
  ```
  ERROR in Step 10 (Monitor MR): Pipeline failed. Fix the pipeline issues and retry. MR: <MR_URL>. Aborting.
  ```

- **`timeout`** (exit 1): MR is still open after 60 minutes. If `--jira-url` provided:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "Monitoring timed out after 60 minutes. MR is still open: $MR_URL

Please check the MR status manually and re-run /create-quay-repo if needed."
  ```
  Then print:
  ```
  WARNING: MR monitoring timed out after 60 minutes.
  The MR is still open: <MR_URL>
  Check it manually and re-run this skill when the MR is merged (it will short-circuit at Step 3).
  ```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITLAB_USER` not set | Step 1 | `export GITLAB_USER=yourusername` |
| `GITLAB_TOKEN` not set | Step 1 | `export GITLAB_TOKEN=yourtoken` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `skopeo` not installed | Step 1 | `brew install skopeo` / `sudo dnf install skopeo` |
| VPN not active | Steps 5, 7, 9, 10 | Activate VPN and re-run |
| Fork creation fails | Step 5 | Check GITLAB_TOKEN permissions (needs `api` scope) |
| Clone fails | Step 7 | Check VPN and GITLAB_TOKEN `write_repository` scope |
| Push fails | Step 9 | Check GITLAB_TOKEN `write_repository` scope |
| MR creation fails 3x | Step 9 | Check VPN; inspect stderr; manual fallback |
| MR closed without merge | Step 10 | Review the MR; re-run after fixing |
| Pipeline failed | Step 10 | Fix pipeline issues; re-run |
