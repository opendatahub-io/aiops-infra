---
name: add-rhoai-dockerfile-labels
description: Checks a component Dockerfile for mandatory RHOAI labels (name, com.redhat.component, summary, description, maintainer, io.k8s.display-name, io.k8s.description). If any are missing or incorrect, clones the component repo, adds the labels, and raises a GitHub PR. Updates the Jira ticket throughout.
allowed-tools: Bash
user-invocable: true
---

# Add RHOAI Dockerfile Labels

Ensures a component Dockerfile contains all mandatory RHOAI OCI labels. Given a Jira issue URL,
this skill:
1. Reads `component_onboarding_details.yaml` from the Jira ticket (or from pipeline state).
2. Fetches the Dockerfile via the GitHub API and checks all 7 mandatory labels.
3. If all labels are correct, exits cleanly with a Jira update.
4. If any labels are missing or wrong, clones the repo, adds them, commits, pushes, and raises a PR.

## Mandatory labels

| Label key | Expected value |
|-----------|----------------|
| `name` | `rhoai/<component_name>-rhel9` |
| `com.redhat.component` | `<component_name>-rhel9` |
| `summary` | `<component_name>` |
| `description` | `<component_name>` |
| `maintainer` | `<component_name>` |
| `io.k8s.display-name` | `<component_name>` |
| `io.k8s.description` | `<component_name>` |

## Prerequisites

- `GITHUB_USER` — GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — personal access token with `repo` scope and push access to the component repo
- `JIRA_USER_EMAIL` — your Atlassian account email (required when a Jira URL is provided)
- `JIRA_API_TOKEN` — Atlassian API token (required when a Jira URL is provided)
  - Create at: https://id.atlassian.com/manage-profile/security/api-tokens
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `git`
- `curl`
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**Jira attachment:** The Jira issue must have `component_onboarding_details.yaml` attached
(created by `/create-component-onboarding-jira`), unless this skill is invoked from the master
onboarding pipeline (which places the YAML in the working directory automatically).

## Usage

```
/add-rhoai-dockerfile-labels [<jira-url>]
```

Examples:
```
/add-rhoai-dockerfile-labels https://redhat.atlassian.net/browse/RHOAIENG-1234
/add-rhoai-dockerfile-labels
```

## Implementation

---

## Step 0: Parse Inputs

```bash
eval "$(bash "scripts/parse_jira_url.sh" "${1:-}")"
echo "JIRA_URL : ${JIRA_URL:-(not provided)}"
echo "JIRA_ID  : ${JIRA_ID:-(not provided)}"
```

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
bash "scripts/check_prerequisites.sh" \
  --env "GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git curl"
```

Required only when `JIRA_URL` is non-empty:
```bash
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

**3d. Fetch Jira issue details** (skip if `$WORKDIR/component_onboarding_details.json` already
exists; only when `JIRA_URL` is non-empty):
```bash
cd "$WORKDIR"
uv run --script scripts/fetch_jira_details.py "$JIRA_URL"
```

On exit 1: display stderr and stop:
```
ERROR in Step 3d (Fetch Jira): Could not fetch issue details. Aborting.
```

---

## Step 4: Parse YAML and Derive Variables

Extract from `$WORKDIR/component_onboarding_details.yaml` (all under the `inputs:` key):

```bash
eval "$(bash "scripts/parse_component_details.sh" \
  --workdir     "$WORKDIR" \
  --jira-id     "$JIRA_ID" \
  --scripts-dir "scripts")"
# Sets: COMPONENT_NAME, REPO_URL, REPO_BRANCH, PRODUCT_CONTEXT, QUAY_ORG, QUAY_VISIBILITY, QUAY_REPO_URI, IS_OPERATOR

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
CONTEXT_PATH=$(grep -m1   'context_path:'     "$YAML_FILE" | awk '{print $2}')
DOCKERFILE_PATH=$(grep -m1 'dockerfile_path:' "$YAML_FILE" | awk '{print $2}')

for _field in CONTEXT_PATH DOCKERFILE_PATH; do
  [[ -z "${!_field}" ]] && {
    echo "ERROR in Step 4: Missing required field '${_field}' in component_onboarding_details.yaml."
    echo "  Re-generate the YAML with /create-component-onboarding-jira <jira-url>."
    exit 1
  }
done
```

Derive:
```bash
# DOCKERFILE_REPO_PATH — path to Dockerfile relative to repo root
CLEAN_CTX="${CONTEXT_PATH#./}"          # strip leading "./"
if [[ -z "$CLEAN_CTX" || "$CLEAN_CTX" == "." ]]; then
  DOCKERFILE_REPO_PATH="$DOCKERFILE_PATH"
else
  DOCKERFILE_REPO_PATH="${CLEAN_CTX}/${DOCKERFILE_PATH}"
fi
# Examples: "Dockerfile", "maas-api/Dockerfile.konflux"

# GitHub API path (owner/repo, no .git suffix)
REPO_PATH=$(echo "$REPO_URL" | sed 's|https://github.com/||;s|\.git$||')
# e.g. "rhoai-rhtap/odh-ai-first-demo"

# Expected label values
LABEL_NAME="rhoai/${COMPONENT_NAME}-rhel9"
LABEL_COMPONENT="${COMPONENT_NAME}-rhel9"
LABEL_DEFAULT="$COMPONENT_NAME"
```

