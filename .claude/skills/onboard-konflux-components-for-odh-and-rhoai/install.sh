#!/usr/bin/env bash
# install.sh — Install the onboard-konflux-components-for-odh-and-rhoai Claude Code skill
#
# Usage:
#   ./install.sh              # installs to ~/.claude/skills/ (global, default)
#   ./install.sh --project    # installs to .claude/skills/ in CWD
#   ./install.sh --dir /path  # installs to an explicit directory

set -euo pipefail

SKILL_NAME="onboard-konflux-components-for-odh-and-rhoai"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; RESET='\033[0m'
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
SKILLS_ROOT="$(dirname "$TARGET_DIR")"

echo ""
echo -e "${BOLD}Installing ${SKILL_NAME}${RESET}"
echo "  Source : ${SCRIPT_DIR}"
echo "  Target : ${TARGET_DIR}"
echo ""

# ── Step 1: Check required tools ──────────────────────────────────────────────
info "Checking required tools..."
for tool in git oc skopeo yamllint jq; do
  if command -v "$tool" &>/dev/null; then
    success "$tool: $(command -v $tool)"
  else
    warn "$tool: NOT FOUND — install before running the skill"
  fi
done

if ! command -v uv &>/dev/null; then
  warn "'uv' not installed. Attempting auto-install..."
  if command -v curl &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget &>/dev/null; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "Cannot install uv: neither curl nor wget found."
  fi
  export PATH="${HOME}/.local/bin:${PATH}"
  command -v uv &>/dev/null || die "uv installed but not on PATH. Open a new terminal."
  success "uv $(uv --version | head -1 | awk '{print $2}') (auto-installed)"
else
  success "uv $(uv --version | head -1 | awk '{print $2}')"
fi

if ! command -v kustomize &>/dev/null; then
  if command -v kubectl &>/dev/null; then
    warn "kustomize not found. Creating kubectl-backed shim at ~/.local/bin/kustomize..."
    mkdir -p "${HOME}/.local/bin"
    printf '#!/usr/bin/env bash\nexec kubectl kustomize "$@"\n' > "${HOME}/.local/bin/kustomize"
    chmod +x "${HOME}/.local/bin/kustomize"
    export PATH="${HOME}/.local/bin:${PATH}"
    success "kustomize shim created (~/.local/bin/kustomize)"
  else
    warn "kustomize not found and kubectl unavailable for shim. Install kustomize manually."
  fi
else
  success "kustomize: $(command -v kustomize)"
fi

# ── Step 2: Verify all child skills are installed ─────────────────────────────
info "Checking child skill installations..."
CHILD_SKILLS=(
  "validate-component-onboarding-jira"
  "create-quay-repo"
  "onboard-component-to-konflux-release-data"
  "add-component-to-odh-konflux-central"
  "add-component-to-rhoai-konflux-central"
  "create-pull-pipelines-in-rhoai-konflux-central"
  "run-odh-konflux-onboarder-workflow"
  "integrate-component-with-odh-operator"
  "integrate-component-with-bundle"
  "create-rhoai-delivery-repo"
  "update-rhoai-product-listing"
  "setup-auto-merge"
  "enable-renovate-on-rhoai-component-repo"
  "sync-rhoai-renovate-configs"
)
ALL_OK=true
for skill in "${CHILD_SKILLS[@]}"; do
  if [[ -f "${SKILLS_ROOT}/${skill}/SKILL.md" ]]; then
    success "${skill}: found"
  else
    error "${skill}: MISSING at ${SKILLS_ROOT}/${skill}/SKILL.md"
    ALL_OK=false
  fi
done
$ALL_OK || die "Install missing child skills first. Run each skill's ./install.sh."

# ── Step 3: Verify required common scripts ────────────────────────────────────
info "Checking common scripts..."
COMMON_DIR="${SKILLS_ROOT}/common/scripts"
COMMON_SCRIPTS=(
  "monitor_github_pr.py"
  "monitor_gitlab_mr.py"
  "update_jira_issue.py"
  "run_github_workflow.py"
  "fetch_jira_details.py"
  "download_jira_attachment.py"
  "validate_yaml_schema.py"
  "sync_state_from_jira.py"
  "build_progress_summary.py"
  "append_delivery_repo_entry.py"
  "check_pr_mr_status.sh"
  "init_pipeline.sh"
)
for script in "${COMMON_SCRIPTS[@]}"; do
  if [[ -f "${COMMON_DIR}/${script}" ]]; then
    success "common/scripts/${script}: found"
  else
    error "common/scripts/${script}: MISSING"
    ALL_OK=false
  fi
done
$ALL_OK || die "Common scripts are missing. Re-run child skill installers."

# ── Step 4: Copy SKILL.md ──────────────────────────────────────────────────────
info "Copying skill files..."
mkdir -p "$TARGET_DIR"
cp "${SCRIPT_DIR}/SKILL.md" "${TARGET_DIR}/SKILL.md"
success "SKILL.md -> ${TARGET_DIR}/SKILL.md"

# ── Step 5: Pre-warm Python dependencies ──────────────────────────────────────
info "Pre-warming Python dependencies..."
for script in "monitor_github_pr.py" "monitor_gitlab_mr.py" "update_jira_issue.py" \
              "run_github_workflow.py" "fetch_jira_details.py" \
              "sync_state_from_jira.py" "build_progress_summary.py" \
              "append_delivery_repo_entry.py"; do
  echo -n "    ${script} ... "
  uv run --script "${COMMON_DIR}/${script}" --help >/dev/null 2>&1 \
    && echo -e "${GREEN}OK${RESET}" \
    || echo -e "${YELLOW}WARN (deps will install on first use)${RESET}"
done

# ── Step 6: Check environment variables ───────────────────────────────────────
echo ""
info "Checking environment variables..."
for var in JIRA_USER_EMAIL JIRA_API_TOKEN GITLAB_USER GITLAB_TOKEN GITHUB_USER GITHUB_TOKEN; do
  if [[ -n "${!var:-}" ]]; then
    [[ "$var" == *TOKEN* || "$var" == *API* ]] \
      && success "${var}=<set>" || success "${var}=${!var}"
  else
    warn "${var} is not set — required before running the skill"
  fi
done
for var in OC_TOKEN APP_INTERFACE_REPO_URL KONFLUX_RELEASE_DATA_REPO_URL \
           ODH_KONFLUX_CENTRAL_REPO_URL RHOAI_KONFLUX_CENTRAL_REPO_URL \
           ODH_OPERATOR_REPO_URL BUILD_CONFIG_REPO_URL OBC_REPO_URL \
           RHODS_DEVOPS_INFRA_REPO_URL PYXIS_REPO_CONFIGS_REPO_URL JIRA_SERVER; do
  [[ -z "${!var:-}" ]] \
    && warn "${var} not set (optional — default applies)" \
    || success "${var}=${!var}"
done

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete!${RESET}"
echo ""
echo "  Restart Claude Code, then run:"
echo ""
echo "    /onboard-konflux-components-for-odh-and-rhoai https://redhat.atlassian.net/browse/RHOAIENG-1234"
echo ""
echo "  Before running:"
echo "    1. VPN active (required for Steps 2 and 3)"
echo "    2. All credentials exported"
echo "    3. component_onboarding_details.yaml attached to the Jira ticket"
echo "       (run /create-component-onboarding-jira <jira-url> if not yet done)"
echo ""
