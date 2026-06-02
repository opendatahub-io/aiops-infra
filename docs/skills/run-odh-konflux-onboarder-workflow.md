# run-odh-konflux-onboarder-workflow

Triggers the `odh-konflux-onboarder` GitHub Actions workflow in `odh-konflux-central`,
waits for it to complete, and extracts the Tekton PR URL it produces.

**Applies to:** ODH only
**Pipeline step:** 4
**Blocked by:** `onboard-component-to-konflux-release-data` (krd) + `add-component-to-odh-konflux-central` (okc) must both merge.

## What it does

No files are edited directly. The skill dispatches a workflow run via the GitHub API:

**Repo:** `opendatahub-io/odh-konflux-central`  
**Workflow file:** `.github/workflows/odh-konflux-onboarder.yml`  
**Trigger branch:** `main`

### Workflow inputs dispatched

| Input | Value |
|-------|-------|
| `component` | `<component_name>` |
| `pr_target_branch` | `main` (CI) or version branch (Release) |
| `build_type` | `CI` or `Release` |
| `version` | *(Release builds only)* |

### What the workflow produces

The workflow creates Tekton objects on the Konflux cluster and opens a PR in the
upstream Tekton config repo. The skill:
1. Polls the workflow run until it completes (success or failure).
2. Parses the workflow logs to extract the Tekton PR URL.
3. Records the URL in the Jira comment.

## Jira update

Label added: `tekton-pr-raised`  
Comment: Tekton PR URL and workflow run URL posted to the onboarding ticket.

## Dependencies

This skill runs only after both of the following PRs have merged:

- [add-component-to-odh-konflux-central](add-component-to-odh-konflux-central.md) — the component must appear in the workflow's `component` options list
- [onboard-component-to-konflux-release-data](onboard-component-to-konflux-release-data.md) — the Konflux release data must be in place
