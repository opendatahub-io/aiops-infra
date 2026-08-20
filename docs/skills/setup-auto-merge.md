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
- name: <repo_name>
  automerge: 'yes'
  ignore-files: .tekton/*
  src:
    url: <upstream_repo_url>.git
    branch: main
  dest:
    url: <midstream_repo_url>.git
    branch: main
```

### main-release-source-map.yaml entry

```yaml
- name: <repo_name>
  automerge: 'yes'
  repo-url: <midstream_repo_url>.git
  ignore-files: .tekton/*
```

`ignore-files: .tekton/*` keeps Tekton/PAC pipelines local to each side of the
mapping (ODH CI stays upstream; RHDS pull pipelines stay on `main`, not release
branches).

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `red-hat-data-services/rhods-devops-infra` |
| Target branch | `main` |
| Title | `Configure auto-merge for <component_name>` |

## Jira update

Label added: `auto-merge-pr-raised`  
Comment: PR URL posted to the onboarding ticket.
