---
name: validate-component-onboarding-jira
description: Pre-flight validation tool for ODH component onboarding. Given a Jira issue URL, fetches issue details, downloads the odh_component_details.yaml attachment, and validates it against the JSON Schema. Use before invoking the full onboarding automation to confirm a ticket is correctly set up.
allowed-tools: Bash
user-invocable: true
---

# Validate Component Onboarding Jira

Pre-flight validation for ODH component onboarding. Given a Jira issue URL, this skill:
1. Fetches all details of the Jira issue and saves them as JSON
2. Downloads the `odh_component_details.yaml` attachment from the issue
3. Validates the YAML against the `odh_component_details.schema.json` schema in the skill assets

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
mkdir -p <issue_id>
echo "Working directory: $(pwd)/<issue_id>"
```

### Step 3: Fetch Jira issue details

Run from inside the working directory so the output file lands there:

```bash
(cd <absolute_path>/<issue_id> && uv run --script <SKILL_DIR>/scripts/fetch_jira_details.py <jira_url>)
```

On success: `<issue_id>/odh_component_details.json` is created.
On failure (exit code 1): display the script's stderr and stop:
`"ERROR in Step 1 (Fetch Jira Details): <message>. Aborting."`

### Step 4: Download YAML attachment

Run from inside the working directory:

```bash
(cd <absolute_path>/<issue_id> && uv run --script <SKILL_DIR>/scripts/download_jira_attachment.py <jira_url> odh_component_details.yaml)
```

On success: `<issue_id>/odh_component_details.yaml` is created.
On failure (exit code 1): display stderr and stop:
`"ERROR in Step 2 (Download Attachment): <message>. Aborting."`

### Step 5: Validate YAML against schema

```bash
uv run --script <SKILL_DIR>/scripts/validate_yaml_schema.py \
  <absolute_path>/<issue_id>/odh_component_details.yaml \
  <SKILL_DIR>/assets/odh_component_details.schema.json
```

On success (exit code 0): print "Validation passed."
On failure (exit code 1): display all errors from stderr and stop:
`"ERROR in Step 3 (Schema Validation): The YAML failed validation. See errors above. Aborting."`

### Step 6: Report success

```
Validation complete for <issue_id>.

  odh_component_details.json  — Jira issue details saved
  odh_component_details.yaml  — Attachment downloaded
  Schema validation            — PASSED

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
| uv not installed | "uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" |
