---
name: onboard-konflux-components-for-odh-and-rhoai
description: Master orchestrator skill for the full ODH/RHOAI component onboarding pipeline. Takes a single Jira URL and coordinates 7 sub-skills in sequence with background PR/MR monitoring. Transitions Jira through In Progress -> Review -> Resolved automatically.
allowed-tools: Bash
user-invocable: true
---

# Onboard Konflux Components for ODH and RHOAI

Orchestrates the complete component onboarding pipeline:

1. `validate-component-onboarding-jira` — fetch + validate Jira YAML
2. `create-quay-repo` — GitLab MR to app-interface
3. `onboard-component-to-konflux-release-data` — GitLab MR to konflux-release-data
4. `add-component-to-odh-konflux-central` **(ODH)** / `add-component-to-rhoai-konflux-central` **(RHOAI)** — GitHub PR for Tekton pipelineruns
5. `run-odh-konflux-onboarder-workflow` — GitHub Actions workflow (deferred, background; **ODH only**)
6. `integrate-component-with-odh-operator` — GitHub PR to opendatahub-operator (if operator)
7. `integrate-component-with-bundle` — GitHub PR to ODH-Build-Config
8. `add-rhoai-dockerfile-labels` — GitHub PR to add OCI labels to Dockerfile (**RHOAI only**)
9. `create-rhoai-delivery-repo` — GitLab MR to pyxis-repo-configs (**RHOAI only**)
10. `setup-auto-merge` — GitHub PR to rhods-devops-infra (**RHOAI only**)
11. `enable-renovate-on-rhoai-component-repo` — GitHub PR to rhoai-konflux-central + deferred `sync-rhoai-renovate-configs` (**RHOAI only**)

## Usage

```
/onboard-konflux-components-for-odh-and-rhoai <jira-url>
```

Example:
```
/onboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Prerequisites

**Jira:** `JIRA_USER_EMAIL`, `JIRA_API_TOKEN`
**GitLab (VPN required):** `GITLAB_USER`, `GITLAB_TOKEN` (api + write_repository scope)
**GitHub:** `GITHUB_USER`, `GITHUB_TOKEN` (repo + actions:write scope)
**OpenShift:** `OC_TOKEN` (if no matching kubeconfig context for Konflux cluster)
**Tools:** `uv`, `git`, `oc`, `skopeo`, `yamllint`, `jq`, `kustomize` (or `kubectl`)

Optional overrides: `APP_INTERFACE_REPO_URL`, `KONFLUX_RELEASE_DATA_REPO_URL`,
`ODH_KONFLUX_CENTRAL_REPO_URL`, `ODH_OPERATOR_REPO_URL`, `OBC_REPO_URL`, `JIRA_SERVER`,
`RHOAI_KONFLUX_CENTRAL_REPO_URL` (used by Steps 7/13; default: `https://github.com/red-hat-data-services/konflux-central.git`),
`PYXIS_REPO_CONFIGS_REPO_URL` (used by Step 11 RHOAI; default: `https://gitlab.cee.redhat.com/releng/pyxis-repo-configs.git`),
`RHODS_DEVOPS_INFRA_REPO_URL` (used by Step 12 RHOAI; default: `https://github.com/red-hat-data-services/rhods-devops-infra.git`)

**VPN must be active** before running — required for Steps 2, 3, and 11/RHOAI (GitLab on gitlab.cee.redhat.com).

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.
VALIDATE_SKILL_DIR is `<SKILL_DIR>/../validate-component-onboarding-jira`.

---

## CRITICAL GLOBAL OVERRIDE RULE

When following any child skill's SKILL.md, at every step that runs
`monitor_github_pr.py` or `monitor_gitlab_mr.py` **without** `--check-only` (a
blocking foreground call), you MUST instead:

1. Record the PR/MR URL in `$WORKDIR/pipeline_state.json` (Write tool).
2. Launch a background monitor using the Background Monitoring Pattern (see below).
3. **Immediately return to the wrapper's main flow** — do NOT wait for merge.

Child skill steps that poll for repo/component creation **after** a merge (e.g.,
`create-quay-repo` Step 11, `onboard-component-to-konflux-release-data` Step 11)
are **also skipped** — handled by `monitor_completion.sh`.

---

## Background Monitoring Pattern

When the Critical Global Override Rule applies, replace the blocking monitor call with a
single `launch_monitor.sh` invocation. The retry loop, Jira update, and PID/log/result file
management are all handled by two scripts in `$COMMON_SCRIPTS_DIR`:

