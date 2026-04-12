#!/usr/bin/env bash
# install.sh — Install the create-quay-repo Claude Code skill
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in the current working directory
#   ./install.sh --dir /path  # installs to an explicit target directory

set -euo pipefail

SKILL_NAME="create-quay-repo"
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
echo "  Source : ${SCRIPT_DIR}"
echo "  Target : ${TARGET_DIR}"
echo "  Common : ${COMMON_DIR}"
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

# skopeo — detect only (cannot safely auto-install cross-platform)
if ! command -v skopeo &>/dev/null; then
  warn "skopeo is not installed. Install it before using this skill:"
  warn "  macOS:        brew install skopeo"
  warn "  RHEL/Fedora:  sudo dnf install skopeo"
  warn "  Ubuntu/Debian: sudo apt-get install skopeo"
  warn "  (skopeo is only needed at runtime — installation continues)"
else
  success "skopeo $(skopeo --version 2>/dev/null | awk '{print $3}') (already installed)"
fi

# git
if ! command -v git &>/dev/null; then
  die "git is not installed. Install git before continuing."
else
  success "git $(git --version | awk '{print $3}') (already installed)"
fi

# ── Step 2: Create directories ─────────────────────────────────────────────────
info "Creating directories..."
mkdir -p "${TARGET_DIR}" "${COMMON_DIR}"
success "Directory ready: ${TARGET_DIR}"
success "Directory ready: ${COMMON_DIR}"

# ── Step 3: Copy skill files ───────────────────────────────────────────────────
info "Copying skill files..."

cp "${SCRIPT_DIR}/SKILL.md"    "${TARGET_DIR}/SKILL.md"
success "Copied: SKILL.md"

# ── Step 4: Copy common scripts ───────────────────────────────────────────────
info "Copying common scripts..."

