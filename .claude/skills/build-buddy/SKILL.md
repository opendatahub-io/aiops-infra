---
name: build-buddy
description: AI-powered Konflux build failure analyzer. Diagnoses PipelineRun failures, classifies intermittent vs persistent issues, suggests fixes, and optionally retriggers builds. Accepts Jira URLs or direct PipelineRun URLs.
allowed-tools: Bash
user-invocable: true
---

# Build Buddy

Diagnoses Konflux PipelineRun failures with a dual-engine architecture:
- **Fix-Engine**: Pipeline-Pilot container (primary) or MCP `ask_persona` (fallback)
- **Verification-Engine**: MCP `ask_persona` (primary) or Claude Code (fallback if MCP is fix-engine)

Constraint: the same tool CANNOT serve as both fix-engine and verification-engine.

## Usage

```
/build-buddy --input <jira-url-or-pipelinerun-url> [options]
```

**Options:**
- `--execution-mode interactive|ci` (default: interactive)
- `--dry-run` — report only, no retrigger or Jira updates
- `--allow-retrigger true|false` (default: true)
- `--pp-image <image>` — PP container image override
- `--output-dir <dir>` — output directory (default: ./build-buddy-output/)

## Locate Scripts Directory

```bash
SCRIPTS_DIR="${AIOPS_INFRA_DIR:-/tmp/aiops-infra}/scripts"
BB_SCRIPTS="${AIOPS_INFRA_DIR:-/tmp/aiops-infra}/.claude/skills/build-buddy/scripts/build-buddy"
if [[ ! -d "$BB_SCRIPTS" ]]; then
  echo "ERROR: build-buddy scripts not found at $BB_SCRIPTS"
  echo "  Set AIOPS_INFRA_DIR to the root of the aiops-infra checkout."
  exit 1
fi
echo "BB_SCRIPTS: $BB_SCRIPTS"
```

---

## Step 0: Parse Inputs

Extract the `--input` URL and flags from arguments.

```bash
source "$BB_SCRIPTS/config.sh"

INPUT_URL=""
BB_EXECUTION_MODE="${BB_EXECUTION_MODE:-interactive}"
BB_DRY_RUN="${BB_DRY_RUN:-false}"
BB_ALLOW_RETRIGGER="${BB_ALLOW_RETRIGGER:-true}"
BB_PP_IMAGE="${BB_PP_IMAGE:-quay.io/rhoai-devops/pipeline-pilot:latest}"
BB_OUTPUT_DIR="${BB_OUTPUT_DIR:-./build-buddy-output}"

for arg in "$@"; do
  case "$prev_arg" in
    --input)           INPUT_URL="$arg" ;;
    --execution-mode)  BB_EXECUTION_MODE="$arg" ;;
    --allow-retrigger) BB_ALLOW_RETRIGGER="$arg" ;;
    --pp-image)        BB_PP_IMAGE="$arg" ;;
    --output-dir)      BB_OUTPUT_DIR="$arg" ;;
  esac
  [[ "$arg" == "--dry-run" ]] && BB_DRY_RUN="true"
  prev_arg="$arg"
done

[[ -z "$INPUT_URL" ]] && { echo "ERROR: --input is required."; exit 1; }
echo "Input: $INPUT_URL | Mode: $BB_EXECUTION_MODE | Dry-run: $BB_DRY_RUN"
```

---

## Step 1: Prerequisites

```bash
bash "$BB_SCRIPTS/prereqs.sh"
```

---

## Step 2: Resolve Input URL

If the input is a Jira URL, extract the Konflux PipelineRun URL from the ticket.

**AI Task — Jira URL Resolution:**
If `INPUT_URL` matches `atlassian.net` or `jira`:

1. Fetch the Jira issue using MCP `get_jira_issue` or `curl` with Jira API.
2. Search these fields for Konflux PipelineRun URLs:
   - Description text
   - Comment bodies
   - Remote links (web links attached to the issue)
3. URL patterns to match: any URL containing `/pipelinerun/` on Konflux domains
   (e.g., `console-openshift-console.apps.stone-prd-rh01.pg1f.p1.openshiftapps.com`).
4. If multiple URLs found, use the most recent one (latest comment first).
5. If no URL found, report error and stop.

```bash
# After AI resolution, the orchestrator sets:
# PIPELINE_URL=<resolved PipelineRun URL>
# JIRA_KEY=<e.g. RHOAIENG-1234>
# NAMESPACE=<extracted from URL path>
# PR_NAME=<extracted from URL path>
echo "Resolved: PIPELINE_URL=$PIPELINE_URL"
```

