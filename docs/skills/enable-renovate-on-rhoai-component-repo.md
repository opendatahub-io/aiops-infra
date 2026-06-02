# enable-renovate-on-rhoai-component-repo

Registers the new RHOAI component's repository with the Renovate configuration in
`rhoai-konflux-central`, enabling automatic dependency-update PRs for the component.

**Applies to:** RHOAI only
**Pipeline step:** 3
**Blocked by:** — (no dependencies, runs in the first batch)

## Repository touched

**`red-hat-data-services/konflux-central`** — `https://github.com/red-hat-data-services/konflux-central`

## File modified

```
config.yaml
```

The component's repository is **appended** to the `sync-repositories` array in the
default Renovate distribution block:

```yaml
sync-repositories:
  - url: <repo_url>
    branch: <repo_branch>
```

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `red-hat-data-services/konflux-central` |
| Target branch | `main` |
| Title | `enable Renovate for <component_name>` |

## Jira update

Label added: `renovate-pr-raised`  
Comment: PR URL posted to the onboarding ticket.

## Related

After this PR merges, [sync-rhoai-renovate-configs](sync-rhoai-renovate-configs.md)
propagates the updated Renovate configuration to all registered repos, including the
newly added one.
