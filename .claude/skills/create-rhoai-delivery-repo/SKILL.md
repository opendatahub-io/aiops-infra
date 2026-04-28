---
name: create-rhoai-delivery-repo
description: Creates an RHOAI delivery repository by raising a GitLab MR to pyxis-repo-configs. Reads component details from the Jira attachment, checks if the delivery repo already exists, and if not, adds the repository entry to products/rhoai/rhoai.yaml and raises and monitors a GitLab MR. VPN required.
allowed-tools: Bash
user-invocable: true
---

# Create RHOAI Delivery Repo

Creates a new RHOAI delivery repository in the Red Hat container registry. The repository is
provisioned automatically when a GitLab MR is merged into `pyxis-repo-configs` — a GitOps repo
maintained by the Release Engineering team. This skill handles the full lifecycle:

1. Check if the delivery repo already exists in `products/rhoai/rhoai.yaml`
2. Check Jira comments for an in-progress MR
3. Clone `pyxis-repo-configs`, append the repository entry, push, raise MR, and monitor

## Usage

```
/create-rhoai-delivery-repo [<jira-url>]
```

Examples:
```
/create-rhoai-delivery-repo https://redhat.atlassian.net/browse/RHOAIENG-1234
/create-rhoai-delivery-repo
```

## Prerequisites

- `GITLAB_USER` — your GitLab username (`export GITLAB_USER=yourusername`)
- `GITLAB_TOKEN` — GitLab personal access token with `api` + `write_repository` scopes
- `JIRA_USER_EMAIL` — your Atlassian account email (required when a Jira URL is provided)
- `JIRA_API_TOKEN` — Atlassian API token (required when a Jira URL is provided)
  - Create at: https://id.atlassian.com/manage-profile/security/api-tokens
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `git`
- `curl`
- Optional: `PYXIS_REPO_CONFIGS_REPO_URL` — override the pyxis-repo-configs URL
  (default: `https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Optional: `GITLAB_SSL_VERIFY` — set to `false` if you encounter certificate errors

**Network:** `gitlab.cee.redhat.com` requires **Red Hat VPN to be active**.

**Jira attachment:** The Jira issue must have `component_onboarding_details.yaml` attached
(created by `/create-component-onboarding-jira`), unless this skill is invoked from the master
onboarding pipeline (which places the YAML in the working directory automatically).

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse Inputs

1. Extract `<jira-url>` from the first positional argument (may be empty/omitted).

2. If provided but does not contain `/browse/`, stop with:
   > ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

3. Set `JIRA_URL` to the parsed URL, or empty string if omitted.
   Set `JIRA_ID` to the last path segment (e.g. `RHOAIENG-1234`), or empty string.

4. Resolve `PYXIS_URL` — **IMPORTANT: this is the single source of truth for ALL Git and GitLab
   API operations in this skill**. Use `$PYXIS_URL` for every Git clone, push, MR source URL,
   MR destination URL, and API path. Never substitute a hardcode URL or the upstream URL in place
   of `$PYXIS_URL`, even if `$PYXIS_URL` appears to point to a personal fork — the user configured
   it intentionally.

   ```bash
   PYXIS_URL="${PYXIS_REPO_CONFIGS_REPO_URL:-https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git}"
   echo "PYXIS_REPO_CONFIGS_REPO_URL=${PYXIS_REPO_CONFIGS_REPO_URL:-(not set, using default)}"
   echo "PYXIS_URL resolved to: $PYXIS_URL"
   ```

5. Derive GitLab path components for API calls:
   ```bash
   PYXIS_PATH=$(echo "$PYXIS_URL" | sed 's|https://gitlab.cee.redhat.com/||;s|\.git$||')
   # e.g. "releng/pyxis-repo-configs"
   PYXIS_PATH_ENCODED=$(echo "$PYXIS_PATH" | sed 's|/|%2F|g')
   # e.g. "releng%2Fpyxis-repo-configs"
   ```

6. Echo the resolved values:
   ```bash
   echo "JIRA_URL  : ${JIRA_URL:-(not provided)}"
   echo "JIRA_ID   : ${JIRA_ID:-(not provided)}"
   echo "PYXIS_URL : $PYXIS_URL"
   echo "PYXIS_PATH: $PYXIS_PATH"
   ```

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "GITLAB_USER GITLAB_TOKEN" \
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

## Step 3: Get Component YAML

**3a. Check for pipeline-state YAML** — skip download if the file already exists (placed by the
master orchestrator):
```bash
if [[ -f "$WORKDIR/component_onboarding_details.yaml" ]]; then
  echo "Using existing component_onboarding_details.yaml from pipeline state."
fi
```

**3b. Download from Jira** (only when file does not exist and `JIRA_URL` is non-empty):
```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/download_jira_attachment.py \
  "$JIRA_URL" component_onboarding_details.yaml
```

On exit 1: display stderr and stop:
```
ERROR in Step 3b: Could not download 'component_onboarding_details.yaml'.
  Ensure the attachment exists on the Jira issue.
  Run /create-component-onboarding-jira <jira-url> first.
```

**3c. Guard — no YAML and no Jira URL:**

If the file still does not exist and `JIRA_URL` is empty, stop:
```
ERROR in Step 3: No component_onboarding_details.yaml found and no Jira URL provided.
  Either provide a Jira URL or run from within the master onboarding pipeline.
```

**3d. Fetch Jira issue details** (skip if `$WORKDIR/component_onboarding_details.json` already
exists; only when `JIRA_URL` is non-empty):
```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py "$JIRA_URL"
```

On exit 1: display stderr and stop:
```
ERROR in Step 3d (Fetch Jira): Could not fetch issue details. Aborting.
```

---

## Step 4: Parse YAML and Derive Variables

```bash
YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
COMPONENT_NAME=$(grep -m1 'component_name:' "$YAML_FILE" | awk '{print $2}')
TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}')

