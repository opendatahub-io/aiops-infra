---
name: onboard-konflux-components-for-odh-and-rhoai
description: Master orchestrator skill for the full ODH/RHOAI component onboarding pipeline. Takes a single Jira URL and coordinates all sub-skills in sequence. Transitions Jira through In Progress -> Review -> Resolved automatically.
allowed-tools: Bash
user-invocable: true
---

# Onboard Konflux Components for ODH and RHOAI

Orchestrates the complete component onboarding pipeline for a single Jira ticket: validates the
onboarding YAML, creates the Quay repo, onboards to konflux-release-data, raises PRs to
odh-konflux-central / opendatahub-operator / ODH-Build-Config, and transitions the Jira ticket
to Review. Background monitors track PR/MR merges and resolve the ticket automatically.

Sub-skills called in order: validate-component-onboarding-jira → create-quay-repo →
onboard-component-to-konflux-release-data → add-component-to-odh-konflux-central (ODH) →
integrate-component-with-odh-operator → integrate-component-with-bundle.

## Prerequisites

- `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — Atlassian credentials
- `GITLAB_USER`, `GITLAB_TOKEN` — GitLab credentials (api + write_repository scopes)
- `GITHUB_USER`, `GITHUB_TOKEN` — GitHub credentials (repo scope)
- Optional: `KRD_REPO_URL`, `ODH_KONFLUX_CENTRAL_REPO_URL`, `ODH_OPERATOR_REPO_URL`, `OBC_REPO_URL`, `APP_INTERFACE_REPO_URL`
- Tools: `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize`

## Usage

```
/onboard-konflux-components-for-odh-and-rhoai <jira-url>
```

Example:
```
/onboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_onboard_konflux_components_for_odh_and_rhoai.sh" "$ARGUMENTS"
```
