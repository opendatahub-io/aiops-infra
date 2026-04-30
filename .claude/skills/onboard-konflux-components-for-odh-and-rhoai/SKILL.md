---
name: onboard-konflux-components-for-odh-and-rhoai
description: Master orchestrator skill for the full ODH/RHOAI component onboarding pipeline. Idempotent — run any number of times for the same Jira. Each run syncs PR/MR state, executes newly-unblocked steps, and posts a summary of what changed. Transitions Jira through In Progress → Review → Resolved automatically.
allowed-tools: Bash
user-invocable: true
---

# Onboard Konflux Components for ODH and RHOAI

Orchestrates the complete component onboarding pipeline (idempotent re-run model):

1. `validate-component-onboarding-jira` — fetch + validate Jira YAML
2. `create-quay-repo` — GitLab MR to app-interface
3. `onboard-component-to-konflux-release-data` — GitLab MR to konflux-release-data
4. `add-component-to-odh-konflux-central` **(ODH)** / `add-component-to-rhoai-konflux-central` + `create-pull-pipelines-in-rhoai-konflux-central` **(RHOAI)**
5. `run-odh-konflux-onboarder-workflow` — triggered once krd+okc are both merged **(ODH only)**
6. `integrate-component-with-odh-operator` — GitHub PR (if is_operator=true)
7. `integrate-component-with-bundle` — GitHub PR to ODH-Build-Config
8. `create-rhoai-delivery-repo` — GitLab MR to pyxis-repo-configs **(RHOAI only)**
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
**OpenShift:** `OC_TOKEN` (if no matching kubeconfig context for Konflux cluster)
**Tools:** `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize` (or `kubectl`)

Optional overrides: `APP_INTERFACE_REPO_URL`, `KONFLUX_RELEASE_DATA_REPO_URL`,
`ODH_KONFLUX_CENTRAL_REPO_URL`, `ODH_OPERATOR_REPO_URL`, `OBC_REPO_URL`, `JIRA_SERVER`,
`RHOAI_KONFLUX_CENTRAL_REPO_URL` (used by Steps 7/8 RHOAI; default: `https://github.com/red-hat-data-services/konflux-central.git`),
`PYXIS_REPO_CONFIGS_REPO_URL` (used by Steps 9/10 RHOAI; default: `https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git`),
`RHODS_DEVOPS_INFRA_REPO_URL` (used by Step 11 RHOAI; default: `https://github.com/red-hat-data-services/rhods-devops-infra.git`)

**VPN must be active** before running — required for Steps 3, 4, and 10 (GitLab on gitlab.cee.redhat.com).

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.
VALIDATE_SKILL_DIR is `<SKILL_DIR>/../validate-component-onboarding-jira`.

---

## Step 0: Parse Inputs

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/parse_jira_url.sh" "${1:-}")"
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
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "JIRA_USER_EMAIL JIRA_API_TOKEN GITLAB_USER GITLAB_TOKEN GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git oc skopeo yamllint jq kustomize"

[[ -x "${HOME}/.local/bin/kustomize" ]] && export PATH="${HOME}/.local/bin:${PATH}"
```

---

## Step 2: Set Up Working Directory and Initialize State

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_pipeline.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
echo "Pipeline state: $PIPELINE_STATE"
```

(Full `--product-context` and `--component-name` are passed after Step 4 parses the YAML;
`init_pipeline.sh` handles both fresh creation and resumption of an existing state file.)

---

## Step 3: Sub-skill — validate-component-onboarding-jira

**Skip if** `steps.validate.status == "done"` in `pipeline_state.json`.

Follow the `validate-component-onboarding-jira` child skill's implementation exactly.

On success:
- `$WORKDIR/component_onboarding_details.json` and `$WORKDIR/component_onboarding_details.yaml` exist
- Jira is in "In Progress" status
- Update pipeline state:
  ```bash
  bash "$COMMON_SCRIPTS_DIR/pipeline_state.sh" set \
    --state "$PIPELINE_STATE" --step validate --field status --value "done"
  ```

On failure: **hard blocker**. Display the child skill's error and stop.

---

## Step 4: Parse Component Details and Derive Computed Variables

**Skip computation if** `component_name` is already non-empty in `pipeline_state.json`, but still read variables from the YAML into shell for use in later steps.

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/parse_component_details.sh" \
  --workdir        "$WORKDIR" \
  --jira-id        "$JIRA_ID" \
  --scripts-dir    "$COMMON_SCRIPTS_DIR" \
  --pipeline-state "$PIPELINE_STATE")"
