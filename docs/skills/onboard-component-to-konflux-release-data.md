# onboard-component-to-konflux-release-data

Registers the component with the Konflux CI platform by appending Tekton `Component`
custom resources to `konflux-release-data`. The component is provisioned on the cluster
when the MR merges.

**Applies to:** ODH and RHOAI (different files per product)  
**Pipeline step:** 2 (ODH) / 3 (RHOAI)

## Repository touched

**`releng/konflux-release-data`** — `https://gitlab.cee.redhat.com/releng/konflux-release-data`

## Files modified

### ODH

| File | Change |
|------|--------|
| `tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant/opendatahub-ci-components.yaml` | Appends a Konflux `Component` document |

### RHOAI

| File | Change |
|------|--------|
| `tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/<VERSION>/ProjectDevelopmentStream-<VERSION>.yaml` | Appends a Konflux `Component` document for the build namespace |
| `tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/automation/resources.yaml` | Appends a pull-request-pipelines `Component` document |
| `config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-<RPA_VAR>-components-stage.yaml` | Appends component to the stage RPA |
| `config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-<RPA_VAR>-components-prod.yaml` | Appends component to the prod RPA |

The `Component` document structure added to each YAML:

```yaml
---
apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  name: <component_name>-<version>
  namespace: <tenant-namespace>
spec:
  application: rhoai-<version>   # or odh equivalent
  componentName: <component_name>-<version>
  source:
    git:
      url: <repo_url>
      revision: <repo_branch>
      context: <context_path>
      dockerfileUrl: <dockerfile_path>
```

## Pre-flight cluster check

Before raising the MR, the skill checks whether the component already exists on the
target OpenShift cluster using `oc get component`:

- **External cluster** (`stone-prd-rh01`) for ODH — uses `EXT_OC_TOKEN`
- **Internal cluster** (`stone-prod-p02`) for RHOAI — uses `INT_OC_TOKEN`

If the component already exists, the MR step is skipped.

## Manifest build & verify

After editing the YAML files, the skill runs `build-manifests.sh` and
`verify-manifests.sh` locally to ensure kustomize renders cleanly before committing.

## MR raised

| Field | Value |
|-------|-------|
| Target repo | `releng/konflux-release-data` |
| Target branch | `main` |
| Title | `onboard <component_name> to Konflux` |

## Jira update

Label added: `krd-mr-raised`  
Comment: MR URL posted to the onboarding ticket.
