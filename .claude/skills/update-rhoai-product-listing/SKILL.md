---
name: update-rhoai-product-listing
description: Updates the RHOAI product listing in pyxis-repo-configs by appending the new component's registry path to product-listings/rhoai/rhoai.yaml and raising a GitLab MR. VPN required.
allowed-tools: Bash
user-invocable: true
---

# Update RHOAI Product Listing

Adds the new component's registry path to the RHOAI product listing in `pyxis-repo-configs`.
The entry is a single line in the `repositories:` array of `product-listings/rhoai/rhoai.yaml`.
This skill handles the full lifecycle:

1. Check if the entry already exists in `product-listings/rhoai/rhoai.yaml`
2. Clone `pyxis-repo-configs`, append the registry path, push, and raise an MR

## Usage

```
/update-rhoai-product-listing [<jira-url>]
```

Examples:
```
/update-rhoai-product-listing https://redhat.atlassian.net/browse/RHOAIENG-1234
/update-rhoai-product-listing
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

### Early-exit: `--existing-mr-url`

If the skill is invoked with `--existing-mr-url <url>`:
```
MR already raised: <url>
```
Exit 0 immediately. The orchestrator passes this flag when the MR URL is already recorded in
`pipeline_state.json`, so no further work is needed.

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
bash "scripts/check_prerequisites.sh" \
  --env "GITLAB_USER GITLAB_TOKEN" \
  --tools "uv git curl"

if [[ -n "$JIRA_URL" ]]; then
  bash "scripts/check_prerequisites.sh" \
    --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi
```

---

## Step 2: Set Up Working Directory

```bash
eval "$(bash "scripts/init_workdir.sh" --jira-url "${JIRA_URL:-}")"
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
uv run --script scripts/download_jira_attachment.py \
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

**3d. Fetch Jira issue details** (only when `JIRA_URL` is non-empty and
`$WORKDIR/component_onboarding_details.json` does not yet exist):
```bash
if [[ -n "$JIRA_URL" && ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  cd "$WORKDIR"
  uv run --script scripts/fetch_jira_details.py "$JIRA_URL"
fi
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

[[ -z "$COMPONENT_NAME" ]] && {
  echo "ERROR in Step 4: Missing required field 'component_name' in component_onboarding_details.yaml."
  echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
  exit 1
}

# The registry path to add to the product listing
PRODUCT_LISTING_ENTRY="registry.access.redhat.com/rhoai/${COMPONENT_NAME}-rhel9"
```

Print resolved values:
```
COMPONENT_NAME        : $COMPONENT_NAME
PRODUCT_LISTING_ENTRY : $PRODUCT_LISTING_ENTRY
PYXIS_URL             : $PYXIS_URL
```

---

## Step 5: Fast-Path Check — Does Product Listing Entry Already Exist?

Fetch `product-listings/rhoai/rhoai.yaml` from the main branch via the GitLab API:

```bash
RHOAI_YAML_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -sk -w "%{http_code}" \
  -H "Authorization: Bearer $GITLAB_TOKEN" \
  "https://gitlab.cee.redhat.com/api/v4/projects/${PYXIS_PATH_ENCODED}/repository/files/product-listings%2Frhoai%2Frhoai.yaml/raw?ref=main" \
  -o "$RHOAI_YAML_TMPFILE")
```

**If `HTTP_STATUS != 200`:** warn and skip fast-path (continue to Step 7):
```
WARN in Step 5: Could not fetch product-listings/rhoai/rhoai.yaml via GitLab API (HTTP $HTTP_STATUS).
  Ensure VPN is active. Continuing with clone.
```
Clean up: `rm -f "$RHOAI_YAML_TMPFILE"`

**If `HTTP_STATUS == 200`:** check whether the entry already exists:
```bash
if grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML_TMPFILE"; then
  ENTRY_EXISTS=true
else
  ENTRY_EXISTS=false
fi
rm -f "$RHOAI_YAML_TMPFILE"
```

If `ENTRY_EXISTS=true`:
```bash
if [[ -n "$JIRA_URL" ]]; then
  uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
    --add-label "product-listing-exists" \
    --comment "Product listing entry '${PRODUCT_LISTING_ENTRY}' already exists in pyxis-repo-configs.

No changes needed. The entry is already present in product-listings/rhoai/rhoai.yaml on the main branch."
fi
```
Print:
```
Product listing entry '$PRODUCT_LISTING_ENTRY' already exists in product-listings/rhoai/rhoai.yaml.
Jira updated (label: product-listing-exists). No MR needed.
```
**Stop with exit 0.**

If `ENTRY_EXISTS=false`: continue to Step 7.

---

## Step 7: Set Up GitLab Playpen (Clone)

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash scripts/setup_gitlab_playpen.sh \
  --src-url "$PYXIS_URL" \
  --dest-url "$PYXIS_URL" \
  --src-branch main \
  ${JIRA_ID:+--dest-branch "component-onboarding-$JIRA_ID"} \
  --sparse-files "product-listings/rhoai/rhoai.yaml")

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

## Step 8: Add Entry to product-listings/rhoai/rhoai.yaml

```bash
RHOAI_YAML="$CLONE_DIR/product-listings/rhoai/rhoai.yaml"
[[ -f "$RHOAI_YAML" ]] || {
  echo "ERROR in Step 8: product-listings/rhoai/rhoai.yaml not found in $CLONE_DIR."
  echo "  Verify PYXIS_URL points to the correct pyxis-repo-configs repository."
  exit 1
}

if grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML"; then
  echo "'$PRODUCT_LISTING_ENTRY' already present in product-listings/rhoai/rhoai.yaml — skipping edit."
else
  python3 "scripts/append_yaml_list_entry.py" "$RHOAI_YAML" \
    --list-key "repositories" \
    --value "$PRODUCT_LISTING_ENTRY" || {
    echo "ERROR in Step 8: Could not append entry to product-listings/rhoai/rhoai.yaml. See details above. Aborting."
    exit 1
  }

  grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML" || {
    echo "ERROR in Step 8: Verification failed — '$PRODUCT_LISTING_ENTRY' not found after append."
    exit 1
  }
  echo "Entry '$PRODUCT_LISTING_ENTRY' added to product-listings/rhoai/rhoai.yaml."
