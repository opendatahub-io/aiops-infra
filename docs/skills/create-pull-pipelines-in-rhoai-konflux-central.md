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

The pull-request and push PipelineRuns are rendered by the same script,
`scripts/render_rhoai_pipelinerun.sh`. Common params, task overrides, the
service account, and the git-auth workspace are defined once. The intentional
differences are the P01/P02 cluster routing, the event, the image tag, and the
platform list.

- Image: `quay.io/rhoai/<component_name>-rhel9:on-pr-{{pull_request_number}}`.
  This is the component delivery repository. The tag above is the only image
  tag; the params list has no `additional-tags` entry.
- `additional-labels`: `version=on-pr-{{revision}}` and
  `io.openshift.tags=<component_name>`, matching the majority of current
  konflux-central pull-request files. Push PipelineRuns do not use
  `additional-labels`.
- `image-expires-after`: `30d`.
- `build-platforms` is always `linux/x86_64` and `linux-m2xlarge/arm64` for
  pull-request builds, matching current konflux-central pull-request files. The
  `architectures` field is still required by the onboarding schema and is used
  by the push PipelineRun, but it does not affect the PR build.
- `prefetch-input` when `scripts/detect_prefetch_input.sh` finds a dependency
  manifest. An empty result leaves the parameter out.
- `hermetic`, `build-source-image`, and `build-image-index` are `true`, matching
  the development push PipelineRun.
- `dockerfile` and `path-context` come from the onboarding YAML. `./` is written
  as `.`.
- `taskRunSpecs` raises the `rpms-signature-scan` step to `500m` CPU / `1Gi`
  memory, matching the konflux-central `all-pipelineruns` convention.
- There is no `on-comment` annotation. Manual retriggers use the
  `issue_comment` event.
- Trigger annotation on the file is `on-cel-expression` only.

The on-CEL expression handles both pull-request events and `/build-konflux`
style issue comments, and uses the same file filter as the development push
pipeline: any change outside `.tekton/`, or a change to this component's
pull-request PipelineRun. A change that only touches a different file under
`.tekton/` leaves the expression false. The expression has no `target_branch`
comparison. Onboarding has no field for an extra path filter such as a
subdirectory glob.

The outer `konflux_cluster` selector routes these builds to P01 only. The
Repository on each cluster must expose its cluster name to PaC CEL. Coordinate
rollout with the konflux-central routing policy (RHOAIENG-103705) and the GAP
monitor's P01 build-status support (RHOAIENG-103869).

```yaml
pipelinesascode.tekton.dev/on-cel-expression: |-
  konflux_cluster == "stone-prod-p01"
  && (event == "pull_request" || event == "issue_comment")
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

Both files are rendered by `scripts/render_rhoai_pipelinerun.sh`, with the
platform list as the only input that differs. This prevents the two templates
from drifting.

The `bundle` step depends on both `okc` and `pull_pipelines` for RHOAI. Once
both PipelineRun PRs merge, `scripts/verify_pr_build.sh` creates a temporary
`DO NOT MERGE` PR in the component repository, waits for the P01
pull-request build, verifies it succeeded, and then closes the PR and deletes
its branch. A failed or still-running PR build blocks bundle integration.

The name `build-pipeline-<component_name>-<VERSION_VAR>` is unchanged between
clusters, but service accounts are cluster-local. The krd step registers the
versioned Component on both P01 and P02 so Konflux can provision its build
service account and credentials independently. Do not copy a P02 service-account
token to P01. The automation Component's account (`build-pipeline-pr-pipelines-…`)
is not the account used by this PipelineRun. Like the current konflux-central
files, the generated file does not hardcode the old
`redhat-appstudio-staginguser-pull-secret` pod override.
