---
name: validate-component-offboarding-jira
description: Pre-flight validation tool for ODH/RHOAI component offboarding. Given a Jira issue URL, fetches issue details, downloads the component_offboarding_details.yaml attachment, and validates it against the JSON Schema. Use before invoking the full offboarding automation.
allowed-tools: Bash
user-invocable: true
---

# Validate Component Offboarding Jira

Pre-flight validation for ODH/RHOAI component offboarding. Given a Jira issue URL, this skill:
1. Fetches all details of the Jira issue and saves them as JSON
2. Downloads the `component_offboarding_details.yaml` attachment from the issue
3. Validates the YAML against the `component_offboarding_details.schema.json` schema

RHOAI tickets must include `target_rhoai_version` (canonical form, e.g. `3.4` or `3.4-ea-2`).
ODH tickets must include `build_type` (`CI` or `Release`).

Any failure is a hard blocker. The skill exits with a clear error message.

## Prerequisites

- `uv` must be installed and in PATH
- `JIRA_USER_EMAIL` environment variable must be set
- `JIRA_API_TOKEN` environment variable must be set
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

## Usage

```
/validate-component-offboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```

The user may also say "validate RHOAIENG-1234" or paste the URL. If only a key is given,
construct the URL: `https://redhat.atlassian.net/browse/RHOAIENG-1234`.

## Implementation

## Locate Scripts Directory

```bash
SCRIPTS_DIR="${AIOPS_INFRA_DIR:-/tmp/aiops-infra}/scripts"
if [[ ! -d "$SCRIPTS_DIR" ]]; then
  echo "ERROR: scripts directory not found at $SCRIPTS_DIR"
  echo "  Set AIOPS_INFRA_DIR to the root of the aiops-infra checkout."
  exit 1
fi
```

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

If not set, stop.

### Step 2: Create working directory

Extract the issue ID from the URL.

```bash
eval "$(bash "$SCRIPTS_DIR/init_workdir.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
```

### Step 3: Fetch Jira issue details

```bash
(cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$JIRA_URL")
```

On success: `component_offboarding_details.json` is created in $WORKDIR.
On failure (exit code 1): display stderr, attempt best-effort Jira update, then stop:

```bash
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboarding-validation-failed" \
  --remove-label "offboarding-validation-successful" \
  --comment "Offboarding validation failed at Step 1 (Fetch Jira Details).

Could not fetch issue details." 2>/dev/null || true
```

Then stop with: `"ERROR in Step 1 (Fetch Jira Details): <message>. Aborting."`

### Step 4: Download YAML attachment

```bash
(cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/download_jira_attachment.py" "$JIRA_URL" component_offboarding_details.yaml)
```

On success: `component_offboarding_details.yaml` is created in $WORKDIR.
On failure: display stderr, update Jira, then stop:

```bash
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboarding-validation-failed" \
  --remove-label "offboarding-validation-successful" \
  --comment "Offboarding validation failed at Step 2 (Download Attachment).

The required attachment 'component_offboarding_details.yaml' was not found.

Please attach a valid 'component_offboarding_details.yaml' file and re-run /validate-component-offboarding-jira."
```

### Step 5: Validate YAML against schema

```bash
uv run --script "$SCRIPTS_DIR/validate_yaml_schema.py" \
  "$WORKDIR/component_offboarding_details.yaml" \
  "${AIOPS_INFRA_DIR:-/tmp/aiops-infra}/schemas/component_offboarding_details.schema.json"
```

On success (exit 0): print "Validation passed."
On failure (exit 1): capture stderr as `<validation_errors>`, display, update Jira, then stop:

```bash
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboarding-validation-failed" \
  --remove-label "offboarding-validation-successful" \
  --comment "Offboarding validation failed at Step 3 (Schema Validation).

Errors found:
<validation_errors>

Please fix the YAML, re-upload it, and re-run /validate-component-offboarding-jira."
```

### Step 6: Update Jira on success and report

Check whether the `offboarding-validation-successful` label is already present:

```bash
ALREADY_VALIDATED=$(jq -r '[.fields.labels[] | select(. == "offboarding-validation-successful")] | length > 0' \
  "$WORKDIR/component_offboarding_details.json")
```

If `ALREADY_VALIDATED == "true"`, skip comment — just update labels and status:

```bash
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboarding-validation-successful" \
  --remove-label "offboarding-validation-failed" \
  --status "In Progress"
```

Otherwise, post success comment:

```bash
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "offboarding-validation-successful" \
  --remove-label "offboarding-validation-failed" \
  --comment "Offboarding validation passed for <issue_id>.

All pre-flight checks completed successfully:
- Jira issue details fetched
- component_offboarding_details.yaml attachment downloaded
- Schema validation passed

This ticket is ready for offboarding automation. Moving to In Progress." \
  --status "In Progress"
```

Then print:

```
Validation complete for <issue_id>.

  component_offboarding_details.json — Jira issue details saved
  component_offboarding_details.yaml — Attachment downloaded
  Schema validation                  — PASSED
  Jira issue updated                 — label: offboarding-validation-successful, status: In Progress

The Jira ticket is valid and ready for offboarding automation.
Output files are in: ./<issue_id>/
```

## Error reference

| Error | Message |
|-------|---------|
| JIRA_USER_EMAIL not set | Export the env var |
| JIRA_API_TOKEN not set | Create token and export |
| Issue not found / no access | Check credentials and issue key |
| Attachment not found | Attach component_offboarding_details.yaml to the ticket |
| YAML fails schema | Fix errors and re-upload |
| uv not installed | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
