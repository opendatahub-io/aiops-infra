# create-quay-repo

Creates a Quay.io repository for the component via a GitOps merge request to
`app-interface`. The repository is provisioned automatically when the MR merges.

**Applies to:** ODH and RHOAI
**Pipeline step:** 1 (ODH) / 1 (RHOAI)
**Blocked by:** — (no dependencies, runs in the first batch)

## Repository touched

**`service/app-interface`** — `https://gitlab.cee.redhat.com/service/app-interface`

## File modified

```
data/services/rhoai/quay/<org>.yml
```

A new repository entry is **appended** to the file's `repos:` list:

```yaml
- name: <component_name>
  description: <short_description>
  visibility: public
  teams:
    - name: rhoai-devtestops
      role: admin
```

## MR raised

| Field | Value |
|-------|-------|
| Target repo | `service/app-interface` |
| Target branch | `master` |
| Title | `Add Quay repo for <component_name>` |

## Jira update

Label added: `quay-mr-raised`  
Comment: MR URL posted to the onboarding ticket.