- **`launch_monitor.sh`** — sets up log/result/pid paths, launches `monitor_pr.sh` via nohup,
  and returns immediately.
- **`monitor_pr.sh`** — the worker: retry loop that calls `monitor_github_pr.py` or
  `monitor_gitlab_mr.py`, writes the result file, and calls `update_jira_issue.py` on merge.

```bash
bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
  --step         "<quay|krd|okc|operator>"  \
  --url          "<MR_or_PR_URL>"           \
  --type         "github"                   \  # or "gitlab"
  --jira-url     "$JIRA_URL"               \
  --label-remove "<label-to-remove>"        \   # Jira label removed on merge
  --comment      "$(printf '<line1>\n\n<line2>')" \   # Jira comment posted on merge
  --workdir      "$WORKDIR"                \
  --scripts-dir  "$COMMON_SCRIPTS_DIR"
```

Output files (all under `$WORKDIR`):

| File | Purpose |
|------|---------|
| `monitor_<step>.log` | Full per-step log including quiet polling output |
| `monitor_<step>.result` | Single line: `merged`, `closed`, `pipeline_failed`, or `timeout` |
| `monitor_<step>.pid` | PID of the background nohup process |
| `events.log` | Shared log of significant events across all monitors (merges, Jira updates, retries) |

**Live view:** run `watch_monitors.sh` in a terminal to follow significant events in real time:
```bash
bash "$COMMON_SCRIPTS_DIR/watch_monitors.sh" --workdir "$WORKDIR"
```

**Retry behaviour:** on connection errors or unexpected exits (e.g. GitLab `RemoteDisconnected`),
`monitor_pr.sh` sleeps 60 s and retries automatically. Monitors survive transient VPN drops.

---

## Step 0: Parse Inputs

```bash
JIRA_URL="${1:-}"
if [[ -z "$JIRA_URL" ]]; then
  echo "ERROR: Jira URL is required."
  echo "  Usage: /onboard-konflux-components-for-odh-and-rhoai <jira-url>"
  exit 1
fi
if [[ "$JIRA_URL" != *"/browse/"* ]]; then
  echo "ERROR: Invalid Jira URL format. Expected: https://redhat.atlassian.net/browse/RHOAIENG-1234"
  exit 1
fi
JIRA_ID="${JIRA_URL##*/}"
echo "Jira ID  : $JIRA_ID"
echo "Jira URL : $JIRA_URL"
```

---

## Step 1: Check Prerequisites

Check in order; stop with a remediation message on first failure.

```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" \
  --env "JIRA_USER_EMAIL JIRA_API_TOKEN GITLAB_USER GITLAB_TOKEN GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git oc skopeo yamllint jq kustomize"

# Add ~/.local/bin to PATH if kustomize shim is there
[[ -x "${HOME}/.local/bin/kustomize" ]] && export PATH="${HOME}/.local/bin:${PATH}"
```

---

## Step 2: Set Up Working Directory and Initialize State

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_pipeline.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
echo "Pipeline state: $PIPELINE_STATE"
```

---

## Step 3: Sub-skill — validate-component-onboarding-jira

**Skip if** `steps.validate.status == "done"` in `pipeline_state.json`.

Follow the `validate-component-onboarding-jira` child skill's implementation exactly.
No monitoring override applies to this skill (it has no PR/MR monitor step).

On success:
- `$WORKDIR/component_onboarding_details.json` and `$WORKDIR/component_onboarding_details.yaml` exist
- Jira is in "In Progress" status
- Update `pipeline_state.json`:
  ```bash
  bash "$COMMON_SCRIPTS_DIR/pipeline_state.sh" set \
    --state "$PIPELINE_STATE" --step validate --field status --value "done"
  ```

On failure: **hard blocker**. Display the child skill's error and stop. Do not continue.

---

## Step 4: Parse Component Details and Derive Computed Variables

**Skip if** `component_name` is already non-empty in `pipeline_state.json`.

Parse `$WORKDIR/component_onboarding_details.yaml` to extract component fields:

```bash
COMPONENT_NAME=$(grep -m1 'component_name:' "$WORKDIR/component_onboarding_details.yaml" | awk '{print $2}')
IS_OPERATOR=$(grep -m1 'is_operator:' "$WORKDIR/component_onboarding_details.yaml" | awk '{print $2}')
REPO_URL=$(grep -m1 'repo_url:' "$WORKDIR/component_onboarding_details.yaml" | awk '{print $2}')
REPO_BRANCH=$(grep -m1 'repo_branch:' "$WORKDIR/component_onboarding_details.yaml" | awk '{print $2}')
```

**Derive `PRODUCT_CONTEXT`** in order:
1. Jira key prefix: `RHOAIENG` → `RHOAI`; `RHODS` → `ODH`
2. `fields.summary` in `component_onboarding_details.json`: contains "RHOAI" → `RHOAI`; "ODH" → `ODH`
3. Fallback: ask the user interactively

**Derive Quay variables:**
```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/derive_quay_vars.sh" \
  --product-context "$PRODUCT_CONTEXT" \
  --component-name "$COMPONENT_NAME")"
