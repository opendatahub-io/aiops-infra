#!/usr/bin/env bash
# Derive workflow inputs, launch deferred_workflow.sh via nohup, update pipeline_state.json.
#
# Usage:
#   bash launch_deferred_workflow.sh \
#     --workdir <dir> --jira-url <url> --scripts-dir <dir> \
#     --repo-url <url> --repo-branch <branch> \
#     [--build-type <CI|CD>] [--okc-url <https://...>]
#
# The pipeline_state.json is derived from --workdir/pipeline_state.json.
# ODH_KONFLUX_CENTRAL_REPO_URL env var is honoured as the default for --okc-url.

set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
REPO_URL=""
REPO_BRANCH=""
BUILD_TYPE=""
OKC_URL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)      WORKDIR="$2";      shift 2 ;;
    --jira-url)     JIRA_URL="$2";     shift 2 ;;
    --scripts-dir)  SCRIPTS_DIR="$2";  shift 2 ;;
    --repo-url)     REPO_URL="$2";     shift 2 ;;
    --repo-branch)  REPO_BRANCH="$2";  shift 2 ;;
    --build-type)   BUILD_TYPE="$2";   shift 2 ;;
    --okc-url)      OKC_URL="$2";      shift 2 ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

for _arg in WORKDIR JIRA_URL SCRIPTS_DIR REPO_URL REPO_BRANCH; do
  [[ -z "${!_arg}" ]] && {
    echo "ERROR: --$(echo "$_arg" | tr '[:upper:]' '[:lower:]') is required" >&2; exit 1
  }
done

PIPELINE_STATE="$WORKDIR/pipeline_state.json"

# Derive REPO_NAME from URL
REPO_NAME="${REPO_URL##*/}"; REPO_NAME="${REPO_NAME%.git}"

# Resolve BUILD_TYPE (arg > YAML field > default "CI")
if [[ -z "$BUILD_TYPE" ]]; then
  BUILD_TYPE=$(grep -m1 'build_type:' "$WORKDIR/component_onboarding_details.yaml" \
    | awk '{print $2}' 2>/dev/null || echo "")
  [[ -z "$BUILD_TYPE" ]] && BUILD_TYPE="CI"
fi

# Resolve OKC_URL (arg > env var > hardcoded default)
OKC_URL="${OKC_URL:-${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}}"
OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"

echo "[launch_deferred_workflow] REPO_NAME    : $REPO_NAME"
echo "[launch_deferred_workflow] BUILD_TYPE   : $BUILD_TYPE"
echo "[launch_deferred_workflow] OKC_URL      : $OKC_URL"
echo "[launch_deferred_workflow] WORKFLOW_FILE: $WORKFLOW_FILE"

nohup bash "$SCRIPTS_DIR/deferred_workflow.sh" \
  --workdir       "$WORKDIR" \
  --jira-url      "$JIRA_URL" \
  --scripts-dir   "$SCRIPTS_DIR" \
  --okc-url       "$OKC_URL" \
  --okc-path      "$OKC_PATH" \
  --workflow-file "$WORKFLOW_FILE" \
  --repo-name     "$REPO_NAME" \
  --repo-branch   "$REPO_BRANCH" \
  --build-type    "$BUILD_TYPE" \
  >> "$WORKDIR/deferred_workflow.log" 2>&1 &
echo $! > "$WORKDIR/deferred_workflow.pid"

echo "[WRAPPER] Deferred workflow trigger started (PID=$(cat "$WORKDIR/deferred_workflow.pid"))"
echo "[WRAPPER] Log: $WORKDIR/deferred_workflow.log"

bash "$SCRIPTS_DIR/pipeline_state.sh" set \
  --state "$PIPELINE_STATE" --step onboarder --field status --value "pending_krd_okc_merge"