for _field in COMPONENT_NAME TARGET_RHOAI_VERSION; do
  [[ -z "${!_field}" ]] && {
    echo "ERROR in Step 4: Missing required field '${_field}' in component_onboarding_details.yaml."
    echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
    exit 1
  }
done

eval "$(bash "$COMMON_SCRIPTS_DIR/parse_rhoai_version.sh" \
  --version "$TARGET_RHOAI_VERSION" \
  --component "$COMPONENT_NAME")"
# Sets: CONTENT_STREAM_TAG, REPOSITORY_NAME, and other version vars
```

Print resolved values:
```
COMPONENT_NAME       : $COMPONENT_NAME
TARGET_RHOAI_VERSION : $TARGET_RHOAI_VERSION
REPOSITORY_NAME      : $REPOSITORY_NAME
CONTENT_STREAM_TAG   : $CONTENT_STREAM_TAG
PYXIS_URL            : $PYXIS_URL
```

---

## Step 5: Fast-Path Check — Does Delivery Repo Already Exist?

Fetch `products/rhoai/rhoai.yaml` from the main branch via the GitLab API:

```bash
RHOAI_YAML_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -sk -w "%{http_code}" \
  -H "Authorization: Bearer $GITLAB_TOKEN" \
  "https://gitlab.cee.redhat.com/api/v4/projects/${PYXIS_PATH_ENCODED}/repository/files/products%2Frhoai%2Frhoai.yaml/raw?ref=main" \
  -o "$RHOAI_YAML_TMPFILE")
```

**If `HTTP_STATUS != 200`:** warn and skip fast-path (continue to Step 6):
```
WARN in Step 5: Could not fetch rhoai.yaml via GitLab API (HTTP $HTTP_STATUS).
  Ensure VPN is active. Continuing with clone.
```
Clean up: `rm -f "$RHOAI_YAML_TMPFILE"`

**If `HTTP_STATUS == 200`:** check whether the repository entry already exists:
```bash
if grep -qF "repository: ${REPOSITORY_NAME}" "$RHOAI_YAML_TMPFILE"; then
  REPO_EXISTS=true
else
  REPO_EXISTS=false
fi
rm -f "$RHOAI_YAML_TMPFILE"
```

If `REPO_EXISTS=true`:
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "delivery-repo-exists" \
    --comment "Delivery repository '${REPOSITORY_NAME}' already exists in pyxis-repo-configs.

No changes needed. The repository is already present in products/rhoai/rhoai.yaml on the main branch."
fi
```
Print:
```
Delivery repository '$REPOSITORY_NAME' already exists in products/rhoai/rhoai.yaml.
Jira updated (label: delivery-repo-exists). No MR needed.
```
**Stop with exit 0.**

