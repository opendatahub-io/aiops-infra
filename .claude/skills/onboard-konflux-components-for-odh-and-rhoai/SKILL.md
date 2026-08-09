---
name: onboard-konflux-components-for-odh-and-rhoai
description: Master orchestrator skill for the full ODH/RHOAI component onboarding pipeline. Idempotent — run any number of times for the same Jira. Each run syncs PR/MR state, executes newly-unblocked steps, and posts a summary of what changed. Transitions Jira through In Progress → Review → Resolved automatically.
allowed-tools: Bash
user-invocable: true
---

> **WARNING:** This skill is not designed to be invoked manually from user playpen
> Only run `onboard-konflux-components-for-odh-and-rhoai` directly if you know what you are doing.

# Onboard Konflux Components for ODH and RHOAI

Orchestrates the complete component onboarding pipeline (idempotent re-run model):

1. `validate-component-onboarding-jira` — fetch + validate Jira YAML
2. `create-quay-repo` — GitLab MR to app-interface
3. `create-rhoai-delivery-repo` — GitLab MR to pyxis-repo-configs **(RHOAI only; prerequisite of krd)**
4. `onboard-component-to-konflux-release-data` — GitLab MR to konflux-release-data **(after quay merges; also after delivery-repo for RHOAI)**
5. `add-component-to-odh-konflux-central` **(ODH)** / `add-component-to-rhoai-konflux-central` + `create-pull-pipelines-in-rhoai-konflux-central` **(RHOAI; after krd merges)**
6. `run-odh-konflux-onboarder-workflow` — triggered once krd+okc are both merged **(ODH only)**
7. `integrate-component-with-bundle` — GitHub PR **(ODH: after onboarder_workflow; RHOAI: after okc merges)**
7b. `krd-release-plan` (`krd_rpa`) — GitLab MR to ReleasePlanAdmission **(RHOAI only; after okc merges, alongside bundle)**
8. `integrate-component-with-odh-operator` — GitHub PR **(after bundle merges; if is_operator=true)**
9. `update-rhoai-product-listing` — GitLab MR, triggered after delivery-repo merges **(RHOAI only)**
10. `setup-auto-merge` — GitHub PR to rhods-devops-infra **(RHOAI only)**
11. `enable-renovate-on-rhoai-component-repo` + deferred `sync-rhoai-renovate-configs` **(RHOAI only)**

**Re-run model:** invoke this skill any number of times for the same Jira URL.
Each run checks Jira labels and PR/MR API status to determine what's already done,
executes the next unblocked steps, and posts a summary of status changes only.
No background nohup processes are used.

## Usage

```
/onboard-konflux-components-for-odh-and-rhoai <jira-url>
```

## Prerequisites

**Jira:** `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`
**GitLab (VPN required):** `GITLAB_USER`, `GITLAB_TOKEN` (api + write_repository scope)
**GitHub:** `GITHUB_USER`, `GITHUB_TOKEN` (repo + actions:write scope)
**OpenShift:** `EXT_OC_TOKEN` (external cluster — stone-prd-rh01, ODH builds), `INT_OC_TOKEN` (internal cluster — stone-prod-p02, RHOAI builds) — each required only if no matching kubeconfig context is found for that cluster
**Tools:** `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize` (or `kubectl`)

Optional overrides: `APP_INTERFACE_REPO_URL`, `KONFLUX_RELEASE_DATA_REPO_URL`,
`ODH_KONFLUX_CENTRAL_REPO_URL`, `ODH_OPERATOR_REPO_URL`, `OBC_REPO_URL`, `JIRA_SERVER`,
`RHOAI_KONFLUX_CENTRAL_REPO_URL` (used by Steps 7/8 RHOAI; default: `https://github.com/red-hat-data-services/konflux-central.git`),
`PYXIS_REPO_CONFIGS_REPO_URL` (used by Steps 9/10 RHOAI; default: `https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git`),
`RHODS_DEVOPS_INFRA_REPO_URL` (used by Step 11 RHOAI; default: `https://github.com/red-hat-data-services/rhods-devops-infra.git`)

**VPN must be active** before running — required for Steps 3, 4, and 10 (GitLab on gitlab.cee.redhat.com).

