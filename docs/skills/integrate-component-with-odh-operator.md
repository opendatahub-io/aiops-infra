# integrate-component-with-odh-operator

Registers an operator/controller component with the ODH or RHOAI operator by appending
an entry to `build/manifests-config.yaml`. This controls how the operator bundles and
deploys the component's manifests.

**Applies to:** ODH and RHOAI — **only when `is_operator: true`**
**Pipeline step:** 8 (both products)
**Blocked by:** `integrate-component-with-bundle` must merge before this step is unblocked.
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

## Target branch

The target branch for cloning and raising the PR is resolved via `OPERATOR_TARGET_BRANCH`:

| Product | Target branch | Source |
|---------|---------------|--------|
| ODH | `main` | Hardcoded default |
| RHOAI | `$REPO_BRANCH` | From `inputs.repo_branch` in `component_onboarding_details.yaml` (e.g. `rhoai-2.20`) |

## PR raised

| Field | ODH | RHOAI |
|-------|-----|-------|
| Target repo | `opendatahub-io/opendatahub-operator` | `red-hat-data-services/rhods-operator` |
| Target branch | `main` | `$REPO_BRANCH` (e.g. `rhoai-2.20`) |
| Title | `Add <component_name> to manifests-config.yaml` | `Add <component_name> to manifests-config.yaml` |

## Jira update

Label added: `operator-pr-raised`
Comment: PR URL posted to the onboarding ticket.

## Related

- [integrate-component-with-bundle](integrate-component-with-bundle.md) — must merge before this step
