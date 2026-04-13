---
name: onboard-component-to-konflux-release-data
description: Onboards a new ODH/RHOAI component onto the Konflux CI platform by raising a merge request to the konflux-release-data GitLab repo. Automates Step 3 of the ODH component onboarding pipeline.
allowed-tools: Bash, Read, Edit
user-invocable: true
---

# Onboard Component to Konflux Release Data

Creates Konflux `Component` resources for a new ODH/RHOAI component by appending a YAML
document to the appropriate tenant config file in the `konflux-release-data` GitLab repository
and raising a merge request. When the MR is merged, a GitOps pipeline provisions the Component
on the Konflux OpenShift cluster.

## Usage

```
/onboard-component-to-konflux-release-data <jira-url>
```

Examples:
```
/onboard-component-to-konflux-release-data https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Prerequisites

- `GITLAB_USER` — your GitLab username (`export GITLAB_USER=yourusername`)
- `GITLAB_TOKEN` — GitLab personal access token with `api` + `write_repository` scopes
- `JIRA_USER_EMAIL` — your Atlassian account email
- `JIRA_API_TOKEN` — Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `oc` — OpenShift CLI (https://console.redhat.com/openshift/downloads)
- Optional: `KONFLUX_RELEASE_DATA_REPO_URL` (default: `https://gitlab.cee.redhat.com/releng/konflux-release-data.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Optional: `OC_TOKEN` — cluster login token if no matching kubeconfig context is found

**Network:** Both `gitlab.cee.redhat.com` and the Konflux OpenShift cluster require
**VPN to be active**.

**Jira attachment:** The Jira issue must have `odh_component_details.yaml` attached. This
YAML is the source of truth for all component parameters (repo URL, branch, Dockerfile path,
context path, etc.).

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.
VALIDATE_SKILL_DIR is `<SKILL_DIR>/../validate-component-onboarding-jira`.

---

## Step 0: Parse Inputs

1. Extract `<jira-url>` (the first positional argument). It must be a full Jira URL.
   Extract `<jira-id>` as the last path segment (e.g., `RHOAIENG-1234`, `RHODS-5678`).

   If the argument cannot be parsed as a Jira URL (no `/browse/` segment or no issue key),
   stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

2. Set `KRD_URL` to `$KONFLUX_RELEASE_DATA_REPO_URL` if set, else
   `https://gitlab.cee.redhat.com/releng/konflux-release-data.git`.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
# 1. GITLAB_USER
if [[ -z "${GITLAB_USER:-}" ]]; then
  echo "ERROR: GITLAB_USER is not set. export GITLAB_USER=yourusername"
  exit 1
fi

# 2. GITLAB_TOKEN
if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  echo "ERROR: GITLAB_TOKEN is not set. export GITLAB_TOKEN=yourtoken"
  exit 1
fi

# 3. JIRA_USER_EMAIL
if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  echo "ERROR: JIRA_USER_EMAIL is not set. export JIRA_USER_EMAIL=you@example.com"
  exit 1
fi

# 4. JIRA_API_TOKEN
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: JIRA_API_TOKEN is not set. export JIRA_API_TOKEN=your-api-token"
  exit 1
fi

# 5. uv
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

# 6. oc
if ! command -v oc &>/dev/null; then
  echo "ERROR: oc CLI is not installed. https://console.redhat.com/openshift/downloads"
  exit 1
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

This step ensures both `odh_component_details.json` (full Jira issue) and
`odh_component_details.yaml` (component parameters) exist in `$WORKDIR`.

**3a. Fetch Jira issue details** (skip if `$WORKDIR/odh_component_details.json` already exists):

```bash
cd "$WORKDIR"
uv run --script <VALIDATE_SKILL_DIR>/scripts/fetch_jira_details.py <jira-url>
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3a (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting.
```

On success: `$WORKDIR/odh_component_details.json` is written.

**3b. Download component YAML** (skip if `$WORKDIR/odh_component_details.yaml` already exists):

```bash
cd "$WORKDIR"
uv run --script <VALIDATE_SKILL_DIR>/scripts/download_jira_attachment.py \
  <jira-url> odh_component_details.yaml
```

On exit 1: display stderr and stop with:
```
ERROR in Step 3b (Download YAML): Could not download 'odh_component_details.yaml' from Jira.
  Ensure the attachment exists on the Jira issue before running this skill.
```