**GitLab SSL note:** `gitlab.cee.redhat.com` uses an internal CA. All scripts pass
`GIT_SSL_NO_VERIFY=true` and `GITLAB_SSL_VERIFY=false` automatically. Do NOT diagnose
GitLab failures as "VPN down" just because `curl gitlab.cee.redhat.com` returns 000 without
`-k` — that is an SSL issue, not a VPN issue. VPN state is not your responsibility to check.

## Implementation

---

## Locate Scripts Directory

Before any other step, resolve the absolute path to the `scripts/` directory.
All subsequent bash calls must use `$SCRIPTS_DIR/` — never bare relative paths.

```bash
# AIOPS_INFRA_DIR is set by CI (setup-skills.sh) and locally via exports.sh.
# Fall back to /tmp/aiops-infra which is the standard CI clone location.
SCRIPTS_DIR="${AIOPS_INFRA_DIR:-/tmp/aiops-infra}/scripts"
if [[ ! -d "$SCRIPTS_DIR" ]]; then
  echo "ERROR: scripts directory not found at $SCRIPTS_DIR"
  echo "  Set AIOPS_INFRA_DIR to the root of the aiops-infra checkout."
  exit 1
fi
echo "SCRIPTS_DIR: $SCRIPTS_DIR"
```

---

## Step 0: Parse Inputs

```bash
eval "$(bash "$SCRIPTS_DIR/parse_jira_url.sh" "${1:-}")"
[[ -z "$JIRA_URL" ]] && {
  echo "ERROR: Jira URL is required."
  echo "  Usage: /onboard-konflux-components-for-odh-and-rhoai <jira-url>"
  exit 1
}
echo "Jira ID  : $JIRA_ID"
echo "Jira URL : $JIRA_URL"
```

---

## Step 1: Check Prerequisites

```bash
bash "$SCRIPTS_DIR/check_prerequisites.sh" \
  --env "JIRA_USER_EMAIL JIRA_API_TOKEN GITLAB_USER GITLAB_TOKEN GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git oc skopeo yamllint jq kustomize"

[[ -x "${HOME}/.local/bin/kustomize" ]] && export PATH="${HOME}/.local/bin:${PATH}"
```

---

## Step 2: Set Up Working Directory and Initialize State

```bash
# init_pipeline.sh writes all informational output to stderr by design.
# Capture stdout only — do NOT add 2>&1 or the status lines will break the eval.
_INIT_VARS=$(bash "$SCRIPTS_DIR/init_pipeline.sh" --jira-url "$JIRA_URL")
eval "$_INIT_VARS"
echo "Working directory: $WORKDIR"
echo "Pipeline state: $PIPELINE_STATE"
```

`$PIPELINE_STATE` is the **full path** to `pipeline_state.json` (e.g. `.../RHOAIENG-1234/pipeline_state.json`).
Use it directly in all `jq` and `bash` calls — never reconstruct it by appending a filename to `$WORKDIR`.

(Full `--product-context` and `--component-name` are passed after Step 4 parses the YAML;
`init_pipeline.sh` handles both fresh creation and resumption of an existing state file.)

---

## Step 3: Sub-skill — validate-component-onboarding-jira

**Skip if** `steps.validate.status == "done"` in `pipeline_state.json`.

> **There is NO `run_step_validate.sh` wrapper for this step.** Do NOT attempt to call one.
> This step uses the full `validate-component-onboarding-jira` child skill with LLM reasoning.

Invoke the validate skill directly:

```bash
# Read the validate-component-onboarding-jira skill and follow its implementation.
# The skill is at: ~/.claude/skills/validate-component-onboarding-jira/SKILL.md
# Pass SCRIPTS_DIR so it resolves script paths correctly.
export SCRIPTS_DIR="$SCRIPTS_DIR"
# Then follow every step in the validate skill for: $JIRA_URL
```

On success:
- `$WORKDIR/component_onboarding_details.json` and `$WORKDIR/component_onboarding_details.yaml` exist
- Jira is in "In Progress" status
- Update pipeline state:
  ```bash
  bash "$SCRIPTS_DIR/pipeline_state.sh" set \
    --state "$PIPELINE_STATE" --step validate --field status --value "done"
  ```

On failure: **hard blocker**. Display the child skill's error and stop.

---

## Step 4: Parse Component Details and Derive Computed Variables

**Skip computation if** `component_name` is already non-empty in `pipeline_state.json`, but still read variables from the YAML into shell for use in later steps.

