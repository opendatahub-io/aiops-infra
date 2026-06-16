#!/bin/bash
# ==============================================================================
# Step 1: conforma-report-fetch
# ==============================================================================
# Usage:       ./conforma-fetch.sh <pipelinerun-name> [options]
# Options:     --handover <file>  Input state JSON (File, Pipe via stdin, or default)
#              --output <file>    Destination path for updated state JSON
# Behavior:    Always exits 0 if a state object is successfully generated. 
#              Downstream tools MUST parse 'report_fetch.status', not '$?'.
# ==============================================================================

set -euo pipefail

# 1. Global Configuration
readonly NAMESPACE="${KONFLUX_NAMESPACE:?Set KONFLUX_NAMESPACE to the target Konflux namespace}"
readonly STEP_NAME="step-detailed-report"
if [ -n "${TEKTON_RESULTS_DOMAIN:-}" ]; then
  readonly DOMAIN="$TEKTON_RESULTS_DOMAIN"
elif [ -n "${KRD_CLUSTER_DOMAIN:-}" ]; then
  readonly DOMAIN="tekton-results-tekton-results.apps.${KRD_CLUSTER_DOMAIN}.openshiftapps.com"
else
  echo "❌ Error: Set TEKTON_RESULTS_DOMAIN or KRD_CLUSTER_DOMAIN." >&2; exit 1
fi
readonly API_BASE="https://$DOMAIN/apis/results.tekton.dev/v1alpha2"

# 2. Handover IO Initialization
HANDOVER_FILE=""
OUTPUT_FILE=""
RAW_INPUT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --handover) HANDOVER_FILE="$2"; shift 2 ;;
        --output)   OUTPUT_FILE="$2";   shift 2 ;;
        *)          RAW_INPUT="$1";     shift 1 ;;
    esac
done

if [ -z "$RAW_INPUT" ]; then
    echo "❌ Error: Please provide the pipeline run name as an argument." >&2
    exit 1
fi

readonly PIPELINERUN_NAME="${RAW_INPUT%-verify}"

# Ingest Incoming Handover State Object (File, Stdin Pipe, or Default Fresh Start)
INITIAL_STATE="{}"
if [ -n "$HANDOVER_FILE" ] && [ -f "$HANDOVER_FILE" ]; then
    INITIAL_STATE=$(cat "$HANDOVER_FILE")
elif [ ! -t 0 ]; then
    INITIAL_STATE=$(cat -)
fi

echo "⏳ [1/4] Gathering authentication token..." >&2
# Leverage an environment token fallback if present, otherwise fetch live CLI context
OC_TOKEN="${KONFLUX_TOKEN:-$(oc whoami -t)}"

