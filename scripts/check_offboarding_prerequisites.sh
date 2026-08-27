#!/usr/bin/env bash
# Usage: check_offboarding_prerequisites.sh [--env "VAR1 VAR2"] [--tools "tool1 tool2"] [--vpn] [--oc-login internal|external]
# Exits 0 if all prerequisites are satisfied; exits 1 with a clear message on first failure.
# Exit 2 for --oc-login when interactive login is needed (outputs OC_LOGIN_NEEDED=<cluster>).
set -euo pipefail

ENV_VARS=()
TOOLS=()
CHECK_VPN="false"
OC_LOGIN_CLUSTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)      read -ra ENV_VARS  <<< "$2"; shift 2 ;;
    --tools)    read -ra TOOLS <<< "$2"; shift 2 ;;
    --vpn)      CHECK_VPN="true"; shift ;;
    --oc-login) OC_LOGIN_CLUSTER="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for var in "${ENV_VARS[@]+"${ENV_VARS[@]}"}"; do
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

for tool in "${TOOLS[@]+"${TOOLS[@]}"}"; do
  if ! _tool_ok "$tool"; then
    echo "ERROR: Required tool '$tool' is not installed or not in PATH." >&2
    _install_hint "$tool"
    exit 1
  fi
done

# ── VPN check ──────────────────────────────────────────────────────────────────
if [[ "$CHECK_VPN" == "true" ]]; then
  if curl -sf --connect-timeout 5 --max-time 10 "https://gitlab.cee.redhat.com" -o /dev/null 2>/dev/null; then
    echo "VPN: connected"
  else
    echo "ERROR: VPN does not appear to be active (cannot reach gitlab.cee.redhat.com)." >&2
    echo "  Connect to the Red Hat VPN and re-run." >&2
    exit 1
  fi
fi

# ── OC login check ────────────────────────────────────────────────────────────
if [[ -n "$OC_LOGIN_CLUSTER" ]]; then
  EXTERNAL_API="https://api.stone-prd-rh01.pg1f.p1.openshiftapps.com:6443"
  INTERNAL_API="https://api.stone-prod-p02.hjvn.p1.openshiftapps.com:6443"

  case "$OC_LOGIN_CLUSTER" in
    external) OC_API_SERVER="$EXTERNAL_API"; OC_TOKEN_VAR="EXT_OC_TOKEN" ;;
    internal) OC_API_SERVER="$INTERNAL_API"; OC_TOKEN_VAR="INT_OC_TOKEN" ;;
    *) echo "ERROR: --oc-login must be 'external' or 'internal'." >&2; exit 1 ;;
  esac

  OC_LOGGED_IN="false"

  # Try existing kubeconfig context
  if oc config get-contexts &>/dev/null 2>&1; then
    while IFS= read -r ctx; do
      cluster_server=$(oc config view --minify --context "$ctx" \
        -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null || true)
      cluster_server="${cluster_server%/}"
      if [[ "$cluster_server" == "${OC_API_SERVER%/}" ]]; then
        oc config use-context "$ctx" >/dev/null 2>&1 || true
        if oc whoami &>/dev/null 2>&1; then
          echo "OC: already authenticated as $(oc whoami) on $OC_LOGIN_CLUSTER cluster"
          OC_LOGGED_IN="true"
        fi
        break
      fi
    done < <(oc config get-contexts -o name 2>/dev/null || true)
  fi

  # Try token env var
  if [[ "$OC_LOGGED_IN" == "false" ]] && [[ -n "${!OC_TOKEN_VAR:-}" ]]; then
    if oc login --server="$OC_API_SERVER" --token="${!OC_TOKEN_VAR}" &>/dev/null 2>&1; then
      echo "OC: logged in via $OC_TOKEN_VAR as $(oc whoami) on $OC_LOGIN_CLUSTER cluster"
      OC_LOGGED_IN="true"
    fi
  fi

  if [[ "$OC_LOGGED_IN" == "false" ]]; then
    echo "OC_LOGIN_NEEDED=$OC_LOGIN_CLUSTER"
    echo "OC_API_SERVER=$OC_API_SERVER"
    echo "OC_TOKEN_VAR=$OC_TOKEN_VAR"
    exit 2
  fi
fi

echo "Prerequisites OK"