```bash
# parse_component_details.sh writes all human-readable output to stderr by design.
# Capture stdout only — do NOT add 2>&1 or the summary lines will break the eval.
_COMP_VARS=$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
  --workdir        "$WORKDIR" \
  --jira-id        "$JIRA_ID" \
  --scripts-dir    "$SCRIPTS_DIR" \
  --pipeline-state "$PIPELINE_STATE")
eval "$_COMP_VARS"
# Sets: COMPONENT_NAME IS_OPERATOR REPO_URL REPO_BRANCH
#       PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI
```

After parsing, update the state schema for any steps not yet in the file
(handles old state files missing new steps):

```bash
bash "$SCRIPTS_DIR/init_pipeline.sh" \
  --jira-url         "$JIRA_URL" \
  --workdir-override "$WORKDIR" \
  --product-context  "$PRODUCT_CONTEXT" \
  --component-name   "$COMPONENT_NAME" \
  --is-operator      "$IS_OPERATOR" \
  > /dev/null
```

On exit 1: display stderr and stop with:
```
ERROR in Step 4 (Parse Component Details): Could not parse YAML or derive PRODUCT_CONTEXT. Aborting.
```

---

## Step 4b: Ensure Template Clone Link

Ensure the Jira has a "clones" link to the product-specific onboarding template
(covers tickets created outside the `create-component-onboarding-jira` skill):

```bash
if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  TEMPLATE_ID="RHOAIENG-35683"
else
  TEMPLATE_ID="RHOAIENG-17225"
fi

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --link-clones "$TEMPLATE_ID" || true
```

Non-fatal — if the link already exists or cannot be created, continue.

---

## Step 5: Sync State from Jira Labels

Reconstruct `pipeline_state.json` from Jira labels (durable even after a fresh checkout)
and extract any PR/MR URLs from Jira comments that aren't already in state:

```bash
uv run --script "$SCRIPTS_DIR/sync_state_from_jira.py" \
  --jira-details   "$WORKDIR/component_onboarding_details.json" \
  --pipeline-state "$PIPELINE_STATE"
```

This is non-fatal. If it fails (e.g., JSON parse error), print a warning and continue.

---

## Step 6: Check Current PR/MR Status

For all steps in `pr_raised` or `mr_raised` state, query the GitHub/GitLab API
(one call per step, `--check-only` mode) and update `pipeline_state.json`:

```bash
NEWLY_MERGED=$(bash "$SCRIPTS_DIR/check_pr_mr_status.sh" \
  --state      "$PIPELINE_STATE" \
  --scripts-dir "$SCRIPTS_DIR")
```

`NEWLY_MERGED` is a newline-separated list of step keys that transitioned to `"merged"`
this run (e.g., `quay\nkrd`). Empty string means no changes.

For each newly merged step, add its `label_done` Jira label so the state persists across runs:

```bash
for MERGED_KEY in $NEWLY_MERGED; do
  DONE_LABEL=$(jq -r --arg k "$MERGED_KEY" '.steps[$k].label_done // ""' "$PIPELINE_STATE")
  RAISED_LABEL=$(jq -r --arg k "$MERGED_KEY" '.steps[$k].label_raised // ""' "$PIPELINE_STATE")
  LABEL_ARGS=()
  [[ -n "$DONE_LABEL" ]]   && LABEL_ARGS+=("--add-label"    "$DONE_LABEL")
  [[ -n "$RAISED_LABEL" ]] && LABEL_ARGS+=("--remove-label" "$RAISED_LABEL")
  if [[ "${#LABEL_ARGS[@]}" -gt 0 ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      "${LABEL_ARGS[@]}" || true
  fi
done
```

---

## Step 7: Compute Unblocked Steps

A step is **executable** this run if:
1. Its `status` is `"pending"` (not `pr_raised`, `mr_raised`, `merged`, `done`, `skipped`, `closed`)
2. All steps in its `depends_on` list have `status == "merged"` or `"done"`

Compute `UNBLOCKED_STEPS` by reading `pipeline_state.json`:

```bash
UNBLOCKED_STEPS=$(jq -r '
  .steps as $steps |
  $steps | to_entries[] |
  select(.value.status == "pending") |
  select(
    .value.depends_on | all(. as $dep |
      $steps[$dep].status == "merged" or $steps[$dep].status == "done"
    )
  ) | .key
' "$PIPELINE_STATE")
```

