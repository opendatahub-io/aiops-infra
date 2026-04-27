#!/usr/bin/env bash
# check_prerequisites.sh — validates required environment variables and CLI tools.
# Exits 1 on first failure with a clear remediation message.
set -euo pipefail

REQUIRED_ENV=""
REQUIRED_TOOLS=""

usage() {
  echo "Usage: $0 [--env \"VAR1 VAR2 ...\"] [--tools \"tool1 tool2 ...\"]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   REQUIRED_ENV="$2";   shift 2 ;;
    --tools) REQUIRED_TOOLS="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

for var in $REQUIRED_ENV; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: $var is not set."
    case "$var" in
      JIRA_USER_EMAIL) echo "  export JIRA_USER_EMAIL=you@redhat.com" ;;
      JIRA_API_TOKEN)  echo "  Generate at: https://id.atlassian.com/manage-profile/security/api-tokens" ;;
      GITLAB_USER)     echo "  export GITLAB_USER=yourusername" ;;
      GITLAB_TOKEN)    echo "  Generate at: https://gitlab.cee.redhat.com/-/profile/personal_access_tokens (api + write_repository scopes)" ;;
      GITHUB_USER)     echo "  export GITHUB_USER=yourusername" ;;
      GITHUB_TOKEN)    echo "  Generate at: https://github.com/settings/tokens (repo + actions:write scopes)" ;;
      OC_TOKEN)        echo "  export OC_TOKEN=<token from Konflux cluster console>" ;;
    esac
    exit 1
  fi
done

for tool in $REQUIRED_TOOLS; do
  if ! command -v "$tool" &>/dev/null; then
    # Special-case kustomize: also check ~/.local/bin
    if [[ "$tool" == "kustomize" && -x "${HOME}/.local/bin/kustomize" ]]; then
      export PATH="${HOME}/.local/bin:${PATH}"
      continue
    fi
    echo "ERROR: '$tool' is not installed or not in PATH."
    case "$tool" in
      uv)       echo "  Install: curl -LsSf https://astral.sh/uv/install.sh | sh" ;;
      oc)       echo "  Install: https://console.redhat.com/openshift/downloads" ;;
      skopeo)   echo "  Install: brew install skopeo  OR  sudo dnf install skopeo" ;;
      yamllint) echo "  Install: pip install yamllint  OR  brew install yamllint" ;;
      jq)       echo "  Install: brew install jq  OR  sudo dnf install jq" ;;
      kustomize) echo "  Install: run install.sh in the skill directory, or see https://kubectl.docs.kubernetes.io/installation/kustomize/" ;;
      git)      echo "  Install: brew install git  OR  sudo dnf install git" ;;
    esac
    exit 1
  fi
done

echo "Prerequisites check passed."
