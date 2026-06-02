# create-rhoai-delivery-repo

Creates the RHOAI delivery repository entry in the Red Hat container registry by
raising a GitLab MR to `pyxis-repo-configs`. The registry repo is provisioned when
the MR merges.

**Applies to:** RHOAI only
**Pipeline step:** 2
**Blocked by:** — (no dependencies, runs in the first batch)

## Repository touched

**`releng/pyxis-repo-configs`** — `https://gitlab.cee.redhat.com/releng/pyxis-repo-configs`

## File modified

```
products/rhoai/rhoai.yaml
```

A new repository entry is **appended** to the file's `repositories:` list:

```yaml
- registry: registry.stage.redhat.io
  repository: rhoai/<component_name>
  content_stream_tags:
    - name: <version>
      architecture: amd64
    - name: <version>
      architecture: arm64
    # ... additional architectures as configured
```

## MR raised

| Field | Value |
|-------|-------|
| Target repo | `releng/pyxis-repo-configs` |
| Target branch | `main` |
| Title | `Add delivery repo for <component_name>` |

## Jira update

Label added: `delivery-repo-mr-raised`  
Comment: MR URL posted to the onboarding ticket.

## Relationship to update-rhoai-product-listing

This skill creates the *delivery repo* record (registry metadata).
[update-rhoai-product-listing](update-rhoai-product-listing.md) runs later and adds the
component to the *product listing* (the public-facing catalog entry) in the same
`pyxis-repo-configs` repo but in a different file.