COMMON_SCRIPTS=(
  "check_quay_repo.sh"
  "setup_gitlab_fork.py"
  "setup_gitlab_playpen.sh"
  "raise_gitlab_mr.py"
  "monitor_gitlab_mr.py"
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

# Copy update_jira_issue.py only if it doesn't already exist at the destination
# (it may have been installed by another skill)
UPDATE_JIRA_SRC="${COMMON_SRC}/update_jira_issue.py"
UPDATE_JIRA_DEST="${COMMON_DIR}/update_jira_issue.py"
if [[ -f "$UPDATE_JIRA_SRC" ]]; then
  cp "$UPDATE_JIRA_SRC" "$UPDATE_JIRA_DEST"
  success "Copied: common/scripts/update_jira_issue.py"
elif [[ -f "$UPDATE_JIRA_DEST" ]]; then
  success "common/scripts/update_jira_issue.py already present — skipping."
else
  warn "update_jira_issue.py not found in source or destination."
  warn "Jira updates will not work. Install validate-component-onboarding-jira first, or copy it manually."
fi

# ── Step 5: Set permissions ────────────────────────────────────────────────────
info "Setting permissions..."
chmod +x "${TARGET_DIR}/SKILL.md" 2>/dev/null || true
chmod +x "${COMMON_DIR}/check_quay_repo.sh"    2>/dev/null || true
chmod +x "${COMMON_DIR}/setup_gitlab_playpen.sh" 2>/dev/null || true
for pyfile in "${COMMON_DIR}"/*.py; do
  [[ -f "$pyfile" ]] && chmod +x "$pyfile"
done
success "Permissions set."

# ── Step 6: Pre-warm Python dependencies ──────────────────────────────────────
info "Pre-warming Python script dependencies (python-gitlab)..."
echo "  (This downloads and caches packages so the first skill invocation is instant)"

PYTHON_SCRIPTS=(
  "setup_gitlab_fork.py"
  "raise_gitlab_mr.py"
  "monitor_gitlab_mr.py"
)

ALL_DEPS_OK=true
for script in "${PYTHON_SCRIPTS[@]}"; do
  path="${COMMON_DIR}/${script}"
  echo -n "    ${script} ... "
  if uv run --script "$path" --help >/dev/null 2>&1; then
    echo -e "${GREEN}OK${RESET}"
  else
    echo -e "${RED}FAILED${RESET}"
    warn "Could not pre-install deps for ${script}. They will be fetched on first use."
    ALL_DEPS_OK=false
  fi
done

# Also pre-warm update_jira_issue.py if present
if [[ -f "$UPDATE_JIRA_DEST" ]]; then
  echo -n "    update_jira_issue.py ... "
  if uv run --script "$UPDATE_JIRA_DEST" --help >/dev/null 2>&1; then
    echo -e "${GREEN}OK${RESET}"
  else
    echo -e "${RED}FAILED${RESET}"
    warn "Could not pre-install deps for update_jira_issue.py."
    ALL_DEPS_OK=false
  fi
fi

if $ALL_DEPS_OK; then
  success "All Python dependencies installed and cached."
else
  warn "Some dependencies could not be pre-installed. uv will retry on first skill invocation."
fi

# ── Step 7: Verify installed files ────────────────────────────────────────────
info "Verifying installation..."

REQUIRED_FILES=(
  "${TARGET_DIR}/SKILL.md"
  "${COMMON_DIR}/check_quay_repo.sh"
  "${COMMON_DIR}/setup_gitlab_fork.py"
  "${COMMON_DIR}/setup_gitlab_playpen.sh"
  "${COMMON_DIR}/raise_gitlab_mr.py"
  "${COMMON_DIR}/monitor_gitlab_mr.py"
)

ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "$f" ]]; then
    success "${f##"${TARGET_DIR}/../"}"
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

if [[ -z "${GITLAB_USER:-}" ]]; then
  warn "GITLAB_USER is not set."
  CREDS_OK=false
else
  success "GITLAB_USER=${GITLAB_USER}"
fi

if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  warn "GITLAB_TOKEN is not set."
  CREDS_OK=false
else
  success "GITLAB_TOKEN=<set>"
fi

if [[ -z "${APP_INTERFACE_REPO_URL:-}" ]]; then
  warn "APP_INTERFACE_REPO_URL is not set — will default to: https://gitlab.cee.redhat.com/service/app-interface"
else
  success "APP_INTERFACE_REPO_URL=${APP_INTERFACE_REPO_URL}"
fi

echo ""
info "Jira credentials (only required when using --jira-url):"
if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  warn "JIRA_USER_EMAIL is not set (needed only when --jira-url is provided)."
else
  success "JIRA_USER_EMAIL=${JIRA_USER_EMAIL}"
fi
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  warn "JIRA_API_TOKEN is not set (needed only when --jira-url is provided)."
else
  success "JIRA_API_TOKEN=<set>"
fi

if ! $CREDS_OK; then
  echo ""
  echo -e "${YELLOW}Add the following to your shell profile (e.g. ~/.zshrc or ~/.bashrc):${RESET}"
  echo ""
  echo "    export GITLAB_USER='yourusername'"
  echo "    export GITLAB_TOKEN='your-gitlab-token'     # needs: api, write_repository scopes"
  echo "    # export APP_INTERFACE_REPO_URL='https://gitlab.cee.redhat.com/service/app-interface'  # optional"
  echo ""
  echo "    # Required only when using --jira-url:"
  echo "    # export JIRA_USER_EMAIL='you@example.com'"
  echo "    # export JIRA_API_TOKEN='your-jira-api-token'"
  echo ""
  echo -e "  Create a GitLab personal access token with api + write_repository scopes in GitLab → User Settings → Access Tokens."
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code (or open a new session), then run:"
echo ""
echo "    /create-quay-repo quay.io/opendatahub/my-component"
echo "    /create-quay-repo rhoai/my-component --jira-url https://redhat.atlassian.net/browse/RHOAIENG-1234"
echo ""
echo "  NOTE: This skill requires VPN access to gitlab.cee.redhat.com"
echo ""