---

## Step 8: Execute Pending Unblocked Steps

For each step in `UNBLOCKED_STEPS`, call the corresponding wrapper script. The script
encodes all multi-step logic (fork, clone, edit YAML, commit, raise PR/MR, update Jira)
and updates `pipeline_state.json` atomically before exiting.

**General invocation contract** (identical for every step):

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_<name>.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
# Exit 0: script wrote pipeline_state.json (status pr_raised/mr_raised, URL, label).
#         Extract URL from last line of $OUTPUT for logging. Set NEW_PRS_RAISED="true".
# Exit 2: step was idempotent (already done). Script wrote pipeline_state.json (status done).
#         Nothing further needed.
# Exit 1: hard failure. Print $OUTPUT and stop this run.
#         pipeline_state.json is unchanged; next CI run retries.
```

**CRITICAL — Exit 1 handling: do NOT read, debug, or edit any script.**
On exit 1, print the output, post a Jira comment (see Step 9), and **immediately stop — do not
print a final summary, do not check remaining steps, do not run any further bash commands.**
The session must end right after the Jira comment is posted.
The wrapper scripts are self-contained; failures are environment or infrastructure issues,
not LLM reasoning tasks. Editing scripts mid-run is strictly forbidden.

Note: `WORKDIR` and `PIPELINE_STATE` must be forwarded explicitly because the Bash tool
preserves CWD across calls (a `cd "$WORKDIR"` earlier in the session would cause the script
to double-nest the Jira ID when computing its own default WORKDIR).

Track whether any PR/MR was raised this run:
```bash
NEW_PRS_RAISED="false"
```
Set `NEW_PRS_RAISED="true"` inside each Exit-0 and Exit-0-equivalent handler below.

### Step 8a: create-quay-repo (step key: `quay`)

**Execute if** `quay` is in `UNBLOCKED_STEPS`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_create_quay_repo.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: the script has already updated `pipeline_state.json` (status `mr_raised`, MR URL recorded, label `quay-mr-raised` added). Extract `MR_URL` from the last line of `$OUTPUT` for logging. Set `NEW_PRS_RAISED="true"`.
- Exit 2: the script has already updated `pipeline_state.json` (status `done`, label `quay-mr-merged` added). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop. `pipeline_state.json` is unchanged; next CI run retries.

### Step 8b: create-rhoai-delivery-repo (step key: `delivery_repo`, RHOAI only)

**Execute if** `delivery_repo` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

> **VPN must be active.**

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_create_rhoai_delivery_repo.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `mr_raised`, MR URL recorded, label `delivery-repo-mr-raised` added). Extract `MR_URL` from last line of `$OUTPUT` for logging. Set `NEW_PRS_RAISED="true"`.
- Exit 2: delivery repo already exists. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8c: onboard-component-to-konflux-release-data (step key: `krd`)

**Execute if** `krd` is in `UNBLOCKED_STEPS`.

> **VPN must be active.**

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_krd.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `mr_raised`, MR URL recorded, label `krd-mr-raised` added). Extract `MR_URL` from last line of `$OUTPUT` for logging. Set `NEW_PRS_RAISED="true"`.
- Exit 2: component already exists on cluster. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8d: add-component-to-*-konflux-central (step key: `okc`)

**Execute if** `okc` is in `UNBLOCKED_STEPS`.

**If `PRODUCT_CONTEXT == "ODH"`:**
```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_add_to_odh_okc.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