# Sets: COMPONENT_NAME IS_OPERATOR REPO_URL REPO_BRANCH
#       PRODUCT_CONTEXT QUAY_ORG QUAY_VISIBILITY QUAY_REPO_URI
```

After parsing, update the state schema for any steps not yet in the file
(handles old state files missing new steps):

```bash
bash "$COMMON_SCRIPTS_DIR/init_pipeline.sh" \
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

## Step 5: Sync State from Jira Labels

Reconstruct `pipeline_state.json` from Jira labels (durable even after a fresh checkout)
and extract any PR/MR URLs from Jira comments that aren't already in state:

```bash
uv run --script "$COMMON_SCRIPTS_DIR/sync_state_from_jira.py" \
  --jira-details   "$WORKDIR/component_onboarding_details.json" \
  --pipeline-state "$PIPELINE_STATE"
```

This is non-fatal. If it fails (e.g., JSON parse error), print a warning and continue.

---

## Step 6: Check Current PR/MR Status

For all steps in `pr_raised` or `mr_raised` state, query the GitHub/GitLab API
(one call per step, `--check-only` mode) and update `pipeline_state.json`:

```bash
NEWLY_MERGED=$(bash "$COMMON_SCRIPTS_DIR/check_pr_mr_status.sh" \
  --state      "$PIPELINE_STATE" \
  --scripts-dir "$COMMON_SCRIPTS_DIR")
```

`NEWLY_MERGED` is a newline-separated list of step keys that transitioned to `"merged"`
this run (e.g., `quay\nkrd`). Empty string means no changes.

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

For each step in `UNBLOCKED_STEPS`, follow the corresponding child skill's implementation
through to and including the PR/MR creation step only (do NOT call any blocking monitor).
After the PR/MR URL is captured, record it in `pipeline_state.json` and add the `label_raised`
label to Jira.

**General pattern for each child skill invocation:**

```bash
# 1. If pr_url/mr_url already set in pipeline_state.json, step is already "pr_raised" — skip
URL_FIELD=$(jq -r ".steps.${STEP_KEY}.pr_url // .steps.${STEP_KEY}.mr_url // \"\"" "$PIPELINE_STATE")
if [[ -n "$URL_FIELD" ]]; then
  echo "[orchestrator] $STEP_KEY already has URL $URL_FIELD — skipping PR raise"
  continue
fi

# 2. Invoke child skill's implementation (raises PR, captures URL)
# 3. Record result:
TMP=$(mktemp); NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq --arg k "$STEP_KEY" --arg u "$PR_URL" --arg s "pr_raised" --arg ts "$NOW" \
  '.steps[$k].pr_url = $u | .steps[$k].status = $s | .last_status_change_at = $ts' \
  "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"

# 4. Add label_raised to Jira
LABEL_RAISED=$(jq -r ".steps.${STEP_KEY}.label_raised // \"\"" "$PIPELINE_STATE")
[[ -n "$LABEL_RAISED" ]] && uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" \
  "$JIRA_URL" --add-label "$LABEL_RAISED" || true
```

### Step 8a: create-quay-repo (step key: `quay`)

**Execute if** `quay` is in `UNBLOCKED_STEPS`.

Follow `create-quay-repo` through **Step 9** (Raise MR). Capture `$MR_URL`.
Record in `pipeline_state.json`: `steps.quay.mr_url = "$MR_URL"`, `status = "mr_raised"`.
Add label `quay-mr-raised` to Jira.

If child exits because Quay repo already exists (Step 3 of child):
set `steps.quay.status = "done"` and add label `quay-mr-merged`.

**Pass `--existing-mr-url`** if `steps.quay.mr_url` is already set — child will skip straight to returning the URL.

### Step 8b: onboard-component-to-konflux-release-data (step key: `krd`)

**Execute if** `krd` is in `UNBLOCKED_STEPS`.

> **VPN must be active.**

Follow `onboard-component-to-konflux-release-data` through **Step 9** (Raise MR). Capture `$MR_URL`.
Record: `steps.krd.mr_url = "$MR_URL"`, `status = "mr_raised"`.
Add label `konflux-mr-raised` to Jira.

If child exits because component already exists: set `status = "done"`, add label `konflux-mr-merged`.

### Step 8c: add-component-to-*-konflux-central (step key: `okc`)

**Execute if** `okc` is in `UNBLOCKED_STEPS`.

**If `PRODUCT_CONTEXT == "ODH"`:** follow `add-component-to-odh-konflux-central` through PR raise.
Record: `steps.okc.pr_url = "$PR_URL"`, `status = "pr_raised"`. Add label `okc-pr-raised`.