**3c. Parse the YAML** using the `Read` tool to read `$WORKDIR/odh_component_details.yaml`.

Extract and store these values (all are under the `inputs:` key):

| Variable | YAML field | Example |
|----------|-----------|---------|
| `COMPONENT_NAME` | `inputs.component_name` | `odh-ai-first-demo` |
| `REPO_URL` | `inputs.repo_url` | `https://github.com/rhoai-rhtap/odh-ai-first-demo` |
| `REPO_BRANCH` | `inputs.repo_branch` | `main` |
| `CONTEXT_PATH` | `inputs.context_path` | `maas-controller` |
| `DOCKERFILE_PATH` | `inputs.dockerfile_path` | `Dockerfile` |

Compute `KONFLUX_COMPONENT_NAME`:
- If `COMPONENT_NAME` already ends with `-ci`: `KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"`
- Otherwise: `KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"`

If any required field is missing, stop with:
```
ERROR in Step 3c: Missing required field '<field>' in odh_component_details.yaml. Aborting.
```

---

## Step 4: Determine Product Context

Set `PRODUCT_CONTEXT` to `ODH` or `RHOAI` using the following rules in order:

1. **From Jira key prefix**: if `<jira-id>` starts with `RHOAIENG` → `RHOAI`; if it starts
   with `RHODS` → `ODH`.
2. **From Jira title** (in `odh_component_details.json` at `fields.summary`): if the title
   contains "RHOAI" (case-insensitive) → `RHOAI`; if it contains "ODH" → `ODH`.
3. **Fallback**: Ask the user:
   > I could not determine the product context (ODH or RHOAI) from the Jira key or title.
   > Is this onboarding for ODH or RHOAI?

Based on `PRODUCT_CONTEXT`, set these variables:

| Variable | ODH | RHOAI |
|----------|-----|-------|
| `CLUSTER_INSTANCE` | `external` | `internal` |
| `KONFLUX_NAMESPACE` | `opendatahub-builds` | `rhoai-builds` |
| `SPARSE_PATHS` | `tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant tenants-config/auto-generated/cluster/stone-prd-rh01/tenants/open-data-hub-tenant` | `tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant` |
| `TARGET_YAML` | `tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant/opendatahub-ci-components.yaml` | `tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/rhoai-ci-components.yaml` |
| `KRD_APPLICATION` | `opendatahub-builds` | `rhoai-builds` |
| `QUAY_ORG` | `opendatahub` | `rhoai` |

> **Note on RHOAI paths:** If the RHOAI values above are incorrect for your environment
> (namespace name, YAML file name, Quay org), pause and ask the user to confirm before
> proceeding.

---

## Step 5: Check If Konflux Component Already Exists

```bash
bash <COMMON_SCRIPTS_DIR>/check_konflux_component.sh \
  "$KONFLUX_COMPONENT_NAME" "$KONFLUX_NAMESPACE" "$CLUSTER_INSTANCE"
```

- **Exit 0** (component exists): Update Jira and stop:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "konflux-component-created" \
    --comment "Konflux Component '$KONFLUX_COMPONENT_NAME' already exists in namespace '$KONFLUX_NAMESPACE'. No action needed."
  ```
  Print: `Konflux Component already exists. Nothing to do.` and **stop**.

- **Exit 1** (does not exist): Continue to Step 6.

- **Exit 2** (tool/login error): Display the error output and stop with:
  ```
  ERROR in Step 5: Could not check Konflux component status. Check VPN and OC_TOKEN.
  ```

---

## Step 6: Check for Existing Open MR in Jira Comments

Use the `Read` tool to read `$WORKDIR/odh_component_details.json`.

Search the array at `fields.comment.comments[].body` for GitLab MR URLs matching:
```
https://gitlab\.cee\.redhat\.com/[^/\s]+/[^/\s]+/-/merge_requests/\d+
```

For each URL found, run:
```bash
GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/monitor_gitlab_mr.py \
  --mr-url <found-url> --check-only