**If `PRODUCT_CONTEXT == "RHOAI"`:**
```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_add_to_rhoai_okc.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `pr_raised`, PR URL recorded, label added). Extract `PR_URL` from last line of `$OUTPUT`. Set `NEW_PRS_RAISED="true"`.
- Exit 2: PipelineRun already exists. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8e: create-pull-pipelines-in-rhoai-konflux-central (step key: `pull_pipelines`, RHOAI only)

**Execute if** `pull_pipelines` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_create_pull_pipelines.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `pr_raised`, PR URL recorded, label `rkc-pull-pr-raised` added). Set `NEW_PRS_RAISED="true"`.
- Exit 2: PipelineRun already exists. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8f: integrate-component-with-bundle (step key: `bundle`)

**Execute if** `bundle` is in `UNBLOCKED_STEPS`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_integrate_bundle.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `pr_raised`, PR URL recorded, label `bundle-pr-raised` added). Set `NEW_PRS_RAISED="true"`.
- Exit 2: entry already present. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8g: integrate-component-with-odh-operator (step key: `operator`)

**Execute if** `operator` is in `UNBLOCKED_STEPS`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_integrate_operator.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `pr_raised`, PR URL recorded, label `operator-pr-raised` added). Set `NEW_PRS_RAISED="true"`.
- Exit 2: `is_operator=false` (skipped) or entry already present. Script updated `pipeline_state.json`. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8h: krd-release-plan (step key: `krd_rpa`, RHOAI only)

**Execute if** `krd_rpa` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

The `depends_on: ["okc"]` check in Step 7 ensures this runs alongside build-config (`bundle`) after okc merges.

> **VPN needed.**

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_krd_rpa.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

Same Exits as other steps.

### Step 8i: update-rhoai-product-listing (step key: `product_listing`, RHOAI only)

**Execute if** `product_listing` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

> **VPN must be active.**

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_update_product_listing.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `mr_raised`, MR URL recorded, label `product-listing-mr-raised` added). Set `NEW_PRS_RAISED="true"`.
- Exit 2: entry already exists. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8j: setup-auto-merge (step key: `auto_merge`, RHOAI only)

**Execute if** `auto_merge` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_setup_auto_merge.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `pr_raised`, PR URL recorded, label `auto-merge-pr-raised` added). Set `NEW_PRS_RAISED="true"`.
- Exit 2: entries already exist. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 8k: enable-renovate-on-rhoai-component-repo (step key: `renovate`, RHOAI only)

**Execute if** `renovate` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_enable_renovate.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: script updated `pipeline_state.json` (status `pr_raised`, PR URL recorded, label `renovate-pr-raised` added). Set `NEW_PRS_RAISED="true"`.
- Exit 2: entry already exists. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

---

## Step 9: Handle Workflow Triggers

Workflow triggers execute once their dependencies are merged. `onboarder_workflow`
produces a Tekton PR URL that must be tracked (record as `pr_raised`); `renovate_sync`
completes with no URL and is marked `done` immediately.

### Step 9a: run-odh-konflux-onboarder-workflow (step key: `onboarder_workflow`, ODH only)

**Execute if** `onboarder_workflow` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "ODH"`.

The `depends_on: ["krd", "okc"]` check in Step 7 ensures both are merged before this runs.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_odh_onboarder_workflow.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: the script has already updated `pipeline_state.json` (status `pr_raised`, Tekton PR URL recorded, label `tekton-pr-raised` added). Extract `PR_URL` from last line of `$OUTPUT`. Set `NEW_PRS_RAISED="true"`.
- Exit 1: hard failure (workflow dispatch failed, 422, or timeout). Print `$OUTPUT` and stop.

### Step 9b: validate-component-onboarding (step key: `validate_component_onboarding`, RHOAI only)

**Execute if** `validate_component_onboarding` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

The `depends_on: ["bundle"]` check ensures bundle is merged before this runs. Runs the `konflux-config-validator` pytest suite from `rhods-devops-infra` to validate the full Konflux YAML configuration for the release — no cluster access required.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_validate_component_onboarding.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: validation passed. Script updated `pipeline_state.json` (status `done`, label `release-validation-passed`). Set `NEW_PRS_RAISED="true"`.
- Exit 2: already validated. Script updated `pipeline_state.json` (status `done`). Nothing further needed.
- Exit 1: validation failed or setup error. Print `$OUTPUT` and stop. `pipeline_state.json` unchanged; next CI run retries.

### Step 9c: sync-rhoai-renovate-configs (step key: `renovate_sync`, RHOAI only)

**Execute if** `renovate_sync` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

The `depends_on: ["renovate"]` check in Step 7 ensures renovate PR is merged before this runs.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_sync_renovate_configs.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: the script has already updated `pipeline_state.json` (status `done`, labels `renovate-sync-done` added). No URL is produced. Set `NEW_PRS_RAISED="true"` (so Step 11 posts the final Jira comment).
- Exit 1: workflow failed, cancelled, or timed out. Print `$OUTPUT` and stop. `pipeline_state.json` is unchanged; next CI run re-triggers.

---

## Step 10: Check Idle Reminder

If any steps are still in `pr_raised` or `mr_raised` status AND `last_status_change_at`
is set AND the gap exceeds 2 days, tag the assignee with a reminder:

