#!/usr/bin/env bash
# install-dependencies.sh — Install all CLI and Python dependencies for the
# onboard-konflux-components-for-odh-and-rhoai skill and all its child skills.
#
# Supports: macOS (Homebrew), RHEL/Fedora (dnf), Debian/Ubuntu (apt)
#
# Usage:
#   bash .claude/skills/install-dependencies.sh [--dry-run] [--skip-python-cache]
#
# Options:
#   --dry-run           Print what would be installed without installing anything.
#   --skip-python-cache Skip pre-warming the uv Python package cache.

set -euo pipefail

# ── Colour helpers ──────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[SKIP]${NC}  $*"; }
info() { echo -e "        $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

DRY_RUN=false
SKIP_PYTHON_CACHE=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)           DRY_RUN=true; shift ;;
    --skip-python-cache) SKIP_PYTHON_CACHE=true; shift ;;
    *) err "Unknown argument: $1"; exit 1 ;;
  esac
done

# ── Detect OS / package manager ─────────────────────────────────────────────────
OS="$(uname -s)"
PM=""   # package manager: brew | dnf | apt

if [[ "$OS" == "Darwin" ]]; then
  PM="brew"
elif [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  source /etc/os-release
  case "${ID:-}" in
    rhel|centos|fedora|rocky|almalinux) PM="dnf" ;;
    ubuntu|debian|linuxmint|pop)        PM="apt"  ;;
  esac
fi

if [[ -z "$PM" ]]; then
  err "Unsupported OS or no recognised package manager (brew/dnf/apt)."
  err "Install the following tools manually and re-run:"
  err "  uv, git, curl, jq, oc, skopeo, yamllint, kustomize"
  exit 1
fi

echo ""
echo "========================================================"
echo "  Dependency installer for RHOAI component onboarding"
echo "========================================================"
echo "  OS / package manager : $OS / $PM"
echo "  Dry run              : $DRY_RUN"
echo "========================================================"
echo ""

# ── Helper: run or print ─────────────────────────────────────────────────────────
run() {
  if [[ "$DRY_RUN" == true ]]; then
    info "(dry-run) $*"
  else
    "$@"
  fi
}

# ── Helper: check if a tool is already installed ─────────────────────────────────
_installed() {
  local t="$1"
  command -v "$t" &>/dev/null && return 0
  # kustomize shim location used by check_prerequisites.sh
  [[ "$t" == "kustomize" && -x "${HOME}/.local/bin/kustomize" ]] && return 0
  return 1
}

# ── 1. uv ───────────────────────────────────────────────────────────────────────
echo "── uv (Python runner) ──────────────────────────────────"
if _installed uv; then
  warn "uv already installed ($(uv --version 2>/dev/null | head -1))"
else
  info "Installing uv via official installer..."
  run curl -LsSf https://astral.sh/uv/install.sh | sh
  # Ensure uv is on PATH for the rest of this script
  export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:$PATH"
  ok "uv installed"
fi
echo ""

# ── 2. git ──────────────────────────────────────────────────────────────────────
echo "── git ─────────────────────────────────────────────────"
if _installed git; then
  warn "git already installed ($(git --version))"
else
  case "$PM" in
    brew) run brew install git ;;
    dnf)  run sudo dnf install -y git ;;
    apt)  run sudo apt-get install -y git ;;
  esac
  ok "git installed"
fi
echo ""

# ── 3. curl ─────────────────────────────────────────────────────────────────────
echo "── curl ────────────────────────────────────────────────"
if _installed curl; then
  warn "curl already installed ($(curl --version | head -1))"
else
  case "$PM" in
    brew) run brew install curl ;;
    dnf)  run sudo dnf install -y curl ;;
    apt)  run sudo apt-get install -y curl ;;
  esac
  ok "curl installed"
fi
echo ""

# ── 4. jq ───────────────────────────────────────────────────────────────────────
echo "── jq (JSON processor) ─────────────────────────────────"
if _installed jq; then
  warn "jq already installed ($(jq --version))"
else
  case "$PM" in
    brew) run brew install jq ;;
    dnf)  run sudo dnf install -y jq ;;
    apt)  run sudo apt-get install -y jq ;;
  esac
  ok "jq installed"
fi
echo ""

# ── 5. yamllint ─────────────────────────────────────────────────────────────────
echo "── yamllint (YAML linter) ──────────────────────────────"
if _installed yamllint; then
  warn "yamllint already installed ($(yamllint --version))"
else
  case "$PM" in
    brew) run brew install yamllint ;;
    dnf)  run sudo dnf install -y yamllint ;;
    apt)  run sudo apt-get install -y yamllint ;;
  esac
  ok "yamllint installed"
fi
echo ""

# ── 6. skopeo ───────────────────────────────────────────────────────────────────
echo "── skopeo (container image inspect) ───────────────────"
if _installed skopeo; then
  warn "skopeo already installed ($(skopeo --version))"
else
  case "$PM" in
    brew) run brew install skopeo ;;
    dnf)  run sudo dnf install -y skopeo ;;
    apt)
      info "Adding containers/skopeo PPA for Ubuntu..."
      run sudo apt-get install -y skopeo || {
        err "skopeo not available via apt. Install manually:"
        err "  https://github.com/containers/skopeo/blob/main/install.md"
        exit 1
      }
      ;;
  esac
  ok "skopeo installed"