# Sets: QUAY_ORG, QUAY_VISIBILITY, QUAY_REPO_URI
```

Update `pipeline_state.json` with all derived values:
```bash
jq \
  --arg cn "$COMPONENT_NAME" \
  --arg pc "$PRODUCT_CONTEXT" \
  --arg qo "$QUAY_ORG" \
  --arg qv "$QUAY_VISIBILITY" \
  --arg qr "$QUAY_REPO_URI" \
  --argjson io "${IS_OPERATOR}" \
  '.component_name = $cn | .product_context = $pc | .quay_org = $qo | .quay_visibility = $qv | .quay_repo_uri = $qr | .is_operator = $io' \
  "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
```

**Mark non-applicable steps as "skipped"** immediately after updating pipeline_state.json:
```bash
if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  bash "$COMMON_SCRIPTS_DIR/pipeline_state.sh" set \
    --state "$PIPELINE_STATE" --step onboarder --field status --value "skipped"
  echo "[WRAPPER] RHOAI: onboarder (deferred workflow) step marked as skipped."
else
  # ODH: skip RHOAI-only steps
  for step in dockerfile_labels delivery_repo auto_merge renovate; do
    bash "$COMMON_SCRIPTS_DIR/pipeline_state.sh" set \
      --state "$PIPELINE_STATE" --step "$step" --field status --value "skipped"
  done
  echo "[WRAPPER] ODH: RHOAI-only steps (dockerfile_labels, delivery_repo, auto_merge, renovate) marked as skipped."
