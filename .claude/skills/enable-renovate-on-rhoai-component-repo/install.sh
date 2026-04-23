#!/usr/bin/env bash
# install.sh — Install the enable-renovate-on-rhoai-component-repo Claude Code skill
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in the current working directory
#   ./install.sh --dir /path  # installs to an explicit target directory

set -euo pipefail

SKILL_NAME="enable-renovate-on-rhoai-component-repo"
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

COMMON_DIR="${TARGET_DIR}/../common/scripts"
COMMON_SRC="${SCRIPT_DIR}/../common/scripts"

echo ""
echo -e "${BOLD}Installing ${SKILL_NAME}${RESET}"
echo "  Source        : ${SCRIPT_DIR}"
echo "  Target        : ${TARGET_DIR}"
echo "  Common scripts: ${COMMON_DIR}"
echo ""

# ── Step 1: Check prerequisites ────────────────────────────────────────────────
info "Checking prerequisites..."

# uv — attempt auto-install
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
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v uv &>/dev/null; then
    die "uv was installed but is not on PATH. Open a new terminal and re-run this script, or:
    export PATH=\"\${HOME}/.local/bin:\${PATH}\""
  fi
  success "uv installed: $(uv --version 2>/dev/null | head -1 | awk '{print $2}')"
else
  success "uv $(uv --version 2>/dev/null | head -1 | awk '{print $2}') (already installed)"
fi

# git
if ! command -v git &>/dev/null; then
  die "git is not installed. Install git before continuing."
else
  success "git $(git --version | awk '{print $3}') (already installed)"
fi

# curl — needed for GitHub API checks in Step 4 of the skill
if ! command -v curl &>/dev/null; then
  die "curl is not installed. Install curl before continuing."
else
  success "curl $(curl --version | head -1 | awk '{print $2}') (already installed)"
fi

# ── Step 2: Create directories ─────────────────────────────────────────────────
info "Creating directories..."
mkdir -p "${TARGET_DIR}" "${COMMON_DIR}"
success "Directory ready: ${TARGET_DIR}"
success "Directory ready: ${COMMON_DIR}"

# ── Step 3: Copy skill files ───────────────────────────────────────────────────
info "Copying skill files..."
cp "${SCRIPT_DIR}/SKILL.md" "${TARGET_DIR}/SKILL.md"
success "Copied: SKILL.md"

# ── Step 4: Copy common scripts ───────────────────────────────────────────────
info "Copying common scripts..."

COMMON_SCRIPTS=(
  "setup_github_playpen.sh"
  "raise_github_pr.py"
  "monitor_github_pr.py"
  "update_jira_issue.py"
  "fetch_jira_details.py"
  "download_jira_attachment.py"
)

for script in "${COMMON_SCRIPTS[@]}"; do
  src="${COMMON_SRC}/${script}"
  if [[ -f "$src" ]]; then
    cp "$src" "${COMMON_DIR}/${script}"
    success "Copied: common/scripts/${script}"
  else
    die "Source script not found: ${src}
  Ensure the full skills directory is present, not just this skill subdirectory."
  fi
done

