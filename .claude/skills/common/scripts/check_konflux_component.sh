#!/usr/bin/env bash
# check_konflux_component.sh — Check if a Konflux Component CRD exists on an OpenShift cluster.
#
# Usage:
#   check_konflux_component.sh <component-name> <namespace> [external|internal]
#
# Arguments:
#   component-name   Name of the Konflux Component CR to look up
#   namespace        Namespace to search in (e.g. opendatahub-builds, rhoai-builds)
#   cluster-instance optional; external (default) or internal
#
# Exit codes:
#   0  Component exists
#   1  Component does not exist
#   2  Error (oc not found, login failed, bad arguments)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info()  { echo "[INFO]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }
die()   { error "$*"; exit 2; }

COMPONENT_NAME="${1:-}"
NAMESPACE="${2:-}"
CLUSTER_INSTANCE="${3:-external}"

[[ -z "$COMPONENT_NAME" ]] && die "component-name is required as the first argument."
[[ -z "$NAMESPACE" ]]      && die "namespace is required as the second argument."

# ── Verify oc is available ──────────────────────────────────────────────────────
if ! command -v oc &>/dev/null; then
  die "oc CLI is not installed. Download from: https://console.redhat.com/openshift/downloads"
fi

# ── Verify authentication — attempt login if needed ────────────────────────────
if ! oc whoami &>/dev/null 2>&1; then
  info "Not logged in. Attempting login to $CLUSTER_INSTANCE cluster..."
  if ! bash "$SCRIPT_DIR/login_to_konflux_cluster.sh" "$CLUSTER_INSTANCE"; then
    die "Could not log in to the $CLUSTER_INSTANCE Konflux cluster. Check VPN and OC_TOKEN."
  fi
fi

# ── Check for the Component CR ─────────────────────────────────────────────────
info "Checking for Konflux Component '$COMPONENT_NAME' in namespace '$NAMESPACE'..."

if oc get component -n "$NAMESPACE" "$COMPONENT_NAME" &>/dev/null 2>&1; then
  info "Component '$COMPONENT_NAME' EXISTS in namespace '$NAMESPACE'."
  exit 0
else
  info "Component '$COMPONENT_NAME' does NOT exist in namespace '$NAMESPACE'."
  exit 1
fi