```

Parse stdout:
- If `state=opened` **and** `title=` line contains `KONFLUX_COMPONENT_NAME` or `COMPONENT_NAME`:
  - This is an existing open MR for the same component.
  - Update Jira:
    ```bash
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
      --comment "Found existing open GitLab MR for $KONFLUX_COMPONENT_NAME: <found-url>. Monitoring it."
    ```
  - Print: `Found existing open MR: <found-url>. Skipping MR creation and jumping to monitor.`
  - Set `MR_URL=<found-url>` and **jump directly to Step 11** (Monitor MR).

If no matching open MR is found, continue to Step 7.

---

## Step 7: Fork konflux-release-data

```bash
FORK_URL=$(GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/setup_gitlab_fork.py \
  --gitlab-repo-url "$KRD_URL")
```

On exit 1: display stderr and stop with:
```
ERROR in Step 7 (Fork KRD): Could not fork konflux-release-data. See details above.
  Check GITLAB_TOKEN permissions (needs 'api' scope) and that VPN is active.
```

On success, `FORK_URL` holds the HTTPS URL of your fork (e.g.,
`https://gitlab.cee.redhat.com/<GITLAB_USER>/konflux-release-data`).

---

## Step 8: Set Up Playpen (Sparse Clone)

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash <COMMON_SCRIPTS_DIR>/setup_gitlab_playpen.sh \
  --src-url "$KRD_URL" \
  --dest-url "$FORK_URL" \
  --src-branch main \
  --dest-branch "<jira-id>" \
  --sparse-files "$SPARSE_PATHS")
```

Parse `PLAYPEN_OUTPUT`:
- Line 1 → `CLONE_DIR` (absolute path to the clone directory — will be named
  `app-interface-playpen` inside `$WORKDIR`, which is the playpen script's fixed output name)
- Line 2 → `DEST_BRANCH` (the branch created and pushed to the fork)

On exit 1: display stderr and stop with:
```
ERROR in Step 8 (Playpen setup): Clone or push failed. See details above.
  Check VPN connectivity and GITLAB_TOKEN write_repository scope.
```

If the initial push fails with "shallow update not allowed", unshallow and retry:
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push dest "<jira-id>"
```

---

## Step 9: Modify the Target YAML File

Use the `Read` tool to read `$CLONE_DIR/$TARGET_YAML`.

**Idempotency check:** Search the file for any occurrence of `name: $KONFLUX_COMPONENT_NAME`.
If found:
- Print: `Component entry '$KONFLUX_COMPONENT_NAME' already present in $TARGET_YAML — skipping append.`
- Continue to Step 10.

If the entry does NOT exist, compose the new YAML document to append (note: the file uses
`---` document separators; append a new document at the end):

```yaml
---
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  annotations:
    build.appstudio.openshift.io/request: configure-pac-no-mr
    mintmaker.appstudio.redhat.com/disabled: "true"
    build.appstudio.openshift.io/pipeline: '{"name":"docker-build-multi-platform-oci-ta","bundle":"latest"}'
  name: <KONFLUX_COMPONENT_NAME>
spec:
  application: <KRD_APPLICATION>
  componentName: <KONFLUX_COMPONENT_NAME>
  containerImage: quay.io/<QUAY_ORG>/<COMPONENT_NAME>
  source:
    git:
      context: <CONTEXT_PATH>
      dockerfileUrl: <DOCKERFILE_PATH>
      revision: <REPO_BRANCH>
      url: <REPO_URL>
```

Substitute all `<...>` placeholders with the variables resolved in Steps 3 and 4.

Use the `Edit` tool to append this block after the last line of `$CLONE_DIR/$TARGET_YAML`.
Maintain consistent 2-space indentation as used in the rest of the file.

After editing, use the `Read` tool to re-read the file and verify:
- `name: <KONFLUX_COMPONENT_NAME>` is present
- The YAML structure is syntactically correct (proper `---` separator, consistent indentation)
- `containerImage` uses `COMPONENT_NAME` (no `-ci` suffix), not `KONFLUX_COMPONENT_NAME`

If the file looks malformed, fix it with another `Edit` call before proceeding.

---

## Step 10: Commit and Raise MR (up to 3 attempts)

**Commit:**

```bash
cd "$CLONE_DIR"
git add "$TARGET_YAML"
git commit -m "Add $KONFLUX_COMPONENT_NAME Component to konflux-release-data"
```

**Push** (remote is named `dest` since fork URL != src URL):

```bash
git push dest "$DEST_BRANCH"
```

If push fails with "shallow update not allowed":
```bash
git fetch --unshallow origin
git push dest "$DEST_BRANCH"
```

