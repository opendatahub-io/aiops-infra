#!/usr/bin/env bash
# verify_pr_build.sh — Verify the RHOAI Konflux pull-request build on P01.
#
# Creates a temporary "DO NOT MERGE" PR in the component repository, waits for
# the P01 pull-request PipelineRun to appear in KubeArchive, verifies it
# succeeded, and then closes the PR and deletes its branch. On timeout the PR is
# left open (and recorded in the workdir) so a retry can continue polling the
# same build instead of creating another PR.
#
# Called by verify_build.sh for RHOAI components only.
#
# Environment:
#   GITHUB_TOKEN        — required; token used to create/close the temporary PR.
#   P01_OC_TOKEN        — required when no matching P01 kubeconfig context exists.
#   PR_BUILD_TIMEOUT    — optional; seconds to wait for the PR build (default 1800).
#   PR_BUILD_INTERVAL   — optional; seconds between polls (default 30).
#   TEKTON_SYNC_TIMEOUT — optional; seconds to wait for the PR PipelineRun file
#                         to sync to the component repository (default 900).
#
# Exit codes:
#   0  Pull-request build verified (succeeded)
#   1  Build not found, still running, or failed
set -euo pipefail

# Append rather than prepend so callers and tests that provide their own `uv`
# (for example a mock) keep precedence; `~/.local/bin` only needs to supply it
# when it is not already on PATH.
export PATH="${PATH}:${HOME}/.local/bin"

info()  { echo "[INFO]  $*" >&2; }
error() { echo "[ERROR] $*" >&2; }
die()   { error "$*"; exit 1; }

JIRA_URL=""
COMPONENT_NAME=""
VERSION_VAR=""
REPO_URL=""
REPO_BRANCH=""
WORKDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url)       JIRA_URL="$2";       shift 2 ;;
    --component-name) COMPONENT_NAME="$2"; shift 2 ;;
    --version-var)    VERSION_VAR="$2";    shift 2 ;;
    --repo-url)       REPO_URL="$2";       shift 2 ;;
    --repo-branch)    REPO_BRANCH="$2";    shift 2 ;;
    --workdir)        WORKDIR="$2";        shift 2 ;;
    *) echo "ERROR: Unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$COMPONENT_NAME" ]] && die "--component-name is required"
[[ -z "$VERSION_VAR" ]]    && die "--version-var is required"
[[ -z "$REPO_URL" ]]       && die "--repo-url is required"

JIRA_ID="${JIRA_URL%/}"; JIRA_ID="${JIRA_ID##*/}"
[[ -z "$JIRA_ID" ]] && die "--jira-url is required"
WORKDIR="${WORKDIR:-$(pwd)/${JIRA_ID}}"
mkdir -p "$WORKDIR"

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${WORKDIR}/pr_build_verify.json"
KONFLUX_COMPONENT="${COMPONENT_NAME}-${VERSION_VAR}"
NAMESPACE="rhoai-tenant"
EXPECTED_API="https://api.stone-prod-p01.wcfb.p1.openshiftapps.com:6443"
KONFLUX_UI="https://konflux-ui.apps.stone-prod-p01.wcfb.p1.openshiftapps.com"
PIPELINE_FILE=".tekton/${COMPONENT_NAME}-pull-request.yaml"

PR_BUILD_TIMEOUT="${PR_BUILD_TIMEOUT:-1800}"
PR_BUILD_INTERVAL="${PR_BUILD_INTERVAL:-30}"
TEKTON_SYNC_TIMEOUT="${TEKTON_SYNC_TIMEOUT:-900}"

if [[ "${ONBOARD_DRY_RUN:-false}" == "true" ]]; then
  echo "ONBOARD_DRY_RUN=true — skipping pull-request build verification."
  exit 0
fi

[[ -z "${GITHUB_TOKEN:-}" ]] && die "GITHUB_TOKEN is required to create the temporary verification PR."

