---
name: run-odh-konflux-onboarder-workflow
description: Triggers the odh-konflux-onboarder GitHub Actions workflow in odh-konflux-central, monitors it to completion, extracts the Tekton PR URL from workflow logs, and updates the Jira issue. Automates Step 6 of the ODH component onboarding pipeline.
allowed-tools: Bash, Read, Write
user-invocable: true
---

# Run ODH Konflux Onboarder Workflow

Triggers the `odh-konflux-onboarder` GitHub Actions workflow in the
`odh-konflux-central` repository, monitors it to completion, extracts the
Tekton PR URL from the workflow logs, and optionally updates the Jira issue with
progress labels and comments.

This is **Step 6** of the ODH component onboarding pipeline ("Run CI/Nightly Build").

> **CRITICAL — `ODH_KONFLUX_CENTRAL_REPO_URL` overrides the default repo for every step.**
> This env var is resolved once in Step 0 into `OKC_URL` and `OKC_PATH`.
> Every subsequent GitHub API call, workflow trigger, and monitor operation **must**
> use `$OKC_URL` / `$OKC_PATH` — never the hardcoded upstream URL
> `https://github.com/opendatahub-io/odh-konflux-central.git`.
> This rule holds for the entire skill execution, even if the URL resolves to a fork.

## Usage

```
/run-odh-konflux-onboarder-workflow [<jira-url>]
```

Examples:
```
/run-odh-konflux-onboarder-workflow https://redhat.atlassian.net/browse/RHODS-14226
/run-odh-konflux-onboarder-workflow   # no Jira — interactive Q&A
```

## Prerequisites

- `GITHUB_USER` — your GitHub username (`export GITHUB_USER=yourusername`)
- `GITHUB_TOKEN` — GitHub PAT with `repo` + `actions:write` scope
- `JIRA_USER_EMAIL` — your Atlassian account email (required only when Jira URL is given)
- `JIRA_API_TOKEN` — Atlassian API token (required only when Jira URL is given)
- `uv` — Python runner (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Optional: `ODH_KONFLUX_CENTRAL_REPO_URL` (default: `https://github.com/opendatahub-io/odh-konflux-central.git`)
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)

**Dependency:** The `add-component-to-odh-konflux-central` skill (Step 4) must have
run and its PR must be merged before this skill will succeed. The component must be
listed in the workflow's `components:` options before dispatch.

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 0: Parse Inputs and Resolve URLs

Extract the optional `<jira-url>` argument from the invocation.

```bash
JIRA_URL="${1:-}"   # first argument, or empty

# Validate format if provided
if [[ -n "$JIRA_URL" && "$JIRA_URL" != *"/browse/"* ]]; then
  echo "ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHODS-14226"
  exit 1
fi

# Extract Jira ID from URL (last path segment, e.g. RHODS-14226)
JIRA_ID=""
if [[ -n "$JIRA_URL" ]]; then
  JIRA_ID="${JIRA_URL##*/}"
fi

# Resolve OKC repo URL — single source of truth for all GitHub operations
OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
echo "ODH_KONFLUX_CENTRAL_REPO_URL=${ODH_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}"
echo "OKC_URL resolved to: $OKC_URL"

# Derive owner/repo path for GitHub API calls and run URLs
OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
# e.g. "opendatahub-io/odh-konflux-central"

# Workflow dispatch target (branch in OKC repo)
OKC_REF="main"

# Relative path to the workflow file inside OKC repo
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"
```

> **Never override or re-derive `OKC_URL` after this step.** Every Git operation,
> GitHub API call, workflow trigger, and monitor call must use `$OKC_URL` / `$OKC_PATH`.

---

## Step 1: Check Prerequisites

Check in order. Stop with a remediation message if any check fails.

```bash
# 1. GITHUB_USER
if [[ -z "${GITHUB_USER:-}" ]]; then
  echo "ERROR: GITHUB_USER is not set. export GITHUB_USER=yourusername"
  exit 1
fi

# 2. GITHUB_TOKEN
if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "ERROR: GITHUB_TOKEN is not set. export GITHUB_TOKEN=yourtoken"
  echo "  Token needs: repo scope + actions:write scope"
  exit 1
fi

# 3. Jira credentials (only when JIRA_URL is non-empty)
if [[ -n "$JIRA_URL" ]]; then
  if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
    echo "ERROR: JIRA_USER_EMAIL is not set. export JIRA_USER_EMAIL=you@redhat.com"
    exit 1
  fi
  if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
    echo "ERROR: JIRA_API_TOKEN is not set."
    echo "  Create at: https://id.atlassian.com/manage-profile/security/api-tokens"
    exit 1
  fi
fi

# 4. uv
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
```

