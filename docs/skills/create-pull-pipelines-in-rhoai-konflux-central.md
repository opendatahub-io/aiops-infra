# create-pull-pipelines-in-rhoai-konflux-central

Adds the pull-request Tekton PipelineRun for a new RHOAI component to
`red-hat-data-services/konflux-central`. The GitHub PR always targets `main`.

The generated file follows the GAP Stage 2 pull-request PipelineRun from
[RHOAIENG-97051](https://issues.redhat.com/browse/RHOAIENG-97051). The first
rollout is konflux-central PR #3630. PR #3682 corrected the pipeline-reference
escape sequence used below.

**Applies to:** RHOAI only
**Pipeline step:** 8b (pull-request pipeline)
**Blocked by:** `onboard-component-to-konflux-release-data` (krd) must merge.

## Repository touched

**`red-hat-data-services/konflux-central`** — `https://github.com/red-hat-data-services/konflux-central`

## File created

```
pipelineruns/<repo-name>/.tekton/<component-name>-pull-request.yaml
```

That path is on `main`. The release-branch push PipelineRun is a separate file,
created by [add-component-to-rhoai-konflux-central](add-component-to-rhoai-konflux-central.md)
on the version branch.

## Version input

`target_rhoai_version` in `component_onboarding_details.yaml` supplies every
versioned field in this PipelineRun. [create-component-onboarding-jira](create-component-onboarding-jira.md)
asks for it and stores the canonical form `x.y` or `x.y-ea-n`.
`scripts/parse_rhoai_version.sh` derives `VERSION_VAR` and `RHOAI_MINOR_VERSION`:

| `target_rhoai_version` | `VERSION_VAR` | `RHOAI_MINOR_VERSION` | Application |
|------------------------|---------------|-----------------------|-------------|
| `3.6` | `v3-6` | `3.6.0` | `rhoai-v3-6` |
| `3.6-ea-1` | `v3-6-ea-1` | `3.6.0-ea.1` | `rhoai-v3-6-ea-1` |

For `target_rhoai_version: "3.6"` and component `odh-eval-hub`:

| Field | Value |
|-------|-------|
| `appstudio.openshift.io/application` | `rhoai-v3-6` |
| `appstudio.openshift.io/component` | `odh-eval-hub-v3-6` |
| `serviceAccountName` | `build-pipeline-odh-eval-hub-v3-6` |
| `rhoai-version` | `"3.6.0"` |

RHOAIENG-97051 identified RHOAI 3.6 as the development version when it was
written. Those identifiers match the development push PipelineRun for the same
`target_rhoai_version`. A ticket that targets an older release, such as `3.5`,
writes `rhoai-v3-5` into this main-branch file. Aligning the pull-request
PipelineRun with the current development application means setting
`target_rhoai_version` to that development version. The step passes the ticket
value through `parse_rhoai_version.sh`.

`component_name` remains at most 50 characters. Konflux release-data still
registers an automation component named `pr-pipelines-<component_name>`, and
that prefix is what the 50-character limit protects. This PipelineRun's
component label is `<component_name>-<VERSION_VAR>`.

## Generated configuration

- Image: `quay.io/rhoai/<component_name>-rhel9:on-pr-{{pull_request_number}}`.
  This is the component delivery repository. The tag above is the only image
  tag; the params list has no `additional-tags` entry.
- `image-expires-after`: `30d`.
- `build-platforms` from `architectures`: `x86_64` → `linux/x86_64`,
  `arm64` → `linux-m2xlarge/arm64`, `ppc64le` → `linux/ppc64le`,
  `s390x` → `linux/s390x`.
- `prefetch-input` when `scripts/detect_prefetch_input.sh` finds a dependency
  manifest. An empty result leaves the parameter out.
- `hermetic`, `build-source-image`, and `build-image-index` are `true`, matching
  the current development push PipelineRun.
- `dockerfile` and `path-context` come from the onboarding YAML. `./` is written
  as `.`.
- Manual builds use `pipelinesascode.tekton.dev/on-comment: "^/build-konflux"`.
- Trigger annotations on the file are `on-comment` and `on-cel-expression`.

The on-CEL expression uses the pull-request event and the same file filter as
the development push pipeline: any change outside `.tekton/`, or a change to
this component's pull-request PipelineRun. A change that only touches a
different file under `.tekton/` leaves the expression false. The pull-request
event stands in place of the push event, and the expression has no
`target_branch` comparison. Onboarding has no field for an extra path filter
such as a subdirectory glob.

```yaml
pipelinesascode.tekton.dev/on-cel-expression: |-
  event == "pull_request"
  && (files.all.exists(p, ! p.matches('^\\.tekton/')) || ".tekton/<component-name>-pull-request.yaml".pathChanged())
```

`pipelineRef.revision` selects the component PR's target branch when the name
is a supported release branch, and `main` for every other target:

```yaml
value: '{{ cel: pac.target_branch.matches("^rhoai-\\d+\\.\\d+(-ea\\.\\d+)?$") ? pac.target_branch : "main" }}'
```

| Component PR target | Pipeline revision |
|---------------------|-------------------|
| `main` | `main` |
| `rhoai-3.6` | `rhoai-3.6` |
| `rhoai-3.6-ea.1` | `rhoai-3.6-ea.1` |
| any other branch | `main` |

The backslashes above are the characters stored in the YAML file. Pipelines as
Code then evaluates `^rhoai-\d+\.\d+(-ea\.\d+)?$`. That escaping is the
correction from konflux-central PR #3682.

[RHOAIENG-97056](https://issues.redhat.com/browse/RHOAIENG-97056) (Quay tagging
safeguards in `rhoai-init`) is still in Backlog. It has not published a new
task version or a new task parameter for generated PipelineRuns. This step
keeps `pathInRepo: pipelines/multi-arch-container-build.yaml`. The pipeline on
the selected revision contains the `rhoai-init` task reference.

## PR raised

| Field | Value |
|-------|-------|
| Target repo | `red-hat-data-services/konflux-central` |
| Target branch | `main` |
| Title | `Add <component_name> pull-request PipelineRun` |

## Jira update

Label added: `rkc-pull-pr-raised`
Comment: PR URL posted to the onboarding ticket.

## Relationship to the push pipeline

[add-component-to-rhoai-konflux-central](add-component-to-rhoai-konflux-central.md)
creates the push PipelineRun on the version branch (`rhoai-3.6`, or
`rhoai-3.6-ea.1` for an EA target). Both skills run after krd merges. They
read the same `target_rhoai_version`, so the application, component, and
service account on this main-branch pull-request PipelineRun match the push
PipelineRun for that version.
