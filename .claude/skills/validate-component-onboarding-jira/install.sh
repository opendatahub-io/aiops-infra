#!/usr/bin/env bash
# install.sh — Install the validate-component-onboarding-jira Claude Code skill
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in the current working directory
#   ./install.sh --dir /path  # installs to an explicit target directory

set -euo pipefail

SKILL_NAME="validate-component-onboarding-jira"
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
if [[ -z "$TARGET_DIR" ]]; then
  TARGET_DIR="${HOME}/.claude/skills/${SKILL_NAME}"
fi

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
    die "Cannot install 'uv': neither 'curl' nor 'wget' is available. Install uv manually:
    https://docs.astral.sh/uv/getting-started/installation/"
  fi
  # The installer adds uv to PATH via shell profile; source the env file if present
  UV_ENV="${HOME}/.local/bin"
  if [[ -f "${HOME}/.cargo/env" ]]; then
    # shellcheck disable=SC1091
    source "${HOME}/.cargo/env" 2>/dev/null || true
  fi
  export PATH="${UV_ENV}:${PATH}"
  if ! command -v uv &>/dev/null; then
    die "uv was installed but is not on PATH. Open a new terminal and re-run this script, or run:
    export PATH=\"\${HOME}/.local/bin:\${PATH}\""
  fi
  success "uv installed: $(uv --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  success "uv $(uv --version 2>/dev/null | head -1 | awk '{print $2}') (already installed)"
fi

# ── Step 2: Copy skill files ───────────────────────────────────────────────────
COMMON_SCRIPTS_SRC="${SCRIPT_DIR}/../common/scripts"

info "Creating skill directory..."
mkdir -p "${TARGET_DIR}/scripts" "${TARGET_DIR}/assets" "${TARGET_DIR}/../common/scripts"
success "Directory ready: ${TARGET_DIR}"

info "Copying skill files..."
cp "${SCRIPT_DIR}/SKILL.md"                                  "${TARGET_DIR}/SKILL.md"
cp "${SCRIPT_DIR}/scripts/fetch_jira_details.py"             "${TARGET_DIR}/scripts/fetch_jira_details.py"
cp "${SCRIPT_DIR}/scripts/download_jira_attachment.py"       "${TARGET_DIR}/scripts/download_jira_attachment.py"
cp "${SCRIPT_DIR}/scripts/validate_yaml_schema.py"           "${TARGET_DIR}/scripts/validate_yaml_schema.py"
cp "${SCRIPT_DIR}/assets/odh_component_details.schema.json"  "${TARGET_DIR}/assets/odh_component_details.schema.json"

info "Copying common scripts..."
if [[ -f "${COMMON_SCRIPTS_SRC}/update_jira_issue.py" ]]; then
  cp "${COMMON_SCRIPTS_SRC}/update_jira_issue.py" "${TARGET_DIR}/../common/scripts/update_jira_issue.py"
  success "Common script installed: common/scripts/update_jira_issue.py"
else
  die "Common script not found: ${COMMON_SCRIPTS_SRC}/update_jira_issue.py
  Ensure the full skills directory is present, not just this skill subdirectory."
fi

# Make Python scripts executable (optional — uv run handles this, but good practice)
chmod +x "${TARGET_DIR}/scripts/"*.py
chmod +x "${TARGET_DIR}/../common/scripts/"*.py

success "Files copied:"
find "${TARGET_DIR}" -type f | sort | while read -r f; do
  echo "    ${f#"${TARGET_DIR}/"}"
done
find "${TARGET_DIR}/../common/scripts" -type f | sort | while read -r f; do
  echo "    common/scripts/${f##*/}"
done

# ── Step 3: Install Python dependencies ───────────────────────────────────────
# Each script declares its own deps via PEP 723 inline metadata.
# Running them with --help triggers uv to resolve and cache the packages now,
# so the first real invocation is instant.
info "Installing Python dependencies..."

declare -A SKILL_SCRIPT_DEPS=(
  ["fetch_jira_details.py"]="jira>=3.0.0"
  ["download_jira_attachment.py"]="jira>=3.0.0, requests>=2.31.0"
  ["validate_yaml_schema.py"]="jsonschema>=4.23.0, pyyaml>=6.0.0"
)

ALL_DEPS_OK=true
for script in "${!SKILL_SCRIPT_DEPS[@]}"; do
  deps="${SKILL_SCRIPT_DEPS[$script]}"
  echo -n "    ${script} (${deps}) ... "
  if uv run --script "${TARGET_DIR}/scripts/${script}" --help >/dev/null 2>&1; then
    echo -e "${GREEN}OK${RESET}"
  else
    echo -e "${RED}FAILED${RESET}"
    warn "Could not pre-install deps for ${script}. They will be fetched on first use."
    ALL_DEPS_OK=false
  fi
done

echo -n "    update_jira_issue.py (jira>=3.0.0) ... "
if uv run --script "${TARGET_DIR}/../common/scripts/update_jira_issue.py" --help >/dev/null 2>&1; then
  echo -e "${GREEN}OK${RESET}"
else
  echo -e "${RED}FAILED${RESET}"
  warn "Could not pre-install deps for update_jira_issue.py. They will be fetched on first use."
  ALL_DEPS_OK=false
fi

if $ALL_DEPS_OK; then
  success "All Python dependencies installed and cached."
else
  warn "Some dependencies could not be pre-installed. uv will retry on first skill invocation."
fi

# ── Step 4: Verify installed files ────────────────────────────────────────────
info "Verifying installation..."
REQUIRED_FILES=(
  "SKILL.md"
  "scripts/fetch_jira_details.py"
  "scripts/download_jira_attachment.py"
  "scripts/validate_yaml_schema.py"
  "assets/odh_component_details.schema.json"
)
ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "${TARGET_DIR}/${f}" ]]; then
    success "${f}"
  else
    error "Missing: ${f}"
    ALL_OK=false
  fi
done

COMMON_SCRIPT="${TARGET_DIR}/../common/scripts/update_jira_issue.py"
if [[ -f "${COMMON_SCRIPT}" ]]; then
  success "common/scripts/update_jira_issue.py"
else
  error "Missing: common/scripts/update_jira_issue.py"
  ALL_OK=false
fi

$ALL_OK || die "Installation incomplete — some files are missing."

# ── Step 5: Check environment variables ───────────────────────────────────────
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
  warn "JIRA_SERVER is not set — will default to https://redhat.atlassian.net"
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
  echo -e "  Create an Atlassian API token at:"
  echo "    https://id.atlassian.com/manage-profile/security/api-tokens"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code (or open a new session), then run:"
echo ""
echo "    /validate-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234"
echo ""