fi
echo ""

# ── 7. kustomize ────────────────────────────────────────────────────────────────
echo "── kustomize (Kubernetes overlay tool) ─────────────────"
if _installed kustomize; then
  warn "kustomize already installed ($(kustomize version 2>/dev/null || echo 'version unknown'))"
else
  case "$PM" in
    brew) run brew install kustomize ;;
    dnf|apt)
      info "Installing kustomize via official install script to ~/.local/bin..."
      run mkdir -p "${HOME}/.local/bin"
      run bash -c "curl -s 'https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh' | bash -s -- '${HOME}/.local/bin'"
      export PATH="${HOME}/.local/bin:$PATH"
      ;;
  esac
  ok "kustomize installed"
fi
echo ""

# ── 8. oc (OpenShift CLI) ───────────────────────────────────────────────────────
echo "── oc (OpenShift / Konflux CLI) ────────────────────────"
if _installed oc; then
  warn "oc already installed ($(oc version --client 2>/dev/null | head -1))"
else
  OC_INSTALL_DIR="${HOME}/.local/bin"
  run mkdir -p "$OC_INSTALL_DIR"

  case "$OS" in
    Darwin)
      OC_PLATFORM="mac"
      if [[ "$(uname -m)" == "arm64" ]]; then
        OC_PLATFORM="mac/arm64"
      fi
      ;;
    Linux)
      OC_PLATFORM="linux"
      ;;
  esac

  OC_MIRROR="https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable"
  OC_TARBALL="openshift-client-${OC_PLATFORM}.tar.gz"

  info "Downloading oc from $OC_MIRROR/$OC_TARBALL..."
  if [[ "$DRY_RUN" == true ]]; then
    info "(dry-run) curl -fsSL $OC_MIRROR/$OC_TARBALL | tar xz -C $OC_INSTALL_DIR oc kubectl"
  else
    curl -fsSL "$OC_MIRROR/$OC_TARBALL" \
      | tar xz -C "$OC_INSTALL_DIR" oc kubectl
    export PATH="$OC_INSTALL_DIR:$PATH"
  fi
  ok "oc installed to $OC_INSTALL_DIR"
  info "Add to PATH: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
echo ""

# ── 9. Python packages (pre-warm uv cache) ──────────────────────────────────────
echo "── Python packages (uv cache pre-warm) ─────────────────"
if [[ "$SKIP_PYTHON_CACHE" == true ]]; then
  warn "--skip-python-cache set; skipping Python package pre-warm"
  info "(packages install automatically on first script invocation via uv)"
else
  # The Python scripts use 'uv run --script' with inline [script] metadata,
  # so packages are installed on first use. Pre-warm the cache here so the
  # first real invocation is instant.
  PYTHON_PACKAGES=(
    "jira>=3.0.0"
    "requests>=2.31.0"
    "PyGithub>=2.0.0"
    "python-gitlab>=3.0.0"
    "ruamel.yaml"
    "jsonschema>=4.23.0"
    "pyyaml>=6.0.0"
  )

  if ! _installed uv; then
    warn "uv not found — cannot pre-warm Python cache. Install uv first."
  else
    info "Pre-warming uv cache for ${#PYTHON_PACKAGES[@]} packages..."
    PKG_ARGS=()
    for pkg in "${PYTHON_PACKAGES[@]}"; do
      PKG_ARGS+=(--with "$pkg")
    done

    if [[ "$DRY_RUN" == true ]]; then
      info "(dry-run) uv run ${PKG_ARGS[*]} python3 -c 'import jira, github, gitlab, ruamel.yaml, jsonschema, yaml'"
    else
      uv run "${PKG_ARGS[@]}" python3 -c \
        "import jira, github, gitlab, ruamel.yaml, jsonschema, yaml; print('All packages importable')" \
        2>/dev/null && ok "Python packages cached" || {
          warn "Some packages failed to import. They will be fetched on first use."
        }
    fi
  fi
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────────────────
echo "========================================================"
echo "  Installation complete. Verifying tools:"
echo "========================================================"

MISSING=()
for tool in uv git curl jq yamllint skopeo kustomize oc; do
  if _installed "$tool"; then
    ok "$tool"
  else
    err "$tool — NOT FOUND"
    MISSING+=("$tool")
  fi
done

echo ""
if [[ ${#MISSING[@]} -gt 0 ]]; then
  err "The following tools are still missing: ${MISSING[*]}"
  err "Install them manually and re-run this script to verify."
  exit 1
else
  echo -e "${GREEN}All tools installed successfully.${NC}"
  echo ""
  echo "Next: export the required environment variables before running a skill:"
  echo "  export GITHUB_USER=your-github-username"
  echo "  export GITHUB_TOKEN=your-github-pat        # repo + actions:write scope"
  echo "  export GITLAB_USER=your-gitlab-username"
  echo "  export GITLAB_TOKEN=your-gitlab-pat         # api scope"
  echo "  export JIRA_USER_EMAIL=you@redhat.com"
  echo "  export JIRA_API_TOKEN=your-atlassian-api-token"
  echo ""
  echo "Optional Konflux cluster login:"
  echo "  export OC_TOKEN=your-cluster-token"
  echo ""
fi