#!/usr/bin/env bash
# prereqs.sh — Validate environment variables and required tools
#
# Usage: bash prereqs.sh
# Exit 0 on success, 1 if required prerequisites are missing.

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BOLD}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }

ERRORS=0
WARNINGS=0

# ── Required tools ──────────────────────────────────────────────────────────
info "Checking required tools..."

REQUIRED_TOOLS=("oc" "jq")
for tool in "${REQUIRED_TOOLS[@]}"; do
  if command -v "$tool" &>/dev/null; then
    success "$tool: $(command -v "$tool")"
  else
    error "$tool: NOT FOUND — required"
    ((ERRORS++))
  fi
done

# Container runtime: podman preferred, docker as fallback
if command -v podman &>/dev/null; then
  success "container runtime: podman ($(command -v podman))"
  export BB_CONTAINER_RUNTIME="podman"
elif command -v docker &>/dev/null; then
  success "container runtime: docker ($(command -v docker))"
  export BB_CONTAINER_RUNTIME="docker"
else
  error "container runtime: neither podman nor docker found — required"
  ((ERRORS++))
fi

# Optional tools
OPTIONAL_TOOLS=("gh" "curl")
for tool in "${OPTIONAL_TOOLS[@]}"; do
  if command -v "$tool" &>/dev/null; then
    success "$tool: $(command -v "$tool")"
  else
    warn "$tool: not found — some features may be unavailable"
    ((WARNINGS++))
  fi
done

# ── Required environment variables ──────────────────────────────────────────
info "Checking required environment variables..."

if [[ -n "${OC_TOKEN:-}" ]]; then
  success "OC_TOKEN=<set>"
else
  error "OC_TOKEN is not set — required for Konflux API access"
  ((ERRORS++))
fi

# ── Optional environment variables ──────────────────────────────────────────
info "Checking optional environment variables..."

OPTIONAL_VARS=(
  "KUBEARCHIVE_URL"
  "VERTEX_PROJECT_ID"
  "VERTEX_LOCATION"
  "GOOGLE_APPLICATION_CREDENTIALS"
  "MCP_TOKEN"
  "MCP_SERVER_URL"
  "GITHUB_TOKEN"
)

for var in "${OPTIONAL_VARS[@]}"; do
  if [[ -n "${!var:-}" ]]; then
    if [[ "$var" == *TOKEN* || "$var" == *CREDENTIALS* ]]; then
      success "${var}=<set>"
    else
      success "${var}=${!var}"
    fi
  else
    warn "${var} not set (optional)"
    ((WARNINGS++))
  fi
done

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
if [[ $ERRORS -gt 0 ]]; then
  error "Prerequisite check FAILED: $ERRORS error(s), $WARNINGS warning(s)"
  exit 1
else
  success "Prerequisite check PASSED: 0 errors, $WARNINGS warning(s)"
  exit 0
fi