If push fails with "already exists on remote", try force-with-lease:
```bash
git push --force-with-lease dest "$DEST_BRANCH"
```

**Raise MR** — attempt up to 3 times:

```bash
MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/raise_gitlab_mr.py \
  --src-url "$FORK_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$KRD_URL" \
  --dest-branch main \
  --title "Add $KONFLUX_COMPONENT_NAME Component for $COMPONENT_NAME" \
  --description "Add Konflux Component '$KONFLUX_COMPONENT_NAME' to $TARGET_YAML.

Product: $PRODUCT_CONTEXT
Application: $KRD_APPLICATION
Container image: quay.io/$QUAY_ORG/$COMPONENT_NAME
Source repo: $REPO_URL @ $REPO_BRANCH
Jira: <jira-url>")
```

On success: `MR_URL` is set.

On failure:
- "Branch not found on fork" → re-run the push and retry
- "Connection error / VPN" → tell user to check VPN and retry
- Any other error → retry (up to 3 times total)

After 3 failures, stop with:
```
ERROR in Step 10 (Raise MR): Could not create MR after 3 attempts. See errors above. Aborting.
```

After a successful MR creation, update Jira:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
  --add-label "konflux-mr-raised" \
  --comment "GitLab MR raised to create Konflux Component '$KONFLUX_COMPONENT_NAME'.

MR URL: $MR_URL

The Component will be provisioned on the Konflux cluster once this MR is merged."
```

---

## Step 11: Monitor MR

```bash
GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/monitor_gitlab_mr.py \
  --mr-url "$MR_URL" \
  --timeout 60
```

The script polls every 60 seconds and writes progress to stderr.

Read the **stdout** result:

- **`merged`** (exit 0): MR is merged; GitOps pipeline will provision the Component shortly.
  Update Jira:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --remove-label "konflux-mr-raised" \
    --comment "MR merged: $MR_URL

Konflux GitOps pipeline is provisioning Component '$KONFLUX_COMPONENT_NAME' on the cluster.
Monitoring for creation..."
  ```
  Print: `MR merged. Proceeding to verify Konflux Component creation...`
  **Continue to Step 12.**

- **`closed`** (exit 1): MR was closed without merging.
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "GitLab MR was closed without merging: $MR_URL

Please review the MR and re-run /onboard-component-to-konflux-release-data if needed."
  ```
  Stop with:
  ```
  ERROR in Step 11 (Monitor MR): MR was closed without merging. Check the MR: <MR_URL>.
  ```

- **`pipeline_failed`** or **`pipeline_canceled`** (exit 1): Pipeline failed.
  Attempt to check out the branch, diagnose the failure from the pipeline job output, fix
  the YAML in `$CLONE_DIR/$TARGET_YAML`, recommit, and push to update the MR:
  ```bash
  cd "$CLONE_DIR"
  # Fix the YAML with Edit tool, then:
  git add "$TARGET_YAML"
  git commit -m "Fix $KONFLUX_COMPONENT_NAME Component definition"
  git push dest "$DEST_BRANCH"
  ```
  Update Jira:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "Pipeline failed on MR $MR_URL. Attempted automated fix and pushed update.

Please review the MR pipeline and re-run if the issue persists."
  ```
  **Jump back to Step 11** to re-monitor the updated MR (once).
  If the pipeline fails again, stop with:
  ```
  ERROR in Step 11 (Monitor MR): Pipeline failed after fix attempt. Manual intervention needed.
  MR: <MR_URL>
  ```

- **`timeout`** (exit 1): MR still open after 60 minutes.
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "MR monitoring timed out after 60 minutes. MR is still open: $MR_URL

Please check the MR status manually. Re-run /onboard-component-to-konflux-release-data
to resume — it will skip MR creation and jump straight to monitoring."
  ```
  Print:
  ```
  WARNING: MR monitoring timed out after 60 minutes.
  The MR is still open: <MR_URL>
  Re-run this skill when the MR is merged (it will short-circuit at Step 6).
  ```

---

## Step 12: Monitor Konflux Component Creation

After the MR is merged, poll `check_konflux_component.sh` every 60 seconds for up to
30 minutes until the Component appears on the Konflux cluster.

```bash
POLL_INTERVAL=60    # seconds between checks
MAX_WAIT=1800       # 30 minutes
ELAPSED=0

