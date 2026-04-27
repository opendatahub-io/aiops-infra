---
name: create-component-onboarding-jira
description: Interactively collects ODH/RHOAI component onboarding parameters from the user, generates a validated component_onboarding_details.yaml, and (when a Jira URL is given) uploads it as an attachment to the ticket. Use this before running other onboarding skills.
allowed-tools: Bash
user-invocable: true
---

# Create Component Onboarding Jira

Interactively collects all parameters needed to onboard an ODH or RHOAI component onto the
Konflux CI/build platform, produces a validated `component_onboarding_details.yaml`, and attaches
it to the Jira ticket. When no Jira URL is provided and the product is ODH, a new Jira ticket is
cloned from the template and the YAML is attached automatically.

## Prerequisites

- Tools: `uv`, `jq`
- Optional: `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — required when a Jira URL is provided or a new ticket is being created
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

## Usage

```
/create-component-onboarding-jira [<jira-url>]
```

Examples:
```
/create-component-onboarding-jira
/create-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_create_component_onboarding_jira.sh" "${ARGUMENTS:-}"
```