If the input is already a PipelineRun URL, extract namespace and name from it:

```bash
# Example URL: https://console.../k8s/ns/<ns>/tekton.dev~v1~PipelineRun/<name>
NAMESPACE=$(echo "$PIPELINE_URL" | grep -oP 'ns/\K[^/]+')
PR_NAME=$(echo "$PIPELINE_URL" | grep -oP 'PipelineRun/\K[^/?#]+')
echo "Namespace: $NAMESPACE | PipelineRun: $PR_NAME"
```

---

## Step 3: Start Pipeline-Pilot Container

```bash
source "$BB_SCRIPTS/pp-container.sh"
trap 'pp_stop 2>/dev/null || true' EXIT
PP_AVAILABLE="false"
if pp_start; then
  PP_AVAILABLE="true"
fi
```

---

## Step 4: Fix-Engine Analysis

### 4a: Primary — Pipeline-Pilot

If `PP_AVAILABLE == "true"`:

```bash
PP_ANALYSIS_FILE="${BB_OUTPUT_DIR}/pp-analysis.json"
mkdir -p "$BB_OUTPUT_DIR"
if pp_analyze "$PIPELINE_URL" --output-file "$PP_ANALYSIS_FILE"; then
  FIX_ENGINE="pipeline-pilot"
  echo "PP analysis succeeded."
else
  echo "PP analysis failed. Using MCP fallback."
  FIX_ENGINE="mcp"
fi
```

### 4b: Fallback — MCP ask_persona

If PP failed or was unavailable, the orchestrator (you, Claude Code) uses MCP to analyze:

**AI Task — MCP Fix Analysis:**
Use `ask_persona` (or equivalent MCP tool) to analyze the PipelineRun failure:
- Pass the PipelineRun name, namespace, and any logs available via `oc`
- Request: failed task name, failed step, failure category (build/test/infra/unknown),
  root cause analysis, and numbered fix steps with concrete commands

Store the result as `FIX_ENGINE="mcp"` and capture the analysis output.

---

## Step 5: Extract Failure Details

From the analysis output (PP JSON or MCP response), extract:

```bash
# These variables should be set by the orchestrator after parsing analysis:
# FAILED_TASK, FAILED_STEP, FAILURE_CATEGORY, ROOT_CAUSE, FIX_STEPS
# COMPONENT_NAME (from PipelineRun labels: appstudio.openshift.io/component)
COMPONENT_NAME=$(oc get pipelinerun "$PR_NAME" -n "$NAMESPACE" \
  -o jsonpath='{.metadata.labels.appstudio\.openshift\.io/component}' 2>/dev/null || echo "unknown")
echo "Component: $COMPONENT_NAME"
```

---

## Step 6: Verification-Engine

Constraint: verification-engine must differ from fix-engine.

- If `FIX_ENGINE == "pipeline-pilot"` → verification-engine = MCP `ask_persona`
- If `FIX_ENGINE == "mcp"` → verification-engine = Claude Code (the orchestrator itself)

**AI Task — Verification Prompt:**

> You are a verification engine for Konflux build failure analysis.
> Review this diagnosis and proposed fix for accuracy:
>
> **Component:** {COMPONENT_NAME}
> **Failed Task:** {FAILED_TASK}
> **Root Cause:** {ROOT_CAUSE}
> **Proposed Fix Steps:**
> {FIX_STEPS}
>
> Evaluate:
> 1. Is the root cause plausible given the failure context?
> 2. Are the fix steps correct and complete?
> 3. Are there any risks or side effects?
> 4. Confidence level: HIGH / MEDIUM / LOW
>
> Respond with verification notes and any corrections.

Store the verification output in `VERIFY_NOTES`.

```bash
VERIFY_ENGINE="mcp"
[[ "$FIX_ENGINE" == "mcp" ]] && VERIFY_ENGINE="claude-code"
echo "Verification engine: $VERIFY_ENGINE"
```

---

## Step 7: Intermittent Failure Classification

**AI Task — Classify Failure:**

Using the analysis output, classify whether the failure is intermittent:

**Intermittent signals** (likely retrigger will help):
- Infrastructure errors: network timeouts, ImagePullBackOff, OOM, TLS failures
- Transient cluster issues: scheduling failures, node pressure
- External service flakiness: registry unavailable, API rate limits

**Persistent signals** (retrigger will NOT help):
- Code compilation errors, test assertion failures
- Configuration mistakes, missing dependencies
- Permission/RBAC errors (unless cluster-wide transient)

