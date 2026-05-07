# add-component-to-odh-konflux-central

Adds the Tekton PipelineRun definitions for a new ODH component to
`odh-konflux-central`, and registers the component in the onboarder workflow so it
can be selected for CI runs.

**Applies to:** ODH only  
**Pipeline step:** 3

## Repository touched

**`opendatahub-io/odh-konflux-central`** — `https://github.com/opendatahub-io/odh-konflux-central`

## Files created / modified

| File | Change |
|------|--------|
| `pipelineruns/<repo-name>/<component-name>-push.yaml` | **Created** — Tekton PipelineRun for push (merge) events |
| `pipelineruns/<repo-name>/<component-name>-pull-request.yaml` | **Created** — Tekton PipelineRun for pull-request events |
| `.github/workflows/odh-konflux-onboarder.yml` | **Modified** — component name appended to the workflow's `component` input options list |

The PipelineRun YAMLs reference the component's repo URL, branch, context path, and
Dockerfile path from `component_onboarding_details.yaml`.

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `opendatahub-io/odh-konflux-central` |
| Target branch | `main` |
| Title | `onboard <component_name> to ODH Konflux` |

## Jira update

Label added: `okc-pr-raised`  
Comment: PR URL posted to the onboarding ticket.

## Related

After this PR merges, [run-odh-konflux-onboarder-workflow](run-odh-konflux-onboarder-workflow.md)
triggers the workflow added to `odh-konflux-onboarder.yml` to create the Tekton
objects on the cluster.
