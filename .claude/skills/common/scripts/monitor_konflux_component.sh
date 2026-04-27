#!/usr/bin/env bash
# monitor_konflux_component.sh — polls check_konflux_component.sh until a Konflux Component
# appears in the cluster or times out. Optionally updates Jira on success or timeout.
# Exit 0: component confirmed live; Exit 1: timed out.
set -euo pipefail

COMPONENT_NAME=""
NAMESPACE=""
CLUSTER_INSTANCE=""
JIRA_URL=""
MR_URL=""
COMMON_SCRIPTS_DIR=""
POLL_INTERVAL=60
MAX_WAIT=1800

usage() {
  echo "Usage: $0 --component-name NAME --namespace NS --cluster-instance INST --scripts-dir PATH [--jira-url URL] [--mr-url URL] [--poll-interval SECS] [--max-wait SECS]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component-name)   COMPONENT_NAME="$2";      shift 2 ;;
    --namespace)        NAMESPACE="$2";            shift 2 ;;
    --cluster-instance) CLUSTER_INSTANCE="$2";     shift 2 ;;
    --jira-url)         JIRA_URL="$2";             shift 2 ;;
    --mr-url)           MR_URL="$2";               shift 2 ;;
    --scripts-dir)      COMMON_SCRIPTS_DIR="$2";   shift 2 ;;
    --poll-interval)    POLL_INTERVAL="$2";        shift 2 ;;
    --max-wait)         MAX_WAIT="$2";             shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$COMPONENT_NAME" || -z "$NAMESPACE" || -z "$CLUSTER_INSTANCE" || -z "$COMMON_SCRIPTS_DIR" ]] && usage

# Map cluster instance to human-readable cluster label
CLUSTER_LABEL="$CLUSTER_INSTANCE"
[[ "$CLUSTER_INSTANCE" == "external" ]] && CLUSTER_LABEL="stone-prd-rh01"
[[ "$CLUSTER_INSTANCE" == "internal" ]] && CLUSTER_LABEL="stone-prod-p02"

echo "Monitoring Konflux Component '${COMPONENT_NAME}' in namespace '${NAMESPACE}' (timeout: $((MAX_WAIT / 60)) minutes)..."

ELAPSED=0
CHECK_EXIT=1

while true; do
  bash "$COMMON_SCRIPTS_DIR/check_konflux_component.sh" \
    "$COMPONENT_NAME" "$NAMESPACE" "$CLUSTER_INSTANCE"
  CHECK_EXIT=$?

  if [[ $CHECK_EXIT -eq 0 ]]; then
    break
  elif [[ $CHECK_EXIT -eq 2 ]]; then
    echo "WARNING: check_konflux_component.sh returned a tool error. Retrying..."
  fi
  # Exit 1 = not yet created; keep polling

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    CHECK_EXIT=3
    break
  fi

  REMAINING=$(( (MAX_WAIT - ELAPSED) / 60 ))
  echo "  Component not yet visible (elapsed=${ELAPSED}s, remaining≈${REMAINING}m). Retrying in ${POLL_INTERVAL}s..."
  sleep "$POLL_INTERVAL"
  ELAPSED=$(( ELAPSED + POLL_INTERVAL ))
done

if [[ $CHECK_EXIT -eq 0 ]]; then
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "konflux-component-created" \
      --comment "Konflux Component successfully provisioned.

Component name: ${COMPONENT_NAME}
Namespace: ${NAMESPACE}
Cluster: ${CLUSTER_INSTANCE} (${CLUSTER_LABEL})

Verified via: oc get component -n ${NAMESPACE} ${COMPONENT_NAME}

Step 3 (Add to konflux-release-data) is complete."
  fi
  echo "✓ Konflux Component '${COMPONENT_NAME}' is live in namespace '${NAMESPACE}'."
  echo "  Step 3 (Add to konflux-release-data) complete."
  exit 0
else
  MR_INFO=""
  [[ -n "$MR_URL" ]] && MR_INFO="
The MR was merged (${MR_URL}) so the GitOps pipeline may still be running."

  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "Konflux Component monitoring timed out after $((MAX_WAIT / 60)) minutes.
'${COMPONENT_NAME}' has not yet appeared in namespace '${NAMESPACE}'.${MR_INFO}

Re-run /onboard-component-to-konflux-release-data to re-check — it will short-circuit
at Step 5 once the Component exists."
  fi
  echo "WARNING: Component '${COMPONENT_NAME}' not visible after $((MAX_WAIT / 60)) minutes."
  [[ -n "$MR_URL" ]] && echo "The MR was merged so the Konflux GitOps pipeline may still be running."
  echo "Re-run this skill later — it will short-circuit at Step 5 once the Component appears."
  exit 1
fi
