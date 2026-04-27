---
name: create-quay-repo
description: Creates a Quay repository via a GitOps MR to app-interface. Handles fork setup, sparse YAML editing, MR creation, and optional Jira tracking. Automates Step 2 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Create Quay Repo

Creates a new Quay repository for an ODH/RHOAI component by raising a merge request to the
`app-interface` GitLab repository (GitOps-driven). The Quay repo is automatically created when
the MR is merged. Optionally tracks progress on a Jira ticket.

## Prerequisites

- `GITLAB_USER` — your GitLab username
- `GITLAB_TOKEN` — GitLab personal access token with `api` + `write_repository` scopes
- Optional: `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — required only when `--jira-url` is provided
- Optional: `APP_INTERFACE_REPO_URL` (default: `https://gitlab.cee.redhat.com/service/app-interface`)
- Tools: `uv`, `skopeo`

## Usage

```
/create-quay-repo <quay-repo> [--jira-url <url>] [--visibility public|private] [--workdir <path>] [--sparse-file <path>]
```

Examples:
```
/create-quay-repo quay.io/opendatahub/my-new-component
/create-quay-repo rhoai/rhoai-data-science-pipelines --jira-url https://redhat.atlassian.net/browse/RHOAIENG-1234
/create-quay-repo opendatahub/odh-ai-first-demo --jira-url https://redhat.atlassian.net/browse/RHOAIENG-5678 --visibility public
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_create_quay_repo.sh" $ARGUMENTS
```
