# setup-auto-merge

Configures automated upstream→downstream merge for the new RHOAI component by adding
it to the auto-merge configuration in `rhods-devops-infra`.

**Applies to:** RHOAI only
**Pipeline step:** 4
**Blocked by:** — (no dependencies, runs in the first batch)

## Repository touched

**`red-hat-data-services/rhods-devops-infra`** — `https://github.com/red-hat-data-services/rhods-devops-infra`

## Files modified

| File | Change |
|------|--------|
| `src/config/upstream-source-map.yaml` | Appends entry mapping the upstream repo to its midstream counterpart |
| `src/config/main-release-source-map.yaml` | Appends entry for the main→release branch merge path |
| `.github/workflows/upstream-auto-merge.yaml` | Adds `<repo_name>` to the `repositories` input options list |
| `.github/workflows/main-release-auto-merge.yaml` | Adds `<repo_name>` to the `repositories` input options list |

### upstream-source-map.yaml entry

```yaml
- upstream: <repo_url>
  midstream: https://github.com/red-hat-data-services/<repo_name>
  branch_mappings:
    - upstream: main
      midstream: rhoai-<version>
```

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `red-hat-data-services/rhods-devops-infra` |
| Target branch | `main` |
| Title | `setup auto-merge for <component_name>` |

## Jira update

Label added: `auto-merge-pr-raised`  
Comment: PR URL posted to the onboarding ticket.
