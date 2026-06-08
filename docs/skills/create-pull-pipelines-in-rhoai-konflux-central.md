# create-pull-pipelines-in-rhoai-konflux-central

Adds the pull-request Tekton PipelineRun definition for a new RHOAI component to
`rhoai-konflux-central`. Unlike the push pipeline (which is version-branch specific),
this PR always targets `main`.

**Applies to:** RHOAI only
**Pipeline step:** 5b (pull-request pipeline)
**Blocked by:** `onboard-component-to-konflux-release-data` (krd) must merge.

## Repository touched

**`red-hat-data-services/konflux-central`** — `https://github.com/red-hat-data-services/konflux-central`

## File created

```
pipelineruns/<repo-name>/.tekton/<component-name>-pull-request.yaml
```

The PipelineRun YAML configures the pull-request event trigger and references the
same source repo and Dockerfile as the push pipeline.

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `red-hat-data-services/konflux-central` |
| Target branch | `main` |
| Title | `onboard <component_name> pull-request pipeline to RHOAI Konflux` |

## Jira update

Label added: `rkc-pull-pr-raised`  
Comment: PR URL posted to the onboarding ticket.

## Relationship to push pipeline

[add-component-to-rhoai-konflux-central](add-component-to-rhoai-konflux-central.md)
creates the push PipelineRun (targeting the version branch). Both skills run at the
same pipeline step and are independent of each other.