# ── Step 5: Set permissions ────────────────────────────────────────────────────
info "Setting permissions..."
chmod +x "${COMMON_DIR}/setup_github_playpen.sh"
for pyfile in "${COMMON_DIR}"/*.py; do
  [[ -f "$pyfile" ]] && chmod +x "$pyfile"
done
success "Permissions set."

# ── Step 6: Pre-warm Python dependencies ──────────────────────────────────────
info "Pre-warming Python script dependencies..."
echo "  (This downloads and caches packages so the first skill invocation is instant)"

ALL_DEPS_OK=true

pre_warm() {
  local label="$1"
  local path="$2"
  echo -n "    ${label} ... "
  if uv run --script "$path" --help >/dev/null 2>&1; then
    echo -e "${GREEN}OK${RESET}"
  else
    echo -e "${RED}FAILED${RESET}"
    warn "Could not pre-install deps for ${label}. They will be fetched on first use."
    ALL_DEPS_OK=false
  fi
}

# GitHub scripts (PyGithub)
pre_warm "raise_github_pr.py"   "${COMMON_DIR}/raise_github_pr.py"
pre_warm "monitor_github_pr.py" "${COMMON_DIR}/monitor_github_pr.py"

# Jira scripts
pre_warm "update_jira_issue.py"        "${COMMON_DIR}/update_jira_issue.py"
pre_warm "fetch_jira_details.py"       "${COMMON_DIR}/fetch_jira_details.py"
pre_warm "download_jira_attachment.py" "${COMMON_DIR}/download_jira_attachment.py"

if $ALL_DEPS_OK; then
  success "All Python dependencies installed and cached."
else
  warn "Some dependencies could not be pre-installed. uv will retry on first skill invocation."
fi

# ── Step 7: Verify installed files ────────────────────────────────────────────
info "Verifying installation..."

REQUIRED_FILES=(
  "${TARGET_DIR}/SKILL.md"
  "${COMMON_DIR}/setup_github_playpen.sh"
  "${COMMON_DIR}/raise_github_pr.py"
  "${COMMON_DIR}/monitor_github_pr.py"
  "${COMMON_DIR}/update_jira_issue.py"
  "${COMMON_DIR}/fetch_jira_details.py"
  "${COMMON_DIR}/download_jira_attachment.py"
)

ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "$f" ]]; then
    success "${f#"${TARGET_DIR}/../"}"
  else
    error "Missing: $f"
    ALL_OK=false
  fi
done

$ALL_OK || die "Installation incomplete — some files are missing."

# ── Step 8: Check environment variables ───────────────────────────────────────
echo ""
info "Checking environment variables..."
CREDS_OK=true

check_var() {
  local var="$1"
  local hint="$2"
  local mask="${3:-false}"
  local val="${!var:-}"
  if [[ -z "$val" ]]; then
    warn "${var} is not set. ${hint}"
    CREDS_OK=false
  else
    if [[ "$mask" == "true" ]]; then
      success "${var}=<set>"
    else
      success "${var}=${val}"
    fi
  fi
}

check_var "GITHUB_USER"     "export GITHUB_USER=yourusername"
check_var "GITHUB_TOKEN"    "Needs 'repo' scope (read and write)" "true"
check_var "JIRA_USER_EMAIL" "export JIRA_USER_EMAIL=you@redhat.com"
check_var "JIRA_API_TOKEN"  "Create at: https://id.atlassian.com/manage-profile/security/api-tokens" "true"

echo ""
info "Checking optional environment variables..."

if [[ -z "${RHOAI_KONFLUX_CENTRAL_REPO_URL:-}" ]]; then
  warn "RHOAI_KONFLUX_CENTRAL_REPO_URL is not set — will default to:"
  warn "  https://github.com/red-hat-data-services/konflux-central.git"
else
  success "RHOAI_KONFLUX_CENTRAL_REPO_URL=${RHOAI_KONFLUX_CENTRAL_REPO_URL}"
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
  echo "    export GITHUB_USER='yourusername'"
  echo "    export GITHUB_TOKEN='your-github-token'         # needs: repo scope"
  echo "    export JIRA_USER_EMAIL='you@redhat.com'"
  echo "    export JIRA_API_TOKEN='your-jira-api-token'"
  echo ""
  echo "    # Optional overrides:"
  echo "    # export RHOAI_KONFLUX_CENTRAL_REPO_URL='https://github.com/red-hat-data-services/konflux-central.git'"
  echo "    # export JIRA_SERVER='https://redhat.atlassian.net'"
  echo ""
  echo "  Create GitHub token: GitHub → Settings → Developer settings → Personal access tokens"
  echo "  Create Jira token:   https://id.atlassian.com/manage-profile/security/api-tokens"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code (or open a new session), then run:"
echo ""
echo "    /enable-renovate-on-rhoai-component-repo https://redhat.atlassian.net/browse/RHOAIENG-1234"
echo ""
echo "  NOTE: This skill requires:"
echo "    - Public internet access to github.com (no VPN needed)"
echo "    - GITHUB_TOKEN with 'repo' scope (read + write on rhoai-konflux-central)"
echo "    - 'component_onboarding_details.yaml' attached to the Jira issue"
echo "      (or the skill must be invoked from within the master onboarding pipeline)"
echo ""
