#!/usr/bin/env bash
# Main script for the onboard-konflux-components-for-odh-and-rhoai skill.
# Parent orchestrator: runs all child onboarding scripts sequentially with
# pipeline_state.json idempotency tracking.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Step 0: Parse Inputs ---
JIRA_URL="${1:-}"
if [[ -z "$JIRA_URL" ]]; then
  echo "ERROR: Jira URL is required." >&2
  echo "  Usage: $(basename "$0") <jira-url>" >&2
  exit 1
fi
if [[ "$JIRA_URL" != *"/browse/"* ]]; then
  echo "ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

# --- Step 1: Check Prerequisites ---
bash "$SCRIPTS_DIR/check_prerequisites.sh" \
  --env   "JIRA_USER_EMAIL JIRA_API_TOKEN GITLAB_USER GITLAB_TOKEN GITHUB_USER GITHUB_TOKEN" \
  --tools "uv git oc skopeo yamllint jq kustomize"

# --- Step 2: Set Up Working Directory and Initialize State ---
eval "$(bash "$SCRIPTS_DIR/init_pipeline.sh" --jira-url "$JIRA_URL")"
PIPELINE_STATE="$WORKDIR/pipeline_state.json"
echo "Jira ID  : $JIRA_ID"
echo "Jira URL : $JIRA_URL"
echo "Working directory: $WORKDIR"

# Helper: read a step status from pipeline_state.json
_state_get() {
  jq -r ".steps.${1}.status // \"pending\"" "$PIPELINE_STATE" 2>/dev/null || echo "pending"
}

# Helper: set a step field in pipeline_state.json
_state_set() {
  local step="$1" field="$2" value="$3"
  jq ".steps.${step}.${field} = \"${value}\"" "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" \
    && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
}

# --- Step 3: validate-component-onboarding-jira ---
if [[ "$(_state_get validate)" != "done" ]]; then
  echo ""
  echo "=== Step 3: validate-component-onboarding-jira ==="
  bash "$SCRIPTS_DIR/run_validate_component_onboarding_jira.sh" "$JIRA_URL" || {
    echo "ERROR in Step 3: validate-component-onboarding-jira failed. Aborting." >&2
    exit 1
  }
  _state_set validate status done
else
  echo "Step 3 (validate): already done — skipping."
fi

# --- Step 4: Parse Component Details ---
COMPONENT_NAME=""
PRODUCT_CONTEXT=""
IS_OPERATOR=""
QUAY_REPO_URI=""
QUAY_VISIBILITY=""
REPO_URL=""
REPO_BRANCH=""

if [[ -z "$(jq -r '.component_name // empty' "$PIPELINE_STATE" 2>/dev/null)" ]]; then
  eval "$(bash "$SCRIPTS_DIR/parse_component_details.sh" \
    --workdir "$WORKDIR" \
    --jira-id "$JIRA_ID")"
else
  COMPONENT_NAME=$(jq -r '.component_name' "$PIPELINE_STATE")
  PRODUCT_CONTEXT=$(jq -r '.product_context' "$PIPELINE_STATE")
  IS_OPERATOR=$(jq -r '.is_operator' "$PIPELINE_STATE")
  QUAY_REPO_URI=$(jq -r '.quay_repo_uri' "$PIPELINE_STATE")
  QUAY_VISIBILITY=$(jq -r '.quay_visibility' "$PIPELINE_STATE")
  REPO_URL=$(jq -r '.repo_url' "$PIPELINE_STATE")
  REPO_BRANCH=$(jq -r '.repo_branch' "$PIPELINE_STATE")
fi

if [[ "${PRODUCT_CONTEXT:-}" == "UNKNOWN" ]]; then
  while true; do
    printf "Could not determine product context. Is this component for ODH or RHOAI? (ODH/RHOAI): "
    read -r PRODUCT_CONTEXT
    PRODUCT_CONTEXT="${PRODUCT_CONTEXT^^}"
    case "$PRODUCT_CONTEXT" in
      ODH|RHOAI) break ;;
      *) echo "  Invalid. Must be ODH or RHOAI." ;;
    esac
  done
  jq ".product_context = \"${PRODUCT_CONTEXT}\"" "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" \
    && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
fi

