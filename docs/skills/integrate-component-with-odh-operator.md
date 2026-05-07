# integrate-component-with-odh-operator

Registers an operator/controller component with the ODH or RHOAI operator by appending
an entry to `build/manifests-config.yaml`. This controls how the operator bundles and
deploys the component's manifests.

**Applies to:** ODH and RHOAI — **only when `is_operator: true`**  
**Pipeline step:** 5 (ODH) / 5 (RHOAI)  
**Skipped silently** when `is_operator: false`.

## Repository touched

| Product | Repo |
|---------|------|
| ODH | `opendatahub-io/opendatahub-operator` — `https://github.com/opendatahub-io/opendatahub-operator` |
| RHOAI | `red-hat-data-services/rhods-operator` — `https://github.com/red-hat-data-services/rhods-operator` |

## File modified

```
build/manifests-config.yaml
```

A new entry is **appended** under the `map:` key:

```yaml
- name: <component_name>
  src: <operator_manifest_src_path>
  dest: <operator_manifest_dest_path>
```

Where `src` and `dest` come from `operator_manifest_src_path` and
`operator_manifest_dest_path` in `component_onboarding_details.yaml`.

## PR raised

| Field | Value |
|-------|-------|
| Target repo | Operator repo (product-specific, see above) |
| Target branch | `main` |
| Title | `add <component_name> manifests to operator` |

## Jira update

Label added: `operator-pr-raised`  
Comment: PR URL posted to the onboarding ticket.