If `REPO_EXISTS=false`: continue to Step 6.

---

## Step 6: Check for Existing Open MR in Jira Comments

Skip this step if `$WORKDIR/component_onboarding_details.json` does not exist.

Extract MR URLs from `$WORKDIR/component_onboarding_details.json`:
```bash
EXISTING_MR_URLS=$(jq -r '.fields.comment.comments[].body' \
  "$WORKDIR/component_onboarding_details.json" 2>/dev/null \
  | grep -oE 'https://gitlab\.cee\.redhat\.com/[^/[:space:]]+/[^/[:space:]]+/-/merge_requests/[0-9]+' \
  | sort -u || true)
```

Search `fields.comment.comments[].body` for GitLab MR URLs matching:
```
https://gitlab\.cee\.redhat\.com/[^/\s]+/[^/\s]+/-/merge_requests/\d+
```

For each URL found, run:
```bash
GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/monitor_gitlab_mr.py \
  --mr-url "<found-url>" --check-only
```

Parse stdout:
- If `state=opened` and the `title=` line contains `COMPONENT_NAME` or `REPOSITORY_NAME`:
  ```bash
  MR_URL="<found-url>"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --comment "Found existing open GitLab MR for '${REPOSITORY_NAME}': ${MR_URL}
  Resuming monitoring of this MR."
  fi
  ```
  Print: `Found existing open MR: $MR_URL. Skipping MR creation and jumping to monitor.`
  **Set `MR_URL` and jump directly to Step 11** (Monitor MR).

- If `state=merged`:
  ```bash
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
      --add-label "delivery-repo-exists" \
      --comment "Previously raised MR has been merged: <found-url>
  The delivery repository '${REPOSITORY_NAME}' has been provisioned."
  fi
  ```
  Print success and **stop with exit 0.**

- If `state=closed`: note it and continue checking other URLs, then continue to Step 7.

If no matching open MR is found, continue to Step 7.

---

## Step 7: Set Up GitLab Playpen (Clone)

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash <COMMON_SCRIPTS_DIR>/setup_gitlab_playpen.sh \
  --src-url "$PYXIS_URL" \
  --dest-url "$PYXIS_URL" \
  --src-branch main \
  ${JIRA_ID:+--dest-branch "$JIRA_ID"} \
  --sparse-files "products/rhoai/rhoai.yaml")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)
```

On exit 1: display stderr and stop:
```
ERROR in Step 7 (Playpen setup): Clone or push failed. See details above.
  Check GITLAB_TOKEN has 'write_repository' scope and push access to $PYXIS_PATH.
  Ensure VPN is active and you can reach gitlab.cee.redhat.com.
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 8: Add Entry to products/rhoai/rhoai.yaml

```bash
RHOAI_YAML="$CLONE_DIR/products/rhoai/rhoai.yaml"
[[ -f "$RHOAI_YAML" ]] || {
  echo "ERROR in Step 8: products/rhoai/rhoai.yaml not found in $CLONE_DIR."
  echo "  Verify PYXIS_URL points to the correct pyxis-repo-configs repository."
  exit 1
}

if grep -qF "repository: ${REPOSITORY_NAME}" "$RHOAI_YAML"; then
  echo "repository: ${REPOSITORY_NAME} already present in rhoai.yaml — skipping edit."
else
  cat >> "$RHOAI_YAML" <<EOF
- image_type: Layered
  base_rhel_version: rhel9
  repository:
    repository: ${REPOSITORY_NAME}
    release_categories:
      - Generally Available
    includes_multiple_content_streams: true
    auto_rebuild_tags: []
    content_stream_tags: ['${CONTENT_STREAM_TAG}']
    build_categories:
      - Standalone image
    team_id: 617017858ebd9a62aec7c3b8
    display_data:
      name: ${COMPONENT_NAME}
      short_description: ${COMPONENT_NAME}
      long_description: ${COMPONENT_NAME}
    vendor_label: redhat
    application_categories:
      - Developer Tools
    privileged_images_allowed: false
    publish_on_push: true
    documentation_links: []
    contacts:
      *team_contacts
    use_latest: false
    requires_terms: true
EOF

  grep -qF "repository: ${REPOSITORY_NAME}" "$RHOAI_YAML" || {
    echo "ERROR in Step 8: Verification failed — '${REPOSITORY_NAME}' not found in rhoai.yaml"
    exit 1
  }
  grep -qF "content_stream_tags: ['${CONTENT_STREAM_TAG}']" "$RHOAI_YAML" || {
    echo "ERROR in Step 8: Verification failed — content_stream_tags not correct in rhoai.yaml"
    exit 1
  }
  echo "Entry for ${REPOSITORY_NAME} added to products/rhoai/rhoai.yaml."
fi
```