---

## Step 2: Set Up Working Directory

```bash
if [[ -n "$JIRA_ID" ]]; then
  WORKDIR="$(pwd)/${JIRA_ID}"
else
  WORKDIR="$(pwd)"
fi
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"

YAML_PATH="${WORKDIR}/component_onboarding_details.yaml"
```

---

## Step 3: Collect Component Inputs

### Branch A — Jira URL provided

**3A-1. Fetch Jira details** (skip if `$WORKDIR/component_onboarding_details.json` already exists):

```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py "$JIRA_URL"
```

On exit 1: display stderr and stop:
```
ERROR in Step 3 (Fetch Jira): Could not fetch Jira issue. See above. Aborting.
```

**3A-2. Download component YAML** (skip if `$YAML_PATH` already exists):

```bash
cd "$WORKDIR"
uv run --script <COMMON_SCRIPTS_DIR>/download_jira_attachment.py \
  "$JIRA_URL" component_onboarding_details.yaml
```

On exit 1: stop with:
```
ERROR in Step 3 (Download YAML): 'component_onboarding_details.yaml' not found as a
  Jira attachment. Please attach the file to the Jira issue and re-run.
```

**3A-3. Parse YAML.** Use the `Read` tool to read `$YAML_PATH`. Extract under `inputs:`:

| Variable | YAML field | Notes |
|----------|-----------|-------|
| `PRODUCT_CONTEXT` | `inputs.product_context` | `ODH` or `RHOAI` |
| `REPO_URL` | `inputs.repo_url` | Full HTTPS URL |
| `PR_TARGET_BRANCH` | `inputs.repo_branch` | Branch to build against |
| `BUILD_TYPE` | `inputs.build_type` | `CI` or `Release` |
| `VERSION` | `inputs.output_image_tag` | Only for Release builds |

If a `component_onboarding_details.yaml` already exists in `$WORKDIR` (JIRA_URL is
empty), use it and announce:
```
Found component_onboarding_details.yaml in current directory. Reading inputs from file.
(Delete or rename it to use interactive mode instead.)
```

Derive `COMPONENT` (the `component` workflow input) from `REPO_URL`:
```bash
# Extract GitHub repo name from URL (last path segment, strip .git)
REPO_NAME="${REPO_URL##*/}"
COMPONENT="${REPO_NAME%.git}"
# e.g. https://github.com/opendatahub-io/opendatahub-operator → opendatahub-operator
```

Normalize `BUILD_TYPE` (case-insensitive from YAML):
```bash
BUILD_TYPE_LOWER="${BUILD_TYPE,,}"
if [[ "$BUILD_TYPE_LOWER" == "ci" ]]; then
  BUILD_TYPE="CI"
elif [[ "$BUILD_TYPE_LOWER" == "release" ]]; then
  BUILD_TYPE="Release"
else
  echo "ERROR in Step 3: Unknown build_type '${BUILD_TYPE}'. Expected CI or Release."
  exit 1
fi
```

If `BUILD_TYPE == Release` and `VERSION` is empty, stop with:
```
ERROR in Step 3: build_type is Release but 'inputs.output_image_tag' is missing from
  component_onboarding_details.yaml. Add 'output_image_tag: <version>' under inputs: and re-run.
```

If any required field (`PRODUCT_CONTEXT`, `REPO_URL`, `PR_TARGET_BRANCH`, `BUILD_TYPE`)
is missing from the YAML, stop with:
```
ERROR in Step 3: Required field '<field>' is missing from component_onboarding_details.yaml.
```

### Branch B — No Jira URL and no YAML file (interactive Q&A)