```bash
# Set by AI classification:
# IS_INTERMITTENT="true" or "false"
echo "Intermittent: $IS_INTERMITTENT"
```

---

## Step 8: Retrigger Decision

```bash
source "$BB_SCRIPTS/retrigger.sh"
RETRIGGER_STATUS="skipped"

if [[ "$IS_INTERMITTENT" == "true" && "$BB_ALLOW_RETRIGGER" == "true" && "$BB_DRY_RUN" != "true" ]]; then
  if [[ "$BB_EXECUTION_MODE" == "ci" ]]; then
    # CI mode: auto-retrigger
    if retrigger_pipeline "$PR_NAME" "$NAMESPACE"; then
      RETRIGGER_STATUS="triggered"
    else
      RETRIGGER_STATUS="failed"
    fi
  else
    # Interactive mode: ask user
    echo ""
    echo "This failure appears intermittent. Retrigger the build?"
    echo "  PipelineRun: $PR_NAME"
    echo "  Namespace:   $NAMESPACE"
    # The orchestrator (Claude Code) should ask the user for confirmation here.
    # If confirmed, call: retrigger_pipeline "$PR_NAME" "$NAMESPACE"
    RETRIGGER_STATUS="awaiting-confirmation"
  fi
elif [[ "$BB_DRY_RUN" == "true" ]]; then
  RETRIGGER_STATUS="dry-run-skipped"
fi
echo "Retrigger status: $RETRIGGER_STATUS"
```

---

## Step 9: Generate Report

```bash
source "$BB_SCRIPTS/output.sh"
REPORT_FILE=$(generate_report \
  --pr-name "$PR_NAME" \
  --namespace "$NAMESPACE" \
  --component "$COMPONENT_NAME" \
  --jira-key "${JIRA_KEY:-}" \
  --fix-engine "$FIX_ENGINE" \
  --verify-engine "$VERIFY_ENGINE" \
  --failed-task "${FAILED_TASK:-}" \
  --failed-step "${FAILED_STEP:-}" \
  --failure-category "${FAILURE_CATEGORY:-unknown}" \
  --is-intermittent "$IS_INTERMITTENT" \
  --root-cause "${ROOT_CAUSE:-}" \
  --fix-steps "${FIX_STEPS:-}" \
  --verify-notes "${VERIFY_NOTES:-}" \
  --retrigger-status "$RETRIGGER_STATUS" \
  --jira-status "${JIRA_STATUS:-N/A}" \
  --output-dir "$BB_OUTPUT_DIR")
echo "Report: $REPORT_FILE"
cat "$REPORT_FILE"
```

---

## Step 10: Jira Update

If a Jira key is available and not in dry-run mode:

**AI Task — Jira Comment:**
Post the report content as a Jira comment using MCP `comment_on_jira_issue` or the Jira API.

```bash
JIRA_STATUS="N/A"
if [[ -n "${JIRA_KEY:-}" && "$BB_DRY_RUN" != "true" ]]; then
  if [[ "$BB_EXECUTION_MODE" == "ci" ]]; then
    # CI mode: auto-update Jira
    JIRA_STATUS="posted"
  else
    # Interactive mode: ask user before posting
    echo "Post analysis report to Jira $JIRA_KEY?"
    JIRA_STATUS="awaiting-confirmation"
  fi
fi
echo "Jira update: $JIRA_STATUS"
```

Regenerate the report with final Jira status if it changed:

```bash
if [[ "$JIRA_STATUS" != "N/A" ]]; then
  REPORT_FILE=$(generate_report \
    --pr-name "$PR_NAME" \
    --namespace "$NAMESPACE" \
    --component "$COMPONENT_NAME" \
    --jira-key "${JIRA_KEY:-}" \
    --fix-engine "$FIX_ENGINE" \
    --verify-engine "$VERIFY_ENGINE" \
    --failed-task "${FAILED_TASK:-}" \
    --failed-step "${FAILED_STEP:-}" \
    --failure-category "${FAILURE_CATEGORY:-unknown}" \
    --is-intermittent "$IS_INTERMITTENT" \
    --root-cause "${ROOT_CAUSE:-}" \
    --fix-steps "${FIX_STEPS:-}" \
    --verify-notes "${VERIFY_NOTES:-}" \
    --retrigger-status "$RETRIGGER_STATUS" \
    --jira-status "$JIRA_STATUS" \
    --output-dir "$BB_OUTPUT_DIR")
fi
```

---

## Step 11: Cleanup

```bash
pp_stop 2>/dev/null || true
echo ""
echo "=== Build Buddy Complete ==="
echo "Report: $REPORT_FILE"
```
