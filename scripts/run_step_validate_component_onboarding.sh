#!/usr/bin/env bash
# Wrapper for the validate-component-onboarding step (RHOAI only).
#
# Triggers the "Run Konflux Config Validator" GitHub Actions workflow in
# red-hat-data-services/rhods-devops-infra and monitors it to completion.
#
# Exit codes:
#   0  Validation passed — writes pipeline_state.json (status done)
#   1  Validation failed, workflow error, or timeout
#   2  Already validated (idempotent)
#
# Set ONBOARD_DRY_RUN=true to bypass (fork testing).
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
TIMEOUT_MINUTES=10
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url) JIRA_URL="$2"; shift 2 ;;
    --timeout)  TIMEOUT_MINUTES="$2"; shift 2 ;;
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

CURRENT_STATUS=$(jq -r '.steps.validate_component_onboarding.status // "pending"' "$PIPELINE_STATE")
if [[ "$CURRENT_STATUS" == "done" ]]; then
  echo "validate_component_onboarding already marked done."
  exit 2
fi

YAML_FILE="$WORKDIR/component_onboarding_details.yaml"
[[ ! -f "$YAML_FILE" ]] && { echo "ERROR: $YAML_FILE not found" >&2; exit 1; }

TARGET_RHOAI_VERSION=$(grep -m1 'target_rhoai_version:' "$YAML_FILE" | awk '{print $2}' | tr -d '"' || echo "")
[[ -z "$TARGET_RHOAI_VERSION" ]] && { echo "ERROR: target_rhoai_version missing from YAML." >&2; exit 1; }

eval "$(bash "$SCRIPTS_DIR/parse_rhoai_version.sh" --version "$TARGET_RHOAI_VERSION" 2>/dev/null)"
VALIDATOR_VERSION="rhoai-${BRANCH_VAR}"

echo "Release version : $VALIDATOR_VERSION"

# ── Dry-run bypass ─────────────────────────────────────────────────────────────
if [[ "${ONBOARD_DRY_RUN:-false}" == "true" ]]; then
  echo "ONBOARD_DRY_RUN=true — skipping konflux-config-validator."
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "release-validation-skipped" \
    --comment "[step:validate_component_onboarding] Skipped (ONBOARD_DRY_RUN=true)." || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step validate_component_onboarding --status done
  exit 0
fi

# ── Trigger GitHub Actions workflow ────────────────────────────────────────────
WORKFLOW_REPO="red-hat-data-services/rhods-devops-infra"
WORKFLOW_ID="run-konflux-config-validator.yaml"

echo "Triggering konflux-config-validator workflow (version: $VALIDATOR_VERSION)..."

gh workflow run "$WORKFLOW_ID" \
  --repo "$WORKFLOW_REPO" \
  --field "RHOAI_VERSION=$VALIDATOR_VERSION" \
  --field "audit=false" 2>&1 || {
  echo "ERROR: Failed to trigger workflow." >&2; exit 1
}

# Get the run ID (wait briefly for it to register)
sleep 8
RUN_URL=$(gh run list --repo "$WORKFLOW_REPO" \
  --workflow="$WORKFLOW_ID" --limit 1 \
  --json url --jq '.[0].url' 2>/dev/null || echo "")
RUN_ID=$(gh run list --repo "$WORKFLOW_REPO" \
  --workflow="$WORKFLOW_ID" --limit 1 \
  --json databaseId --jq '.[0].databaseId' 2>/dev/null || echo "")

echo "Workflow run: $RUN_URL"

uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --comment "[step:validate_component_onboarding] konflux-config-validator triggered for ${VALIDATOR_VERSION}.

Workflow run: ${RUN_URL}

Monitoring..." || true

# ── Monitor ────────────────────────────────────────────────────────────────────
DEADLINE=$(( $(date +%s) + TIMEOUT_MINUTES * 60 ))
while true; do
  if [[ $(date +%s) -ge $DEADLINE ]]; then
    echo "ERROR: Timed out after ${TIMEOUT_MINUTES} minutes." >&2
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "[step:validate_component_onboarding] TIMEOUT — workflow did not complete within ${TIMEOUT_MINUTES} minutes.
Run URL: ${RUN_URL}" || true
    exit 1
  fi

  STATUS=$(gh run view "$RUN_ID" --repo "$WORKFLOW_REPO" \
    --json status,conclusion --jq '"\(.status) \(.conclusion)"' 2>/dev/null || echo "unknown unknown")
  WF_STATUS=$(echo "$STATUS" | awk '{print $1}')
  WF_CONCLUSION=$(echo "$STATUS" | awk '{print $2}')

  echo "  Status: $WF_STATUS / $WF_CONCLUSION"

  if [[ "$WF_STATUS" == "completed" ]]; then
    break
  fi
  sleep 30
done

# ── Report ─────────────────────────────────────────────────────────────────────
if [[ "$WF_CONCLUSION" == "success" ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "release-validation-passed" \
    --comment "[step:validate_component_onboarding] konflux-config-validator PASSED for ${VALIDATOR_VERSION}.

Workflow run: ${RUN_URL}" || true
  bash "$SCRIPTS_DIR/update_pipeline_state.sh" \
    --state "$PIPELINE_STATE" --step validate_component_onboarding --status done
  echo "Validation PASSED: $RUN_URL"
  exit 0
else
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "release-validation-failed" \
    --comment "[step:validate_component_onboarding] konflux-config-validator FAILED for ${VALIDATOR_VERSION} (conclusion: ${WF_CONCLUSION}).

Workflow run: ${RUN_URL}" || true
  echo "ERROR: Validation $WF_CONCLUSION: $RUN_URL" >&2
  exit 1
fi
