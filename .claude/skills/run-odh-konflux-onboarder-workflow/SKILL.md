---
name: run-odh-konflux-onboarder-workflow
description: Triggers the odh-konflux-onboarder GitHub Actions workflow in odh-konflux-central, monitors it to completion, extracts the Tekton PR URL from workflow logs, and updates the Jira issue. Automates Step 6 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Run ODH Konflux Onboarder Workflow

Triggers the `odh-konflux-onboarder` GitHub Actions workflow in `odh-konflux-central`, monitors
it to completion, extracts the Tekton PR URL from the workflow logs, and optionally updates the
Jira issue with progress labels and comments.

## Prerequisites

- `GITHUB_USER` — your GitHub username
- `GITHUB_TOKEN` — GitHub personal access token with `repo` + `workflow` scopes
- Optional: `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — required only when Jira URL is provided
- Optional: `ODH_KONFLUX_CENTRAL_REPO_URL` (default: `https://github.com/opendatahub-io/odh-konflux-central.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Tools: `uv`, `git`

## Usage

```
/run-odh-konflux-onboarder-workflow [<jira-url>]
```

Examples:
```
/run-odh-konflux-onboarder-workflow
/run-odh-konflux-onboarder-workflow https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_run_odh_konflux_onboarder_workflow.sh" "${ARGUMENTS:-}"
```