fi
```

Print:
```
Component : <COMPONENT_NAME>
Product   : <PRODUCT_CONTEXT>
Quay repo : <QUAY_REPO_URI> (<QUAY_VISIBILITY>)
Operator  : <IS_OPERATOR>
```

---

## Step 5: Sub-skill — create-quay-repo

**Skip if** `steps.quay.status` is `"merged"` or `"skipped"`.

Follow the `create-quay-repo` child skill's implementation directly.

Pass these arguments to the skill's logic:
- Quay repo (first positional arg): `$QUAY_REPO_URI` (e.g., `quay.io/opendatahub/my-component`)
- `--jira-url $JIRA_URL`
- `--visibility $QUAY_VISIBILITY`

Follow the skill's implementation through to and including **Step 9** (Raise MR, up to 3 attempts).
After `$MR_URL` is captured from the child skill:

1. Update `pipeline_state.json`: `steps.quay.mr_url = "$MR_URL"`, `steps.quay.status = "mr_raised"`.
2. Apply the Background Monitoring Pattern (GitLab MR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "quay" \
     --url          "$MR_URL" \
     --type         "gitlab" \
     --jira-url     "$JIRA_URL" \
     --label-remove "quay-mr-raised" \
     --comment      "$(printf 'MR merged: %s\n\napp-interface GitOps reconciliation is in progress. Monitoring %s for creation...' "$MR_URL" "$QUAY_REPO_URI")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. **Skip Step 10** (inline MR monitor) and **Step 11** (Quay repo poll).
4. Return to the wrapper.

If the child skill exits because the Quay repo already exists (Step 3 of child):
write `steps.quay.status = "merged"` and continue to Step 6.

---

## Step 6: Sub-skill — onboard-component-to-konflux-release-data

**Skip if** `steps.krd.status` is `"merged"` or `"done"`.

> **VPN must be active for this step.**

Follow the `onboard-component-to-konflux-release-data` child skill's implementation
with `$JIRA_URL` as the positional argument.

Follow through to and including **Step 9** (Raise MR, up to 3 attempts).
After `$MR_URL` is captured:

1. Update `pipeline_state.json`: `steps.krd.mr_url = "$MR_URL"`, `steps.krd.status = "mr_raised"`.
2. Apply the Background Monitoring Pattern (GitLab MR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "krd" \
     --url          "$MR_URL" \
     --type         "gitlab" \
     --jira-url     "$JIRA_URL" \
     --label-remove "konflux-mr-raised" \
     --comment      "$(printf 'MR merged: %s\n\nKonflux GitOps pipeline is provisioning Component '\''%s'\'' on the cluster. Monitoring for creation...' "$MR_URL" "$COMPONENT_NAME")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. **Skip Step 10** (inline MR monitor) and **Step 11** (Component creation poll).
4. Return to the wrapper.

If the child skill exits because the Konflux Component already exists (Step 5 of child):
write `steps.krd.status = "done"` and continue to Step 7.

---

## Step 7: Sub-skill — [ODH] add-component-to-odh-konflux-central / [RHOAI] add-component-to-rhoai-konflux-central

**Skip if** `steps.okc.status` is `"merged"`.

**If `PRODUCT_CONTEXT == "ODH"`:**

Follow the `add-component-to-odh-konflux-central` child skill's implementation
with `$JIRA_URL` as the positional argument.

Follow through to and including the step that raises the GitHub PR and captures `$PR_URL`.
After the PR is created:

1. Update `pipeline_state.json`: `steps.okc.pr_url = "$PR_URL"`, `steps.okc.status = "pr_raised"`.
2. Apply the Background Monitoring Pattern (GitHub PR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "okc" \
     --url          "$PR_URL" \
     --type         "github" \
     --jira-url     "$JIRA_URL" \
     --label-remove "okc-pr-raised" \
     --comment      "$(printf 'PR merged: %s\n\nKonflux CI is now configured for '\''%s'\''. Builds will trigger on pushes and pull requests to '\''%s'\'' branch of %s.\n\nStep 4 (odh-konflux-central update) is complete.' "$PR_URL" "$COMPONENT_NAME" "$REPO_BRANCH" "$REPO_URL")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. Skip the inline blocking `monitor_github_pr.py` call in the child skill.
4. Return to the wrapper.

If the child skill exits because pipelineruns already exist: write
`steps.okc.status = "merged"` and continue.

**If `PRODUCT_CONTEXT == "RHOAI"`:**

Follow the `add-component-to-rhoai-konflux-central` child skill's implementation
with `$JIRA_URL` as the positional argument.

> **NOTE:** The RHOAI child skill derives `$BRANCH_NAME` (e.g., `rhoai-v3.4-ea.2`) from
> `target_rhoai_version` in Steps 3f. Allow this derivation to proceed — the wrapper follows
> the child's Steps 0-10 in full so the version-specific branch is resolved correctly.
> The PR targets `$BRANCH_NAME`, not `main`.

Follow through to and including **Step 10** (Raise PR, up to 3 attempts), which captures `$PR_URL`.
After the PR is created:

1. Update `pipeline_state.json`: `steps.okc.pr_url = "$PR_URL"`, `steps.okc.status = "pr_raised"`.
2. Apply the Background Monitoring Pattern (GitHub PR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "okc" \
     --url          "$PR_URL" \
     --type         "github" \
     --jira-url     "$JIRA_URL" \
     --label-remove "rkc-pr-raised" \
     --comment      "$(printf 'PR merged: %s\n\nKonflux CI is now configured for '\''%s'\'' on RHOAI version-specific branch. Step 4 (rhoai-konflux-central) is complete.' "$PR_URL" "$COMPONENT_NAME")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. Skip child skill Step 11 (inline monitor) and Step 12 (report).
4. Return to the wrapper.

If the child skill exits because PipelineRun already exists (child exits 0 at Step 4):
write `steps.okc.status = "merged"` and continue.

---

## Step 8: Sub-skill — integrate-component-with-odh-operator

**Skip if** `steps.operator.status` is `"merged"` or `"skipped"`.

Follow the `integrate-component-with-odh-operator` child skill's implementation
with `$JIRA_URL` as the positional argument.

- **If `IS_OPERATOR == false`:** The child skill exits cleanly at Step 4a. Write
  `steps.operator.status = "skipped"` to `pipeline_state.json`. Continue to Step 9.

- **If `IS_OPERATOR == true`:** Follow through to and including Step 9 (Raise PR, up to 3
  attempts). After `$PR_URL` is captured:
  1. Update `pipeline_state.json`: `steps.operator.pr_url = "$PR_URL"`, `steps.operator.status = "pr_raised"`.
  2. Apply the Background Monitoring Pattern (GitHub PR variant):
     ```bash
     bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
       --step         "operator" \
       --url          "$PR_URL" \
       --type         "github" \
       --jira-url     "$JIRA_URL" \
       --label-remove "operator-pr-raised" \
       --comment      "$(printf 'Operator PR merged: %s\n\nOperator manifest config for '\''%s'\'' is now integrated into opendatahub-operator.' "$PR_URL" "$COMPONENT_NAME")" \
       --workdir      "$WORKDIR" \
       --scripts-dir  "$COMMON_SCRIPTS_DIR"
     ```
  3. Skip Step 10 (inline PR monitor) and Step 11 (final Jira update).
  4. Return to the wrapper.

---

## Step 9: Sub-skill — integrate-component-with-bundle

**Skip if** `steps.bundle.status` is `"pr_raised"` or `"merged"`.

Follow the `integrate-component-with-bundle` child skill's implementation
with `$JIRA_URL` as the positional argument.

This child skill exits after raising the PR (no inline monitoring). After `$PR_URL` is
captured from the child skill's Step 10 (Raise PR):

1. Update `pipeline_state.json`: `steps.bundle.pr_url = "$PR_URL"`, `steps.bundle.status = "pr_raised"`.
2. No background monitor launch needed.
3. Return to the wrapper.

---

## Step 10: Sub-skill — add-rhoai-dockerfile-labels (RHOAI only)

**Skip if** `PRODUCT_CONTEXT == "ODH"` or `steps.dockerfile_labels.status` is
`"pr_raised"`, `"merged"`, `"done"`, or `"skipped"`.

Follow the `add-rhoai-dockerfile-labels` child skill's implementation
with `$JIRA_URL` as the positional argument.

Follow through to and including **Step 9** (Raise PR, up to 3 attempts).
After `$PR_URL` is captured:

1. Update `pipeline_state.json`: `steps.dockerfile_labels.pr_url = "$PR_URL"`,
   `steps.dockerfile_labels.status = "pr_raised"`.
2. Apply the Background Monitoring Pattern (GitHub PR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "dockerfile_labels" \
     --url          "$PR_URL" \
     --type         "github" \
     --jira-url     "$JIRA_URL" \
     --label-remove "dockerfile-labels-pr-raised" \
     --comment      "$(printf 'Dockerfile labels PR merged: %s\n\nAll mandatory RHOAI OCI labels are now present in the component Dockerfile for '\''%s'\''.' "$PR_URL" "$COMPONENT_NAME")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. Skip child skill Step 10 (report). Return to the wrapper.

If child skill exits 0 at Step 5 (labels already correct): write
`steps.dockerfile_labels.status = "done"` and continue.

---

## Step 11: Sub-skill — create-rhoai-delivery-repo (RHOAI only)

**Skip if** `PRODUCT_CONTEXT == "ODH"` or `steps.delivery_repo.status` is
`"merged"`, `"done"`, or `"skipped"`.

> **VPN must be active for this step.**

Follow the `create-rhoai-delivery-repo` child skill's implementation
with `$JIRA_URL` as the positional argument.

Follow through to and including **Step 10** (Raise MR, up to 3 attempts).
After `$MR_URL` is captured:

1. Update `pipeline_state.json`: `steps.delivery_repo.mr_url = "$MR_URL"`,
   `steps.delivery_repo.status = "mr_raised"`.
2. Apply the Background Monitoring Pattern (GitLab MR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "delivery_repo" \
     --url          "$MR_URL" \
     --type         "gitlab" \
     --jira-url     "$JIRA_URL" \
     --label-remove "delivery-repo-mr-raised" \
     --comment      "$(printf 'Delivery repo MR merged: %s\n\nThe RHOAI delivery repository '\''rhoai/%s-rhel9'\'' has been provisioned.' "$MR_URL" "$COMPONENT_NAME")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. Skip child skill Step 11 (inline monitor) and Step 12 (report). Return to the wrapper.

If child skill exits 0 at Step 5 (delivery repo already exists): write
`steps.delivery_repo.status = "done"` and continue.

---

## Step 12: Sub-skill — setup-auto-merge (RHOAI only)

**Skip if** `PRODUCT_CONTEXT == "ODH"` or `steps.auto_merge.status` is
`"merged"`, `"done"`, or `"skipped"`.

Follow the `setup-auto-merge` child skill's implementation
with `$JIRA_URL` as the positional argument.

Follow through to and including **Step 9** (Raise PR, up to 3 attempts).
After `$PR_URL` is captured:

1. Update `pipeline_state.json`: `steps.auto_merge.pr_url = "$PR_URL"`,
   `steps.auto_merge.status = "pr_raised"`.
2. Apply the Background Monitoring Pattern (GitHub PR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "auto_merge" \
     --url          "$PR_URL" \
     --type         "github" \
     --jira-url     "$JIRA_URL" \
     --label-remove "auto-merge-setup-done" \
     --comment      "$(printf 'Auto-merge PR merged: %s\n\nAuto-merge is now configured for '\''%s'\'' in rhods-devops-infra.' "$PR_URL" "$COMPONENT_NAME")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. Skip child skill Step 10 (inline monitor) and Step 11 (report). Return to the wrapper.

If child skill exits 0 at Step 4 (entries already exist): write
`steps.auto_merge.status = "done"` and continue.

---

## Step 13: Sub-skill — enable-renovate-on-rhoai-component-repo + deferred sync (RHOAI only)

**Skip if** `PRODUCT_CONTEXT == "ODH"` or `steps.renovate.status` is not `"pending"`.

Follow the `enable-renovate-on-rhoai-component-repo` child skill's implementation
with `$JIRA_URL` as the positional argument.

Follow through to and including **Step 9** (Raise PR, up to 3 attempts).
After `$PR_URL` is captured:

1. Update `pipeline_state.json`: `steps.renovate.pr_url = "$PR_URL"`,
   `steps.renovate.status = "pr_raised"`.
2. Apply the Background Monitoring Pattern (GitHub PR variant):
   ```bash
   bash "$COMMON_SCRIPTS_DIR/launch_monitor.sh" \
     --step         "renovate" \
     --url          "$PR_URL" \
     --type         "github" \
     --jira-url     "$JIRA_URL" \
     --label-remove "renovate-pr-raised" \
     --comment      "$(printf 'Renovate enable PR merged: %s\n\nRenovate is now enabled for '\''%s'\''.' "$PR_URL" "$COMPONENT_NAME")" \
     --workdir      "$WORKDIR" \
     --scripts-dir  "$COMMON_SCRIPTS_DIR"
   ```
3. Skip child skill Step 10 (inline monitor) and Step 11 (report).
4. **Also write and launch `$WORKDIR/renovate_sync.sh`** (see below).
5. Return to the wrapper.

If child skill exits 0 at Step 4 (entry already exists): write
`steps.renovate.status = "done"` and continue (no renovate_sync.sh needed).

### Deferred Renovate Sync Script

Derive `RKC_URL` once and launch the renovate sync background script:

```bash
RKC_URL="${RHOAI_KONFLUX_CENTRAL_REPO_URL:-https://github.com/red-hat-data-services/konflux-central.git}"