Skip this branch if `$YAML_PATH` already exists (use Branch A's YAML parsing instead).

Ask each question sequentially. Wait for the answer before proceeding. Re-ask on
invalid input with an explanation.

**B1 — Product context**
> Which product is this component being onboarded for?
> Options: ODH, RHOAI

→ Store in `PRODUCT_CONTEXT` (uppercase).

**B2 — Component (repository name)**
> What is the GitHub repository name of the component to onboard?
> (e.g. opendatahub-operator, modelmesh-serving)

→ Store in `COMPONENT`. Must match `^[a-z0-9]+(-[a-z0-9]+)*$`. Re-ask with rule if invalid.

**B3 — PR target branch**
> What is the branch to onboard the component into?
> (e.g. main, release-2.x)

→ Store in `PR_TARGET_BRANCH`. Must be non-empty.

**B4 — Build type**
> Should this be a CI or Release build?
> Options: CI, Release

→ Store in `BUILD_TYPE`. Must be exactly `CI` or `Release`.

**B5 — Version (Release only)**
> What is the version string for this release build? (e.g. 2.21.0)

→ Only asked when `BUILD_TYPE == Release`. Store in `VERSION`. Must be non-empty.

### Product context gate (applies to both branches)

```bash
if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  echo "ERROR: This workflow is for ODH component onboarding only."
  echo "  RHOAI onboarding uses a different process. Aborting."
  exit 1
fi
```

---

## Step 4: Show Collected Inputs and Confirm

Display a summary table and ask the user to confirm before triggering:

```
Workflow inputs collected:

  OKC repo              : $OKC_URL
  Workflow file         : $WORKFLOW_FILE
  Dispatch ref          : $OKC_REF

  component             : $COMPONENT
  pr_target_branch      : $PR_TARGET_BRANCH
  build_type            : $BUILD_TYPE
  version               : ${VERSION:-N/A}
  product_context       : $PRODUCT_CONTEXT

Proceed? (yes / no)
```

- `yes` → continue
- `no` → print `Aborted by user.` and stop
- any other input → re-ask

---

## Step 5: Idempotency Check — Existing Tekton PR

**Skip this step if `JIRA_URL` is empty.**

Use the `Read` tool to read `$WORKDIR/component_onboarding_details.json`.
Scan `fields.comment.comments[].body` for GitHub PR URLs matching:
```
https://github\.com/[^/\s]+/[^/\s]+/pull/\d+
```

For each URL found, run:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url <found-url> --check-only
```

If stdout contains `state=open` or `state=merged` **and** the URL domain matches
`$OKC_PATH`:
```
Found existing Tekton PR: <found-url> (state=<state>)
This PR appears to be from a previous workflow run for this component.
Jump to monitoring this PR instead of triggering a new workflow run? (yes / no)
```

- `yes` → set `TEKTON_PR_URL=<found-url>` and **jump to Step 9** (Monitor PR)
- `no` → continue to Step 6 (trigger a new run)

If no matching URL is found, continue to Step 6.

---

## Step 6: Trigger the Workflow

Build the inputs and dispatch:

```bash
cd "$WORKDIR"

# Collect inputs into an array of --input k=v flags
TRIGGER_INPUTS=(
  "--input" "component=${COMPONENT}"
  "--input" "pr_target_branch=${PR_TARGET_BRANCH}"
  "--input" "build_type=${BUILD_TYPE}"
)
if [[ "$BUILD_TYPE" == "Release" ]]; then
  TRIGGER_INPUTS+=("--input" "version=${VERSION}")
fi

RUN_ID=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py trigger \
  --repo-url "$OKC_URL" \
  --workflow "$WORKFLOW_FILE" \
  --ref "$OKC_REF" \
  "${TRIGGER_INPUTS[@]}")
```

On exit 1:
- If stderr mentions "422" or "inputs" → display the full stderr and stop:
  ```
  ERROR in Step 6 (Trigger): Workflow dispatch rejected (HTTP 422).
    Most likely cause: '$COMPONENT' is not yet in the workflow's component options list.
    Ensure the Step 4 skill PR (add-component-to-odh-konflux-central) is merged first.
    Check Jira comments for a label 'okc-changes-done' confirming Step 4 is complete.
  ```
- If stderr mentions "403" → stop:
  ```
  ERROR in Step 6 (Trigger): Permission denied (HTTP 403).
    GITHUB_TOKEN needs 'actions:write' scope (or 'workflow' scope on classic PATs).
  ```
- Any other error → display stderr and stop:
  ```
  ERROR in Step 6 (Trigger): Could not dispatch workflow. See above. Aborting.
  ```

On success:
```
Workflow run triggered.
  Run ID   : $RUN_ID
  Run URL  : https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}
```

Post an interim Jira comment if `JIRA_URL` is non-empty:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --comment "odh-konflux-onboarder workflow triggered (Run #${RUN_ID}).

Component       : $COMPONENT
PR target branch: $PR_TARGET_BRANCH
Build type      : $BUILD_TYPE${VERSION:+
Version         : $VERSION}

Workflow run: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Monitoring in progress (max 30 minutes)..."
```

---

## Step 7: Monitor Workflow (30 minutes max)

