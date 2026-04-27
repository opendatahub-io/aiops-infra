---
name: validate-component-onboarding-jira
description: Pre-flight validation tool for ODH component onboarding. Given a Jira issue URL, fetches issue details, downloads the component_onboarding_details.yaml attachment, and validates it against the JSON Schema. Use before invoking the full onboarding automation to confirm a ticket is correctly set up.
allowed-tools: Bash
user-invocable: true
---

# Validate Component Onboarding Jira

Pre-flight validation for ODH/RHOAI component onboarding. Given a Jira issue URL, fetches the
issue details, downloads the `component_onboarding_details.yaml` attachment, and validates it
against the JSON schema. Any failure is a hard blocker — the script exits with a clear error.

## Prerequisites

- `JIRA_USER_EMAIL` — your Atlassian account email
- `JIRA_API_TOKEN` — Atlassian Cloud API token (create at https://id.atlassian.com/manage-profile/security/api-tokens)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Tools: `uv`

## Usage

```
/validate-component-onboarding-jira <jira-url>
```

Example:
```
/validate-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_validate_component_onboarding_jira.sh" "$ARGUMENTS"
```
