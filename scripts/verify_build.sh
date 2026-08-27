#!/usr/bin/env bash
# verify_build.sh — Check that a Konflux push build has succeeded for a component.
#
# Called by run_step_integrate_bundle.sh before raising the bundle PR.
# Queries KubeArchive for the most recent push/incoming build and verifies it succeeded.
#
# Exit codes:
#   0  Build verified (succeeded)
#   1  Build not found, still running, or failed — caller should exit 1
#
# Set ONBOARD_DRY_RUN=true to bypass (fork testing without cluster access).
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

JIRA_URL=""
COMPONENT_NAME=""
PRODUCT_CONTEXT=""
VERSION_VAR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url)        JIRA_URL="$2";        shift 2 ;;
    --component-name)  COMPONENT_NAME="$2";  shift 2 ;;
    --product-context) PRODUCT_CONTEXT="$2"; shift 2 ;;
    --version-var)     VERSION_VAR="$2";     shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$COMPONENT_NAME" ]]  && { echo "ERROR: --component-name is required" >&2; exit 1; }
[[ -z "$PRODUCT_CONTEXT" ]] && { echo "ERROR: --product-context is required" >&2; exit 1; }

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Dry-run bypass ─────────────────────────────────────────────────────────────
if [[ "${ONBOARD_DRY_RUN:-false}" == "true" ]]; then
  echo "ONBOARD_DRY_RUN=true — skipping build verification."
  exit 0
fi

# ── Cluster / component config by product ─────────────────────────────────────
if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  CLUSTER_INSTANCE="external"
  NAMESPACE="open-data-hub-tenant"
  KONFLUX_COMPONENT="${COMPONENT_NAME}-ci"
  KONFLUX_UI="https://konflux-ui.apps.stone-prd-rh01.pg1f.p1.openshiftapps.com"
elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
  [[ -z "$VERSION_VAR" ]] && { echo "ERROR: --version-var is required for RHOAI." >&2; exit 1; }
  CLUSTER_INSTANCE="internal"
  NAMESPACE="rhoai-tenant"
  KONFLUX_COMPONENT="${COMPONENT_NAME}-${VERSION_VAR}"
  KONFLUX_UI="https://konflux-ui.apps.stone-prod-p02.hjvn.p1.openshiftapps.com"
else
  echo "ERROR: Unknown PRODUCT_CONTEXT '${PRODUCT_CONTEXT}'" >&2; exit 1
fi

echo "Verifying Konflux build for '${KONFLUX_COMPONENT}' in '${NAMESPACE}'..."

# ── Cluster login ─────────────────────────────────────────────────────────────
# Always call login_to_konflux_cluster.sh for the target cluster instance.
# A bare "oc whoami" check is insufficient — the session may be authenticated
# against a *different* cluster, producing wrong KubeArchive URLs and silent
# curl failures.
if [[ "$CLUSTER_INSTANCE" == "external" ]]; then
  EXPECTED_API="https://api.stone-prd-rh01.pg1f.p1.openshiftapps.com:6443"
else
  EXPECTED_API="https://api.stone-prod-p02.hjvn.p1.openshiftapps.com:6443"
fi

CURRENT_SERVER=$(oc whoami --show-server 2>/dev/null || echo "")
if [[ "${CURRENT_SERVER%/}" != "${EXPECTED_API%/}" ]]; then
  echo "Current oc context (${CURRENT_SERVER:-none}) does not match target ($EXPECTED_API). Logging in..." >&2
  bash "$SCRIPTS_DIR/login_to_konflux_cluster.sh" "$CLUSTER_INSTANCE" || {
    echo "ERROR: Could not log in to $CLUSTER_INSTANCE cluster. Check EXT_OC_TOKEN/INT_OC_TOKEN." >&2
    exit 1
  }
fi

OC_TOKEN=$(oc whoami --show-token 2>/dev/null || echo "")
OC_SERVER=$(oc whoami --show-server 2>/dev/null || echo "")
[[ -z "$OC_TOKEN" ]] && { echo "ERROR: No oc token — cannot verify build." >&2; exit 1; }

