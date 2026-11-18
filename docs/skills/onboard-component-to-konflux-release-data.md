# onboard-component-to-konflux-release-data

Registers the component with the Konflux CI platform by appending Tekton `Component`
custom resources to `konflux-release-data`. The component is provisioned on the cluster
when the MR merges.

**Applies to:** ODH and RHOAI (different files per product)
**Pipeline step:** 4 (both products)
**Blocked by:** `create-quay-repo` must merge (both products); for RHOAI, `create-rhoai-delivery-repo` must also merge.

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

For RHOAI, the krd script registers the versioned Component in the PDS on
**both `stone-prod-p01` and `stone-prod-p02`**, and registers the
`pr-pipelines-<component_name>` automation Component on both clusters. If P01 has
no automation directory yet, it creates the `automation` Application,
`automation/resources.yaml`, and the kustomization references. Both target
version streams must already exist; onboarding does not bootstrap a release
stream or copy P02 release plans, Early Gate resources, or secrets to P01.

The versioned Component provisions the cluster-local
`build-pipeline-<component_name>-<version>` service account used by the push
(P02) and PR (P01) PipelineRuns. The automation Component is a separate identity.
Cluster-wide secrets and PaC's `konflux_cluster` binding must already be
configured on each cluster. After provisioning, verify both build service
accounts and one PR build on P01 plus one push build on P02.

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

For ODH, before raising the MR the skill checks whether the component already
exists on the target OpenShift cluster using `oc get component`:

- **External cluster** (`stone-prd-rh01`) for ODH — uses `EXT_OC_TOKEN`

If the component already exists, the MR step is skipped.

For RHOAI, the script reconciles both clusters' Git manifests instead. A
Component already present on P02 must not skip missing P01 registration. If
neither manifests nor generated output change, the step finishes without an MR.

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
