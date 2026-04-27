#!/usr/bin/env bash
# Validates optional Jira URL, resolves OKC repo URL and workflow constants.
# Outputs KEY=VALUE lines for eval in the caller. Diagnostics go to stderr.
set -euo pipefail

JIRA_URL="${1:-}"

if [[ -n "$JIRA_URL" && "$JIRA_URL" != *"/browse/"* ]]; then
  echo "ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHODS-14226" >&2
  exit 1
fi

JIRA_ID=""
if [[ -n "$JIRA_URL" ]]; then
  JIRA_ID="${JIRA_URL##*/}"
fi

OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
echo "ODH_KONFLUX_CENTRAL_REPO_URL=${ODH_KONFLUX_CENTRAL_REPO_URL:-(not set, using default)}" >&2
echo "OKC_URL resolved to: $OKC_URL" >&2

OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
OKC_REF="main"
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"

echo "JIRA_URL=${JIRA_URL}"
echo "JIRA_ID=${JIRA_ID}"
echo "OKC_URL=${OKC_URL}"
echo "OKC_PATH=${OKC_PATH}"
echo "OKC_REF=${OKC_REF}"
echo "WORKFLOW_FILE=${WORKFLOW_FILE}"
