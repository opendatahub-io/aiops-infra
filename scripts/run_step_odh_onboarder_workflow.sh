#!/usr/bin/env bash
# Wrapper for the run-odh-konflux-onboarder-workflow step (ODH only).
#
# Triggers the odh-konflux-onboarder GitHub Actions workflow, extracts the
# resulting Tekton PR URL from the workflow logs, and records it in pipeline state.
#
# Exit codes:
#   0  Workflow triggered and Tekton PR URL extracted — prints PR_URL=<url>;
#      writes pipeline_state.json (status=pr_raised)
#   1  Failure (403/404 from API, workflow failed, timeout) — stderr has error;
#      pipeline_state.json NOT written
#
# Known failure modes encoded here:
#   - HTTP 422 from workflow dispatch: okc/krd not yet merged — exit 1 with message
#   - HTTP 403: GITHUB_TOKEN lacks actions:write — exit 1 immediately (no retry)
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$JIRA_URL" ]] && { echo "ERROR: --jira-url is required" >&2; exit 1; }

JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
PIPELINE_STATE="${PIPELINE_STATE:-${WORKDIR}/pipeline_state.json}"
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ ! -f "$PIPELINE_STATE" ]] && {
  echo "ERROR: pipeline_state.json not found at $PIPELINE_STATE" >&2; exit 1
}

EXISTING_URL=$(jq -r '.steps.onboarder_workflow.pr_url // ""' "$PIPELINE_STATE")
if [[ -n "$EXISTING_URL" ]]; then
  echo "PR already recorded in state: $EXISTING_URL"
  echo "PR_URL=$EXISTING_URL"
  exit 0
fi

# Dry-run bypass — workflow requires GitHub App secrets unavailable on forks
if [[ "${ONBOARD_DRY_RUN:-false}" == "true" ]]; then
  echo "ONBOARD_DRY_RUN=true — skipping onboarder workflow trigger, marking onboarder_workflow as done."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "tekton-pr-raised" \
    --comment "[step:onboarder_workflow] Skipped (ONBOARD_DRY_RUN=true). ODH onboarder workflow not triggered." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step onboarder_workflow \
    --status done
  exit 0
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

REPO_URL=$(grep -m1       'repo_url:'      "$YAML_FILE" | awk '{print $2}')
REPO_BRANCH=$(grep -m1    'repo_branch:'   "$YAML_FILE" | awk '{print $2}')
BUILD_TYPE=$(grep -m1     'build_type:'    "$YAML_FILE" | awk '{print $2}' 2>/dev/null || echo "CI")
VERSION=$(grep -m1        'odh_release_tag:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null || echo "")
PRODUCT_CONTEXT=$(grep -m1 'product_context:' "$YAML_FILE" | awk '{print $2}' 2>/dev/null || echo "ODH")

REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"
COMPONENT="$REPO_NAME"

BUILD_TYPE_LOWER=$(echo "$BUILD_TYPE" | tr '[:upper:]' '[:lower:]')
if [[ "$BUILD_TYPE_LOWER" == "ci" ]]; then
  BUILD_TYPE="CI"
elif [[ "$BUILD_TYPE_LOWER" == "release" ]]; then
  BUILD_TYPE="Release"
  [[ -z "$VERSION" ]] && {
    echo "ERROR: build_type=Release but odh_release_tag is missing from YAML." >&2; exit 1
  }
fi

OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"
OKC_REF="main"

echo "Triggering odh-konflux-onboarder workflow for component: $COMPONENT"
echo "OKC_URL     : $OKC_URL"
echo "Build type  : $BUILD_TYPE"
echo "Branch      : $REPO_BRANCH"

# Build workflow inputs
WORKFLOW_INPUTS=(
  "--input" "component=$COMPONENT"
  "--input" "repo_url=$REPO_URL"
  "--input" "pr_target_branch=$REPO_BRANCH"
  "--input" "build_type=$BUILD_TYPE"
)
[[ -n "$VERSION" ]] && WORKFLOW_INPUTS+=("--input" "version=$VERSION")

# Trigger (up to 3 attempts)
RUN_ID=""
for attempt in 1 2 3; do
  TRIGGER_ERR=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" trigger \
    --repo-url  "$OKC_URL" \
    --workflow  "$WORKFLOW_FILE" \
    --ref       "$OKC_REF" \
    "${WORKFLOW_INPUTS[@]}" 2>/tmp/onboarder_trigger_err.txt) && {
    RUN_ID="$TRIGGER_ERR"
    break
  }
  ERR_CONTENT=$(cat /tmp/onboarder_trigger_err.txt 2>/dev/null || echo "")
  if echo "$ERR_CONTENT" | grep -q "403"; then
    echo "ERROR: HTTP 403 — GITHUB_TOKEN needs 'actions:write' scope." >&2; exit 1
  fi
  if echo "$ERR_CONTENT" | grep -q "404"; then
    echo "ERROR: HTTP 404 — workflow or repo not found." >&2; exit 1
  fi
  if echo "$ERR_CONTENT" | grep -q "422"; then
    echo "ERROR: HTTP 422 — component may not be registered in the workflow yet." >&2
    echo "  Ensure the okc PR is merged and the component appears in the workflow's component list." >&2
    exit 1
  fi
  [[ "$attempt" -eq 3 ]] && {
    echo "ERROR: Could not trigger odh-konflux-onboarder workflow after 3 attempts." >&2
    cat /tmp/onboarder_trigger_err.txt >&2
    exit 1
  }
  sleep 10
