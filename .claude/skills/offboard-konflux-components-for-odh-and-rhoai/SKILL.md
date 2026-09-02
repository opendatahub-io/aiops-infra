---
name: offboard-konflux-components-for-odh-and-rhoai
description: Master orchestrator skill for the full ODH/RHOAI component offboarding pipeline. Idempotent — run any number of times for the same Jira. Each run syncs PR/MR state, executes newly-unblocked steps, and posts a summary of what changed. Transitions Jira through In Progress → Review → Resolved automatically.
allowed-tools: Bash
user-invocable: true
---

> **WARNING:** This skill is not designed to be invoked manually from user playpen.
> Only run `offboard-konflux-components-for-odh-and-rhoai` directly if you know what you are doing.

# Offboard Konflux Components for ODH and RHOAI

Orchestrates the complete component offboarding pipeline (idempotent re-run model):

1. `validate-component-offboarding-jira` — fetch + validate Jira YAML
2. `remove-from-krd` — GitLab MR to konflux-release-data (remove Component from PDS YAML, RPA files, automation)
3. `remove-from-okc` — GitHub PR to remove push PipelineRun from Konflux Central
4. `remove-pull-pipelines` — GitHub PR to remove pull-request PipelineRun **(RHOAI only)**
5. `remove-from-bundle` — GitHub PR to remove relatedImages + build-config entries
6. `remove-from-operator` — GitHub PR to remove operator manifests **(if is_operator=true)**
7. `sync-component-tekton` — GitHub PR(s) to remove stale PipelineRun files from the component repo's `.tekton/` **(after OKC/pull-pipeline PRs are merged)**
8. `remove-component-cr` — Delete Konflux Component CR from OpenShift cluster **(after all other steps are done; requires confirmation)**

Steps 2–6 are independent and can run in parallel. Step 7 depends on steps 3–4
being merged. Step 8 depends on all prior steps and requires human confirmation.

**Re-run model:** invoke this skill any number of times for the same Jira URL.
Each run checks Jira labels and PR/MR API status to determine what's already done,
executes pending steps, and posts a summary of status changes only.

## Usage

```
/offboard-konflux-components-for-odh-and-rhoai <jira-url>
```

## Prerequisites

**Jira:** `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`
**GitLab (VPN required):** `GITLAB_USER`, `GITLAB_TOKEN` (api + write_repository scope)
**GitHub:** `GITHUB_USER`, `GITHUB_TOKEN` (repo scope)
**OpenShift:** Handled automatically — the skill prompts for `oc login --web` if no valid session exists
**Tools:** `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize` (or `kubectl`)

**VPN:** Checked automatically at startup — the skill verifies connectivity to gitlab.cee.redhat.com.

## Dry Run

Set `OFFBOARD_DRY_RUN=true` to test the full pipeline end-to-end. All PRs/MRs are
created with "[DRY RUN]" in the title, Jira comments are prefixed with "[DRY RUN]",
and the Component CR deletion step is skipped (prints what it would do).

```bash
export OFFBOARD_DRY_RUN=true
/offboard-konflux-components-for-odh-and-rhoai <test-jira-url>
```

Clean up after testing: close the dry-run PRs/MRs and delete their branches.

## Implementation

---

## Locate Scripts Directory

```bash
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
  echo "  Usage: /offboard-konflux-components-for-odh-and-rhoai <jira-url>"
  exit 1
}
echo "Jira ID  : $JIRA_ID"
echo "Jira URL : $JIRA_URL"
```

---

## Step 1: Check Prerequisites

### Step 1a: Tools and credentials

```bash
bash "$SCRIPTS_DIR/check_offboarding_prerequisites.sh" \
  --env "JIRA_USER_EMAIL JIRA_API_TOKEN GITLAB_USER GITLAB_TOKEN GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git oc skopeo yamllint jq kustomize"

[[ -x "${HOME}/.local/bin/kustomize" ]] && export PATH="${HOME}/.local/bin:${PATH}"
```

### Step 1b: VPN connectivity

```bash
bash "$SCRIPTS_DIR/check_offboarding_prerequisites.sh" --vpn
```

On exit 1: tell the user to connect to the Red Hat VPN and re-run. Stop.

### Step 1c: OpenShift cluster login

Determine the cluster from the Jira (RHOAI → `internal`, ODH → `external`).
The product context is not yet parsed at this point, so check both or default to
`internal` (most common). If the validate step has already run and we can read the
YAML, derive it from `product_context`. Otherwise, default to `internal`.

