# integrate-component-with-bundle

Updates the build-config repository with the new component's image reference so it is
included in the ODH or RHOAI bundle.

**Applies to:** ODH and RHOAI (different repos and file sets)  
**Pipeline step:** 6 (ODH) / 6 (RHOAI)

## Repositories touched

| Product | Repo |
|---------|------|
| ODH | `opendatahub-io/ODH-Build-Config` — `https://github.com/opendatahub-io/ODH-Build-Config` |
| RHOAI | `red-hat-data-services/RHOAI-Build-Config` — `https://github.com/red-hat-data-services/RHOAI-Build-Config` |

## Files modified

### ODH (1 file)

| File | Change |
|------|--------|
| `bundle/bundle-patch.yaml` | Appends a `relatedImages` entry with the component's Quay image reference |

### RHOAI (3 files)

| File | Change |
|------|--------|
| `bundle/bundle-patch.yaml` | Appends a `relatedImages` entry with the component's registry image reference |
| `config/build-config.yaml` | Appends a `repo_mappings` entry linking the component's source repo to its build image |
| `bundle/Dockerfile` | Appends `ARG <COMPONENT_NAME>_IMAGE` and `LABEL <component_name>-image` entries |

### bundle-patch.yaml entry (both products)

```yaml
- name: <COMPONENT_NAME>_IMAGE
  image: quay.io/opendatahub/<component_name>:latest   # ODH
  # or
  image: registry.stage.redhat.io/rhoai/<component_name>:<version>  # RHOAI
```

### build-config.yaml entry (RHOAI only)

```yaml
repo_mappings:
  - source_repo: <repo_url>
    build_image: <component_name>
```

## PR raised

| Field | ODH | RHOAI |
|-------|-----|-------|
| Target repo | `ODH-Build-Config` | `RHOAI-Build-Config` |
| Target branch | `main` | Version-specific (e.g. `rhoai-3.5`) |
| Title | `add <component_name> to bundle` | `add <component_name> to RHOAI bundle (<version>)` |

## Jira update

Label added: `bundle-pr-raised`  
Comment: PR URL posted to the onboarding ticket.