# ── KubeArchive query ──────────────────────────────────────────────────────────
CLUSTER_SUFFIX=$(echo "$OC_SERVER" | sed 's|https://api||;s|:[0-9]*$||')
KUBEARCHIVE_BASE="https://kubearchive-api-server-product-kubearchive.apps${CLUSTER_SUFFIX}"

LABEL="appstudio.openshift.io/component=${KONFLUX_COMPONENT},pipelinesascode.tekton.dev/event-type in (push,incoming,retest-comment)"
LABEL_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$LABEL")

echo "KubeArchive : ${KUBEARCHIVE_BASE}" >&2
RESULTS=$(curl -sk -w '%{http_code}' -o /dev/stdout \
  -H "Authorization: Bearer $OC_TOKEN" \
  -H "Accept: application/json" \
  "${KUBEARCHIVE_BASE}/apis/tekton.dev/v1/namespaces/${NAMESPACE}/pipelineruns?labelSelector=${LABEL_ENC}&limit=10" \
  2>/dev/null) || {
  echo "ERROR: curl to KubeArchive failed (network error or unreachable)." >&2
  echo "  URL: ${KUBEARCHIVE_BASE}/apis/tekton.dev/v1/namespaces/${NAMESPACE}/pipelineruns" >&2
  exit 1
}

HTTP_CODE="${RESULTS: -3}"
RESULTS="${RESULTS:0:${#RESULTS}-3}"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "ERROR: KubeArchive returned HTTP $HTTP_CODE." >&2
  echo "  URL: ${KUBEARCHIVE_BASE}/apis/tekton.dev/v1/namespaces/${NAMESPACE}/pipelineruns" >&2
  echo "  Response: ${RESULTS:0:500}" >&2
  exit 1
fi

COUNT=$(echo "$RESULTS" | jq '.items | length' 2>/dev/null || echo "0")

if [[ "$COUNT" -eq 0 ]]; then
  echo "ERROR: No push build found for '${KONFLUX_COMPONENT}' — build has not run yet." >&2
  echo "  Retry after the component's first push build completes on Konflux." >&2
  exit 1
fi

# Sort by creationTimestamp and take the most recent
LATEST=$(echo "$RESULTS" | jq '
  .items | sort_by(.metadata.creationTimestamp) | last
')
PR_NAME=$(echo "$LATEST" | jq -r '.metadata.name')
APP_LABEL=$(echo "$LATEST" | jq -r '.metadata.labels["appstudio.openshift.io/application"] // ""')
SUCCEEDED=$(echo "$LATEST" | jq -r '.status.conditions[]? | select(.type=="Succeeded") | .status')
REASON=$(echo "$LATEST" | jq -r '.status.conditions[]? | select(.type=="Succeeded") | .reason // ""')
BUILD_URL="${KONFLUX_UI}/ns/${NAMESPACE}/applications/${APP_LABEL:-unknown}/pipelineruns/${PR_NAME}"

echo "PipelineRun : $PR_NAME"
echo "Status      : Succeeded=${SUCCEEDED:-Unknown}  Reason=${REASON}"
echo "Build URL   : $BUILD_URL"

if [[ "$SUCCEEDED" == "True" ]]; then
  echo "Build verified: ${PR_NAME}"
  echo "Build URL   : ${BUILD_URL}"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "[step:bundle] Konflux push build verified for '${COMPONENT_NAME}'.

PipelineRun: ${PR_NAME}
Build URL: ${BUILD_URL}

Proceeding with bundle integration." || true
  fi
  exit 0
elif [[ "$SUCCEEDED" == "False" ]]; then
  echo "ERROR: Most recent push build FAILED (${REASON})." >&2
  echo "  Build URL: ${BUILD_URL}" >&2
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "[step:bundle] Blocked — Konflux push build FAILED.

PipelineRun: ${PR_NAME}
Build URL: ${BUILD_URL}

Fix the build failure and re-run." || true
  fi
  exit 1
else
  echo "ERROR: Most recent push build is still running (${REASON:-Running})." >&2
  echo "  Build URL: ${BUILD_URL}" >&2
  echo "  Retry after the build completes." >&2
  exit 1
fi
