---
name: onboard-konflux-components-for-odh-and-rhoai
description: Master orchestrator skill for the full ODH/RHOAI component onboarding pipeline. Takes a single Jira URL and coordinates 7 sub-skills in sequence with background PR/MR monitoring. Transitions Jira through In Progress -> Review -> Resolved automatically.
allowed-tools: Bash, Read, Write, Edit
user-invocable: true
---

# Onboard Konflux Components for ODH and RHOAI

Orchestrates the complete component onboarding pipeline:

1. `validate-component-onboarding-jira` — fetch + validate Jira YAML
2. `create-quay-repo` — GitLab MR to app-interface
3. `onboard-component-to-konflux-release-data` — GitLab MR to konflux-release-data
4. `add-component-to-odh-konflux-central` — GitHub PR for Tekton pipelineruns
5. `run-odh-konflux-onboarder-workflow` — GitHub Actions workflow (deferred, background)
6. `integrate-component-with-odh-operator` — GitHub PR to opendatahub-operator (if operator)
7. `integrate-component-with-bundle` — GitHub PR to ODH-Build-Config

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
`ODH_KONFLUX_CENTRAL_REPO_URL`, `ODH_OPERATOR_REPO_URL`, `OBC_REPO_URL`, `JIRA_SERVER`

**VPN must be active** before running — required for Steps 2 and 3 (GitLab on gitlab.cee.redhat.com).

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
[[ -z "${JIRA_USER_EMAIL:-}" ]] && echo "ERROR: JIRA_USER_EMAIL not set. export JIRA_USER_EMAIL=you@example.com" && exit 1
[[ -z "${JIRA_API_TOKEN:-}" ]]  && echo "ERROR: JIRA_API_TOKEN not set." && exit 1
[[ -z "${GITLAB_USER:-}" ]]     && echo "ERROR: GITLAB_USER not set. export GITLAB_USER=yourusername" && exit 1
[[ -z "${GITLAB_TOKEN:-}" ]]    && echo "ERROR: GITLAB_TOKEN not set." && exit 1
[[ -z "${GITHUB_USER:-}" ]]     && echo "ERROR: GITHUB_USER not set. export GITHUB_USER=yourusername" && exit 1
[[ -z "${GITHUB_TOKEN:-}" ]]    && echo "ERROR: GITHUB_TOKEN not set." && exit 1

for tool in uv git oc skopeo yamllint jq; do
  command -v "$tool" &>/dev/null || {
    echo "ERROR: '$tool' is not installed."
    case "$tool" in
      uv)       echo "  Install: curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
      oc)       echo "  Install: https://console.redhat.com/openshift/downloads" ;;
      skopeo)   echo "  Install: brew install skopeo  OR  sudo dnf install skopeo" ;;
      yamllint) echo "  Install: pip install yamllint  OR  brew install yamllint" ;;
      jq)       echo "  Install: brew install jq  OR  sudo dnf install jq" ;;
    esac
    exit 1
  }
done

# kustomize (standalone binary or shim created by install.sh)
if ! command -v kustomize &>/dev/null && [[ ! -x "${HOME}/.local/bin/kustomize" ]]; then
  echo "ERROR: kustomize not found. Run install.sh or install kustomize manually:"
  echo "  https://kubectl.docs.kubernetes.io/installation/kustomize/"
  exit 1