if [[ "$REPO_URL" =~ ^https://github\.com/([^/]+)/([^/]+?)(\.git)?$ ]]; then
  GITHUB_REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
else
  die "Unsupported repo URL '${REPO_URL}'. Expected https://github.com/<owner>/<repo>."
fi
GITHUB_API="https://api.github.com/repos/${GITHUB_REPO}"

# ── GitHub helpers ────────────────────────────────────────────────────────────
github_api() {
  curl -sS --max-time 60 \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$@"
}

github_api_code() {
  curl -sS --max-time 60 -o /dev/null -w '%{http_code}' \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "$@"
}

check_api_error() {
  local body="$1" context="$2" message
  message=$(echo "$body" | jq -r '.message // empty' 2>/dev/null || true)
  [[ -z "$message" ]] || die "GitHub API error while ${context}: ${message}"
}

jira_comment() {
  [[ -n "$JIRA_URL" ]] || return 0
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --comment "$1" >/dev/null 2>&1 || true
}

# ── P01 login and KubeArchive endpoint ────────────────────────────────────────
CURRENT_SERVER=$(oc whoami --show-server 2>/dev/null || echo "")
if [[ "${CURRENT_SERVER%/}" != "${EXPECTED_API%/}" ]]; then
  info "Logging in to the P01 Konflux cluster..."
  bash "$SCRIPTS_DIR/login_to_konflux_cluster.sh" p01 || \
    die "Could not log in to the P01 cluster. Set P01_OC_TOKEN."
fi

OC_TOKEN=$(oc whoami --show-token 2>/dev/null || echo "")
OC_SERVER=$(oc whoami --show-server 2>/dev/null || echo "")
[[ -z "$OC_TOKEN" ]] && die "No P01 oc token — cannot verify the pull-request build."

CLUSTER_SUFFIX=$(echo "$OC_SERVER" | sed 's|https://api||;s|:[0-9]*$||')
KUBEARCHIVE_BASE="https://kubearchive-api-server-product-kubearchive.apps${CLUSTER_SUFFIX}"
echo "KubeArchive : ${KUBEARCHIVE_BASE}" >&2

# ── Resolve the base branch and wait for the PR PipelineRun to sync ───────────
info "Resolving ${GITHUB_REPO} default branch..."
REPO_JSON=$(github_api "$GITHUB_API")
check_api_error "$REPO_JSON" "reading repository metadata"
DEFAULT_BRANCH=$(echo "$REPO_JSON" | jq -r '.default_branch // empty')
[[ -z "$DEFAULT_BRANCH" ]] && die "Could not determine the default branch for ${GITHUB_REPO}."

BASE_BRANCH="${REPO_BRANCH:-$DEFAULT_BRANCH}"
BASE_BRANCH="${BASE_BRANCH%\"}"; BASE_BRANCH="${BASE_BRANCH#\"}"
BASE_BRANCH="${BASE_BRANCH:-$DEFAULT_BRANCH}"

pipeline_file_exists() {
  local branch="$1" code
  code=$(github_api_code "${GITHUB_API}/contents/${PIPELINE_FILE}?ref=${branch}")
  [[ "$code" == "200" ]]
}

if ! pipeline_file_exists "$BASE_BRANCH"; then
  if pipeline_file_exists "main"; then
    info "PR PipelineRun not found on '${BASE_BRANCH}'; using 'main'."
    BASE_BRANCH="main"
  else
    info "Waiting for '${PIPELINE_FILE}' to sync to '${BASE_BRANCH}' or 'main'..."
    SYNC_DEADLINE=$((SECONDS + TEKTON_SYNC_TIMEOUT))
    while ! pipeline_file_exists "$BASE_BRANCH" && ! pipeline_file_exists "main"; do
      if (( SECONDS >= SYNC_DEADLINE )); then
        die "Timed out waiting for '${PIPELINE_FILE}' to appear in ${GITHUB_REPO}. The konflux-central sync may not have run yet."
      fi
      sleep 15
    done
    pipeline_file_exists "$BASE_BRANCH" || BASE_BRANCH="main"
  fi
fi
info "Using base branch '${BASE_BRANCH}' for the verification PR."

# ── Reuse or create the temporary PR ──────────────────────────────────────────
TITLE_PREFIX="DO NOT MERGE: Konflux pull-request build verification for ${JIRA_ID}"
PR_NUMBER=""
PR_URL=""
BRANCH=""

close_stale_verification_prs() {
  local open_prs
  open_prs=$(github_api "${GITHUB_API}/pulls?state=open&per_page=100") || return 0
  while IFS=$'\t' read -r num ref; do
    [[ -z "$num" || "$num" == "null" ]] && continue
    info "Closing stale verification PR #${num} (${ref})..."
    github_api -X PATCH "${GITHUB_API}/pulls/${num}" -d '{"state":"closed"}' >/dev/null 2>&1 || true
    github_api -X DELETE "${GITHUB_API}/git/refs/heads/${ref}" >/dev/null 2>&1 || true
  done < <(echo "$open_prs" | jq -r --arg prefix "$TITLE_PREFIX" \
    '.[] | select((.title // "") | startswith($prefix)) | "\(.number)\t\(.head.ref)"')
}

if [[ -f "$STATE_FILE" ]]; then
  PR_NUMBER=$(jq -r '.pr_number // empty' "$STATE_FILE" 2>/dev/null || true)
  BRANCH=$(jq -r '.branch // empty' "$STATE_FILE" 2>/dev/null || true)
  SAVED_BASE=$(jq -r '.base_branch // empty' "$STATE_FILE" 2>/dev/null || true)
  if [[ -n "$PR_NUMBER" ]]; then
    PR_JSON=$(github_api "${GITHUB_API}/pulls/${PR_NUMBER}") || PR_JSON=""
    PR_STATE=$(echo "$PR_JSON" | jq -r '.state // empty' 2>/dev/null || true)
    if [[ "$PR_STATE" == "open" ]]; then
      PR_URL=$(echo "$PR_JSON" | jq -r '.html_url // empty')
      [[ -n "$SAVED_BASE" ]] && BASE_BRANCH="$SAVED_BASE"
      info "Reusing existing verification PR #${PR_NUMBER}: ${PR_URL}"
    else
      info "Previous verification PR #${PR_NUMBER} is no longer open; creating a new one."
      rm -f "$STATE_FILE"
      PR_NUMBER=""; PR_URL=""; BRANCH=""
    fi
  fi
fi

if [[ -z "$PR_NUMBER" ]]; then
  close_stale_verification_prs

  BASE_SHA=$(github_api "${GITHUB_API}/git/ref/heads/${BASE_BRANCH}" | jq -r '.object.sha // empty')
  [[ -z "$BASE_SHA" ]] && die "Could not resolve '${BASE_BRANCH}' in ${GITHUB_REPO}."

  BRANCH="${JIRA_ID}-pr-build-verify-$(date -u +%Y%m%d%H%M%S)"
  info "Creating branch ${BRANCH} from ${BASE_BRANCH}..."
  RESP=$(github_api -X POST "${GITHUB_API}/git/refs" \
    -d "$(jq -n --arg ref "refs/heads/${BRANCH}" --arg sha "$BASE_SHA" '{ref:$ref,sha:$sha}')")
  check_api_error "$RESP" "creating branch ${BRANCH}"

  FILE_PATH=".onboarding-build-verify/${JIRA_ID}.txt"
  CONTENT="Automated pull-request build verification for ${JIRA_ID}. Do not merge."
  CONTENT_B64=$(printf '%s\n' "$CONTENT" | base64 | tr -d '\n')
  info "Adding ${FILE_PATH}..."
  RESP=$(github_api -X PUT "${GITHUB_API}/contents/${FILE_PATH}" \
    -d "$(jq -n \
      --arg message "Add temporary build verification marker for ${JIRA_ID} [skip ci]" \
      --arg content "$CONTENT_B64" \
      --arg branch "$BRANCH" \
      '{message:$message,content:$content,branch:$branch}')")
  check_api_error "$RESP" "adding ${FILE_PATH}"

  PR_BODY="Automated onboarding verification PR. It triggers the Konflux pull-request build on P01 and is closed automatically. Do not merge.

Jira: ${JIRA_URL}"
  info "Opening verification PR..."
  RESP=$(github_api -X POST "${GITHUB_API}/pulls" \
    -d "$(jq -n \
      --arg title "$TITLE_PREFIX" \
      --arg head "$BRANCH" \
      --arg base "$BASE_BRANCH" \
      --arg body "$PR_BODY" \
      '{title:$title,head:$head,base:$base,body:$body}')")
  check_api_error "$RESP" "opening verification PR"

  PR_NUMBER=$(echo "$RESP" | jq -r '.number // empty')
  PR_URL=$(echo "$RESP" | jq -r '.html_url // empty')
  [[ -z "$PR_NUMBER" ]] && die "GitHub did not return a PR number."

  jq -n \
    --argjson pr_number "$PR_NUMBER" \
    --arg pr_url "$PR_URL" \
    --arg branch "$BRANCH" \
    --arg base_branch "$BASE_BRANCH" \
    --arg created_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{pr_number:$pr_number,pr_url:$pr_url,branch:$branch,base_branch:$base_branch,created_at:$created_at}' \
    > "$STATE_FILE"

  jira_comment "[step:bundle] Created a temporary PR to verify the Konflux pull-request build on P01.

PR: ${PR_URL}
Component: ${KONFLUX_COMPONENT}
Base branch: ${BASE_BRANCH}"
fi

echo "Verification PR: ${PR_URL}"

# ── Wait for the P01 pull-request build ───────────────────────────────────────
LABEL="appstudio.openshift.io/component=${KONFLUX_COMPONENT},pipelinesascode.tekton.dev/event-type in (pull_request,issue_comment)"
LABEL_ENC=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$LABEL")
KUBEARCHIVE_URL="${KUBEARCHIVE_BASE}/apis/tekton.dev/v1/namespaces/${NAMESPACE}/pipelineruns?labelSelector=${LABEL_ENC}&limit=20"

cleanup() {
  if [[ -n "${PR_NUMBER:-}" ]]; then
    info "Closing verification PR #${PR_NUMBER}..."
    github_api -X PATCH "${GITHUB_API}/pulls/${PR_NUMBER}" \
      -d '{"state":"closed"}' >/dev/null 2>&1 || true
  fi
  if [[ -n "${BRANCH:-}" ]]; then
    info "Deleting verification branch ${BRANCH}..."
    github_api -X DELETE "${GITHUB_API}/git/refs/heads/${BRANCH}" >/dev/null 2>&1 || true
  fi
  rm -f "$STATE_FILE"
}

info "Waiting up to ${PR_BUILD_TIMEOUT}s for the pull-request build..."
DEADLINE=$((SECONDS + PR_BUILD_TIMEOUT))
LAST_STATUS="not found"
while :; do
  RESP=$(curl -sk --max-time 60 -w '%{http_code}' -o /dev/stdout \
    -H "Authorization: Bearer $OC_TOKEN" \
    -H "Accept: application/json" \
    "$KUBEARCHIVE_URL" 2>/dev/null) || RESP=""
  HTTP_CODE="${RESP: -3}"
  BODY="${RESP:0:${#RESP}-3}"

  if [[ "$HTTP_CODE" == "200" ]]; then
    LATEST=$(echo "$BODY" | jq -c --arg pr "$PR_NUMBER" '
      .items
      | map(select(
          (.metadata.annotations["build.appstudio.redhat.com/pull_request_number"] // "") == $pr
          or ((.metadata.name // "") | endswith("-on-pull-request-" + $pr))
        ))
      | sort_by(.metadata.creationTimestamp)
      | last // empty
    ' 2>/dev/null || echo "")

    if [[ -n "$LATEST" ]]; then
      PR_NAME=$(echo "$LATEST" | jq -r '.metadata.name // empty')
      APP_LABEL=$(echo "$LATEST" | jq -r '.metadata.labels["appstudio.openshift.io/application"] // empty')
      SUCCEEDED=$(echo "$LATEST" | jq -r '[.status.conditions[]? | select(.type=="Succeeded") | .status][0] // "Unknown"')
      REASON=$(echo "$LATEST" | jq -r '[.status.conditions[]? | select(.type=="Succeeded") | .reason][0] // ""')
      BUILD_URL="${KONFLUX_UI}/ns/${NAMESPACE}/applications/${APP_LABEL:-unknown}/pipelineruns/${PR_NAME}"

      echo "PipelineRun : ${PR_NAME}"
      echo "Status      : Succeeded=${SUCCEEDED}  Reason=${REASON:-none}"
      echo "Build URL   : ${BUILD_URL}"

      if [[ "$SUCCEEDED" == "True" ]]; then
        jira_comment "[step:bundle] Konflux pull-request build verified for '${COMPONENT_NAME}' on P01.

PipelineRun: ${PR_NAME}
Build URL: ${BUILD_URL}
Verification PR (closed automatically): ${PR_URL}"
        cleanup
        echo "Pull-request build verified: ${PR_NAME}"
        exit 0
      elif [[ "$SUCCEEDED" == "False" ]]; then
        jira_comment "[step:bundle] Blocked — Konflux pull-request build FAILED on P01.

PipelineRun: ${PR_NAME}
Build URL: ${BUILD_URL}
Reason: ${REASON:-unknown}

Fix the build failure and re-run."
        cleanup
        error "Pull-request build FAILED (${REASON:-unknown})."
        error "  Build URL: ${BUILD_URL}"
        exit 1
      else
        LAST_STATUS="running"
      fi
    else
      LAST_STATUS="not found"
    fi
  else
    LAST_STATUS="KubeArchive HTTP ${HTTP_CODE:-error}"
  fi

  if (( SECONDS >= DEADLINE )); then
    jira_comment "[step:bundle] Timed out waiting for the Konflux pull-request build on P01.

Component: ${KONFLUX_COMPONENT}
Verification PR (left open for retry): ${PR_URL}

The next run will reuse this PR and keep polling."
    error "Timed out waiting for the pull-request build (${LAST_STATUS})."
    error "  Verification PR left open for retry: ${PR_URL}"
    exit 1
  fi

  info "Pull-request build ${LAST_STATUS}; polling again in ${PR_BUILD_INTERVAL}s..."
  sleep "$PR_BUILD_INTERVAL"
done