nohup bash "$COMMON_SCRIPTS_DIR/renovate_sync.sh" \
  --workdir      "$WORKDIR" \
  --jira-url     "$JIRA_URL" \
  --scripts-dir  "$COMMON_SCRIPTS_DIR" \
  --rkc-url      "$RKC_URL" \
  >> "$WORKDIR/renovate_sync.log" 2>&1 &
echo $! > "$WORKDIR/renovate_sync.pid"
echo "[WRAPPER] Renovate sync deferred script started (PID=$(cat $WORKDIR/renovate_sync.pid))"
echo "[WRAPPER] Log: $WORKDIR/renovate_sync.log"
```

---

## Step 14: Launch Deferred Workflow Trigger (Background) — ODH only

**Skip if** `steps.onboarder.status` is not `"pending"`.

The `run-odh-konflux-onboarder-workflow` skill requires both the KRD MR (Step 3) and the
OKC PR (Step 4) to be merged before the GitHub Actions workflow can succeed. A background
script handles this dependency without blocking the wrapper.

Derive workflow inputs and launch the deferred workflow background script:

```bash
REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
BUILD_TYPE=$(grep -m1 'build_type:' "$WORKDIR/component_onboarding_details.yaml" \
  | awk '{print $2}' 2>/dev/null || echo "CI")
