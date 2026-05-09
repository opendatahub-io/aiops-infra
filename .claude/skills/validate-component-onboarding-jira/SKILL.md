---
name: validate-component-onboarding-jira
description: Pre-flight validation tool for ODH component onboarding. Given a Jira issue URL, fetches issue details, downloads the component_onboarding_details.yaml attachment, and validates it against the JSON Schema. Use before invoking the full onboarding automation to confirm a ticket is correctly set up.
allowed-tools: Bash
user-invocable: true
---

# Validate Component Onboarding Jira

Pre-flight validation for ODH component onboarding. Given a Jira issue URL, this skill:
1. Fetches all details of the Jira issue and saves them as JSON
2. Downloads the `component_onboarding_details.yaml` attachment from the issue
3. Validates the YAML against the `component_onboarding_details.schema.json` schema in the skill assets

RHOAI tickets must include `architectures`, `target_rhoai_version` (canonical form, e.g. `3.4` or `3.4-ea-2`), and `release_category` (`Generally Available`, `Tech Preview`, or `Beta`) in addition to the common required fields. ODH tickets must include `build_type`.

Any failure is a hard blocker. The skill exits with a clear error message.

## Prerequisites

- `uv` must be installed and in PATH
- `JIRA_USER_EMAIL` environment variable must be set to your Atlassian account email
  - Set: `export JIRA_USER_EMAIL='you@example.com'`
- `JIRA_API_TOKEN` environment variable must be set with an Atlassian Cloud API token
  - Create at: https://id.atlassian.com/manage-profile/security/api-tokens
  - Set: `export JIRA_API_TOKEN='your-api-token-here'`
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)



## Usage

```
/validate-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```

The user may also say "validate RHOAIENG-1234" or paste the URL. If only a key is given (e.g., `RHOAIENG-1234`), construct the URL: `https://redhat.atlassian.net/browse/RHOAIENG-1234`.

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts` (i.e., the `common/scripts` directory next to this skill).

## Step 0: Check prerequisites

Check if `JIRA_USER_EMAIL`, `JIRA_SERVER`, and `JIRA_API_TOKEN` environment variables are set.
If `JIRA_SERVER` is not set then set the default value as https://redhat.atlassian.net
If `JIRA_USER_EMAIL` or `JIRA_API_TOKEN` is not set, tell the user:

> It requires Jira API credentials to be set to validate the jira. Set the environment variables:
> ```
> export JIRA_USER_EMAIL=you@example.com
> export JIRA_API_TOKEN=your-api-token
> export JIRA_SERVER=https://your-site.atlassian.net  # optional
> ```
> To create an Atlassian Cloud API token, go to https://id.atlassian.com/manage-profile/security/api-tokens
>
> After environment variables are set, re-run `/validate-component-onboarding-jira`.

If not set, tell the user and stop.

### Step 2: Create working directory

Extract the issue ID from the URL — the last non-empty path segment.
For `https://redhat.atlassian.net/browse/RHOAIENG-1234`, the issue ID is `RHOAIENG-1234`.

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_workdir.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
```

### Step 3: Fetch Jira issue details

Run from inside the working directory so the output file lands there:

```bash
(cd <absolute_path>/<issue_id> && uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py <jira_url>)
```

On success: `<issue_id>/component_onboarding_details.json` is created.
On failure (exit code 1): display the script's stderr, then attempt a best-effort Jira update (it may also fail if credentials are the root cause — suppress any error from the update call), then stop:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Validation failed at Step 1 (Fetch Jira Details).

Could not fetch issue details. This is typically caused by:
- An invalid or expired JIRA_API_TOKEN
- An incorrect issue key
- A network or permissions issue

Please check your credentials and issue key, then re-run /validate-component-onboarding-jira." 2>/dev/null || true
```

Then stop with: `"ERROR in Step 1 (Fetch Jira Details): <message>. Aborting."`

### Step 4: Download YAML attachment

