---
name: onboard-component-to-konflux-release-data
description: Onboards a new ODH/RHOAI component onto the Konflux CI platform by raising a merge request to the konflux-release-data GitLab repo. Automates Step 3 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Onboard Component to Konflux Release Data

Creates Konflux `Component` resources for a new ODH/RHOAI component by appending a YAML document
to the appropriate tenant config file in the `konflux-release-data` GitLab repository and raising
a merge request. When the MR is merged, a GitOps pipeline provisions the Component on the Konflux
OpenShift cluster.

## Prerequisites

- `GITLAB_USER` — your GitLab username
- `GITLAB_TOKEN` — GitLab personal access token with `api` + `write_repository` scopes
- `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — Atlassian credentials
- Optional: `KRD_REPO_URL` (default: `https://gitlab.cee.redhat.com/rhoai/konflux-release-data`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Tools: `uv`, `git`, `yamllint`, `jq`, `kustomize`

## Usage

```
/onboard-component-to-konflux-release-data <jira-url>
```

Example:
```
/onboard-component-to-konflux-release-data https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_onboard_component_to_konflux_release_data.sh" "$ARGUMENTS"
```