done

RUN_URL="https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}"
echo "Workflow triggered. Run ID: $RUN_ID"
echo "Run URL: $RUN_URL"

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "tekton-pr-raised" \
  --comment "odh-konflux-onboarder workflow triggered (Run #${RUN_ID}).

Component: ${COMPONENT}
Repo: ${REPO_URL}

Workflow run: ${RUN_URL}

Monitoring for Tekton PR URL..." || true

# Monitor (up to 30 minutes) and extract Tekton PR URL from logs
MONITOR_OUTPUT=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" monitor \
  --repo-url      "$OKC_URL" \
  --run-id        "$RUN_ID" \
  --timeout       30 \
  --poll-interval 60 2>/dev/null || echo "status=failure")
WORKFLOW_STATUS="${MONITOR_OUTPUT#status=}"

if [[ "$WORKFLOW_STATUS" != "success" ]]; then
  echo "ERROR: Onboarder workflow run ${RUN_ID} ended with status '${WORKFLOW_STATUS}'." >&2
  echo "Run URL: $RUN_URL" >&2
  exit 1
fi

# Extract Tekton PR URL from workflow logs
TEKTON_PR_URL=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
  --repo-url  "$OKC_URL" \
  --run-id    "$RUN_ID" 2>/dev/null || echo "")

[[ -z "$TEKTON_PR_URL" ]] && {
  # Fallback: look for PR URL in logs directly
  TEKTON_PR_URL=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" get-step-logs \
    --repo-url "$OKC_URL" \
    --run-id   "$RUN_ID" \
    --step     "Create PR" 2>/dev/null \
    | grep -oE 'https://github.com/[^/]+/[^/]+/pull/[0-9]+' | head -1 || echo "")
}

[[ -z "$TEKTON_PR_URL" ]] && {
  echo "WARN: Could not extract Tekton PR URL from workflow logs."
  echo "  Check run manually: $RUN_URL"
  TEKTON_PR_URL="$RUN_URL"
}

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment "[step:onboarder_workflow] odh-konflux-onboarder workflow completed.

Tekton PR: ${TEKTON_PR_URL}
Workflow run: ${RUN_URL}" || true

bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
  --state "$PIPELINE_STATE" --step onboarder_workflow \
  --status pr_raised --url "$TEKTON_PR_URL" --url-field pr_url

echo "PR_URL=${TEKTON_PR_URL}"
