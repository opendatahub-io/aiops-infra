---
name: integrate-component-with-odh-operator
description: Updates the opendatahub-operator repository to include a new operator component in build/manifests-config.yaml and raises a GitHub PR. Exits cleanly (no-op) when is_operator=false. Automates Step 9 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Integrate Component with ODH Operator

Adds a new operator component to `opendatahub-operator` by inserting an entry into
`build/manifests-config.yaml` and raising a GitHub PR. Exits cleanly with a Jira comment when
`is_operator: false` — no changes are made to the operator repo.

## Prerequisites

- `GITHUB_USER` — your GitHub username
- `GITHUB_TOKEN` — GitHub personal access token with `repo` scope
- `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — Atlassian credentials
- Optional: `ODH_OPERATOR_REPO_URL` (default: `https://github.com/opendatahub-io/opendatahub-operator.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Tools: `uv`, `git`

## Usage

```
/integrate-component-with-odh-operator <jira-url>
```

Example:
```
/integrate-component-with-odh-operator https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_integrate_component_with_odh_operator.sh" "$ARGUMENTS"
```