```bash
MONITOR_OUTPUT=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py monitor \
  --repo-url "$OKC_URL" \
  --run-id "$RUN_ID" \
  --timeout 30 \
  --poll-interval 60)
# MONITOR_OUTPUT is e.g. "status=success" or "status=failure"
WORKFLOW_STATUS="${MONITOR_OUTPUT#status=}"
```

**On `success`:** print:
```
Workflow run $RUN_ID completed successfully.
```
Continue to Step 8.

**On `failure`:**

Attempt automated diagnosis — fetch the failure logs:
```bash
FAILURE_LOGS=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py get-step-logs \
  --repo-url "$OKC_URL" \
  --run-id "$RUN_ID" \
  --step "Run onboarder" 2>/dev/null) || true
```

Display to the user:
```
Workflow run $RUN_ID FAILED.
Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Log excerpt:
<first 60 lines of FAILURE_LOGS, or "(could not fetch logs)" if empty>

Would you like to re-trigger the workflow with the same inputs? (yes / no)
```

- `yes` → return to Step 6 (re-trigger **once only**). If the second run also fails,
  update Jira and stop with:
  ```
  ERROR in Step 7: Workflow failed on second attempt. Manual investigation required.
  Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}
  ```
- `no` → update Jira (if applicable) and stop:
  ```
  ERROR in Step 7: Workflow run $RUN_ID failed. See logs above.
  ```

If `JIRA_URL` non-empty, update Jira on failure (before stopping):
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --comment "odh-konflux-onboarder workflow run #${RUN_ID} FAILED.

Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Please inspect the run logs and re-run /run-odh-konflux-onboarder-workflow to retry."
```

**On `cancelled`:** Display and stop:
```
ERROR in Step 7: Workflow run $RUN_ID was cancelled.
Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}
```

**On `timeout`:** Print and stop:
```
WARNING: Workflow run $RUN_ID has not completed after 30 minutes.
Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

The run may still be in progress. Re-run this skill — at Step 5 you will be offered
the option to skip triggering and jump directly to PR monitoring.
```
If `JIRA_URL` non-empty, post a Jira comment before stopping:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --comment "odh-konflux-onboarder workflow run #${RUN_ID} monitoring timed out after 30 minutes.

The run may still be completing. Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Re-run /run-odh-konflux-onboarder-workflow — it will detect the existing PR and resume."
```

---

## Step 8: Extract Tekton PR URL from Workflow Logs

Fetch the logs of the "Create pull request" step:

```bash
STEP_LOGS=$(uv run --script <COMMON_SCRIPTS_DIR>/run_github_workflow.py get-step-logs \
  --repo-url "$OKC_URL" \
  --run-id "$RUN_ID" \
  --step "Create pull request" 2>/dev/null)
STEP_EXIT=$?
```

If exit 1 (step not found), try the fallback step names in order:
1. `--step "create-pull-request"`
2. `--step "Create PR"`
3. `--step "pull request"`

If all fallbacks fail, ask the user:
```
WARNING: Could not locate the "Create pull request" step in run $RUN_ID.
Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Please open the run in GitHub and locate the PR URL from the step logs.
Paste the PR URL here to continue (or type "skip" to exit):
```
If the user pastes a URL, set `TEKTON_PR_URL` to that value and continue to Step 9.
If the user types "skip", stop with:
```
Stopped at Step 8. Re-run /run-odh-konflux-onboarder-workflow when you have the PR URL.
```

If step logs were fetched, extract the PR URL:
```bash
TEKTON_PR_URL=$(echo "$STEP_LOGS" \
  | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' \
  | head -1)
```

If `TEKTON_PR_URL` is empty after extraction, display the full `$STEP_LOGS` and ask:
```
Could not auto-extract a PR URL from the step logs above.
Please paste the PR URL here (or type "skip" to exit):
```
Set `TEKTON_PR_URL` to the user's response (or stop on "skip").

Print:
```
Tekton PR URL: $TEKTON_PR_URL
```

---

## Step 9: Update Jira with PR URL

**Skip this step if `JIRA_URL` is empty.**

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --add-label "tekton-pr-raised" \
  --comment "odh-konflux-onboarder workflow completed successfully.

Tekton PR raised: $TEKTON_PR_URL

Component        : $COMPONENT
PR target branch : $PR_TARGET_BRANCH
Build type       : $BUILD_TYPE${VERSION:+
Version          : $VERSION}
Workflow run     : https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Monitoring the PR for merge..."
```

On exit 1: display stderr but **do not abort** — the PR URL has been found, so log
the Jira error as a warning and continue to Step 10.

---

## Step 10: Monitor the Tekton PR

```bash
uv run --script <COMMON_SCRIPTS_DIR>/monitor_github_pr.py \
  --pr-url "$TEKTON_PR_URL" \
  --timeout 60