fi
[[ -x "${HOME}/.local/bin/kustomize" ]] && export PATH="${HOME}/.local/bin:${PATH}"
```

---

## Step 2: Set Up Working Directory and Initialize State

```bash
WORKDIR="$(pwd)/${JIRA_ID}"
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"
PIPELINE_STATE="$WORKDIR/pipeline_state.json"
```

**If `$PIPELINE_STATE` does not exist**, use the Write tool to create it with these exact
contents (substituting `<JIRA_URL>` and `<JIRA_ID>` with their actual values):

```json
{
  "jira_url": "<JIRA_URL>",
  "jira_id": "<JIRA_ID>",
  "component_name": "",
  "product_context": "",
  "quay_org": "",
  "quay_visibility": "",
  "quay_repo_uri": "",
  "is_operator": false,
  "steps": {
    "validate":  { "status": "pending" },
    "quay":      { "mr_url": "",  "status": "pending" },
    "krd":       { "mr_url": "",  "status": "pending" },
    "okc":       { "pr_url": "",  "status": "pending" },
    "onboarder": { "run_id": "", "tekton_pr_url": "", "status": "pending" },
    "operator":  { "pr_url": "",  "status": "pending" },
    "bundle":    { "pr_url": "",  "status": "pending" }
  }
}
```

**If `$PIPELINE_STATE` already exists**, read it with the Read tool and print statuses:

```bash
echo "Resuming from existing state:"
jq -r '.steps | to_entries[] | "  \(.key): \(.value.status)"' "$PIPELINE_STATE"
```

---

## Step 3: Sub-skill — validate-component-onboarding-jira

**Skip if** `steps.validate.status == "done"` in `pipeline_state.json`.

Read `<VALIDATE_SKILL_DIR>/SKILL.md` with the Read tool. Follow its implementation exactly.
No monitoring override applies to this skill (it has no PR/MR monitor step).

On success:
- `$WORKDIR/component_onboarding_details.json` and `$WORKDIR/component_onboarding_details.yaml` exist
- Jira is in "In Progress" status
- Use the Write tool to update `pipeline_state.json`: set `steps.validate.status = "done"`.

On failure: **hard blocker**. Display the child skill's error and stop. Do not continue.

---

## Step 4: Parse Component Details and Derive Computed Variables

**Skip if** `component_name` is already non-empty in `pipeline_state.json`.

Read `$WORKDIR/component_onboarding_details.yaml` with the Read tool. Extract:

| Variable | YAML field | Required |
|----------|-----------|----------|
| `COMPONENT_NAME` | `inputs.component_name` | Yes |
| `IS_OPERATOR` | `inputs.is_operator` | Yes |
| `REPO_URL` | `inputs.repo_url` | Yes |
| `REPO_BRANCH` | `inputs.repo_branch` | Yes |

**Derive `PRODUCT_CONTEXT`** in order:
1. Jira key prefix: `RHOAIENG` → `RHOAI`; `RHODS` → `ODH`
2. `fields.summary` in `component_onboarding_details.json`: contains "RHOAI" → `RHOAI`; "ODH" → `ODH`
3. Fallback: ask the user interactively

**Derive Quay variables:**
```bash
if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  QUAY_ORG="opendatahub"; QUAY_VISIBILITY="public"
elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  QUAY_ORG="rhoai"; QUAY_VISIBILITY="private"
fi
QUAY_REPO_URI="quay.io/${QUAY_ORG}/${COMPONENT_NAME}"
```

Use the Write tool to update `pipeline_state.json` with all derived values:
`component_name`, `product_context`, `quay_org`, `quay_visibility`, `quay_repo_uri`, `is_operator`.

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

Read `<SKILL_DIR>/../create-quay-repo/SKILL.md` with the Read tool.

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

Read `<SKILL_DIR>/../onboard-component-to-konflux-release-data/SKILL.md` with the Read tool.
Follow its implementation with `$JIRA_URL` as the positional argument.

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

## Step 7: Sub-skill — add-component-to-odh-konflux-central

**Skip if** `steps.okc.status` is `"merged"`.

Read `<SKILL_DIR>/../add-component-to-odh-konflux-central/SKILL.md` with the Read tool.
Follow its implementation with `$JIRA_URL` as the positional argument.

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

---

## Step 8: Sub-skill — integrate-component-with-odh-operator

**Skip if** `steps.operator.status` is `"merged"` or `"skipped"`.

Read `<SKILL_DIR>/../integrate-component-with-odh-operator/SKILL.md` with the Read tool.
Follow its implementation with `$JIRA_URL` as the positional argument.

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

Read `<SKILL_DIR>/../integrate-component-with-bundle/SKILL.md` with the Read tool.
Follow its implementation with `$JIRA_URL` as the positional argument.

This child skill exits after raising the PR (no inline monitoring). After `$PR_URL` is
captured from the child skill's Step 10 (Raise PR):

1. Update `pipeline_state.json`: `steps.bundle.pr_url = "$PR_URL"`, `steps.bundle.status = "pr_raised"`.
2. No background monitor launch needed.
3. Return to the wrapper.

---

## Step 10: Launch Deferred Workflow Trigger (Background)

**Skip if** `steps.onboarder.status` is not `"pending"`.

The `run-odh-konflux-onboarder-workflow` skill requires both the KRD MR (Step 3) and the
OKC PR (Step 4) to be merged before the GitHub Actions workflow can succeed. A background
script handles this dependency without blocking the wrapper.

Derive workflow inputs:
```bash
REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
BUILD_TYPE=$(grep 'build_type:' "$WORKDIR/component_onboarding_details.yaml" \
  | awk '{print $2}' 2>/dev/null || echo "CI")