Print resolved values:
```
COMPONENT_NAME       : $COMPONENT_NAME
REPO_URL             : $REPO_URL
DOCKERFILE_REPO_PATH : $DOCKERFILE_REPO_PATH
Expected labels:
  name                 = $LABEL_NAME
  com.redhat.component = $LABEL_COMPONENT
  summary              = $LABEL_DEFAULT
  description          = $LABEL_DEFAULT
  maintainer           = $LABEL_DEFAULT
  io.k8s.display-name  = $LABEL_DEFAULT
  io.k8s.description   = $LABEL_DEFAULT
```

---

## Step 5: Fast-Path Label Check (GitHub API)

Fetch the raw Dockerfile content from GitHub before cloning:

```bash
DOCKERFILE_TMPFILE=$(mktemp)
HTTP_STATUS=$(curl -s -w "%{http_code}" \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3.raw" \
  "https://api.github.com/repos/${REPO_PATH}/contents/${DOCKERFILE_REPO_PATH}?ref=main" \
  -o "$DOCKERFILE_TMPFILE")
```

**If `HTTP_STATUS != 200`:** warn and skip fast-path (continue to Step 6):
```
WARN in Step 5: Could not fetch Dockerfile via GitHub API (HTTP $HTTP_STATUS).
  Continuing with clone.
```
Clean up: `rm -f "$DOCKERFILE_TMPFILE"`

**If `HTTP_STATUS == 200`:** parse all `LABEL` instructions in the file.