echo "⏳ [2/4] Resolving PipelineRun UUID..." >&2
RESULT_UUID=$(oc get pipelinerun "$PIPELINERUN_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.uid}' 2>/dev/null || echo "")

if [ -n "$RESULT_UUID" ] && [ "$RESULT_UUID" != "null" ]; then
    echo "    ✅ Success: Identified active live run token." >&2
fi

if [ -z "$RESULT_UUID" ] || [ "$RESULT_UUID" = "null" ]; then
    echo "    ⚠️  Run pruned from live cluster memory. Searching Tekton Results API index..." >&2
    CEL_FILTER="(data_type == 'tekton.dev/v1beta1.PipelineRun' || data_type == 'tekton.dev/v1.PipelineRun') && data.metadata.name == '${PIPELINERUN_NAME}'"
    
    RAW_RES=$(curl -s -k -G \
      -H "Authorization: Bearer $OC_TOKEN" \
      --data-urlencode "filter=${CEL_FILTER}" \
      "$API_BASE/parents/$NAMESPACE/results/-/records")
    
    RECORD_PATH=$(echo "$RAW_RES" | jq -r '.records[0].name' 2>/dev/null || echo "")
    
    if [ -n "$RECORD_PATH" ] && [ "$RECORD_PATH" != "null" ]; then
        RESULT_UUID=$(echo "$RECORD_PATH" | sed -n 's/.*results\/\([0-9a-f-]*\).*/\1/p')
        echo "    ✅ Success: Recovered archived run identifier from API logs." >&2
    fi
fi

if [ -z "$RESULT_UUID" ] || [ "$RESULT_UUID" = "null" ]; then
    echo "❌ Error: Could not locate PipelineRun '$PIPELINERUN_NAME'." >&2
    exit 1
fi

echo "⏳ [3/4] Resolving unique 'verify' task log record..." >&2
LOG_UUID=$(oc get taskrun -n "$NAMESPACE" -l tekton.dev/pipelineRun="$PIPELINERUN_NAME",tekton.dev/pipelineTask=verify -o jsonpath='{.items[0].metadata.uid}' 2>/dev/null || echo "")
LIVE_POD_NAME=$(oc get taskrun -n "$NAMESPACE" -l tekton.dev/pipelineRun="$PIPELINERUN_NAME",tekton.dev/pipelineTask=verify -o jsonpath='{.items[0].status.podName}' 2>/dev/null || echo "")

if [ -z "$LOG_UUID" ] || [ "$LOG_UUID" = "null" ]; then
    echo "    ⚠️  Task layer pruned from cluster. Requesting historical log index metadata..." >&2
    RECORDS_URL="$API_BASE/parents/$NAMESPACE/results/$RESULT_UUID/records?page_size=100"
    RAW_REC=$(curl -s -k -H "Authorization: Bearer $OC_TOKEN" "$RECORDS_URL")
    
    LOG_UUID=$(echo "$RAW_REC" | jq -r '
      .records[]? | 
      select(
        (try (.data_type // .dataType // "") catch "" | contains("Log")) or
        (try (.summary.name // "") catch "" | contains("verify")) or
        (try (.data.value | @base64d | fromjson | .metadata.name | contains("verify")) catch false) or
        (try (.data.value | @base64d | fromjson | .metadata.labels["tekton.dev/pipelineTask"] == "verify") catch false)
      ) | .name' 2>/dev/null | awk -F'/' '{print $NF}' | grep -v "$RESULT_UUID" | head -n 1 || echo "")
fi

if [ -z "$LOG_UUID" ] || [ "$LOG_UUID" = "null" ]; then
    echo "❌ Error: Specific verification log tracking data is missing." >&2
    exit 1
fi

readonly REPORT_STORAGE_PATH="/tmp/conforma-report-${RESULT_UUID}.json"

echo "⏳ [4/4] Executing log payload stream extraction..." >&2
FINAL_URL="$API_BASE/parents/$NAMESPACE/results/$RESULT_UUID/logs/$LOG_UUID"

curl -s -k -H "Authorization: Bearer $OC_TOKEN" "$FINAL_URL" \
  | awk -v step="$STEP_NAME" '$0 ~ "^" step " :-"{flag=1; next} /^step-.* :-/{flag=0} flag' > "$REPORT_STORAGE_PATH"

if [ ! -s "$REPORT_STORAGE_PATH" ] && [ -n "$LIVE_POD_NAME" ] && [ "$LIVE_POD_NAME" != "null" ]; then
    echo "    ⚠️  Archive log unpopulated. Pivoting to live pod container read..." >&2
    oc logs "$LIVE_POD_NAME" -c "$STEP_NAME" -n "$NAMESPACE" 2>/dev/null > "$REPORT_STORAGE_PATH" || true
fi

# 3. Handover Assembly Phase
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Back to basics: Verify that data was successfully written to disk
if [ -s "$REPORT_STORAGE_PATH" ]; then
    UPDATED_HANDOVER=$(echo "$INITIAL_STATE" | jq \
      --arg run "$PIPELINERUN_NAME" \
      --arg ns "$NAMESPACE" \
      --arg time "$TIMESTAMP" \
      --arg path "$REPORT_STORAGE_PATH" '
      .metadata.pipeline_run = $run |
      .metadata.namespace = $ns |
      .metadata.created_at = (.metadata.created_at // $time) |
      .metadata.policy_source = (.metadata.policy_source // "github.com/conforma/config//default") |
      .report_fetch.status = "completed" |
      .report_fetch.completed_at = $time |
      .report_fetch.raw_report_path = $path |
      .report_fetch.error = null |
      .violation_parse = (.violation_parse // null) |
      .investigation = (.investigation // null)
    ')
else
    UPDATED_HANDOVER=$(echo "$INITIAL_STATE" | jq --arg time "$TIMESTAMP" '
      .report_fetch.status = "failed" |
      .report_fetch.completed_at = $time |
      .report_fetch.error = "Log payload returned empty or unpopulated from execution rails."
    ')
fi

if [ -n "$OUTPUT_FILE" ]; then
    echo "$UPDATED_HANDOVER" > "$OUTPUT_FILE"
    echo "🎯 Handover step saved to file: $OUTPUT_FILE" >&2
else
    echo "$UPDATED_HANDOVER"
fi
