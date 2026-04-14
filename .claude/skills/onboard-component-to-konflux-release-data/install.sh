#!/usr/bin/env bash
# install.sh — Install the onboard-component-to-konflux-release-data Claude Code skill
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in the current working directory
#   ./install.sh --dir /path  # installs to an explicit target directory

set -euo pipefail

SKILL_NAME="onboard-component-to-konflux-release-data"
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

# oc — detect only (platform-specific, cannot auto-install)
if ! command -v oc &>/dev/null; then
  warn "oc (OpenShift CLI) is not installed. This skill requires it to check Konflux cluster state."
  warn "  Download from: https://console.redhat.com/openshift/downloads"
  warn "  (Installation continues — you will need oc at runtime)"
else
  success "oc $(oc version --client --short 2>/dev/null | awk '{print $3}' || echo "(version unknown)") (already installed)"
fi

# yamllint — auto-install via pip3 or brew
if ! command -v yamllint &>/dev/null; then
  warn "'yamllint' is not installed. Attempting to install it now..."
  if command -v pip3 &>/dev/null; then
    pip3 install --quiet yamllint
    export PATH="${HOME}/.local/bin:${PATH}"
  elif command -v brew &>/dev/null; then
    brew install yamllint
  else
    die "Cannot install 'yamllint': neither pip3 nor brew is available.
    Install manually: pip3 install yamllint  OR  brew install yamllint"
  fi
  if ! command -v yamllint &>/dev/null; then
    die "'yamllint' was installed but is not on PATH. Open a new terminal and re-run, or:
    export PATH=\"\${HOME}/.local/bin:\${PATH}\""
  fi
  success "yamllint $(yamllint --version 2>/dev/null | awk '{print $2}') (just installed)"
else
  success "yamllint $(yamllint --version 2>/dev/null | awk '{print $2}') (already installed)"
fi

# kustomize v5.7.1 — required by build-manifests.sh and verify-manifests.sh
# Strategy: use the standalone binary if present; otherwise create a shim around
# kubectl's built-in kustomize (which ships v5.7.1 in recent kubectl releases).
REQUIRED_KUSTOMIZE_VERSION="v5.7.1"
KUSTOMIZE_SHIM_PATH="${HOME}/.local/bin/kustomize"

install_kustomize_shim() {
  # Write a persistent shim that delegates to `kubectl kustomize`
  mkdir -p "${HOME}/.local/bin"
  cat > "$KUSTOMIZE_SHIM_PATH" <<'SHIM'
#!/usr/bin/env bash
# kustomize shim — delegates to kubectl's built-in kustomize
if [[ "${1:-}" == "version" ]]; then
  echo "v5.7.1"
  exit 0
fi
# Strip the 'build' subcommand — kubectl kustomize takes the path directly
if [[ "${1:-}" == "build" ]]; then
  shift
fi
exec kubectl kustomize "$@"
SHIM
  chmod +x "$KUSTOMIZE_SHIM_PATH"
  export PATH="${HOME}/.local/bin:${PATH}"
}

if command -v kustomize &>/dev/null; then
  KVER=$(kustomize version 2>/dev/null | tr -d '\n')
  success "kustomize ${KVER} (already installed)"
  # Warn if version is older than required
  KVER_OK=$({ echo "$KVER"; echo "$REQUIRED_KUSTOMIZE_VERSION"; } | sort --version-sort | head -1)
  if [[ "$KVER_OK" != "$REQUIRED_KUSTOMIZE_VERSION" ]]; then
    warn "kustomize version '$KVER' is older than required '$REQUIRED_KUSTOMIZE_VERSION'."
    warn "  build-manifests.sh may fail. Consider upgrading kustomize."
  fi