```bash
OC_CLUSTER="internal"
bash "$SCRIPTS_DIR/check_offboarding_prerequisites.sh" --oc-login "$OC_CLUSTER"
OC_EXIT=$?
```

On exit 0: already authenticated — continue.

On exit 2 (`OC_LOGIN_NEEDED`): the user needs to log in interactively.
Tell the user:

> You need to log in to the OpenShift cluster. Please run this command:
> ```
> ! oc login --web <OC_API_SERVER>
> ```
> This will open a browser for authentication.

**Wait for the user to confirm they have logged in.** Then capture the token:

```bash
export <OC_TOKEN_VAR>=$(oc whoami -t)
```

Verify the login succeeded:

```bash
bash "$SCRIPTS_DIR/check_offboarding_prerequisites.sh" --oc-login "$OC_CLUSTER"
```

On failure again: stop with an error.

### Step 1d: Set active oc project

Once login is confirmed (whether it was already authenticated or completed interactively),
always switch the active project to the RHOAI tenant namespace so subsequent `oc` commands
default to it:

```bash
oc project rhoai-tenant
```

If this fails (e.g. the namespace is not visible on the current cluster), print a warning
and continue — the removal steps still target their namespace explicitly with `-n`.

---

## Step 2: Set Up Working Directory and Initialize State

```bash
_INIT_VARS=$(bash "$SCRIPTS_DIR/init_offboarding_pipeline.sh" --jira-url "$JIRA_URL")
eval "$_INIT_VARS"
echo "Working directory: $WORKDIR"
echo "Pipeline state: $PIPELINE_STATE"
```

`$PIPELINE_STATE` is the **full path** to `pipeline_state.json`.

---

## Step 3: Sub-skill — validate-component-offboarding-jira

**Skip if** `steps.validate.status == "done"` in `pipeline_state.json`.

Invoke the validate skill directly:

```bash
export SCRIPTS_DIR="$SCRIPTS_DIR"
# Read the validate-component-offboarding-jira skill at:
#   ~/.claude/skills/validate-component-offboarding-jira/SKILL.md
# Follow every step for: $JIRA_URL
```

On success:
- `$WORKDIR/component_offboarding_details.json` and `$WORKDIR/component_offboarding_details.yaml` exist
- Jira is in "In Progress" status
- Update pipeline state:
  ```bash
  bash "$SCRIPTS_DIR/pipeline_state.sh" set \
    --state "$PIPELINE_STATE" --step validate --field status --value "done"
  ```

On failure: **hard blocker**. Display the error and stop.

---

## Step 4: Parse Component Details and Derive Variables

```bash
_COMP_VARS=$(bash "$SCRIPTS_DIR/parse_offboarding_details.sh" \
  --workdir        "$WORKDIR" \
  --jira-id        "$JIRA_ID" \
  --scripts-dir    "$SCRIPTS_DIR")
eval "$_COMP_VARS"
# Sets: COMPONENT_NAME IS_OPERATOR REPO_URL PRODUCT_CONTEXT QUAY_ORG
```

After parsing, update the state for product-context-specific skip logic:

```bash
bash "$SCRIPTS_DIR/init_offboarding_pipeline.sh" \
  --jira-url          "$JIRA_URL" \
  --workdir-override  "$WORKDIR" \
  --product-context   "$PRODUCT_CONTEXT" \
  --component-name    "$COMPONENT_NAME" \
  --is-operator       "$IS_OPERATOR" \
  > /dev/null
```

On exit 1: display stderr and stop.

---

## Step 5: Check Current PR/MR Status

For all steps in `pr_raised` or `mr_raised` state, query the GitHub/GitLab API and
update `pipeline_state.json`:

```bash
NEWLY_MERGED=$(bash "$SCRIPTS_DIR/check_offboarding_pr_mr_status.sh" \
  --state      "$PIPELINE_STATE" \
  --scripts-dir "$SCRIPTS_DIR")
```

For each newly merged step, add its `label_done` Jira label:

```bash
for MERGED_KEY in $NEWLY_MERGED; do
  DONE_LABEL=$(jq -r --arg k "$MERGED_KEY" '.steps[$k].label_done // ""' "$PIPELINE_STATE")
  RAISED_LABEL=$(jq -r --arg k "$MERGED_KEY" '.steps[$k].label_raised // ""' "$PIPELINE_STATE")
  LABEL_ARGS=()
  [[ -n "$DONE_LABEL" ]]   && LABEL_ARGS+=("--add-label"    "$DONE_LABEL")
  [[ -n "$RAISED_LABEL" ]] && LABEL_ARGS+=("--remove-label" "$RAISED_LABEL")
  if [[ "${#LABEL_ARGS[@]}" -gt 0 ]]; then
    uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
      "${LABEL_ARGS[@]}" || true
  fi
done
```