fi
```

---

## Step 9: Commit and Push

```bash
bash "scripts/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "product-listings/rhoai/rhoai.yaml" \
  --message   "Add ${COMPONENT_NAME} to RHOAI product listing

Adds registry path to product-listings/rhoai/rhoai.yaml:
  ${PRODUCT_LISTING_ENTRY}

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
MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script scripts/raise_gitlab_mr.py \
  --src-url "$PYXIS_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$PYXIS_URL" \
  --dest-branch main \
  --title "Add ${COMPONENT_NAME} to RHOAI product listing" \
  --description "Adds a new registry path entry to \`product-listings/rhoai/rhoai.yaml\`.

## Entry details

| Field | Value |
|-------|-------|
| \`component_name\` | \`${COMPONENT_NAME}\` |
| \`registry_path\` | \`${PRODUCT_LISTING_ENTRY}\` |

**File changed:** \`product-listings/rhoai/rhoai.yaml\`
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
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "product-listing-mr-raised" \
  --comment "[step:product_listing] GitLab MR raised to add '${COMPONENT_NAME}' to the RHOAI product listing.

MR URL: $MR_URL

File changed: product-listings/rhoai/rhoai.yaml
Registry path: ${PRODUCT_LISTING_ENTRY}

The product listing entry will be active once the MR is merged."
```

---

## Step 11: Report Completion

Print:
```
Done.

  product-listings/rhoai/rhoai.yaml  — ${PRODUCT_LISTING_ENTRY} added
  GitLab MR                          : $MR_URL
  Jira                               : ${JIRA_ID:-(none)} — label: product-listing-mr-raised
```

Print the MR URL and exit 0.

---

## Error Reference

| Error | Step | Action |
|-------|------|--------|
| `GITLAB_USER` not set | 1 | `export GITLAB_USER=yourusername` |
| `GITLAB_TOKEN` not set | 1 | `export GITLAB_TOKEN=yourtoken` (needs `api` + `write_repository`) |
| `JIRA_USER_EMAIL` not set | 1 | `export JIRA_USER_EMAIL=you@example.com` |
| `JIRA_API_TOKEN` not set | 1 | `export JIRA_API_TOKEN=your-api-token` |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| VPN not active | 5, 7, 10 | Connect to Red Hat VPN then retry |
| No YAML and no Jira URL | 3 | Provide Jira URL or run from master pipeline |
| YAML attachment missing on Jira | 3b | Run `/create-component-onboarding-jira <jira-url>` first |
| `component_name` missing | 4 | Fix field in YAML and re-upload to Jira |
| Product listing entry already exists | 5 | Expected — exits 0; Jira labelled `product-listing-exists` |
| Push fails (shallow update) | 7, 9 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| MR creation fails 3× | 10 | Check GITLAB_TOKEN scopes; ensure VPN active |