```bash
LAST_CHANGE=$(jq -r '.last_status_change_at // ""' "$PIPELINE_STATE")
IDLE_DAYS=0
if [[ -n "$LAST_CHANGE" ]]; then
  EPOCH_NOW=$(date +%s)
  # macOS-compatible date parsing
  EPOCH_LAST=$(date -jf "%Y-%m-%dT%H:%M:%SZ" "$LAST_CHANGE" +%s 2>/dev/null \
    || date -d "$LAST_CHANGE" +%s 2>/dev/null || echo "$EPOCH_NOW")
  IDLE_DAYS=$(( (EPOCH_NOW - EPOCH_LAST) / 86400 ))
fi

HAS_OPEN=$(jq -r '[.steps | to_entries[] | select(.value.status == "pr_raised" or .value.status == "mr_raised")] | length' "$PIPELINE_STATE")
ASSIGNEE=$(jq -r '.fields.assignee.accountId // ""' "$WORKDIR/component_onboarding_details.json" 2>/dev/null || true)

POST_IDLE_REMINDER="false"
if [[ "$HAS_OPEN" -gt 0 && "$IDLE_DAYS" -ge 2 && -n "$ASSIGNEE" ]]; then
  POST_IDLE_REMINDER="true"
fi
```

---

## Step 11: Post Pending PRs/MRs Summary to Jira

**Only post a comment if something changed this run** (i.e., `NEWLY_MERGED` is non-empty OR
at least one new PR/MR was raised in Step 8). If nothing changed, skip this step entirely —
do not post any comment.

When posting, include only the PRs/MRs that are **still pending** (status `pr_raised` or
`mr_raised`), not the full pipeline table. Tag the assignee if present.

```bash
# Determine whether anything changed this run
SOMETHING_CHANGED="false"
[[ -n "$NEWLY_MERGED" ]] && SOMETHING_CHANGED="true"
# NEW_PRS_RAISED is set to "true" during Step 8 whenever a new PR/MR URL is recorded
[[ "${NEW_PRS_RAISED:-false}" == "true" ]] && SOMETHING_CHANGED="true"

if [[ "$SOMETHING_CHANGED" == "true" ]]; then
  PENDING_COMMENT=$(uv run --script "$SCRIPTS_DIR/build_progress_summary.py" \
    --state           "$PIPELINE_STATE" \
    --component-name  "$COMPONENT_NAME" \
    --product-context "$PRODUCT_CONTEXT" \
    --mode            "pending-only" \
    ${ASSIGNEE:+--assignee "$ASSIGNEE"})

  if [[ -n "$PENDING_COMMENT" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "$PENDING_COMMENT" || true
  fi
fi
```

Set `NEW_PRS_RAISED="true"` in Step 8 immediately after recording any new PR/MR URL into
`pipeline_state.json` so this step can detect it.

---

## Step 12: Resolve or Keep in Review

**Check if all applicable steps are done by reading `$PIPELINE_STATE` with `jq`:**

```bash
ALL_DONE=$(jq -r '
  [.steps | to_entries[] | select(.value.status != "skipped")] |
  all(.value.status == "done" or .value.status == "merged")
' "$PIPELINE_STATE")
```

**If `ALL_DONE == "true"`:**

Post the full table summary as the final comment, then resolve:

```bash
FULL_COMMENT=$(uv run --script "$SCRIPTS_DIR/build_progress_summary.py" \
  --state           "$PIPELINE_STATE" \
  --component-name  "$COMPONENT_NAME" \
  --product-context "$PRODUCT_CONTEXT" \
  --mode            "full")

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment   "$FULL_COMMENT" \
  --add-label "component-onboarding-completed" \
  --status    "Resolved"

echo "[orchestrator] All steps complete — Jira resolved with component-onboarding-completed label."
```

Do not tag the assignee on the resolution comment.

**If `ALL_DONE == "false"` and any PRs/MRs are pending:**

Transition Jira to "Review" (idempotent — safe to call if already in Review):

```bash
bash "$SCRIPTS_DIR/raise_jira_review.sh" \
  --workdir         "$WORKDIR" \
  --jira-url        "$JIRA_URL" \
  --scripts-dir     "$SCRIPTS_DIR" \
  --component-name  "$COMPONENT_NAME" \
  --product-context "$PRODUCT_CONTEXT" \
  ${ASSIGNEE:+--assignee "$ASSIGNEE"}
```

