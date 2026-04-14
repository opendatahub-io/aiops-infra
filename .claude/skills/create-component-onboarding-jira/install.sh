#!/usr/bin/env bash
# install.sh — Install the create-component-onboarding-jira Claude Code skill
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in the current working directory
#   ./install.sh --dir /path  # installs to an explicit target directory

set -euo pipefail

SKILL_NAME="create-component-onboarding-jira"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${BOLD}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
die()     { error "$*"; exit 1; }

# ── Parse arguments ────────────────────────────────────────────────────────────
TARGET_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)  TARGET_DIR="$(pwd)/.claude/skills/${SKILL_NAME}"; shift ;;
    --dir)      TARGET_DIR="${2:?--dir requires a path argument}/${SKILL_NAME}"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--project | --dir /path]"
      echo ""
      echo "  (no flag)      Install to ~/.claude/skills/${SKILL_NAME}  (global default)"
      echo "  --project      Install to .claude/skills/${SKILL_NAME} in the current directory"
      echo "  --dir /path    Install to /path/${SKILL_NAME}"
      exit 0 ;;
    *) die "Unknown argument: $1. Run '$0 --help' for usage." ;;
  esac
done

# Default: global install
[[ -z "$TARGET_DIR" ]] && TARGET_DIR="${HOME}/.claude/skills/${SKILL_NAME}"

VALIDATE_SKILL_DIR="${TARGET_DIR}/../validate-component-onboarding-jira"
COMMON_DIR="${TARGET_DIR}/../common/scripts"

echo ""
echo -e "${BOLD}Installing ${SKILL_NAME}${RESET}"
echo "  Source : ${SCRIPT_DIR}"
echo "  Target : ${TARGET_DIR}"
echo ""

# ── Step 1: Check prerequisites ────────────────────────────────────────────────
info "Checking prerequisites..."

if ! command -v uv &>/dev/null; then
  warn "'uv' is not installed. Attempting to install it now..."
  if command -v curl &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget &>/dev/null; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "Cannot install 'uv': neither 'curl' nor 'wget' is available.
    Install manually: https://docs.astral.sh/uv/getting-started/installation/"
  fi
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v uv &>/dev/null; then
    die "uv was installed but is not on PATH. Open a new terminal and re-run, or:
    export PATH=\"\${HOME}/.local/bin:\${PATH}\""
  fi
  success "uv installed: $(uv --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  success "uv $(uv --version 2>/dev/null | head -1 | awk '{print $2}') (already installed)"
fi

# ── Step 2: Verify adjacent skill dependencies ─────────────────────────────────
info "Checking adjacent skill dependencies..."

if [[ ! -f "${VALIDATE_SKILL_DIR}/SKILL.md" ]]; then
  die "validate-component-onboarding-jira skill not found at: ${VALIDATE_SKILL_DIR}
  Install it first:
    cd $(dirname "${SCRIPT_DIR}")/validate-component-onboarding-jira && ./install.sh --project"
fi
success "validate-component-onboarding-jira: found"

if [[ ! -f "${COMMON_DIR}/fetch_jira_details.py" ]]; then
  die "Missing: ${COMMON_DIR}/fetch_jira_details.py"
fi
success "common/scripts/fetch_jira_details.py: found"

if [[ ! -f "${COMMON_DIR}/validate_yaml_schema.py" ]]; then
  die "Missing: ${COMMON_DIR}/validate_yaml_schema.py"
fi
success "common/scripts/validate_yaml_schema.py: found"

if [[ ! -f "${VALIDATE_SKILL_DIR}/assets/component_onboarding_details.schema.json" ]]; then
  die "Missing: ${VALIDATE_SKILL_DIR}/assets/component_onboarding_details.schema.json"
fi
success "validate-component-onboarding-jira/assets/component_onboarding_details.schema.json: found"

if [[ ! -f "${COMMON_DIR}/update_jira_issue.py" ]]; then
  die "Common script not found: ${COMMON_DIR}/update_jira_issue.py
  Ensure the full skills directory is present, not just this skill subdirectory."
fi
success "common/scripts/update_jira_issue.py: found"

# ── Step 3: Copy skill files ───────────────────────────────────────────────────
info "Creating skill directory..."
mkdir -p "${TARGET_DIR}"
success "Directory ready: ${TARGET_DIR}"

info "Copying skill files..."
cp "${SCRIPT_DIR}/SKILL.md" "${TARGET_DIR}/SKILL.md"
success "Files copied:"
echo "    SKILL.md"

# ── Step 4: Pre-warm Python dependencies ──────────────────────────────────────
# This skill delegates all Jira operations to common/scripts/update_jira_issue.py.
# Pre-warm it here so the first invocation is instant.
info "Pre-warming Python dependencies..."
echo -n "    update_jira_issue.py (jira>=3.0.0) ... "
if uv run --script "${COMMON_DIR}/update_jira_issue.py" --help >/dev/null 2>&1; then
  echo -e "${GREEN}OK${RESET}"
else
  echo -e "${RED}FAILED${RESET}"
  warn "Could not pre-install deps for update_jira_issue.py. They will be fetched on first use."
fi

# ── Step 5: Verify installed files ────────────────────────────────────────────
info "Verifying installation..."
ALL_OK=true
if [[ -f "${TARGET_DIR}/SKILL.md" ]]; then
  success "SKILL.md"
else
  error "Missing: SKILL.md"
  ALL_OK=false
fi
$ALL_OK || die "Installation incomplete — some files are missing."

# ── Step 6: Check environment variables ───────────────────────────────────────
echo ""
info "Checking Jira credentials..."
CREDS_OK=true

if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  warn "JIRA_USER_EMAIL is not set."
  CREDS_OK=false
else
  success "JIRA_USER_EMAIL=${JIRA_USER_EMAIL}"
fi

if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  warn "JIRA_API_TOKEN is not set."
  CREDS_OK=false
else
  success "JIRA_API_TOKEN=<set>"
fi

if [[ -z "${JIRA_SERVER:-}" ]]; then
  warn "JIRA_SERVER not set — will default to https://redhat.atlassian.net"
else
  success "JIRA_SERVER=${JIRA_SERVER}"
fi

if ! $CREDS_OK; then
  echo ""
  echo -e "${YELLOW}Add the following to your shell profile (e.g. ~/.zshrc or ~/.bashrc):${RESET}"
  echo ""
  echo "    export JIRA_USER_EMAIL='you@example.com'"
  echo "    export JIRA_API_TOKEN='your-api-token'"
  echo "    # export JIRA_SERVER='https://redhat.atlassian.net'  # optional"
  echo ""
  echo "  Create an Atlassian API token at:"
  echo "    https://id.atlassian.com/manage-profile/security/api-tokens"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code (or open a new session), then run:"
echo ""
echo "    /create-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234"
echo "    /create-component-onboarding-jira   # no Jira URL — generates YAML locally only"
echo ""
echo "  NOTE: This skill requires:"
echo "    - validate-component-onboarding-jira skill (already verified above)"
echo "    - JIRA_USER_EMAIL and JIRA_API_TOKEN when a Jira URL is provided"
echo ""