A label is "present and correct" when:
- Its key appears in a `LABEL` instruction (accounting for multi-line `\` continuation), and
- Its value matches the expected string (exact match; ignore surrounding double-quotes).

Check all 7 mandatory labels. Accumulate `MISSING_LABELS` (those absent or with wrong values).

**If `MISSING_LABELS` is empty** (all labels correct):

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "dockerfile-labels-present" \
  --comment "All mandatory RHOAI Dockerfile labels are already present in ${DOCKERFILE_REPO_PATH}.

Labels verified:
  name                 = $LABEL_NAME
  com.redhat.component = $LABEL_COMPONENT
  summary              = $LABEL_DEFAULT
  description          = $LABEL_DEFAULT
  maintainer           = $LABEL_DEFAULT
  io.k8s.display-name  = $LABEL_DEFAULT
  io.k8s.description   = $LABEL_DEFAULT

No changes needed."
```

Print:
```
All 7 mandatory RHOAI labels are already correct in $DOCKERFILE_REPO_PATH.
Jira updated (label: dockerfile-labels-present). No PR needed.
```

**Stop with exit 0.**

**If labels are missing or wrong:** print which ones and continue to Step 6:
```
Missing/incorrect labels: <comma-separated list>
Proceeding to add them.
```

Clean up: `rm -f "$DOCKERFILE_TMPFILE"`

---

## Step 6: Set Up Playpen (Clone)

Run from inside `$WORKDIR`:

```bash
cd "$WORKDIR"

PLAYPEN_OUTPUT=$(bash scripts/setup_github_playpen.sh \
  --src-url "$REPO_URL" \
  --dest-url "$REPO_URL" \
  --src-branch main \
  ${JIRA_ID:+--dest-branch "component-onboarding-$JIRA_ID"} \
  --sparse-files "$DOCKERFILE_REPO_PATH")
```

Parse `PLAYPEN_OUTPUT` from stdout:
- Line 1 → `CLONE_DIR` (absolute path to the clone)
- Line 2 → `DEST_BRANCH` (the branch created and pushed)

On exit 1: display stderr and stop:
```
ERROR in Step 6 (Playpen setup): Clone or push failed. See details above.
  Check GITHUB_TOKEN has push access to $REPO_PATH.
```

If push fails with "shallow update not allowed":
```bash
cd "$CLONE_DIR"
git fetch --unshallow origin
git push origin "$DEST_BRANCH"
```

---

## Step 7: Add/Update Missing Labels in Dockerfile

Verify the file exists:
```bash
[[ -f "$CLONE_DIR/$DOCKERFILE_REPO_PATH" ]] || {
  echo "ERROR in Step 7: Dockerfile not found at $CLONE_DIR/$DOCKERFILE_REPO_PATH."
  echo "  Verify context_path and dockerfile_path in component_onboarding_details.yaml."
  exit 1
}
```

Apply and verify all 7 mandatory labels using the shared helper script:

```bash
uv run --script "scripts/update_dockerfile_labels.py" \
  "$CLONE_DIR/$DOCKERFILE_REPO_PATH" \
  --name      "$LABEL_NAME" \
  --component "$LABEL_COMPONENT" \
  --default   "$LABEL_DEFAULT"
```

The script appends missing/incorrect labels after the last `FROM` instruction and verifies all
7 mandatory labels are present with correct values before exiting. On failure it exits 1 with
an error message — stop and report the error if it does so.

Confirm the result with:
```bash
grep -q "name=\"${LABEL_NAME}\"" "$CLONE_DIR/$DOCKERFILE_REPO_PATH" || {
  echo "ERROR in Step 7: Verification failed — 'name' label not set correctly"; exit 1
}
echo "All mandatory RHOAI labels confirmed present in $DOCKERFILE_REPO_PATH."
```

---

## Step 8: Commit and Push

```bash
bash "scripts/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "$DOCKERFILE_REPO_PATH" \
  --message   "Add mandatory RHOAI Dockerfile labels for $COMPONENT_NAME

Adds the required OCI/Red Hat labels to $DOCKERFILE_REPO_PATH:
  name, com.redhat.component, summary, description,
  maintainer, io.k8s.display-name, io.k8s.description

Related: ${JIRA_ID:-no-jira}" \
  --branch    "$DEST_BRANCH"
```

---

## Step 9: Raise PR (up to 3 attempts)

```bash
PR_URL=$(uv run --script scripts/raise_github_pr.py \
  --src-url "$REPO_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$REPO_URL" \
  --dest-branch main \
  --title "Add mandatory RHOAI Dockerfile labels for $COMPONENT_NAME" \
  --description "Adds the seven mandatory RHOAI OCI labels to \`${DOCKERFILE_REPO_PATH}\`.

## Labels added / corrected

| Label | Value |
|-------|-------|
| \`name\` | \`${LABEL_NAME}\` |
| \`com.redhat.component\` | \`${LABEL_COMPONENT}\` |
| \`summary\` | \`${LABEL_DEFAULT}\` |
| \`description\` | \`${LABEL_DEFAULT}\` |
| \`maintainer\` | \`${LABEL_DEFAULT}\` |
| \`io.k8s.display-name\` | \`${LABEL_DEFAULT}\` |
| \`io.k8s.description\` | \`${LABEL_DEFAULT}\` |

**File changed:** \`${DOCKERFILE_REPO_PATH}\`
**Component repo:** ${REPO_URL}
**Jira:** ${JIRA_URL:-(none)}")
```

On failure:
- "Branch not found" → re-push the branch (`git push origin "$DEST_BRANCH"`) and retry.
- "Connection error" → notify user to check network, retry.
- Any other error → retry.

After 3 failures, stop:
```
ERROR in Step 9 (Raise PR): Could not create PR after 3 attempts. See errors above. Aborting.
```

On success: update Jira (only when `JIRA_URL` is non-empty):
```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "dockerfile-labels-pr-raised" \
  --comment "GitHub PR raised to add mandatory RHOAI Dockerfile labels for '$COMPONENT_NAME'.

PR URL: $PR_URL

File changed: $DOCKERFILE_REPO_PATH
Labels added/corrected: name, com.redhat.component, summary, description,
                        maintainer, io.k8s.display-name, io.k8s.description

Review and merge the PR to complete this step."
```

---

## Step 10: Report Completion

Print:
```
Done.

  Dockerfile           : $DOCKERFILE_REPO_PATH
  Labels added         : name, com.redhat.component, summary, description,
                         maintainer, io.k8s.display-name, io.k8s.description
  GitHub PR            : $PR_URL
  Jira                 : ${JIRA_ID:-(none)} — label: dockerfile-labels-pr-raised

Next step: review and merge the PR.
```

---

## Error Reference

| Error | Step | Action |
|-------|------|--------|
| `GITHUB_USER` not set | 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | 1 | `export GITHUB_TOKEN=yourtoken` (needs `repo` scope + push) |
| `JIRA_USER_EMAIL` not set | 1 | `export JIRA_USER_EMAIL=you@example.com` |
| `JIRA_API_TOKEN` not set | 1 | `export JIRA_API_TOKEN=your-api-token` |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| No YAML and no Jira URL | 3 | Provide a Jira URL or run from master pipeline |
| `component_onboarding_details.yaml` not on Jira | 3b | Run `/create-component-onboarding-jira <jira-url>` first |
| Missing required YAML field | 4 | Regenerate YAML with `/create-component-onboarding-jira` |
| All labels already correct | 5 | Expected — exits 0; Jira labelled `dockerfile-labels-present` |
| Dockerfile not found in clone | 7 | Verify `context_path` and `dockerfile_path` in YAML |
| Push fails (shallow update) | 6, 8 | `git fetch --unshallow origin && git push origin "$DEST_BRANCH"` |
| PR creation fails 3× | 9 | Check GITHUB_TOKEN push access; verify branch was pushed |