echo "Monitoring Konflux Component '$KONFLUX_COMPONENT_NAME' in namespace '$KONFLUX_NAMESPACE' (timeout: 30 minutes)..."

while true; do
  bash <COMMON_SCRIPTS_DIR>/check_konflux_component.sh \
    "$KONFLUX_COMPONENT_NAME" "$KONFLUX_NAMESPACE" "$CLUSTER_INSTANCE"
  CHECK_EXIT=$?

  if [[ $CHECK_EXIT -eq 0 ]]; then
    break   # Component found
  elif [[ $CHECK_EXIT -eq 2 ]]; then
    echo "WARNING: check_konflux_component.sh returned a tool error. Retrying..."
  fi
  # Exit 1 = not yet created; keep polling

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    CHECK_EXIT=3
    break
  fi

  REMAINING=$(( (MAX_WAIT - ELAPSED) / 60 ))
  echo "  Component not yet visible (elapsed=${ELAPSED}s, remaining≈${REMAINING}m). Retrying in ${POLL_INTERVAL}s..."
  sleep $POLL_INTERVAL
  ELAPSED=$(( ELAPSED + POLL_INTERVAL ))
done
```

Handle the result:

- **`CHECK_EXIT=0`** (Component created): Update Jira and print success:
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --add-label "konflux-component-created" \
    --comment "Konflux Component successfully provisioned.

Component name: $KONFLUX_COMPONENT_NAME
Namespace: $KONFLUX_NAMESPACE
Cluster: $CLUSTER_INSTANCE ($([ "$CLUSTER_INSTANCE" = "external" ] && echo "stone-prd-rh01" || echo "stone-prod-p02"))

Verified via: oc get component -n $KONFLUX_NAMESPACE $KONFLUX_COMPONENT_NAME

Step 3 (Add to konflux-release-data) is complete."
  ```
  Print:
  ```
  ✓ Konflux Component '$KONFLUX_COMPONENT_NAME' is live in namespace '$KONFLUX_NAMESPACE'.
    Step 3 (Add to konflux-release-data) complete.
  ```

- **`CHECK_EXIT=3`** (30-minute timeout): Component not yet visible.
  ```bash
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira-url> \
    --comment "Konflux Component monitoring timed out after 30 minutes.
'$KONFLUX_COMPONENT_NAME' has not yet appeared in namespace '$KONFLUX_NAMESPACE'.

The MR was merged ($MR_URL) so the GitOps pipeline may still be running.
Re-run /onboard-component-to-konflux-release-data to re-check — it will short-circuit
at Step 5 once the Component exists."
  ```
  Print:
  ```
  WARNING: Component '$KONFLUX_COMPONENT_NAME' not visible after 30 minutes.
  The MR was merged so the Konflux GitOps pipeline may still be running.
  Re-run this skill later — it will short-circuit at Step 5 once the Component appears.
  ```

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| `GITLAB_USER` not set | Step 1 | `export GITLAB_USER=yourusername` |
| `GITLAB_TOKEN` not set | Step 1 | `export GITLAB_TOKEN=yourtoken` |
| `JIRA_USER_EMAIL` not set | Step 1 | `export JIRA_USER_EMAIL=you@redhat.com` |
| `JIRA_API_TOKEN` not set | Step 1 | `export JIRA_API_TOKEN=your-token` |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `oc` not installed | Step 1 | Download from console.redhat.com/openshift/downloads |
| `odh_component_details.yaml` not attached to Jira | Step 3b | Upload the YAML to the Jira issue |
| VPN not active | Steps 5, 7, 8, 10, 11 | Activate VPN and re-run |
| `OC_TOKEN` not set | Step 5 | `export OC_TOKEN=<token-from-openshift-console>` |
| Fork creation fails | Step 7 | Check GITLAB_TOKEN `api` scope |
| Shallow push rejected | Steps 8, 10 | `git fetch --unshallow origin` then retry push |
| Clone fails | Step 8 | Check VPN and GITLAB_TOKEN `write_repository` scope |
| MR creation fails 3× | Step 10 | Check VPN; inspect stderr; fix manually |
| MR pipeline fails | Step 11 | YAML fix attempted automatically; check MR if it fails again |
| MR closed without merge | Step 11 | Review the MR; re-run after fixing |
| Component not visible after 30m | Step 12 | GitOps pipeline may still be running; re-run to re-check |
