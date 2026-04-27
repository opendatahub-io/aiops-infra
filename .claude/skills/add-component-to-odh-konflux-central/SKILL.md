---
name: add-component-to-odh-konflux-central
description: Onboards a new ODH/RHOAI component onto the Konflux CI platform by adding PipelineRun YAMLs and updating the onboarder workflow in the odh-konflux-central GitHub repository and raising a pull request. Automates Step 4 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Add Component to ODH Konflux Central

Generates Tekton `PipelineRun` YAMLs for push and pull-request events from the OKC templates,
adds the component's GitHub repo to the onboarder workflow's component list, and raises a GitHub
PR to `odh-konflux-central`. When merged, Konflux CI will start building the component.

## Prerequisites

- `GITHUB_USER` — your GitHub username
- `GITHUB_TOKEN` — GitHub personal access token with `repo` scope
- `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — Atlassian credentials
- Optional: `ODH_KONFLUX_CENTRAL_REPO_URL` (default: `https://github.com/opendatahub-io/odh-konflux-central.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Tools: `uv`, `git`

## Usage

```
/add-component-to-odh-konflux-central <jira-url>
```

Example:
```
/add-component-to-odh-konflux-central https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_add_component_to_odh_konflux_central.sh" "$ARGUMENTS"
```
