# add-component-to-rhoai-konflux-central

Adds the push-event Tekton PipelineRun definition for a new RHOAI component to
`rhoai-konflux-central`, targeting the version-specific release branch.

**Applies to:** RHOAI only  
**Pipeline step:** 4 (push pipeline)

## Repository touched

**`red-hat-data-services/konflux-central`** — `https://github.com/red-hat-data-services/konflux-central`

## File created

```
pipelineruns/<repo-name>/.tekton/<component-name>-<version>-push.yaml
```

The PipelineRun YAML configures:
- Source repo, branch, context path, and Dockerfile from `component_onboarding_details.yaml`
- Target architectures (multi-arch build matrix)
- Konflux push-event trigger

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `red-hat-data-services/konflux-central` |
| Target branch | `rhoai-<VERSION_X>.<VERSION_Y>` (e.g. `rhoai-3.5`) |
| Title | `onboard <component_name> to RHOAI Konflux (<version>)` |

## Jira update

Label added: `rkc-pr-raised`  
Comment: PR URL posted to the onboarding ticket.

## Pull-request pipeline

This skill creates only the push PipelineRun. The pull-request PipelineRun is handled
separately by [create-pull-pipelines-in-rhoai-konflux-central](create-pull-pipelines-in-rhoai-konflux-central.md),
which targets `main` rather than the version branch.