[[ -z "$BUILD_TYPE" ]] && BUILD_TYPE="CI"
OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"
```

Use the Write tool to write `$WORKDIR/deferred_workflow.sh` with the following content.
After writing, substitute all `PLACEHOLDER_*` tokens with the actual variable values using
`sed` (see the sed block below the heredoc).

```bash
#!/usr/bin/env bash
# deferred_workflow.sh — waits for KRD MR + OKC PR to merge, then triggers
# the odh-konflux-onboarder workflow and monitors the Tekton PR to merge.
# Generated by onboard-konflux-components-for-odh-and-rhoai.
set -euo pipefail

WORKDIR="PLACEHOLDER_WORKDIR"
JIRA_URL="PLACEHOLDER_JIRA_URL"
COMMON_SCRIPTS_DIR="PLACEHOLDER_COMMON_SCRIPTS_DIR"
OKC_URL="PLACEHOLDER_OKC_URL"
OKC_PATH="PLACEHOLDER_OKC_PATH"
WORKFLOW_FILE="PLACEHOLDER_WORKFLOW_FILE"
REPO_NAME="PLACEHOLDER_REPO_NAME"
REPO_BRANCH="PLACEHOLDER_REPO_BRANCH"
BUILD_TYPE="PLACEHOLDER_BUILD_TYPE"
PIPELINE_STATE="$WORKDIR/pipeline_state.json"

log() { echo "[deferred $(date '+%H:%M:%S')] $*" >> "$WORKDIR/deferred_workflow.log"; }
log "Started. Waiting for Quay MR, KRD MR, and OKC PR to merge."

wait_for_merge() {
  local label="$1" result_file="$WORKDIR/monitor_${1}.result"
  local max_minutes=180 elapsed=0
  while true; do
    if [[ -f "$result_file" ]]; then
      local r; r=$(cat "$result_file" | tr -d '[:space:]')
      [[ "$r" == "merged" ]] && { log "$label: merged."; return 0; }
      if [[ "$r" == "closed" || "$r" == "pipeline_failed" || "$r" == "timeout" ]]; then
        log "ERROR: $label finished with '$r'. Cannot proceed."
        return 1
      fi
    fi
    [[ $elapsed -ge $max_minutes ]] && { log "ERROR: Timed out waiting for $label after ${max_minutes}m."; return 1; }
    sleep 300
    elapsed=$(( elapsed + 5 ))
  done
}

wait_for_merge "quay" || {
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "Deferred workflow aborted: Quay MR did not merge successfully.
Check \$WORKDIR/monitor_quay.result and re-trigger the workflow manually." 2>/dev/null || true
  exit 1
}

wait_for_merge "krd" || {
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "Deferred workflow aborted: KRD MR did not merge successfully.
Check \$WORKDIR/monitor_krd.result and re-trigger the workflow manually." 2>/dev/null || true
  exit 1
}

wait_for_merge "okc" || {
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "Deferred workflow aborted: OKC PR did not merge successfully.
Check \$WORKDIR/monitor_okc.result and re-trigger the workflow manually." 2>/dev/null || true
  exit 1
}

log "Quay, KRD, and OKC all merged. Triggering odh-konflux-onboarder workflow..."

RUN_ID=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" trigger \
  --repo-url "$OKC_URL" \
  --workflow "$WORKFLOW_FILE" \
  --ref main \
  --input "component=${REPO_NAME}" \
  --input "pr_target_branch=${REPO_BRANCH}" \
  --input "build_type=${BUILD_TYPE}") || {
  log "ERROR: Workflow dispatch failed. Check GITHUB_TOKEN actions:write scope."
  exit 1
}
log "Workflow triggered. Run ID: $RUN_ID"

jq --arg rid "$RUN_ID" \
  '.steps.onboarder.run_id = $rid | .steps.onboarder.status = "workflow_running"' \
  "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment "odh-konflux-onboarder workflow triggered.

Component: $REPO_NAME | Branch: $REPO_BRANCH | Build type: $BUILD_TYPE
Workflow run: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}" 2>/dev/null || true

# Monitor workflow run (30 minute timeout)
MONITOR_RESULT=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" monitor \
  --repo-url "$OKC_URL" --run-id "$RUN_ID" --timeout 30) || true
WORKFLOW_STATUS="${MONITOR_RESULT#status=}"
log "Workflow status: $WORKFLOW_STATUS"