**If `PRODUCT_CONTEXT == "RHOAI"`:** follow `add-component-to-rhoai-konflux-central` through
**Step 10** (Raise PR). The child derives `$BRANCH_NAME` from `target_rhoai_version` in Step 3f —
allow this derivation to proceed.
Record: `steps.okc.pr_url = "$PR_URL"`, `status = "pr_raised"`. Add label `rkc-pr-raised`.

If child exits because PipelineRun already exists: set `status = "done"`.

### Step 8d: create-pull-pipelines-in-rhoai-konflux-central (step key: `pull_pipelines`, RHOAI only)

**Execute if** `pull_pipelines` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

Follow `create-pull-pipelines-in-rhoai-konflux-central` through **Step 10** (Raise PR). Capture `$PULL_PR_URL`.
Record: `steps.pull_pipelines.pr_url = "$PULL_PR_URL"`, `status = "pr_raised"`. Add label `rkc-pull-pr-raised`.

If PipelineRun already exists: set `status = "done"`.

### Step 8e: integrate-component-with-odh-operator (step key: `operator`)

**Execute if** `operator` is in `UNBLOCKED_STEPS`.

If `IS_OPERATOR == false`: child exits at Step 4a — set `status = "skipped"`.

If `IS_OPERATOR == true`: follow through to Step 9 (Raise PR). Capture `$PR_URL`.
Record: `steps.operator.pr_url = "$PR_URL"`, `status = "pr_raised"`. Add label `operator-pr-raised`.

### Step 8f: integrate-component-with-bundle (step key: `bundle`)

**Execute if** `bundle` is in `UNBLOCKED_STEPS`.

Follow `integrate-component-with-bundle` through **Step 10** (Raise PR). Capture `$PR_URL`.
Record: `steps.bundle.pr_url = "$PR_URL"`, `status = "pr_raised"`. Add label `bundle-pr-raised`.

### Step 8g: create-rhoai-delivery-repo (step key: `delivery_repo`, RHOAI only)

**Execute if** `delivery_repo` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

> **VPN must be active.**

Follow `create-rhoai-delivery-repo` through **Step 10** (Raise MR). Capture `$MR_URL`.
Record: `steps.delivery_repo.mr_url = "$MR_URL"`, `status = "mr_raised"`. Add label `delivery-repo-mr-raised`.

If delivery repo already exists (child Step 5 exits 0): set `status = "done"`, add label `delivery-repo-exists`.

### Step 8h: update-rhoai-product-listing (step key: `product_listing`, RHOAI only)

**Execute if** `product_listing` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

> **VPN must be active. Only runs after `delivery_repo` status == "merged" or "done".**

Follow `update-rhoai-product-listing` through the MR raise step. Capture `$MR_URL`.
Record: `steps.product_listing.mr_url = "$MR_URL"`, `status = "mr_raised"`. Add label `product-listing-mr-raised`.

If entry already exists: set `status = "done"`, add label `product-listing-exists`.

### Step 8i: setup-auto-merge (step key: `auto_merge`, RHOAI only)

**Execute if** `auto_merge` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

Follow `setup-auto-merge` through **Step 9** (Raise PR). Capture `$PR_URL`.
Record: `steps.auto_merge.pr_url = "$PR_URL"`, `status = "pr_raised"`. Add label `auto-merge-pr-raised`.

If entries already exist: set `status = "done"`.

### Step 8j: enable-renovate-on-rhoai-component-repo (step key: `renovate`, RHOAI only)

**Execute if** `renovate` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

Follow `enable-renovate-on-rhoai-component-repo` through **Step 9** (Raise PR). Capture `$PR_URL`.
Record: `steps.renovate.pr_url = "$PR_URL"`, `status = "pr_raised"`. Add label `renovate-pr-raised`.

If entry already exists: set `status = "done"`.

---

## Step 9: Handle Workflow Triggers

Workflow triggers are not PRs — they execute once their dependencies are merged and
produce no URL to track. Mark as `"done"` immediately after triggering.

### Step 9a: run-odh-konflux-onboarder-workflow (step key: `onboarder_workflow`, ODH only)

**Execute if** `onboarder_workflow` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "ODH"`.

The `depends_on: ["krd", "okc"]` check in Step 7 ensures both are merged before this runs.

Follow `run-odh-konflux-onboarder-workflow` completely. On success:
```bash
TMP=$(mktemp); NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq --arg ts "$NOW" \
  '.steps.onboarder_workflow.status = "done" | .last_status_change_at = $ts' \
  "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "onboarder-workflow-triggered" || true