---

## Step 9: Commit and Push

```bash
bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "products/rhoai/rhoai.yaml" \
  --message   "Add ${REPOSITORY_NAME} delivery repository for ${COMPONENT_NAME}

Adds a new repository entry to products/rhoai/rhoai.yaml:
  repository: ${REPOSITORY_NAME}
  content_stream_tags: ['${CONTENT_STREAM_TAG}']

Related: ${JIRA_ID:-no-jira}" \
  --branch    "$DEST_BRANCH"
```

On exit 1, display stderr and stop:
```
ERROR in Step 9 (Push): Could not push branch '$DEST_BRANCH'. See details above.
```

---

## Step 10: Raise MR (up to 3 attempts)

```bash
MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/raise_gitlab_mr.py \
  --src-url "$PYXIS_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$PYXIS_URL" \
  --dest-branch main \
  --title "Add ${REPOSITORY_NAME} delivery repository for ${COMPONENT_NAME}" \
  --description "Adds a new delivery repository entry to \`products/rhoai/rhoai.yaml\`.

## Repository details

| Field | Value |
|-------|-------|
| \`repository\` | \`${REPOSITORY_NAME}\` |
| \`content_stream_tags\` | \`['${CONTENT_STREAM_TAG}']\` |
| \`component_name\` | \`${COMPONENT_NAME}\` |
| \`target_rhoai_version\` | \`${TARGET_RHOAI_VERSION}\` |

**File changed:** \`products/rhoai/rhoai.yaml\`
**Jira:** ${JIRA_URL:-(none)}")
```

On failure:
- "Branch not found" → re-push the branch (`git push origin "$DEST_BRANCH"`) and retry.
- "Connection error" → notify user to check VPN, retry.
- Any other error → retry.

After 3 failures, stop:
```
ERROR in Step 10 (Raise MR): Could not create MR after 3 attempts. See errors above. Aborting.
```

On success, update Jira (only when `JIRA_URL` is non-empty):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "delivery-repo-mr-raised" \
  --comment "GitLab MR raised to create RHOAI delivery repository '${REPOSITORY_NAME}'.

MR URL: $MR_URL

File changed: products/rhoai/rhoai.yaml
Repository: ${REPOSITORY_NAME}
Content stream tag: ${CONTENT_STREAM_TAG}

The delivery repository will be provisioned automatically once the MR is merged."
```

> **CRITICAL: Proceed immediately to Step 11.** Do NOT stop here. Step 11 is mandatory
> follow-through after every successful MR creation.

---

## Step 11: Monitor MR

```bash
RESULT=$(GITLAB_SSL_VERIFY=false uv run --script <COMMON_SCRIPTS_DIR>/monitor_gitlab_mr.py \
  --mr-url "$MR_URL" \
  --timeout 60)
```

The script polls every 60 seconds and writes progress to stderr. Read **stdout** for the result.

**`merged` (exit 0):**
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "delivery-repo-created" \
    --remove-label "delivery-repo-mr-raised" \
    --comment "GitLab MR merged: $MR_URL

The delivery repository '${REPOSITORY_NAME}' has been provisioned in the Red Hat container registry.
Provisioning typically completes within a few minutes of merge."
fi
```
Print:
```
MR merged: $MR_URL
Delivery repository '$REPOSITORY_NAME' is being provisioned.
```
Continue to Step 12.

**`closed` (exit 1):**
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --add-label "delivery-repo-mr-closed" \
    --comment "GitLab MR was closed without merging: $MR_URL