[[ -z "$BUILD_TYPE" ]] && BUILD_TYPE="CI"
OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"

nohup bash "$COMMON_SCRIPTS_DIR/deferred_workflow.sh" \
  --workdir       "$WORKDIR" \
  --jira-url      "$JIRA_URL" \
  --scripts-dir   "$COMMON_SCRIPTS_DIR" \
  --okc-url       "$OKC_URL" \
  --okc-path      "$OKC_PATH" \
  --workflow-file "$WORKFLOW_FILE" \
  --repo-name     "$REPO_NAME" \
  --repo-branch   "$REPO_BRANCH" \
  --build-type    "$BUILD_TYPE" \
  >> "$WORKDIR/deferred_workflow.log" 2>&1 &
echo $! > "$WORKDIR/deferred_workflow.pid"
echo "[WRAPPER] Deferred workflow trigger started (PID=$(cat $WORKDIR/deferred_workflow.pid))"
echo "[WRAPPER] Log: $WORKDIR/deferred_workflow.log"

bash "$COMMON_SCRIPTS_DIR/pipeline_state.sh" set \
  --state "$PIPELINE_STATE" --step onboarder --field status --value "pending_krd_okc_merge"
```

---

## Step 15: Transition Jira to "Review"

Build a summary of all raised PR/MR URLs from `pipeline_state.json`:

```bash
QUAY_MR=$(jq -r '.steps.quay.mr_url // "N/A"'                  "$PIPELINE_STATE")
KRD_MR=$(jq  -r '.steps.krd.mr_url // "N/A"'                   "$PIPELINE_STATE")
OKC_PR=$(jq  -r '.steps.okc.pr_url // "N/A"'                   "$PIPELINE_STATE")
OP_PR=$(jq   -r '.steps.operator.pr_url // "N/A"'              "$PIPELINE_STATE")
BDLPR=$(jq   -r '.steps.bundle.pr_url // "N/A"'                "$PIPELINE_STATE")
LABELS_PR=$(jq -r '.steps.dockerfile_labels.pr_url // "N/A"'   "$PIPELINE_STATE")
DELIV_MR=$(jq  -r '.steps.delivery_repo.mr_url // "N/A"'       "$PIPELINE_STATE")
AM_PR=$(jq     -r '.steps.auto_merge.pr_url // "N/A"'          "$PIPELINE_STATE")
RENOV_PR=$(jq  -r '.steps.renovate.pr_url // "N/A"'            "$PIPELINE_STATE")
IS_OP=$(jq     -r '.is_operator'                               "$PIPELINE_STATE")