echo ""
echo "Component : $COMPONENT_NAME"
echo "Product   : $PRODUCT_CONTEXT"
echo "Quay repo : $QUAY_REPO_URI ($QUAY_VISIBILITY)"
echo "Operator  : $IS_OPERATOR"

# --- Step 5: create-quay-repo ---
_quay_status="$(_state_get quay)"
if [[ "$_quay_status" != "merged" && "$_quay_status" != "done" && "$_quay_status" != "skipped" ]]; then
  echo ""
  echo "=== Step 5: create-quay-repo ==="

  # Derive sparse file from org
  _QUAY_ORG="${QUAY_REPO_URI#quay.io/}"
  _QUAY_ORG="${_QUAY_ORG%%/*}"
  case "$_QUAY_ORG" in
    opendatahub) _QUAY_SPARSE="data/services/rhoai/quay/opendatahub.yml" ;;
    rhoai)       _QUAY_SPARSE="data/services/rhoai/quay/rhoai.yml" ;;
    modh)        _QUAY_SPARSE="data/services/rhoai/quay/modh.yml" ;;
    *)           _QUAY_SPARSE="" ;;
  esac

  _SPARSE_FLAG=""
  [[ -n "$_QUAY_SPARSE" ]] && _SPARSE_FLAG="--sparse-file $_QUAY_SPARSE"

  bash "$SCRIPTS_DIR/run_create_quay_repo.sh" \
    "$QUAY_REPO_URI" \
    --jira-url "$JIRA_URL" \
    --visibility "$QUAY_VISIBILITY" \
    --workdir "$WORKDIR" \
    ${_SPARSE_FLAG:+$_SPARSE_FLAG} || {
    echo "ERROR in Step 5: create-quay-repo failed. Aborting." >&2
    exit 1
  }

  QUAY_MR=$(cat "$WORKDIR/quay_mr_url" 2>/dev/null || echo "N/A")
  _state_set quay status merged
  _state_set quay mr_url "$QUAY_MR"
else
  QUAY_MR=$(jq -r '.steps.quay.mr_url // "N/A"' "$PIPELINE_STATE")
  echo "Step 5 (create-quay-repo): already done — skipping."
fi

# --- Step 6: onboard-component-to-konflux-release-data ---
_krd_status="$(_state_get krd)"
if [[ "$_krd_status" != "merged" && "$_krd_status" != "done" && "$_krd_status" != "skipped" ]]; then
  echo ""
  echo "=== Step 6: onboard-component-to-konflux-release-data ==="
  bash "$SCRIPTS_DIR/run_onboard_component_to_konflux_release_data.sh" "$JIRA_URL" \
    --workdir "$WORKDIR" || {
    echo "ERROR in Step 6: onboard-component-to-konflux-release-data failed. Aborting." >&2
    exit 1
  }
  KRD_MR=$(cat "$WORKDIR/krd_mr_url" 2>/dev/null || echo "N/A")
  _state_set krd status merged
  _state_set krd mr_url "$KRD_MR"
else
  KRD_MR=$(jq -r '.steps.krd.mr_url // "N/A"' "$PIPELINE_STATE")
  echo "Step 6 (krd): already done — skipping."
fi

# --- Step 7: add-component-to-odh-konflux-central (ODH) ---
OKC_PR="N/A"
_okc_status="$(_state_get okc)"
if [[ "$_okc_status" != "merged" && "$_okc_status" != "done" && "$_okc_status" != "skipped" ]]; then
  echo ""
  if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
    echo "=== Step 7: add-component-to-odh-konflux-central ==="
    bash "$SCRIPTS_DIR/run_add_component_to_odh_konflux_central.sh" "$JIRA_URL" \
      --workdir "$WORKDIR" || {
      echo "ERROR in Step 7: add-component-to-odh-konflux-central failed. Aborting." >&2
      exit 1
    }
    OKC_PR=$(cat "$WORKDIR/okc_pr_url" 2>/dev/null || echo "N/A")
    _state_set okc status merged
    _state_set okc pr_url "$OKC_PR"
  else
    echo "Step 7 (add-component-to-rhoai-konflux-central): RHOAI — run_add_component_to_rhoai_konflux_central.sh (not yet implemented as script; run child skill manually)"
    echo "  Update pipeline_state.json manually when done: jq '.steps.okc.status = \"merged\"' $PIPELINE_STATE > $PIPELINE_STATE.tmp && mv $PIPELINE_STATE.tmp $PIPELINE_STATE"
    _state_set okc status pending_manual
  fi
