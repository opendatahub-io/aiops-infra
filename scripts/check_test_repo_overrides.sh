#!/usr/bin/env bash
# Fail closed in isolated repo-test mode unless every repository override points
# to the configured test GitHub organization or personal GitLab namespace.
set -euo pipefail

[[ "${AIOPS_TEST_REPO_MODE:-false}" == "true" ]] || exit 0

TEST_GITHUB_OWNER="${AIOPS_TEST_GITHUB_OWNER:-}"
TEST_GITLAB_NAMESPACE="${AIOPS_TEST_GITLAB_NAMESPACE:-}"
[[ -n "$TEST_GITHUB_OWNER" ]] || { echo "ERROR: AIOPS_TEST_GITHUB_OWNER is required in test mode." >&2; exit 1; }
[[ -n "$TEST_GITLAB_NAMESPACE" ]] || { echo "ERROR: AIOPS_TEST_GITLAB_NAMESPACE is required in test mode." >&2; exit 1; }

REPO_VARS=(
  APP_INTERFACE_REPO_URL
  KONFLUX_RELEASE_DATA_REPO_URL
  PYXIS_REPO_CONFIGS_REPO_URL
  ODH_KONFLUX_CENTRAL_REPO_URL
  RHOAI_KONFLUX_CENTRAL_REPO_URL
  ODH_OPERATOR_REPO_URL
  RHOAI_OPERATOR_REPO_URL
  ODH_BUILD_CONFIG_REPO_URL
  RHOAI_BUILD_CONFIG_REPO_URL
  RHODS_DEVOPS_INFRA_REPO_URL
)

check_repo_url() {
  local name="$1" url="$2"
  case "$url" in
    "https://github.com/${TEST_GITHUB_OWNER}/"*) ;;
    "https://gitlab.cee.redhat.com/${TEST_GITLAB_NAMESPACE}/"*) ;;
    *)
      echo "ERROR: ${name} points outside the test forks: ${url}" >&2
      exit 1
      ;;
  esac
}

for name in "${REPO_VARS[@]}"; do
  value="${!name:-}"
  [[ -n "$value" ]] || { echo "ERROR: ${name} must be explicitly set in test mode." >&2; exit 1; }
  check_repo_url "$name" "$value"
done

for name in BUILD_CONFIG_REPO_URL OBC_REPO_URL; do
  value="${!name:-}"
  [[ -z "$value" ]] || check_repo_url "$name" "$value"
done

while [[ $# -gt 0 ]]; do
  case "$1" in
    --component-repo-url)
      [[ $# -ge 2 ]] || { echo "ERROR: --component-repo-url requires a URL." >&2; exit 1; }
      case "$2" in
        "https://github.com/${TEST_GITHUB_OWNER}/"*) ;;
        *) echo "ERROR: component repo URL is not in the test GitHub org: $2" >&2; exit 1 ;;
      esac
      shift 2
      ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

echo "Test repository overrides verified: GitHub owner=${TEST_GITHUB_OWNER}, GitLab namespace=${TEST_GITLAB_NAMESPACE}."