STEP5_VAL=$([ "$PRODUCT_CONTEXT" = "ODH" ] \
  && echo "auto-triggered once Steps 3+4 are merged (background script running)" \
  || echo "N/A (RHOAI)")
STEP6_VAL=$([ "$IS_OP" = "true" ] && echo "$OP_PR" || echo "N/A (is_operator=false)")
STEP8_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$LABELS_PR"  || echo "N/A (ODH)")
STEP9_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$DELIV_MR"   || echo "N/A (ODH)")
STEP10_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$AM_PR"     || echo "N/A (ODH)")
STEP11_PR_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] && echo "$RENOV_PR" || echo "N/A (ODH)")
STEP11_SYNC_VAL=$([ "$PRODUCT_CONTEXT" = "RHOAI" ] \
  && echo "deferred; will trigger on renovate PR merge" \
  || echo "N/A (ODH)")

REVIEW_COMMENT="All PRs and MRs raised for '${COMPONENT_NAME}' onboarding. Pending review and merge.

| Step    | Description        | URL / Status                                                              |
|---------|--------------------|---------------------------------------------------------------------------|
| Step 2  | Quay MR            | ${QUAY_MR}                                                                |
| Step 3  | KRD MR             | ${KRD_MR}                                                                 |
| Step 4  | OKC/RKC PR         | ${OKC_PR}                                                                 |
| Step 5  | Tekton/Workflow     | ${STEP5_VAL}                                                              |
| Step 6  | Operator PR        | ${STEP6_VAL}                                                              |
| Step 7  | Bundle PR          | ${BDLPR}                                                                  |
| Step 8  | Dockerfile Labels  | ${STEP8_VAL}                                                              |
| Step 9  | Delivery Repo MR   | ${STEP9_VAL}                                                              |
| Step 10 | Auto-Merge PR      | ${STEP10_VAL}                                                             |
| Step 11 | Renovate PR        | ${STEP11_PR_VAL}                                                          |
| Step 11 | Renovate Sync      | ${STEP11_SYNC_VAL}                                                        |

Background monitors are running. Jira will be moved to Resolved automatically when all PRs/MRs are merged."

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "onboarding-in-review" \
  --status "Review" \
  --comment "$REVIEW_COMMENT"
```

---

## Step 16: Launch Final Completion Monitor (Background)

```bash
nohup bash "$COMMON_SCRIPTS_DIR/monitor_completion.sh" \
  --workdir     "$WORKDIR" \
  --jira-url    "$JIRA_URL" \
  --scripts-dir "$COMMON_SCRIPTS_DIR" \
  >> "$WORKDIR/monitor_completion.log" 2>&1 &
echo $! > "$WORKDIR/monitor_completion.pid"
echo "[WRAPPER] Completion monitor started (PID=$(cat $WORKDIR/monitor_completion.pid))"
echo "[WRAPPER] Log: $WORKDIR/monitor_completion.log"
```

---

## Step 17: Print Final Summary

Print the following, substituting all variable values:

```
=== onboard-konflux-components-for-odh-and-rhoai — Phase 1 Complete ===

  Component      : <COMPONENT_NAME>
  Product        : <PRODUCT_CONTEXT>
  Jira           : <JIRA_URL> (status: Review)

