#!/usr/bin/env bash
# install.sh — Install the build-buddy Claude Code skill
#
# Validates prerequisites and copies skill files into place.
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in CWD
#   ./install.sh --dir /path  # installs to an explicit directory

set -euo pipefail

SKILL_NAME="build-buddy"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BOLD}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

TARGET_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) TARGET_DIR="$(pwd)/.claude/skills/${SKILL_NAME}"; shift ;;
    --dir)     TARGET_DIR="${2:?--dir requires a path}/${SKILL_NAME}"; shift 2 ;;
    -h|--help) echo "Usage: $0 [--project | --dir /path]"; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done
[[ -z "$TARGET_DIR" ]] && TARGET_DIR="${HOME}/.claude/skills/${SKILL_NAME}"

echo ""
echo -e "${BOLD}Installing ${SKILL_NAME}${RESET}"
echo "  Source : ${SCRIPT_DIR}"
echo "  Target : ${TARGET_DIR}"
echo ""

ERRORS=0

# ── Step 1: Check required tools ────────────────────────────────────────────
info "Checking required tools..."

for tool in oc jq; do
  if command -v "$tool" &>/dev/null; then
    success "$tool: $(command -v "$tool")"
  else
    error "$tool: NOT FOUND — required"
    ((ERRORS++))
  fi
done

# Container runtime
if command -v podman &>/dev/null; then
  success "container runtime: podman"
elif command -v docker &>/dev/null; then
  success "container runtime: docker"
else
  error "container runtime: neither podman nor docker found — required"
  ((ERRORS++))
fi

# Optional tools
for tool in gh curl; do
  if command -v "$tool" &>/dev/null; then
    success "$tool: $(command -v "$tool")"
  else
    warn "$tool: not found — some features may be limited"
  fi
done

# ── Step 2: Pull Pipeline-Pilot image ──────────────────────────────────────
info "Pulling Pipeline-Pilot image..."
PP_IMAGE="${BB_PP_IMAGE:-quay.io/rhoai-devops/pipeline-pilot:latest}"

if command -v podman &>/dev/null; then
  RUNTIME="podman"
elif command -v docker &>/dev/null; then
  RUNTIME="docker"
fi

if [[ -n "${RUNTIME:-}" ]]; then
  if $RUNTIME pull "$PP_IMAGE" 2>&1; then
    success "Pipeline-Pilot image pulled: $PP_IMAGE"
  else
    warn "Failed to pull PP image. It will be pulled on first use."
  fi
else
  warn "No container runtime — skipping image pull."
fi

# ── Step 3: Check environment variables ─────────────────────────────────────
info "Checking environment variables..."

if [[ -n "${OC_TOKEN:-}" ]]; then
  success "OC_TOKEN=<set>"
else
  error "OC_TOKEN is not set — required for Konflux API access"
  ((ERRORS++))
fi

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
  fi
done

# ── Step 4: Copy skill files ───────────────────────────────────────────────
info "Copying skill files..."
mkdir -p "$TARGET_DIR/scripts/build-buddy"
cp "${SCRIPT_DIR}/SKILL.md" "${TARGET_DIR}/SKILL.md"
success "SKILL.md -> ${TARGET_DIR}/SKILL.md"

for script in config.sh prereqs.sh pp-container.sh retrigger.sh output.sh main.sh; do
  cp "${SCRIPT_DIR}/scripts/build-buddy/${script}" "${TARGET_DIR}/scripts/build-buddy/${script}"
  chmod +x "${TARGET_DIR}/scripts/build-buddy/${script}"
  success "scripts/build-buddy/${script} -> ${TARGET_DIR}/scripts/build-buddy/${script}"
done

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
if [[ $ERRORS -gt 0 ]]; then
  error "Installation completed with $ERRORS error(s). Fix issues above before running."
  exit 1
fi

echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code, then run:"
echo ""
echo "    /build-buddy --input <jira-or-pipelinerun-url>"
echo ""
echo "  Before running:"
echo "    1. OC_TOKEN exported (required)"
echo "    2. GITHUB_TOKEN exported (recommended, for retrigger)"
echo "    3. Container runtime (podman/docker) available"
echo ""