---

## Step 6: Compute Unblocked Steps

A step is **executable** if its `status` is `"pending"` and all `depends_on` items are
`"merged"` or `"done"`. For offboarding, all steps have empty `depends_on`, so all
pending steps are immediately executable.

```bash
UNBLOCKED_STEPS=$(jq -r '
  .steps as $steps |
  $steps | to_entries[] |
  select(.value.status == "pending") |
  select(
    .value.depends_on | all(. as $dep |
      $steps[$dep].status == "merged" or $steps[$dep].status == "done" or $steps[$dep].status == "skipped"
    )
  ) | .key
' "$PIPELINE_STATE")
```

---

## Step 7: Execute Pending Unblocked Steps

For each step in `UNBLOCKED_STEPS`, call the corresponding wrapper script.

Track whether any PR/MR was raised this run:
```bash
NEW_PRS_RAISED="false"
```

### Step 7a: remove-from-krd (step key: `remove_krd`)

**Execute if** `remove_krd` is in `UNBLOCKED_STEPS`.

> **VPN must be active.**

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_from_krd.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: MR raised. Extract `MR_URL` from output. Set `NEW_PRS_RAISED="true"`.
- Exit 2: already removed. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 7b: remove-from-okc (step key: `remove_okc`)

**Execute if** `remove_okc` is in `UNBLOCKED_STEPS`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_from_okc.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: PR raised. Set `NEW_PRS_RAISED="true"`.
- Exit 2: already removed. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 7c: remove-pull-pipelines (step key: `remove_pull_pipelines`, RHOAI only)

**Execute if** `remove_pull_pipelines` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_pull_pipelines.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: PR raised. Set `NEW_PRS_RAISED="true"`.
- Exit 2: already removed. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 7d: remove-from-bundle (step key: `remove_bundle`)

**Execute if** `remove_bundle` is in `UNBLOCKED_STEPS`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_from_bundle.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: PR raised. Set `NEW_PRS_RAISED="true"`.
- Exit 2: already removed. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 7e: remove-from-operator (step key: `remove_operator`)

**Execute if** `remove_operator` is in `UNBLOCKED_STEPS`.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_from_operator.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: PR raised. Set `NEW_PRS_RAISED="true"`.
- Exit 2: skipped (is_operator=false) or already removed. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 7h: sync-component-tekton (step key: `sync_component_tekton`)

**Execute if** `sync_component_tekton` is in `UNBLOCKED_STEPS`. This step has `depends_on`
`remove_okc` and `remove_pull_pipelines` — it only unblocks when both are `done`/`merged`/`skipped`.

The sync-pipelineruns workflow only copies files (`cp -rf`) from konflux-central to
the component repo — it never deletes. After OKC/pull-pipeline PRs merge, the stale
PipelineRun files remain in the component repo's `.tekton/`. This step raises PR(s)
to the component repo to remove them.

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_sync_component_tekton.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0: PR(s) raised. Set `NEW_PRS_RAISED="true"`.
- Exit 2: already clean. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

### Step 7i: remove-component-cr (step key: `remove_component_cr`)

**Execute if** `remove_component_cr` is in `UNBLOCKED_STEPS`. This step has `depends_on`
all other removal steps — it only unblocks when everything else is `done` or `merged`.

**This step requires human confirmation.** First run without `--confirm` to show what
will be deleted. Display the output to the user and ask them to confirm. Only if they
confirm, re-run with `--confirm`.

```bash
# First: show what will be deleted
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_component_cr.sh" --jira-url "$JIRA_URL")
EXIT_CODE=$?
```

- Exit 0 (without --confirm): prints confirmation summary. **Show this to the user and ask
  "Do you want to proceed with deleting the Component CR?"**. If they confirm:

```bash
OUTPUT=$(WORKDIR="$WORKDIR" PIPELINE_STATE="$PIPELINE_STATE" bash "$SCRIPTS_DIR/run_step_remove_component_cr.sh" --jira-url "$JIRA_URL" --confirm)
EXIT_CODE=$?
```

- Exit 0 (with --confirm): Component CR deleted.
- Exit 2: already removed. Nothing further needed.
- Exit 1: hard failure. Print `$OUTPUT` and stop.

