#!/usr/bin/env bash
# Usage: check_prerequisites.sh [--env "VAR1 VAR2"] [--tools "tool1 tool2"]
# Exits 0 if all prerequisites are satisfied; exits 1 with a clear message on first failure.
set -euo pipefail

ENV_VARS=()
TOOLS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   read -ra ENV_VARS  <<< "$2"; shift 2 ;;
    --tools) read -ra TOOLS <<< "$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for var in "${ENV_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: Required environment variable '$var' is not set." >&2
    case "$var" in
      JIRA_USER_EMAIL)
        echo "  Set it with: export JIRA_USER_EMAIL='you@example.com'" >&2 ;;
      JIRA_API_TOKEN)
        echo "  Create an Atlassian API token at: https://id.atlassian.com/manage-profile/security/api-tokens" >&2
        echo "  Set it with: export JIRA_API_TOKEN='your-token'" >&2 ;;
      GITHUB_TOKEN)
        echo "  Set it with: export GITHUB_TOKEN='your-github-pat'" >&2 ;;
      GITHUB_USER)
        echo "  Set it with: export GITHUB_USER='your-github-username'" >&2 ;;
      GITLAB_TOKEN)
        echo "  Set it with: export GITLAB_TOKEN='your-gitlab-pat'" >&2 ;;
      GITLAB_USER)
        echo "  Set it with: export GITLAB_USER='your-gitlab-username'" >&2 ;;
      *)
        echo "  Set it with: export ${var}='<value>'" >&2 ;;
    esac
    exit 1
  fi
done

_tool_ok() {
  local tool="$1"
  if command -v "$tool" &>/dev/null; then return 0; fi
  # kustomize may be installed as a shim in ~/.local/bin
  if [[ "$tool" == "kustomize" ]] && [[ -x "${HOME}/.local/bin/kustomize" ]]; then return 0; fi
  return 1
}

_install_hint() {
  local tool="$1"
  case "$tool" in
    uv)        echo "  Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
    skopeo)    echo "  Install with: brew install skopeo  (macOS) or dnf install skopeo (RHEL/Fedora)" ;;
    oc)        echo "  Download from: https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/" ;;
    kustomize) echo "  Install with: brew install kustomize  or  curl -s 'https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh' | bash" ;;
    yamllint)  echo "  Install with: pip install yamllint  or  brew install yamllint" ;;
    jq)        echo "  Install with: brew install jq  or  dnf install jq" ;;
    git)       echo "  Install with: brew install git  or  dnf install git" ;;
    *)         echo "  Install '$tool' via your system package manager or project documentation." ;;
  esac
}

for tool in "${TOOLS[@]}"; do
  if ! _tool_ok "$tool"; then
    echo "ERROR: Required tool '$tool' is not installed or not in PATH." >&2
    _install_hint "$tool"
    exit 1
  fi
done

exit 0