```

Read the stdout result:

**`merged` (exit 0):** PR merged.

If `JIRA_URL` is non-empty:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --remove-label "tekton-pr-raised" \
  --add-label "tekton-pr-merged" \
  --comment "Tekton PR merged: $TEKTON_PR_URL

Konflux CI pipeline definitions for '$COMPONENT' are now live on '$PR_TARGET_BRANCH'.

Step 6 (Run CI/Nightly Build) is complete."
```
Print: `PR merged. Step 6 (Run CI/Nightly Build) complete.`
Continue to Step 11.

**`closed` (exit 1):** PR closed without merging.

If `JIRA_URL` is non-empty:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --comment "Tekton PR was closed without merging: $TEKTON_PR_URL

Please review and re-trigger if needed."
```
Stop with:
```
ERROR in Step 10: PR was closed without merging.
PR: $TEKTON_PR_URL
```

**`pipeline_failed` or `pipeline_canceled` (exit 1):** CI checks failed on the PR.

Display the failure to the user. If `JIRA_URL` is non-empty:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --comment "CI checks failed on Tekton PR: $TEKTON_PR_URL

Please review the PR checks and push a fix, then re-run this skill to resume monitoring."
```
Stop with:
```
ERROR in Step 10: CI checks failed on PR $TEKTON_PR_URL.
Manual intervention required — review the PR and push a fix, then re-run.
```

**`timeout` (exit 1):** PR still open after 60 minutes.

If `JIRA_URL` is non-empty:
```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --comment "PR monitoring timed out after 60 minutes. PR is still open: $TEKTON_PR_URL

Re-run /run-odh-konflux-onboarder-workflow to resume — at Step 5 it will detect the
existing PR and jump straight to monitoring."
```
Print:
```
WARNING: PR monitoring timed out after 60 minutes.
PR is still open: $TEKTON_PR_URL
Re-run this skill to resume monitoring (Step 5 will skip triggering a new run).
```

---

## Step 11: Final Status Report

Print:
```
=== run-odh-konflux-onboarder-workflow complete ===

  Component             : $COMPONENT
  PR target branch      : $PR_TARGET_BRANCH
  Build type            : $BUILD_TYPE${VERSION:+
  Version               : $VERSION}

  Workflow run          : https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}
  Tekton PR             : $TEKTON_PR_URL (merged)

  Jira updated          : ${JIRA_URL:-(no Jira URL provided)}

Step 6 (Run CI/Nightly Build) complete.
```

---

## Error Reference

| Error | Step | Remediation |
|-------|------|-------------|
| `GITHUB_USER` not set | 1 | `export GITHUB_USER=yourusername` |
| `GITHUB_TOKEN` not set | 1 | `export GITHUB_TOKEN=yourtoken` (needs repo + actions:write) |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` not set | 1 | Export env vars |
| `uv` not installed | 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Invalid Jira URL format | 0 | Check URL contains `/browse/` |
| YAML attachment missing from Jira | 3A | Attach `component_onboarding_details.yaml` to the issue |
| Unknown `build_type` in YAML | 3A | Set to `CI` or `Release` in the YAML |
| `output_image_tag` missing for Release | 3A | Add `output_image_tag: <version>` under `inputs:` in YAML |
| `PRODUCT_CONTEXT == RHOAI` | 3 | Wrong skill — RHOAI uses a different onboarding process |
| Dispatch 422 (inputs rejected) | 6 | Step 4 PR not merged yet — component not in workflow options list |
| Dispatch 403 (permission denied) | 6 | Regenerate GITHUB_TOKEN with `actions:write` scope |
| Workflow run not found after 60 s | 6 | Check OKC repo and workflow file path; retry |
| Workflow run failed | 7 | Inspect logs at run URL; fix component config; re-trigger |
| Workflow run cancelled | 7 | Re-trigger manually or re-run the skill |
| Workflow monitoring timeout | 7 | Re-run skill — Step 5 will detect existing PR |
| "Create pull request" step not found | 8 | Paste PR URL manually when prompted |
| PR CI checks failed | 10 | Review PR checks; push fix; re-run |
| PR closed without merge | 10 | Review and re-run |
| PR monitoring timeout | 10 | Re-run skill — Step 5 detects existing PR and skips triggering |