Run from inside the working directory:

```bash
(cd <absolute_path>/<issue_id> && uv run --script <COMMON_SCRIPTS_DIR>/download_jira_attachment.py <jira_url> component_onboarding_details.yaml)
```

On success: `<issue_id>/component_onboarding_details.yaml` is created.
On failure (exit code 1): display stderr, update the Jira issue, then stop:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Validation failed at Step 2 (Download Attachment).

The required attachment 'component_onboarding_details.yaml' was not found on this issue.

Please attach a valid 'component_onboarding_details.yaml' file to this ticket and re-run /validate-component-onboarding-jira."
```

Then stop with: `"ERROR in Step 2 (Download Attachment): <message>. Aborting."`

### Step 5: Validate YAML against schema

```bash
uv run --script <COMMON_SCRIPTS_DIR>/validate_yaml_schema.py \
  <absolute_path>/<issue_id>/component_onboarding_details.yaml \
  <SKILL_DIR>/assets/component_onboarding_details.schema.json
```

On success (exit code 0): print "Validation passed." and continue to the branch check below.
On failure (exit code 1): capture all stderr output as `<validation_errors>`, display them, update the Jira issue with the specific errors, then stop:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Validation failed at Step 3 (Schema Validation).

The 'component_onboarding_details.yaml' attachment did not pass schema validation.

Errors found:
<validation_errors>

Please fix the YAML, re-upload it as an attachment to this ticket, and re-run /validate-component-onboarding-jira."
```

Then stop with: `"ERROR in Step 3 (Schema Validation): The YAML failed validation. See errors above. Aborting."`

#### Step 5b: Cross-validate repo_branch for RHOAI

Read `inputs.product_context` and `inputs.repo_branch` from the downloaded YAML.

If `product_context == "RHOAI"`:
- Read `inputs.target_rhoai_version` (canonical form, e.g. `3.5` or `3.5-ea-1`).
- Derive the expected branch:
  - If no EA suffix: `expected_branch = "rhoai-<VERSION_X>.<VERSION_Y>"` (e.g. `rhoai-3.5`)
  - If EA suffix present (format `<x>.<y>-ea-<n>`): `expected_branch = "rhoai-<VERSION_X>.<VERSION_Y>-ea.<VERSION_N>"` (e.g. `rhoai-3.5-ea.1`)
- If `repo_branch != expected_branch`, update Jira and stop:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Validation failed at Step 3b (Branch Cross-Validation).

For RHOAI components, repo_branch must match the target version.
  target_rhoai_version : <target_rhoai_version>
  expected repo_branch : <expected_branch>
  actual repo_branch   : <repo_branch>

Please correct repo_branch in the YAML, re-upload it, and re-run /validate-component-onboarding-jira."
```

Then stop with: `"ERROR in Step 3b (Branch Cross-Validation): repo_branch '<repo_branch>' does not match expected '<expected_branch>'. Aborting."`

### Step 5c: Dockerfile digest check

**Skip this entire step if `inputs.product_context == "ODH"`.** Digest pinning is only
required for RHOAI components. If ODH, print:
```
Dockerfile digest check skipped (not required for ODH components).
```
and proceed to Step 6.

Read `inputs.repo_url`, `inputs.repo_branch`, `inputs.context_path`, and
`inputs.dockerfile_path` from the downloaded YAML.

Construct the raw GitHub URL:

```bash
REPO_RAW_BASE="${repo_url/github.com/raw.githubusercontent.com}"
CLEAN_CTX="${context_path%/}"; CLEAN_CTX="${CLEAN_CTX#./}"
if [[ -z "$CLEAN_CTX" || "$CLEAN_CTX" == "." ]]; then
  DOCKERFILE_RAW_URL="${REPO_RAW_BASE}/${repo_branch}/${dockerfile_path}"
else
  DOCKERFILE_RAW_URL="${REPO_RAW_BASE}/${repo_branch}/${CLEAN_CTX}/${dockerfile_path}"
