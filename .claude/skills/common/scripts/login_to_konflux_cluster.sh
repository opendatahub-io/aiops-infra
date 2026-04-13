#!/usr/bin/env bash
# login_to_konflux_cluster.sh — Log in to a Konflux OpenShift cluster using oc cli.
#
# Usage:
#   login_to_konflux_cluster.sh [external|internal]
#
#   external (default) — stone-prd-rh01  (ODH builds)
#   internal           — stone-prod-p02  (RHOAI builds)
#
# Environment:
#   OC_TOKEN  — optional; cluster login token. Required only when no matching
#               kubeconfig context is found.
#
# Exit codes:
#   0  Success (already authenticated or login succeeded)
#   1  Error

set -euo pipefail

info()  { echo "[INFO]  $*" >&2; }
warn()  { echo "[WARN]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }
die()   { error "$*"; exit 1; }

CLUSTER_INSTANCE="${1:-external}"

EXTERNAL_API="https://api.stone-prd-rh01.pg1f.p1.openshiftapps.com:6443"
INTERNAL_API="https://api.stone-prod-p02.hjvn.p1.openshiftapps.com:6443"

case "$CLUSTER_INSTANCE" in
  external) API_SERVER="$EXTERNAL_API" ;;
  internal) API_SERVER="$INTERNAL_API" ;;
  *) die "Invalid cluster instance '$CLUSTER_INSTANCE'. Must be 'external' or 'internal'." ;;
esac

# ── Check oc is available ───────────────────────────────────────────────────────
if ! command -v oc &>/dev/null; then
  die "oc CLI is not installed. Download from: https://console.redhat.com/openshift/downloads"
fi

# ── Try to find a matching context in the existing kubeconfig ───────────────────
if oc config get-contexts &>/dev/null 2>&1; then
  MATCHING_CONTEXT=""
  while IFS= read -r ctx; do
    # Retrieve the cluster server URL for this context
    cluster_server=$(oc config view --minify --context "$ctx" \
      -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)
    # Strip trailing slash for comparison
    cluster_server="${cluster_server%/}"
    if [[ "$cluster_server" == "${API_SERVER%/}" ]]; then
      MATCHING_CONTEXT="$ctx"
      break
    fi
  done < <(oc config get-contexts -o name 2>/dev/null || true)

  if [[ -n "$MATCHING_CONTEXT" ]]; then
    info "Found matching kubeconfig context: $MATCHING_CONTEXT"
    oc config use-context "$MATCHING_CONTEXT" >/dev/null 2>&1 || true
    if oc whoami &>/dev/null 2>&1; then
      info "Already authenticated as: $(oc whoami)"
      exit 0
    fi
    warn "Context found but token appears expired. Falling back to OC_TOKEN login."
  else
    info "No matching kubeconfig context found for $CLUSTER_INSTANCE cluster ($API_SERVER)."
  fi
fi

# ── Login with OC_TOKEN ─────────────────────────────────────────────────────────
OC_TOKEN="${OC_TOKEN:-}"
if [[ -z "$OC_TOKEN" ]]; then
  die "No valid kubeconfig context found and OC_TOKEN is not set.
  Get a login token from the OpenShift web console at:
    $API_SERVER
  Then: export OC_TOKEN=<your-token>"
fi

info "Logging in to $CLUSTER_INSTANCE cluster ($API_SERVER)..."
if ! oc login --server="$API_SERVER" --token="$OC_TOKEN" 2>&1; then
  die "oc login failed. Check OC_TOKEN validity and VPN connectivity."
fi

info "Logged in as: $(oc whoami)"