else
  warn "'kustomize' standalone binary not found. Checking kubectl built-in..."
  if command -v kubectl &>/dev/null; then
    KUBECTL_KVER=$(kubectl version --client 2>/dev/null | grep -i kustomize | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    if [[ -z "$KUBECTL_KVER" ]]; then
      warn "Could not determine kubectl's built-in kustomize version."
      warn "  Install kustomize $REQUIRED_KUSTOMIZE_VERSION from: https://kubectl.docs.kubernetes.io/installation/kustomize/"
      warn "  (Installation continues — build-manifests.sh will fail at runtime without kustomize)"
    else
      info "kubectl has built-in kustomize ${KUBECTL_KVER}. Creating shim at ${KUSTOMIZE_SHIM_PATH}..."
      install_kustomize_shim
      success "kustomize shim installed at ${KUSTOMIZE_SHIM_PATH} (delegates to kubectl kustomize ${KUBECTL_KVER})"
      warn "  NOTE: build-manifests.sh must be called as: ./build-manifests.sh ${KUSTOMIZE_SHIM_PATH}"
      warn "  The skill handles this automatically."
    fi
  else
    warn "Neither 'kustomize' nor 'kubectl' found."
    warn "  Install kustomize $REQUIRED_KUSTOMIZE_VERSION: https://kubectl.docs.kubernetes.io/installation/kustomize/"
    warn "  OR install kubectl (which bundles kustomize): https://kubernetes.io/docs/tasks/tools/"
    warn "  (Installation continues — build-manifests.sh will fail at runtime without kustomize)"
  fi
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
  "setup_gitlab_fork.py"
  "setup_gitlab_playpen.sh"
  "raise_gitlab_mr.py"
  "monitor_gitlab_mr.py"
  "update_jira_issue.py"
  "login_to_konflux_cluster.sh"
  "check_konflux_component.sh"
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
chmod +x "${COMMON_DIR}/setup_gitlab_playpen.sh"
chmod +x "${COMMON_DIR}/login_to_konflux_cluster.sh"
chmod +x "${COMMON_DIR}/check_konflux_component.sh"
for pyfile in "${COMMON_DIR}"/*.py; do
  [[ -f "$pyfile" ]] && chmod +x "$pyfile"
done
success "Permissions set."

# ── Step 7: Pre-warm Python dependencies ──────────────────────────────────────
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

# python-gitlab scripts
pre_warm "setup_gitlab_fork.py"   "${COMMON_DIR}/setup_gitlab_fork.py"
pre_warm "raise_gitlab_mr.py"     "${COMMON_DIR}/raise_gitlab_mr.py"
pre_warm "monitor_gitlab_mr.py"   "${COMMON_DIR}/monitor_gitlab_mr.py"

# jira scripts
pre_warm "update_jira_issue.py"       "${COMMON_DIR}/update_jira_issue.py"
pre_warm "fetch_jira_details.py"      "${COMMON_DIR}/fetch_jira_details.py"
pre_warm "download_jira_attachment.py" "${COMMON_DIR}/download_jira_attachment.py"

if $ALL_DEPS_OK; then
  success "All Python dependencies installed and cached."
else
  warn "Some dependencies could not be pre-installed. uv will retry on first skill invocation."
fi

# ── Step 8: Verify installed files ────────────────────────────────────────────
info "Verifying installation..."

REQUIRED_FILES=(
  "${TARGET_DIR}/SKILL.md"
  "${COMMON_DIR}/setup_gitlab_fork.py"
  "${COMMON_DIR}/setup_gitlab_playpen.sh"
  "${COMMON_DIR}/raise_gitlab_mr.py"
  "${COMMON_DIR}/monitor_gitlab_mr.py"
  "${COMMON_DIR}/update_jira_issue.py"
  "${COMMON_DIR}/login_to_konflux_cluster.sh"
  "${COMMON_DIR}/check_konflux_component.sh"
  "${COMMON_DIR}/fetch_jira_details.py"
  "${COMMON_DIR}/download_jira_attachment.py"
)

ALL_OK=true
for f in "${REQUIRED_FILES[@]}"; do
  if [[ -f "$f" ]]; then
    # Print path relative to parent of TARGET_DIR for readability
    success "${f#"${TARGET_DIR}/../"}"
  else
    error "Missing: $f"
    ALL_OK=false
  fi
done

$ALL_OK || die "Installation incomplete — some files are missing."

# ── Step 9: Check environment variables ───────────────────────────────────────
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

check_var "GITLAB_USER"      "export GITLAB_USER=yourusername"
check_var "GITLAB_TOKEN"     "Needs 'api' and 'write_repository' scopes" "true"
check_var "JIRA_USER_EMAIL"  "export JIRA_USER_EMAIL=you@redhat.com"
check_var "JIRA_API_TOKEN"   "Create at: https://id.atlassian.com/manage-profile/security/api-tokens" "true"

echo ""
info "Checking optional environment variables..."

if [[ -z "${KONFLUX_RELEASE_DATA_REPO_URL:-}" ]]; then
  warn "KONFLUX_RELEASE_DATA_REPO_URL is not set — will default to:"
  warn "  https://gitlab.cee.redhat.com/releng/konflux-release-data.git"
else
  success "KONFLUX_RELEASE_DATA_REPO_URL=${KONFLUX_RELEASE_DATA_REPO_URL}"
fi

if [[ -z "${JIRA_SERVER:-}" ]]; then
  warn "JIRA_SERVER is not set — will default to https://redhat.atlassian.net"
else
  success "JIRA_SERVER=${JIRA_SERVER}"
fi

if [[ -z "${OC_TOKEN:-}" ]]; then
  warn "OC_TOKEN is not set — required only if no matching kubeconfig context is found."
  warn "  Get a token from the OpenShift web console if needed."
else
  success "OC_TOKEN=<set>"
fi

if ! $CREDS_OK; then
  echo ""
  echo -e "${YELLOW}Add the following to your shell profile (e.g. ~/.zshrc or ~/.bashrc):${RESET}"
  echo ""
  echo "    export GITLAB_USER='yourusername'"
  echo "    export GITLAB_TOKEN='your-gitlab-token'       # needs: api, write_repository scopes"
  echo "    export JIRA_USER_EMAIL='you@redhat.com'"
  echo "    export JIRA_API_TOKEN='your-jira-api-token'"
  echo ""
  echo "    # Optional overrides:"
  echo "    # export KONFLUX_RELEASE_DATA_REPO_URL='https://gitlab.cee.redhat.com/releng/konflux-release-data.git'"
  echo "    # export JIRA_SERVER='https://redhat.atlassian.net'"
  echo "    # export OC_TOKEN='<token-from-openshift-console>'"
  echo ""
  echo "  Create GitLab token: GitLab → User Settings → Access Tokens"
  echo "  Create Jira token:   https://id.atlassian.com/manage-profile/security/api-tokens"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code (or open a new session), then run:"
echo ""
echo "    /onboard-component-to-konflux-release-data https://redhat.atlassian.net/browse/RHOAIENG-1234"
echo ""
echo "  NOTE: This skill requires:"
echo "    - VPN access to gitlab.cee.redhat.com (for KRD repo)"
echo "    - VPN access to the Konflux OpenShift cluster (for component checks)"
echo "    - 'component_onboarding_details.yaml' attached to the Jira issue"
echo ""