```

### Step 9b: sync-rhoai-renovate-configs (step key: `renovate_sync`, RHOAI only)

**Execute if** `renovate_sync` is in `UNBLOCKED_STEPS` and `PRODUCT_CONTEXT == "RHOAI"`.

The `depends_on: ["renovate"]` check in Step 7 ensures renovate PR is merged before this runs.

```bash
RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"
```

Follow `sync-rhoai-renovate-configs` completely. On success:
```bash
TMP=$(mktemp); NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq --arg ts "$NOW" \
  '.steps.renovate_sync.status = "done" | .last_status_change_at = $ts' \
  "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "renovate-sync-triggered" || true
```

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
  PENDING_COMMENT=$(uv run --script "$COMMON_SCRIPTS_DIR/build_progress_summary.py" \
    --state           "$PIPELINE_STATE" \
    --component-name  "$COMPONENT_NAME" \
    --product-context "$PRODUCT_CONTEXT" \
    --mode            "pending-only" \
    ${ASSIGNEE:+--assignee "$ASSIGNEE"})

  if [[ -n "$PENDING_COMMENT" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "$PENDING_COMMENT" || true
  fi
fi
```

Set `NEW_PRS_RAISED="true"` in Step 8 immediately after recording any new PR/MR URL into
`pipeline_state.json` so this step can detect it.

---

## Step 12: Resolve or Keep in Review

**Check if all applicable steps are done:**

```bash
ALL_DONE=$(jq -r '
  [.steps | to_entries[] | select(.value.status != "skipped")] |
  all(.value.status == "done" or .value.status == "merged")
' "$PIPELINE_STATE")
```

**If `ALL_DONE == "true"`:**

Post the full table summary as the final comment, then resolve:

```bash
FULL_COMMENT=$(uv run --script "$COMMON_SCRIPTS_DIR/build_progress_summary.py" \
  --state           "$PIPELINE_STATE" \
  --component-name  "$COMPONENT_NAME" \
  --product-context "$PRODUCT_CONTEXT" \
  --mode            "full")

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment   "$FULL_COMMENT" \
  --add-label "component-onboarding-completed" \
  --status    "Resolved"

echo "[orchestrator] All steps complete — Jira resolved with component-onboarding-completed label."
```

Do not tag the assignee on the resolution comment.

**If `ALL_DONE == "false"` and any PRs/MRs are pending:**

Transition Jira to "Review" (idempotent — safe to call if already in Review):

```bash
bash "$COMMON_SCRIPTS_DIR/raise_jira_review.sh" \
  --workdir         "$WORKDIR" \
  --jira-url        "$JIRA_URL" \
  --scripts-dir     "$COMMON_SCRIPTS_DIR" \
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
  delivery_repo   : <steps.delivery_repo.status or "N/A (ODH)">
  product_listing : <steps.product_listing.status or "N/A (ODH)">
  auto_merge      : <steps.auto_merge.status or "N/A (ODH)">
  renovate        : <steps.renovate.status or "N/A (ODH)">
  renovate_sync   : <steps.renovate_sync.status or "N/A (ODH)">
  onboarder_workflow: <steps.onboarder_workflow.status or "N/A (RHOAI)">

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
| KRD MR fails | 8b | Check VPN; `GITLAB_TOKEN` needs `write_repository` scope |
| OKC/RKC PR fails | 8c | Verify `GITHUB_TOKEN` `repo` scope and push access |
| Pull pipelines PR fails 3× | 8d | Check GITHUB_TOKEN push access to rhoai-konflux-central |
| Operator PR fails | 8e | Verify `GITHUB_TOKEN` push access to `opendatahub-operator` |
| Bundle PR fails | 8f | Verify `GITHUB_TOKEN` push access to `ODH-Build-Config` |
| Delivery repo MR fails 3× | 8g | Check VPN and GITLAB_TOKEN `write_repository` scope |
| Product listing MR fails | 8h | Check VPN; delivery_repo must be merged first |
| Onboarder workflow 422 | 9a | krd or okc not yet merged — check their status and re-run |
| Auto-merge PR fails 3× | 8i | Check GITHUB_TOKEN push access to rhods-devops-infra |
| Renovate PR fails 3× | 8j | Check GITHUB_TOKEN push access to rhoai-konflux-central |
| Renovate sync workflow 403 | 9b | GITHUB_TOKEN needs `actions:write` scope |
| Jira `--status "Resolved"` fails | 13 | Check available Jira transitions |
| State lost / fresh checkout | Any | Re-run; Step 5 restores state from Jira labels |
| PR/MR still not detected merged | 6 | Check if URL in pipeline_state.json is correct; verify API connectivity |
