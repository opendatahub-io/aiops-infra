# Spec: Verify push and pull-request builds before bundle integration

## What and why

After the Tekton pipeline definition PRs are merged, PipelinesAsCode triggers
builds on the Konflux clusters. Onboarding must not be marked complete without
checking that those builds actually succeed. RHOAI now builds pull requests on
P01 and pushes on P02, so both must be verified.

The verification runs inside the existing `bundle` step
(`run_step_integrate_bundle.sh` → `verify_build.sh`) before the bundle PR is
raised. There is no separate `build_verify` state-machine step.

## When does each build fire

- **ODH push build**: when the Tekton PR raised by the onboarder workflow into
  the component's source repo is merged. `bundle` depends on
  `onboarder_workflow`.
- **RHOAI push build**: when the OKC PR adding the push PipelineRun YAML to the
  version branch of `konflux-central` is merged. `bundle` depends on `okc`.
- **RHOAI pull-request build**: when a PR targets the component repository.
  `bundle` also depends on `pull_pipelines`, so the PR PipelineRun PR is merged
  before verification runs.

## Cluster details

| Build | Cluster | Token | Namespace | UI domain |
|-------|---------|-------|-----------|-----------|
| ODH push | `stone-prd-rh01` | `EXT_OC_TOKEN` | `open-data-hub-tenant` | `stone-prd-rh01.pg1f.p1.openshiftapps.com` |
| RHOAI push | `stone-prod-p02` | `INT_OC_TOKEN` | `rhoai-tenant` | `stone-prod-p02.hjvn.p1.openshiftapps.com` |
| RHOAI PR | `stone-prod-p01` | `P01_OC_TOKEN` | `rhoai-tenant` | `stone-prod-p01.wcfb.p1.openshiftapps.com` |

`login_to_konflux_cluster.sh` supports `external`, `internal`, and `p01`.

Component names are `{name}-ci` for ODH and `{name}-{VERSION_VAR}` for RHOAI
(from `parse_rhoai_version.sh`).

## How to find a PipelineRun

**Do not use `oc get pipelineruns`** — Konflux purges live CRs quickly. Query
the KubeArchive API with the component label and event type:

```bash
CLUSTER_SUFFIX=$(echo "$OC_SERVER" | sed 's|https://api||;s|:[0-9]*$||')
KUBEARCHIVE_BASE="https://kubearchive-api-server-product-kubearchive.apps${CLUSTER_SUFFIX}"
```

Push builds:

```text
labelSelector=appstudio.openshift.io/component=<component>,pipelinesascode.tekton.dev/event-type in (push,incoming,retest-comment)
```

Pull-request builds:

```text
labelSelector=appstudio.openshift.io/component=<component>,pipelinesascode.tekton.dev/event-type in (pull_request,issue_comment)
```

For PR builds, filter to the temporary verification PR by checking
`build.appstudio.redhat.com/pull_request_number` or the
`-on-pull-request-<number>` PipelineRun name suffix. This avoids matching an
unrelated PR build for the same component.

## Push verification behavior (`verify_build.sh`)

Single check — no polling loop. The CI scheduler retries on the next run.

- **No PipelineRun found**: post "not started yet" comment, exit 1.
- **Still running**: post "still running" comment with URL, exit 1.
- **Failed**: post failure comment with URL, exit 1.
- **Succeeded**: post success comment with URL, then continue to PR verification
  for RHOAI (or exit 0 for ODH).
- **`ONBOARD_DRY_RUN=true`**: skip cluster checks entirely, exit 0.

## Pull-request verification behavior (`verify_pr_build.sh`)

RHOAI only. Called by `verify_build.sh` after the push build succeeds.

1. Resolve the component repository and choose the base branch. Prefer the
   onboarding `repo_branch`; if the PR PipelineRun file (`.tekton/<component>-pull-request.yaml`)
   is not present there, fall back to `main`. Wait for the konflux-central sync
   if the file is not present yet.
2. Create a temporary branch and commit `.onboarding-build-verify/<JIRA>.txt`.
3. Open a PR titled `DO NOT MERGE: Konflux pull-request build verification for <JIRA>`.
4. Poll KubeArchive on P01 (default timeout 1800s, interval 30s) for the
   matching pull-request PipelineRun.
5. On success: post the build URL to Jira, close the PR, delete the branch, and
   exit 0.
6. On failure: post the failure to Jira, close the PR, delete the branch, and
   exit 1.
7. On timeout: post the still-running status, leave the PR open, and record it
   in `<workdir>/pr_build_verify.json`. The next run reuses that PR and keeps
   polling instead of opening another one.

## Files

1. `scripts/render_rhoai_pipelinerun.sh` — shared PR/push PipelineRun renderer.
2. `scripts/verify_build.sh` — push verification; calls PR verification for RHOAI.
3. `scripts/verify_pr_build.sh` — temporary-PR creation, P01 polling, cleanup.
4. `scripts/login_to_konflux_cluster.sh` — P01 login support.
5. `scripts/init_pipeline.sh` — `bundle` depends on `okc` and `pull_pipelines`
   for RHOAI.