else
  OKC_PR=$(jq -r '.steps.okc.pr_url // "N/A"' "$PIPELINE_STATE")
  echo "Step 7 (okc): already done — skipping."
fi

# --- Step 8: integrate-component-with-odh-operator ---
OP_PR="N/A"
_op_status="$(_state_get operator)"
if [[ "$_op_status" != "merged" && "$_op_status" != "done" && "$_op_status" != "skipped" ]]; then
  echo ""
  echo "=== Step 8: integrate-component-with-odh-operator ==="
  bash "$SCRIPTS_DIR/run_integrate_component_with_odh_operator.sh" "$JIRA_URL" \
    --workdir "$WORKDIR" || {
    echo "ERROR in Step 8: integrate-component-with-odh-operator failed. Aborting." >&2
    exit 1
  }
  if [[ "${IS_OPERATOR,,}" == "true" ]]; then
    OP_PR=$(cat "$WORKDIR/operator_pr_url" 2>/dev/null || echo "N/A")
    _state_set operator status pr_raised
    _state_set operator pr_url "$OP_PR"
  else
    _state_set operator status skipped
  fi
else
  OP_PR=$(jq -r '.steps.operator.pr_url // "N/A"' "$PIPELINE_STATE")
  echo "Step 8 (operator): already done — skipping."
fi

# --- Step 9: integrate-component-with-bundle ---
BDLPR="N/A"
_bdl_status="$(_state_get bundle)"
if [[ "$_bdl_status" != "merged" && "$_bdl_status" != "done" && "$_bdl_status" != "skipped" ]]; then
  echo ""
  echo "=== Step 9: integrate-component-with-bundle ==="
  bash "$SCRIPTS_DIR/run_integrate_component_with_bundle.sh" "$JIRA_URL" \
    --workdir "$WORKDIR" || {
    echo "ERROR in Step 9: integrate-component-with-bundle failed. Aborting." >&2
    exit 1
  }
  BDLPR=$(cat "$WORKDIR/bundle_pr_url" 2>/dev/null || echo "N/A")
  _state_set bundle status pr_raised
  _state_set bundle pr_url "$BDLPR"
else
  BDLPR=$(jq -r '.steps.bundle.pr_url // "N/A"' "$PIPELINE_STATE")
  echo "Step 9 (bundle): already done — skipping."
fi

# --- Steps 10–13: RHOAI-only steps ---
LABELS_PR="N/A"
DELIV_MR="N/A"
AM_PR="N/A"
RENOV_PR="N/A"

if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  echo ""
  echo "=== RHOAI-only steps (10–13) ==="
  echo "  These require additional child skills (add-rhoai-dockerfile-labels, create-rhoai-delivery-repo,"
  echo "  setup-auto-merge, enable-renovate-on-rhoai-component-repo) that are not yet scripted."
  echo "  Run each child skill manually and update pipeline_state.json."
  LABELS_PR=$(jq -r '.steps.dockerfile_labels.pr_url // "N/A"' "$PIPELINE_STATE")
  DELIV_MR=$(jq -r '.steps.delivery_repo.mr_url // "N/A"' "$PIPELINE_STATE")
  AM_PR=$(jq -r '.steps.auto_merge.pr_url // "N/A"' "$PIPELINE_STATE")
  RENOV_PR=$(jq -r '.steps.renovate.pr_url // "N/A"' "$PIPELINE_STATE")
fi

