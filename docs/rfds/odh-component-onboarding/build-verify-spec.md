# Spec: Add `build_verify` step to the onboarding pipeline

## What and why

After the Tekton pipeline definition PRs are merged, PipelinesAsCode triggers a push
build on the Konflux cluster. Currently onboarding is marked complete without checking
whether that build actually succeeds. This step closes that gap.

## When does the build fire

- **ODH**: when the Tekton PR raised by the onboarder workflow into the component's
  source repo is merged. `build_verify` should depend on `onboarder_workflow`.
- **RHOAI**: when the OKC PR adding the push PipelineRun YAML to `rhoai-konflux-central`
  is merged — PAC picks up the YAML and starts building. `build_verify` should depend
  on `okc`.

## Cluster details

ODH uses the **external** cluster (`stone-prd-rh01`, `EXT_OC_TOKEN`), namespace
`open-data-hub-tenant`. RHOAI uses the **internal** cluster (`stone-prod-p02`,
`INT_OC_TOKEN`), namespace `rhoai-tenant`. Both already have a
`login_to_konflux_cluster.sh external|internal` helper.

Component name is `{name}-ci` for ODH and `{name}-{VERSION_VAR}` for RHOAI (from
`parse_rhoai_version.sh`).

## How to find the PipelineRun

**Do not use `oc get pipelineruns`** — Konflux purges live CRs quickly (list is nearly
always empty). Use the **Tekton Results API** instead (same approach as
`rhoai-monitoring/checks/check_konflux_pipeline_results.py`):

```bash
RESULTS_BASE="https://tekton-results-tekton-results.apps.${CLUSTER_DOMAIN}/apis/results.tekton.dev/v1alpha2"
OC_TOKEN=$(oc whoami --show-token)

curl -sfk -H "Authorization: Bearer $OC_TOKEN" --get \
  --data-urlencode "filter=(data_type=='tekton.dev/v1.PipelineRun' || data_type=='tekton.dev/v1beta1.PipelineRun') && data.metadata.labels['pipelinesascode.tekton.dev/event-type']=='push' && data.metadata.labels['pipelines.appstudio.openshift.io/type']=='build' && data.metadata.labels['appstudio.openshift.io/component']=='<COMPONENT>'" \
  --data-urlencode "page_size=10" \
  --data-urlencode "order_by=create_time desc" \
  "${RESULTS_BASE}/parents/<namespace>/results/-/records"
```

`data.value` in each record is base64-encoded PipelineRun JSON. `page_size` must be
**> 5** (API rejects ≤ 5). Application name for the URL comes from the decoded
PipelineRun's own `appstudio.openshift.io/application` label — don't hardcode it.

## Build URL format

```
https://konflux-ui.apps.<cluster-domain>/ns/<namespace>/applications/<app>/pipelineruns/<name>
```

ODH cluster domain: `stone-prd-rh01.pg1f.p1.openshiftapps.com`
RHOAI cluster domain: `stone-prod-p02.hjvn.p1.openshiftapps.com`

## Script behavior (`run_step_verify_build.sh`)

Single check — no polling loop. The CI scheduler retries on the next run.

- **No PipelineRun found**: post "not started yet" comment, exit 1.
- **Still running**: post "still running" comment with URL, exit 1.
- **Failed**: post failure comment with URL + failed task names, add label
  `konflux-build-failed`, exit 1.
- **Succeeded**: post success comment with URL, add label `konflux-build-verified`,
  write state done, exit 0.
- **`ONBOARD_DRY_RUN=true`**: skip cluster check entirely, mark done, exit 0.

## Files to change

1. **`scripts/run_step_verify_build.sh`** — new wrapper script (see behavior above).
2. **`scripts/init_pipeline.sh`** — add `build_verify` step for both products with the
   right `depends_on` per product. Add schema migration for old state files. Do not put
   it in the ODH/RHOAI-only skip blocks — it applies to both.
3. **`SKILL.md`** — add Step 9b (between `onboarder_workflow` and `renovate_sync`),
   update final summary, add error reference entries.
4. **`sync_state_from_jira.py`** — add `"konflux-build-verified" → ("build_verify", "done")`
   to `LABEL_MAP` so state is restored from Jira labels on resume.
