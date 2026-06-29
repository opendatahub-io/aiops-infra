#!/bin/bash
# ==============================================================================
# Step 1: conforma-report-fetch (Time-Sorted High-Speed Edition)
# ==============================================================================
# Usage:       ./fetch-conforma.sh <pipelinerun-name OR rhoai-version> [options]
# Options:     --handover <file>  Input state JSON (File, Pipe via stdin, or default)
#              --output <file>    Destination path for updated state JSON
# Behavior:    Always exits 0 if a state object is successfully generated. 
#              Downstream tools MUST parse 'report_fetch.status', not '$?'.
# ==============================================================================

set -euo pipefail

# 1. Global Configuration (Locked to p02 Source of Truth)
readonly NAMESPACE="rhoai-tenant"
readonly STEP_NAME="step-detailed-report"
readonly DOMAIN="tekton-results-tekton-results.apps.stone-prod-p02.hjvn.p1.openshiftapps.com"
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
    echo "❌ Error: Please provide the pipeline run name or version as an argument." >&2
    exit 1
fi

# Ingest Incoming Handover State Object (File, Stdin Pipe, or Default Fresh Start)
INITIAL_STATE="{}"
if [ -n "$HANDOVER_FILE" ] && [ -f "$HANDOVER_FILE" ]; then
    INITIAL_STATE=$(cat "$HANDOVER_FILE")
elif [ ! -t 0 ]; then
    INITIAL_STATE=$(cat -)
fi

echo "⏳ [1/4] Gathering authentication token..." >&2
OC_TOKEN="${KONFLUX_TOKEN:-$(oc whoami -t)}"

# ==============================================================================
# Dynamic Input Routing: Parse Exact Name vs Version Shortcode
# ==============================================================================
RAW_NAME="${RAW_INPUT%-verify}"
PIPELINERUN_NAME=""

# Check if the input looks like a version shortcode (starts with a digit or 'rhoai-')
if [[ "$RAW_NAME" =~ ^[0-9] ]] || [[ "$RAW_NAME" =~ ^rhoai-[0-9] ]]; then
    CLEAN_VERSION=$(echo "$RAW_NAME" | sed 's/rhoai-//' | tr '.' '-' | sed 's/\([0-9]\)\(ea\)/\1-\2/')
    SEARCH_PATTERN="v${CLEAN_VERSION}"
    
    echo "⏳ [Input Router] Target version shortcut detected. Searching for newest run..." >&2

    EXACT_APP_PREFIX="conforma-registry-rhoai-prod-${SEARCH_PATTERN}-single-component"

    # Strategy 1: Live cluster query (fast, reliable for non-pruned runs)
    PIPELINERUN_NAME=$(oc get pipelinerun -n "$NAMESPACE" --sort-by=.metadata.creationTimestamp -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null \
      | grep "^${EXACT_APP_PREFIX}" | tail -n 1 || echo "")

    if [ -n "$PIPELINERUN_NAME" ]; then
        echo "    🎯 Success: Found newest live cluster run -> $PIPELINERUN_NAME" >&2
    else
        # Strategy 2: Fall back to Tekton Results API for archived/pruned runs
        echo "    ⚠️  No live runs found. Searching Tekton Results API archive..." >&2
        RAW_LATEST=$(curl -s -k -G \
          -H "Authorization: Bearer $OC_TOKEN" \
          --data-urlencode "order_by=create_time desc" \
          --data-urlencode "page_size=100" \
          "$API_BASE/parents/$NAMESPACE/results/-/records")

        PIPELINERUN_NAME=$(echo "$RAW_LATEST" | jq -r --arg pattern "$EXACT_APP_PREFIX" '
          .records[]? |
          select(.data.value) |
          try (.data.value | @base64d | fromjson) catch null |
          select(.metadata.name? | strings | contains($pattern)) |
          .metadata.name
        ' | head -n 1 || echo "")
    fi

    if [ -z "$PIPELINERUN_NAME" ] || [ "$PIPELINERUN_NAME" = "null" ]; then
        echo "❌ Error: Could not discover any Conforma registry runs for version '${RAW_NAME}'." >&2
        exit 1
    fi
    echo "    🎯 Resolved target -> $PIPELINERUN_NAME" >&2
else
    # Input is already an exact run name string
    PIPELINERUN_NAME="$RAW_NAME"
fi

# ==============================================================================
# Step 2: Resolving PipelineRun UUID
# ==============================================================================
echo "⏳ [2/4] Resolving PipelineRun UUID..." >&2
RESULT_UUID=$(oc get pipelinerun "$PIPELINERUN_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.uid}' 2>/dev/null || echo "")

if [ -n "$RESULT_UUID" ] && [ "$RESULT_UUID" != "null" ]; then
    echo "    ✅ Success: Identified active live run token." >&2
fi

if [ -z "$RESULT_UUID" ] || [ "$RESULT_UUID" = "null" ]; then
    echo "    ⚠️  Run pruned from live cluster memory. Searching Tekton Results API index..." >&2
    
    # Strategy: Direct un-guarded exact equality check. Highly indexed and fast.
    CEL_FILTER="data.metadata.name == '${PIPELINERUN_NAME}'"

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

# ==============================================================================
# Step 3: Resolving unique 'verify' task log record
# ==============================================================================
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

# ==============================================================================
# Step 4: Executing log payload stream extraction
# ==============================================================================
echo "⏳ [4/4] Executing log payload stream extraction..." >&2
FINAL_URL="$API_BASE/parents/$NAMESPACE/results/$RESULT_UUID/logs/$LOG_UUID"

curl -s -k -H "Authorization: Bearer $OC_TOKEN" "$FINAL_URL" \
  | awk -v step="$STEP_NAME" '$0 ~ "^" step " :-"{flag=1; next} /^step-.* :-/{flag=0} flag' > "$REPORT_STORAGE_PATH"

if [ ! -s "$REPORT_STORAGE_PATH" ] && [ -n "$LIVE_POD_NAME" ] && [ "$LIVE_POD_NAME" != "null" ]; then
    echo "    ⚠️  Archive log unpopulated. Pivoting to live pod container read..." >&2
    oc logs "$LIVE_POD_NAME" -c "$STEP_NAME" -n "$NAMESPACE" 2>/dev/null > "$REPORT_STORAGE_PATH" || true
fi

# ==============================================================================
# Handover Assembly Phase
# ==============================================================================
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

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