fi

uv run --script <COMMON_SCRIPTS_DIR>/check_dockerfile_digests.py \
  --dockerfile-url "$DOCKERFILE_RAW_URL"
```

On **exit 0**: print `Dockerfile digest check passed.` and continue.

On **exit 2** (Dockerfile not reachable): update Jira and stop:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Validation failed at Step 5c (Dockerfile Digest Check).

Could not fetch the Dockerfile at:
  $DOCKERFILE_RAW_URL

Ensure the repo_url, repo_branch, context_path, and dockerfile_path in the YAML are correct
and that the Dockerfile exists on the specified branch."
```

Then stop with: `ERROR in Step 5c (Dockerfile Digest Check): Could not fetch Dockerfile. Aborting.`

On **exit 1** (digest violations found): capture stderr as `<digest_errors>`, update Jira and stop:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Validation failed at Step 5c (Dockerfile Digest Check).

The Dockerfile at $DOCKERFILE_RAW_URL contains FROM instructions that do not pin images
with @sha256 digests:

<digest_errors>

All base and builder images must be pinned using SHA digests, not tags alone.
Example: FROM registry.access.redhat.com/ubi9/ubi-minimal@sha256:<hex>

Please update the Dockerfile and re-run /validate-component-onboarding-jira."
```

Then stop with: `ERROR in Step 5c (Dockerfile Digest Check): FROM instructions without @sha256 digests found. Aborting.`

---

### Step 6: Update Jira on success and report

Check whether the `validation-successful` label is already present on the issue
(from the JSON fetched in Step 3):

```bash
ALREADY_VALIDATED=$(jq -r '[.fields.labels[] | select(. == "validation-successful")] | length > 0' \
  "$WORKDIR/component_onboarding_details.json")
```

If `ALREADY_VALIDATED == "true"`, skip the comment — just update labels and status silently:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-successful" \
  --remove-label "validation-failed" \
  --status "In Progress"
```

If `ALREADY_VALIDATED != "true"`, post the full success comment:

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py <jira_url> \
  --add-label "validation-successful" \
  --remove-label "validation-failed" \
  --comment "Validation passed for <issue_id>.

All pre-flight checks completed successfully:
- Jira issue details fetched
- component_onboarding_details.yaml attachment downloaded
- Schema validation passed

This ticket is ready for onboarding automation. Moving to In Progress." \
  --status "In Progress"
```

Then print:

```
Validation complete for <issue_id>.

  component_onboarding_details.json  — Jira issue details saved
  component_onboarding_details.yaml  — Attachment downloaded
  Schema validation            — PASSED
  Jira issue updated           — label: validation-successful, status: In Progress

The Jira ticket is valid and ready for onboarding automation.
Output files are in: ./<issue_id>/
```

## Error reference

| Error | Message |
|-------|---------|
| JIRA_USER_EMAIL not set | "JIRA_USER_EMAIL is not set. Set it to your Atlassian account email: export JIRA_USER_EMAIL='you@example.com'." |
| JIRA_API_TOKEN not set | "JIRA_API_TOKEN is not set. Create an API token at https://id.atlassian.com/manage-profile/security/api-tokens, then export JIRA_API_TOKEN='your-token'." |
| Issue not found / no access | Script 1 exits 1; display its stderr |
| Attachment not found | Script 2 exits 1; display its stderr (includes list of available attachments) |
| YAML fails schema | Script 3 exits 1; display all field-level errors from stderr |
| `repo_branch` / `target_rhoai_version` mismatch | Step 5b; correct the YAML and re-upload |
| Dockerfile not reachable (exit 2) | Step 5c; check repo_url, repo_branch, context_path, dockerfile_path |
| FROM instructions missing `@sha256` digest (exit 1) | Step 5c; update Dockerfile to pin all images with SHA digests |
| uv not installed | "uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" |