if [[ "$WORKFLOW_STATUS" != "success" ]]; then
  log "ERROR: Workflow run $RUN_ID finished with: $WORKFLOW_STATUS"
  jq '.steps.onboarder.status = "failed"' "$PIPELINE_STATE" > \
    "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
  uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "odh-konflux-onboarder workflow FAILED (${WORKFLOW_STATUS}).
Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}
Manual intervention required." 2>/dev/null || true
  exit 1
fi

# Extract Tekton PR URL from workflow logs
STEP_LOGS=$(uv run --script "$COMMON_SCRIPTS_DIR/run_github_workflow.py" get-step-logs \
  --repo-url "$OKC_URL" --run-id "$RUN_ID" --step "Create pull request" 2>/dev/null || true)
TEKTON_PR=$(echo "$STEP_LOGS" | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' | head -1 || true)
log "Tekton PR: ${TEKTON_PR:-<not found in logs>}"

jq --arg tpr "${TEKTON_PR:-}" \
  '.steps.onboarder.tekton_pr_url = $tpr | .steps.onboarder.status = "tekton_pr_raised"' \
  "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "tekton-pr-raised" \
  --comment "odh-konflux-onboarder workflow completed successfully.

Tekton PR: ${TEKTON_PR:-<check workflow run logs>}
Workflow run: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Monitoring Tekton PR for merge..." 2>/dev/null || true

# Monitor Tekton PR (60 minute timeout)
if [[ -n "$TEKTON_PR" ]]; then
  log "Monitoring Tekton PR: $TEKTON_PR"
  TEKTON_RESULT=$(uv run --script "$COMMON_SCRIPTS_DIR/monitor_github_pr.py" \
    --pr-url "$TEKTON_PR" --timeout 60 2>>"$WORKDIR/deferred_workflow.log") || true

  if [[ "$TEKTON_RESULT" == "merged" ]]; then
    jq '.steps.onboarder.status = "merged"' "$PIPELINE_STATE" > \
      "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "tekton-pr-merged" \
      --comment "Tekton PR merged: $TEKTON_PR

Step 5 (Run CI/Nightly Build) is complete." 2>/dev/null || true
    log "Tekton PR merged. Step 5 complete."
  else
    jq '.steps.onboarder.status = "failed"' "$PIPELINE_STATE" > \
      "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
    log "ERROR: Tekton PR result: $TEKTON_RESULT. Check: $TEKTON_PR"
  fi
fi
log "Deferred workflow script complete."
```

After writing the file with the Write tool, perform substitution and launch:

```bash
sed -i'' \
  -e "s|PLACEHOLDER_WORKDIR|$WORKDIR|g" \
  -e "s|PLACEHOLDER_JIRA_URL|$JIRA_URL|g" \
  -e "s|PLACEHOLDER_COMMON_SCRIPTS_DIR|$COMMON_SCRIPTS_DIR|g" \
  -e "s|PLACEHOLDER_OKC_URL|$OKC_URL|g" \
  -e "s|PLACEHOLDER_OKC_PATH|$OKC_PATH|g" \
  -e "s|PLACEHOLDER_WORKFLOW_FILE|$WORKFLOW_FILE|g" \
  -e "s|PLACEHOLDER_REPO_NAME|$REPO_NAME|g" \
  -e "s|PLACEHOLDER_REPO_BRANCH|$REPO_BRANCH|g" \
  -e "s|PLACEHOLDER_BUILD_TYPE|$BUILD_TYPE|g" \
  "$WORKDIR/deferred_workflow.sh"
chmod +x "$WORKDIR/deferred_workflow.sh"

nohup bash "$WORKDIR/deferred_workflow.sh" >> "$WORKDIR/deferred_workflow.log" 2>&1 &
echo $! > "$WORKDIR/deferred_workflow.pid"
echo "[WRAPPER] Deferred workflow trigger started (PID=$(cat $WORKDIR/deferred_workflow.pid))"
echo "[WRAPPER] Log: $WORKDIR/deferred_workflow.log"

jq '.steps.onboarder.status = "pending_krd_okc_merge"' "$PIPELINE_STATE" > \
  "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
```

---

## Step 11: Transition Jira to "Review"

Read `pipeline_state.json` with the Read tool. Build a summary of all raised PR/MR URLs.

```bash
QUAY_MR=$(jq -r '.steps.quay.mr_url // "N/A"'             "$PIPELINE_STATE")
KRD_MR=$(jq  -r '.steps.krd.mr_url // "N/A"'              "$PIPELINE_STATE")
OKC_PR=$(jq  -r '.steps.okc.pr_url // "N/A"'              "$PIPELINE_STATE")
OP_PR=$(jq   -r '.steps.operator.pr_url // "N/A"'         "$PIPELINE_STATE")
BDLPR=$(jq   -r '.steps.bundle.pr_url // "N/A"'           "$PIPELINE_STATE")
IS_OP=$(jq   -r '.is_operator'                            "$PIPELINE_STATE")

uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "onboarding-in-review" \
  --status "Review" \
  --comment "All PRs and MRs raised for '$COMPONENT_NAME' onboarding. Pending review and merge.

  Step 2 — Quay MR     : $QUAY_MR
  Step 3 — KRD MR      : $KRD_MR
  Step 4 — OKC PR      : $OKC_PR
  Step 5 — Tekton PR   : auto-triggered once Steps 3+4 are merged (background script running)
  Step 6 — Operator PR : $([ "$IS_OP" = "true" ] && echo "$OP_PR" || echo "N/A (is_operator=false)")
  Step 7 — Bundle PR   : $BDLPR

Background monitors are running. Jira will be moved to Resolved automatically when
all PRs/MRs are merged.

WARNING: Bundle PR requires the SHA256 image digest to be updated before merging."
```

---

## Step 12: Launch Final Completion Monitor (Background)

Use the Write tool to write `$WORKDIR/monitor_completion.sh` with the content below.
After writing, substitute `PLACEHOLDER_*` values using `sed`, then launch.

```bash
#!/usr/bin/env bash
# monitor_completion.sh — polls pipeline_state.json until all steps are done,
# then transitions the Jira issue to Resolved.
# Generated by onboard-konflux-components-for-odh-and-rhoai.
set -euo pipefail

WORKDIR="PLACEHOLDER_WORKDIR"
JIRA_URL="PLACEHOLDER_JIRA_URL"
COMMON_SCRIPTS_DIR="PLACEHOLDER_COMMON_SCRIPTS_DIR"
PIPELINE_STATE="$WORKDIR/pipeline_state.json"
MAX_WAIT=14400    # 4 hours
POLL_INTERVAL=300 # 5 minutes
ELAPSED=0

log() { echo "[completion $(date '+%H:%M:%S')] $*" >> "$WORKDIR/monitor_completion.log"; }
log "Started. Max wait: ${MAX_WAIT}s, poll: ${POLL_INTERVAL}s."

sync_results() {
  for step in quay krd okc operator; do
    local rf="$WORKDIR/monitor_${step}.result"
    [[ -f "$rf" ]] || continue
    local cur; cur=$(jq -r ".steps.${step}.status" "$PIPELINE_STATE")
    [[ "$cur" == "merged" || "$cur" == "skipped" || "$cur" == "done" ]] && continue
    local r; r=$(cat "$rf" | tr -d '[:space:]')
    if [[ "$r" == "merged" ]]; then
      jq --arg s "$step" '.steps[$s].status = "merged"' "$PIPELINE_STATE" > \
        "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
      log "Step $step: updated to merged."
    fi
  done
}

all_done() {
  local v q k o on op b
  v=$(jq -r  '.steps.validate.status'  "$PIPELINE_STATE")
  q=$(jq -r  '.steps.quay.status'      "$PIPELINE_STATE")
  k=$(jq -r  '.steps.krd.status'       "$PIPELINE_STATE")
  o=$(jq -r  '.steps.okc.status'       "$PIPELINE_STATE")
  on=$(jq -r '.steps.onboarder.status' "$PIPELINE_STATE")
  op=$(jq -r '.steps.operator.status'  "$PIPELINE_STATE")
  b=$(jq -r  '.steps.bundle.status'    "$PIPELINE_STATE")
  log "Status: validate=$v quay=$q krd=$k okc=$o onboarder=$on operator=$op bundle=$b"
  [[ "$v"  == "done"   ]] || return 1
  [[ "$q"  == "merged" || "$q"  == "skipped" || "$q"  == "done" ]] || return 1
  [[ "$k"  == "merged" || "$k"  == "done"    ]] || return 1
  [[ "$o"  == "merged" ]] || return 1
  [[ "$on" == "merged" || "$on" == "skipped" ]] || return 1
  [[ "$op" == "merged" || "$op" == "skipped" ]] || return 1
  # bundle: pr_raised is acceptable (SHA placeholder must be manually fixed before merge)
  [[ "$b"  == "merged" || "$b"  == "pr_raised" ]] || return 1
  return 0
}

while true; do
  sync_results
  if all_done; then
    log "All steps complete. Transitioning Jira to Resolved."
    COMP=$(jq -r  '.component_name'                          "$PIPELINE_STATE")
    Q_MR=$(jq -r  '.steps.quay.mr_url // "N/A"'             "$PIPELINE_STATE")
    K_MR=$(jq -r  '.steps.krd.mr_url // "N/A"'              "$PIPELINE_STATE")
    O_PR=$(jq -r  '.steps.okc.pr_url // "N/A"'              "$PIPELINE_STATE")
    T_PR=$(jq -r  '.steps.onboarder.tekton_pr_url // "N/A"' "$PIPELINE_STATE")
    OP_PR=$(jq -r '.steps.operator.pr_url // "N/A"'         "$PIPELINE_STATE")
    B_PR=$(jq -r  '.steps.bundle.pr_url // "N/A"'           "$PIPELINE_STATE")

    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --remove-label "onboarding-in-review" \
      --add-label    "onboarding-complete" \
      --status       "Resolved" \
      --comment "ODH/RHOAI component onboarding for '$COMP' is COMPLETE.

All PRs and MRs merged:
  Step 2 — Quay MR     : $Q_MR
  Step 3 — KRD MR      : $K_MR
  Step 4 — OKC PR      : $O_PR
  Step 5 — Tekton PR   : $T_PR
  Step 6 — Operator PR : $OP_PR
  Step 7 — Bundle PR   : $B_PR" \
      2>/dev/null || true

    jq '.all_done = true' "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && \
      mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
    log "Jira moved to Resolved. Onboarding complete."
    exit 0
  fi

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    log "WARNING: Timed out after ${MAX_WAIT}s. Not all steps are done."
    log "Check pipeline_state.json and individual .result files."
    exit 1
  fi
  log "Not all done. Sleeping ${POLL_INTERVAL}s. (elapsed=${ELAPSED}s)"
  sleep $POLL_INTERVAL
  ELAPSED=$(( ELAPSED + POLL_INTERVAL ))
done
```

After writing, substitute and launch:

```bash
sed -i'' \
  -e "s|PLACEHOLDER_WORKDIR|$WORKDIR|g" \
  -e "s|PLACEHOLDER_JIRA_URL|$JIRA_URL|g" \
  -e "s|PLACEHOLDER_COMMON_SCRIPTS_DIR|$COMMON_SCRIPTS_DIR|g" \
  "$WORKDIR/monitor_completion.sh"
chmod +x "$WORKDIR/monitor_completion.sh"

nohup bash "$WORKDIR/monitor_completion.sh" >> "$WORKDIR/monitor_completion.log" 2>&1 &
echo $! > "$WORKDIR/monitor_completion.pid"
echo "[WRAPPER] Completion monitor started (PID=$(cat $WORKDIR/monitor_completion.pid))"
echo "[WRAPPER] Log: $WORKDIR/monitor_completion.log"
```

---

## Step 13: Print Final Summary

Print the following, substituting all variable values:

```
=== onboard-konflux-components-for-odh-and-rhoai — Phase 1 Complete ===

  Component      : <COMPONENT_NAME>
  Product        : <PRODUCT_CONTEXT>
  Jira           : <JIRA_URL> (status: Review)

PRs / MRs raised:
  Step 2 Quay MR    : <QUAY_MR>
  Step 3 KRD MR     : <KRD_MR>
  Step 4 OKC PR     : <OKC_PR>
  Step 5 Workflow   : pending KRD+OKC merge (deferred_workflow.sh running in background)
  Step 6 Operator   : <OP_PR>  (or "N/A" if is_operator=false)
  Step 7 Bundle     : <BDLPR>

Background processes:
  monitor_quay.pid       log: $WORKDIR/monitor_quay.log
  monitor_krd.pid        log: $WORKDIR/monitor_krd.log
  monitor_okc.pid        log: $WORKDIR/monitor_okc.log
  monitor_operator.pid   log: $WORKDIR/monitor_operator.log   [if is_operator=true]
  deferred_workflow.pid  log: $WORKDIR/deferred_workflow.log
  monitor_completion.pid log: $WORKDIR/monitor_completion.log

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
| Completion monitor times out (4h) | 12 | Check `.result` files; re-run `monitor_completion.sh` |
| Jira `--status "Resolved"` fails | 12 | Check available Jira transitions; adjust status name |
| Re-run needed after failure | Any | Re-invoke skill; `pipeline_state.json` skips completed steps |