---

## Print Final Summary

```
=== onboard-konflux-components-for-odh-and-rhoai — Run Complete ===

  Component      : <COMPONENT_NAME>
  Product        : <PRODUCT_CONTEXT>
  Jira           : <JIRA_URL>

PRs / MRs:
  quay            : <steps.quay.status> — <steps.quay.mr_url or "not yet raised">
  krd             : <steps.krd.status> — <steps.krd.mr_url or "not yet raised">
  okc             : <steps.okc.status> — <steps.okc.pr_url or "not yet raised">
  pull_pipelines  : <steps.pull_pipelines.status or "N/A (ODH)">
  operator        : <steps.operator.status>
  bundle          : <steps.bundle.status>
  krd_rpa         : <steps.krd_rpa.status or "N/A (ODH)"> — <steps.krd_rpa.mr_url or "not yet raised">
  delivery_repo   : <steps.delivery_repo.status or "N/A (ODH)">
  product_listing : <steps.product_listing.status or "N/A (ODH)">
  auto_merge      : <steps.auto_merge.status or "N/A (ODH)">
  renovate        : <steps.renovate.status or "N/A (ODH)">
  renovate_sync   : <steps.renovate_sync.status or "N/A (ODH)">
  onboarder_workflow: <steps.onboarder_workflow.status or "N/A (RHOAI)">
  validate_component_onboarding : <steps.validate_component_onboarding.status or "N/A (ODH)">

Newly merged this run : <NEWLY_MERGED or "none">
State file            : $PIPELINE_STATE

Re-run this skill after PRs/MRs are merged to advance the pipeline.
```

---

## Error Reference

| Error | Step | Remediation |
|-------|------|-------------|
| Credential not set | 1 | `export <VAR>=<value>` per prerequisites list |
| Tool not installed | 1 | Install per Step 1 guidance |
| `kustomize` not found | 1 | Run `install.sh` (creates kubectl-backed shim) |
| YAML not attached to Jira | 3 | Run `/create-component-onboarding-jira <jira-url>` first |
| YAML fails schema validation | 3 | Fix YAML, re-upload to Jira, re-run skill |
| VPN not active | 4, 8b, 8g, 8h | Activate Red Hat VPN; re-run (idempotent) |
| Quay MR fails 3× | 8a | Check VPN and `GITLAB_TOKEN` `api` scope |
| Delivery repo MR fails 3× | 8b | Check VPN and GITLAB_TOKEN `write_repository` scope |
| KRD MR fails | 8c | Check VPN; `GITLAB_TOKEN` needs `write_repository` scope |
| OKC/RKC PR fails | 8d | Verify `GITHUB_TOKEN` `repo` scope and push access |
| Pull pipelines PR fails 3× | 8e | Check GITHUB_TOKEN push access to rhoai-konflux-central |
| Operator PR fails | 8f | Verify `GITHUB_TOKEN` push access to `opendatahub-operator` |
| Bundle PR fails | 8g | Verify `GITHUB_TOKEN` push access to `ODH-Build-Config` |
| Product listing MR fails | 8h | Check VPN; delivery_repo must be merged first |
| Onboarder workflow 422 | 9a | krd or okc not yet merged — check their status and re-run |
| Build verify: EXT_OC_TOKEN expired | 9b | Export fresh `EXT_OC_TOKEN` from stone-prd-rh01 console; re-run |
| Build verify: timeout | 9b | PipelineRun did not appear — check PAC config and re-run |
| Build verify: PipelineRun failed | 9b | Check build URL in Jira comment; fix Dockerfile/lockfile; re-run |
| Auto-merge PR fails 3× | 8i | Check GITHUB_TOKEN push access to rhods-devops-infra |
| Renovate PR fails 3× | 8j | Check GITHUB_TOKEN push access to rhoai-konflux-central |
| Renovate sync workflow 403 | 9b | GITHUB_TOKEN needs `actions:write` scope |
| Jira `--status "Resolved"` fails | 13 | Check available Jira transitions |
| State lost / fresh checkout | Any | Re-run; Step 5 restores state from Jira labels |
| PR/MR still not detected merged | 6 | Check if URL in pipeline_state.json is correct; verify API connectivity |