**CRITICAL — Exit 1 handling:** On exit 1, print the output, post a Jira comment, and
**immediately stop**. Do not print a final summary, do not check remaining steps.
The wrapper scripts are self-contained; editing scripts mid-run is strictly forbidden.

---

## Step 8: Post Pending PRs/MRs Summary to Jira

**Only post a comment if something changed this run** (i.e., `NEWLY_MERGED` is non-empty OR
at least one new PR/MR was raised).

```bash
SOMETHING_CHANGED="false"
[[ -n "$NEWLY_MERGED" ]] && SOMETHING_CHANGED="true"
[[ "${NEW_PRS_RAISED:-false}" == "true" ]] && SOMETHING_CHANGED="true"

if [[ "$SOMETHING_CHANGED" == "true" ]]; then
  PENDING_COMMENT=$(uv run --script "$SCRIPTS_DIR/build_offboarding_progress_summary.py" \
    --state           "$PIPELINE_STATE" \
    --component-name  "$COMPONENT_NAME" \
    --product-context "$PRODUCT_CONTEXT" \
    --mode            "pending-only")

  if [[ -n "$PENDING_COMMENT" ]]; then
    uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
      --comment "$PENDING_COMMENT" || true
  fi
fi
```

---

## Step 9: Resolve or Keep in Review

**Check if all applicable steps are done:**

```bash
ALL_DONE=$(jq -r '
  [.steps | to_entries[] | select(.value.status != "skipped")] |
  all(.value.status == "done" or .value.status == "merged")
' "$PIPELINE_STATE")
```

**If `ALL_DONE == "true"`:**

```bash
FULL_COMMENT=$(uv run --script "$SCRIPTS_DIR/build_offboarding_progress_summary.py" \
  --state           "$PIPELINE_STATE" \
  --component-name  "$COMPONENT_NAME" \
  --product-context "$PRODUCT_CONTEXT" \
  --mode            "full")

uv run --script "$SCRIPTS_DIR/update_offboarding_jira.py" "$JIRA_URL" \
  --comment   "$FULL_COMMENT" \
  --add-label "component-offboarding-completed" \
  --status    "Resolved"

echo "[orchestrator] All steps complete — Jira resolved with component-offboarding-completed label."
```

**If `ALL_DONE == "false"` and any PRs/MRs are pending:**

Transition Jira to "Review":

```bash
bash "$SCRIPTS_DIR/raise_offboarding_jira_review.sh" \
  --workdir         "$WORKDIR" \
  --jira-url        "$JIRA_URL" \
  --scripts-dir     "$SCRIPTS_DIR" \
  --component-name  "$COMPONENT_NAME" \
  --product-context "$PRODUCT_CONTEXT"
```

---

## Print Final Summary

```
=== offboard-konflux-components-for-odh-and-rhoai — Run Complete ===

  Component      : <COMPONENT_NAME>
  Product        : <PRODUCT_CONTEXT>
  Jira           : <JIRA_URL>

PRs / MRs:
  remove_krd            : <steps.remove_krd.status> — <steps.remove_krd.mr_url or "not yet raised">
  remove_okc            : <steps.remove_okc.status> — <steps.remove_okc.pr_url or "not yet raised">
  remove_pull_pipelines : <steps.remove_pull_pipelines.status or "N/A (ODH)">
  remove_bundle         : <steps.remove_bundle.status> — <steps.remove_bundle.pr_url or "not yet raised">
  remove_operator       : <steps.remove_operator.status>
  sync_component_tekton : <steps.sync_component_tekton.status> — <steps.sync_component_tekton.pr_url or "not yet raised">
  remove_component_cr   : <steps.remove_component_cr.status>

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
| YAML not attached to Jira | 3 | Run `/create-component-offboarding-jira <jira-url>` first |
| YAML fails schema validation | 3 | Fix YAML, re-upload to Jira, re-run |
| VPN not active | 7a | Activate Red Hat VPN; re-run (idempotent) |
| KRD MR fails | 7a | Check VPN; GITLAB_TOKEN needs write_repository scope |
| OKC/RKC PR fails | 7b | Verify GITHUB_TOKEN repo scope and push access |
| Pull pipelines PR fails | 7c | Check GITHUB_TOKEN push access to rhoai-konflux-central |
| Bundle PR fails | 7d | Verify GITHUB_TOKEN push access to build-config repo |
| Operator PR fails | 7e | Verify GITHUB_TOKEN push access to operator repo |
| Tekton cleanup PR fails | 7h | Verify GITHUB_TOKEN push access to the component repo |
| State lost / fresh checkout | Any | Re-run; pipeline state rebuilt from Jira labels |
