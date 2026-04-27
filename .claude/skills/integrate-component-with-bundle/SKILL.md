---
name: integrate-component-with-bundle
description: Updates the ODH-Build-Config repository with a new component's relatedImages entry (bundle/bundle-patch.yaml), then raises a GitHub PR. Automates Step 8 of the ODH component onboarding pipeline.
allowed-tools: Bash
user-invocable: true
---

# Integrate Component with Bundle

Updates the `ODH-Build-Config` repository for a new component by appending a `relatedImages`
entry to `bundle/bundle-patch.yaml` and raising a GitHub PR. Resolves the component image digest
via skopeo; uses a placeholder if the image is not yet published.

## Prerequisites

- `GITHUB_USER` — your GitHub username
- `GITHUB_TOKEN` — GitHub personal access token with `repo` scope
- `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` — Atlassian credentials
- Optional: `OBC_REPO_URL` (default: `https://github.com/opendatahub-io/ODH-Build-Config.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- Tools: `uv`, `git`, `skopeo`

## Usage

```
/integrate-component-with-bundle <jira-url>
```

Example:
```
/integrate-component-with-bundle https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `$SKILL_DIR/../common/scripts`.

```bash
bash "$COMMON_SCRIPTS_DIR/run_integrate_component_with_bundle.sh" "$ARGUMENTS"
```