PRs / MRs raised:
  Step 2 Quay MR           : <QUAY_MR>
  Step 3 KRD MR            : <KRD_MR>
  Step 4 OKC/RKC PR        : <OKC_PR>
  Step 5 Workflow          : <ODH: pending KRD+OKC merge (deferred_workflow.sh running) | RHOAI: N/A>
  Step 6 Operator          : <OP_PR or "N/A" if is_operator=false>
  Step 7 Bundle            : <BDLPR>
  Step 8 Dockerfile Labels : <LABELS_PR or "N/A" if ODH>
  Step 9 Delivery Repo MR  : <DELIV_MR or "N/A" if ODH>
  Step 10 Auto-Merge PR    : <AM_PR or "N/A" if ODH>
  Step 11 Renovate PR      : <RENOV_PR or "N/A" if ODH>

Background processes:
  monitor_quay.pid            log: $WORKDIR/monitor_quay.log
  monitor_krd.pid             log: $WORKDIR/monitor_krd.log
  monitor_okc.pid             log: $WORKDIR/monitor_okc.log
  monitor_operator.pid        log: $WORKDIR/monitor_operator.log   [if is_operator=true]
  [ODH] deferred_workflow.pid log: $WORKDIR/deferred_workflow.log
  [RHOAI] monitor_dockerfile_labels.pid log: $WORKDIR/monitor_dockerfile_labels.log
  [RHOAI] monitor_delivery_repo.pid     log: $WORKDIR/monitor_delivery_repo.log
  [RHOAI] monitor_auto_merge.pid        log: $WORKDIR/monitor_auto_merge.log
  [RHOAI] monitor_renovate.pid          log: $WORKDIR/monitor_renovate.log
  [RHOAI] renovate_sync.pid             log: $WORKDIR/renovate_sync.log
  monitor_completion.pid      log: $WORKDIR/monitor_completion.log

Live event stream (merges, Jira updates, retries — run in a separate terminal):
  bash "$COMMON_SCRIPTS_DIR/watch_monitors.sh" --workdir "$WORKDIR"

State file: $WORKDIR/pipeline_state.json

The Jira ticket will move to Resolved automatically when all PRs/MRs are merged.
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
| VPN not active | 5, 6 | Activate Red Hat VPN; re-run (idempotent via `pipeline_state.json`) |
| Quay MR fails 3× | 5 | Check VPN and `GITLAB_TOKEN` `api` scope |
| KRD MR fails | 6 | Check VPN; `GITLAB_TOKEN` needs `write_repository` scope |
| OKC PR fails | 7 | Verify `GITHUB_TOKEN` `repo` scope and push access |
| Operator PR fails | 8 | Verify `GITHUB_TOKEN` push access to `opendatahub-operator` |
| Bundle PR fails | 9 | Verify `GITHUB_TOKEN` push access to `ODH-Build-Config` |
| Deferred workflow 422 error | 10 deferred | OKC PR not yet merged; script waits automatically |
| Deferred workflow times out (3h) | 10 deferred | Check `deferred_workflow.log`; re-run script manually |
| Tekton PR not in workflow logs | 10 deferred | Check run URL in Jira; update `pipeline_state.json` manually |
| VPN not active | 11 (RHOAI) | Activate Red Hat VPN; re-run (idempotent) |
| Dockerfile labels PR fails 3× | 10 (RHOAI) | Check GITHUB_TOKEN push access to component repo |
| Delivery repo MR fails 3× | 11 (RHOAI) | Check VPN and GITLAB_TOKEN `write_repository` scope |
| Auto-merge PR fails 3× | 12 (RHOAI) | Check GITHUB_TOKEN push access to rhods-devops-infra |
| Renovate PR fails 3× | 13 (RHOAI) | Check GITHUB_TOKEN push access to rhoai-konflux-central |
| Renovate sync workflow 403 | 13 (RHOAI) | GITHUB_TOKEN needs `actions:write` scope |
| Renovate sync times out (3h) | 13 deferred | Check `renovate_sync.log`; re-run `/sync-rhoai-renovate-configs` manually |
| Completion monitor times out (4h) | 16 | Check `.result` files; re-run `monitor_completion.sh` |
| Jira `--status "Resolved"` fails | 16 | Check available Jira transitions; adjust status name |
| Re-run needed after failure | Any | Re-invoke skill; `pipeline_state.json` skips completed steps |