Please review and re-run /create-rhoai-delivery-repo <jira-url>."
fi
```
Stop with:
```
ERROR in Step 11 (Monitor MR): MR was closed without merging. Check: $MR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):**

Attempt automated fix:
1. Check YAML validity:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('$CLONE_DIR/products/rhoai/rhoai.yaml'))" 2>&1
   ```
2. Verify the added entry is present:
   ```bash
   grep -qF "repository: ${REPOSITORY_NAME}" "$CLONE_DIR/products/rhoai/rhoai.yaml" \
     && echo "Entry present." || echo "WARN: Entry missing — re-apply may be needed."
   ```
3. If reapply needed, re-run the cat-append from Step 8 and push a new commit:
   ```bash
   bash "$COMMON_SCRIPTS_DIR/git_commit_push.sh" \
     --clone-dir "$CLONE_DIR" \
     --files     "products/rhoai/rhoai.yaml" \
     --message   "Fix rhoai.yaml YAML for ${REPOSITORY_NAME}" \
     --branch    "$DEST_BRANCH"
   ```
   Update Jira:
   ```bash
   uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
     --comment "Pipeline failed on MR $MR_URL. Attempted automated fix and pushed update.
Please review the MR pipeline and re-run if the issue persists."
   ```
   **Jump back to Step 11** to re-monitor the updated MR (once).
4. If the pipeline fails again or the issue is not fixable, update Jira with failure details and stop:
   ```
   ERROR in Step 11 (Monitor MR): Pipeline failed after fix attempt. Manual intervention needed.
   MR: $MR_URL
   ```

**`timeout` (exit 1):**
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
    --comment "MR monitoring timed out after 60 minutes: $MR_URL
The MR is still open. Check it manually and re-run /create-rhoai-delivery-repo <jira-url>
when ready — it will detect the open MR and resume monitoring."
fi
```
Print:
```
WARNING: MR monitoring timed out after 60 minutes.
The MR is still open: $MR_URL
Re-run this skill — it will detect the open MR in Jira comments and resume monitoring.
```
Continue to Step 12 (reporting only; no hard stop).

---

## Step 12: Report Completion

Print:
```
Done.

  products/rhoai/rhoai.yaml  — ${REPOSITORY_NAME} entry added
  content_stream_tags        : ['${CONTENT_STREAM_TAG}']
  GitLab MR                  : $MR_URL — $RESULT
  Jira                       : ${JIRA_ID:-(none)} — label: delivery-repo-created

The delivery repository will be available at:
  https://quay.io/${REPOSITORY_NAME}

Note: short_description and long_description default to '${COMPONENT_NAME}'.
  Update them in the MR before merge if a better description is needed.
```

---

## Error Reference

| Error | Step | Action |
|-------|------|--------|
| `GITLAB_USER` not set | 1 | `export GITLAB_USER=yourusername` |
| `GITLAB_TOKEN` not set | 1 | `export GITLAB_TOKEN=yourtoken` (needs `api` + `write_repository`) |
| `JIRA_USER_EMAIL` not set | 1 | `export JIRA_USER_EMAIL=you@example.com` |
| `JIRA_API_TOKEN` not set | 1 | `export JIRA_API_TOKEN=your-api-token` |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| VPN not active | 5, 7, 10, 11 | Connect to Red Hat VPN then retry |
| No YAML and no Jira URL | 3 | Provide Jira URL or run from master pipeline |
| YAML attachment missing on Jira | 3b | Run `/create-component-onboarding-jira <jira-url>` first |
| `target_rhoai_version` missing/invalid | 4 | Fix field in YAML and re-upload to Jira |
| Delivery repo already exists | 5 | Expected — exits 0; Jira labelled `delivery-repo-exists` |
| Open MR already found in Jira comments | 6 | Expected — jumps to Step 11 to monitor |
| Push fails (shallow update) | 7, 9 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| MR creation fails 3× | 10 | Check GITLAB_TOKEN scopes; ensure VPN active |
| MR closed without merge | 11 | Review MR manually; re-run skill |
| Pipeline failed | 11 | Skill attempts auto-fix and retries monitor once |
| MR monitoring timeout (60 min) | 11 | MR still open; re-run to resume monitoring |
