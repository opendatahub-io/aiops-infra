# sync-rhoai-renovate-configs

Triggers the `sync-renovate-configs` GitHub Actions workflow in `rhoai-konflux-central`
to propagate the current Renovate configuration to all registered component repositories.

**Applies to:** RHOAI only
**Pipeline step:** 7
**Blocked by:** `enable-renovate-on-rhoai-component-repo` PR must merge.

## What it does

No files are edited directly. The skill dispatches a workflow run via the GitHub API:

**Repo:** `red-hat-data-services/konflux-central`  
**Workflow file:** `.github/workflows/sync-renovate-configs.yml`  
**Trigger branch:** `main`

### Workflow inputs dispatched

| Input | Value |
|-------|-------|
| `dry_run` | `false` |
| `renovate-config` | `all` |

The workflow reads `config.yaml` (updated by
[enable-renovate-on-rhoai-component-repo](enable-renovate-on-rhoai-component-repo.md))
and pushes the Renovate config to every listed repository, including the newly added
component repo.

## Outputs

The skill polls the workflow run until completion and posts the run URL to Jira.

## Jira update

Label added: `renovate-sync-done`  
Comment: Workflow run URL posted to the onboarding ticket.