# --- Step 14: Launch Deferred Workflow Trigger (ODH only) ---
_wf_status="$(_state_get onboarder)"
if [[ "${PRODUCT_CONTEXT^^}" == "ODH" && "$_wf_status" == "pending" ]]; then
  echo ""
  echo "=== Step 14: Deferred workflow trigger (ODH) ==="

  REPO_NAME="${REPO_URL##*/}"
  REPO_NAME="${REPO_NAME%.git}"
  BUILD_TYPE=$(python3 -c "
import yaml
with open('$WORKDIR/component_onboarding_details.yaml') as f:
    d = yaml.safe_load(f)
print(d.get('inputs', {}).get('build_type', 'CI') or 'CI')
" 2>/dev/null || echo "CI")
  [[ -z "$BUILD_TYPE" ]] && BUILD_TYPE="CI"

  OKC_URL="${ODH_KONFLUX_CENTRAL_REPO_URL:-https://github.com/opendatahub-io/odh-konflux-central.git}"
  OKC_PATH=$(echo "$OKC_URL" | sed 's|https://github.com/||;s|\.git$||')
  WORKFLOW_FILE=".github/workflows/odh-konflux-onboarder.yml"

  nohup bash "$SCRIPTS_DIR/deferred_workflow.sh" \
    --workdir       "$WORKDIR"      \
    --jira-url      "$JIRA_URL"     \
    --scripts-dir   "$SCRIPTS_DIR"  \
    --okc-url       "$OKC_URL"      \
    --okc-path      "$OKC_PATH"     \
    --workflow-file "$WORKFLOW_FILE" \
    --repo-name     "$REPO_NAME"    \
    --repo-branch   "$REPO_BRANCH"  \
    --build-type    "$BUILD_TYPE"   \
    >> "$WORKDIR/deferred_workflow.log" 2>&1 &
  echo $! > "$WORKDIR/deferred_workflow.pid"
  echo "[WRAPPER] Deferred workflow trigger started (PID=$(cat "$WORKDIR/deferred_workflow.pid"))"
  echo "[WRAPPER] Log: $WORKDIR/deferred_workflow.log"

  _state_set onboarder status pending_krd_okc_merge
fi

# --- Step 15: Transition Jira to "Review" ---
echo ""
echo "=== Step 15: Raising Jira review ==="
bash "$SCRIPTS_DIR/raise_jira_review.sh" \
  --workdir     "$WORKDIR"   \
  --jira-url    "$JIRA_URL"  \
  --scripts-dir "$SCRIPTS_DIR"

# --- Step 16: Launch Final Completion Monitor ---
echo ""
echo "=== Step 16: Launching completion monitor ==="
nohup bash "$SCRIPTS_DIR/monitor_completion.sh" \
  --workdir     "$WORKDIR"   \
  --jira-url    "$JIRA_URL"  \
  --scripts-dir "$SCRIPTS_DIR" \
  >> "$WORKDIR/monitor_completion.log" 2>&1 &
echo $! > "$WORKDIR/monitor_completion.pid"
echo "[WRAPPER] Completion monitor started (PID=$(cat "$WORKDIR/monitor_completion.pid"))"
echo "[WRAPPER] Log: $WORKDIR/monitor_completion.log"

# --- Step 17: Print Final Summary ---
echo ""
echo "=== onboard-konflux-components-for-odh-and-rhoai — Phase 1 Complete ==="
echo ""
echo "  Component      : $COMPONENT_NAME"
echo "  Product        : $PRODUCT_CONTEXT"
echo "  Jira           : $JIRA_URL (status: Review)"
echo ""
echo "PRs / MRs raised:"
echo "  Step 2 Quay MR           : $QUAY_MR"
echo "  Step 3 KRD MR            : $KRD_MR"
echo "  Step 4 OKC/RKC PR        : $OKC_PR"
if [[ "${PRODUCT_CONTEXT^^}" == "ODH" ]]; then
  echo "  Step 5 Workflow          : pending KRD+OKC merge (deferred_workflow.sh running)"
else
  echo "  Step 5 Workflow          : N/A (RHOAI)"
fi
echo "  Step 6 Operator          : ${OP_PR}"
echo "  Step 7 Bundle            : $BDLPR"
if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  echo "  Step 8 Dockerfile Labels : $LABELS_PR"
  echo "  Step 9 Delivery Repo MR  : $DELIV_MR"
  echo "  Step 10 Auto-Merge PR    : $AM_PR"
  echo "  Step 11 Renovate PR      : $RENOV_PR"
fi
echo ""
echo "Background processes:"
[[ "${PRODUCT_CONTEXT^^}" == "ODH" ]] && \
  echo "  deferred_workflow.pid     log: $WORKDIR/deferred_workflow.log"
echo "  monitor_completion.pid    log: $WORKDIR/monitor_completion.log"
echo ""
echo "Live event stream (run in a separate terminal):"
echo "  bash \"$SCRIPTS_DIR/watch_monitors.sh\" --workdir \"$WORKDIR\""
echo ""
echo "State file: $WORKDIR/pipeline_state.json"
echo ""
echo "The Jira ticket will move to Resolved automatically when all PRs/MRs are merged."
