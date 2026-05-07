# update-rhoai-product-listing

Adds the new component's container registry path to the RHOAI product listing in
`pyxis-repo-configs`. This makes the component visible in the Red Hat container catalog.

**Applies to:** RHOAI only  
**Pipeline step:** 7  
**Runs after:** `create-rhoai-delivery-repo` MR has merged.

## Repository touched

**`releng/pyxis-repo-configs`** — `https://gitlab.cee.redhat.com/releng/pyxis-repo-configs`

*(Same repo as [create-rhoai-delivery-repo](create-rhoai-delivery-repo.md), but a different file.)*

## File modified

```
product-listings/rhoai/rhoai.yaml
```

The component's registry path is **appended** to the `repositories:` array:

```yaml
repositories:
  - registry.stage.redhat.io/rhoai/<component_name>
```

## MR raised

| Field | Value |
|-------|-------|
| Target repo | `releng/pyxis-repo-configs` |
| Target branch | `main` |
| Title | `Add <component_name> to RHOAI product listing` |

## Jira update

Label added: `product-listing-mr-raised`  
Comment: MR URL posted to the onboarding ticket.
