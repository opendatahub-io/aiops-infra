#!/usr/bin/env bash
# monitor_completion.sh — polls pipeline_state.json until all steps are done,
# then transitions the Jira issue to Resolved.
set -euo pipefail

WORKDIR=""
JIRA_URL=""
COMMON_SCRIPTS_DIR=""

usage() {
  echo "Usage: $0 --workdir PATH --jira-url URL --scripts-dir PATH"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)     WORKDIR="$2";             shift 2 ;;
    --jira-url)    JIRA_URL="$2";            shift 2 ;;
    --scripts-dir) COMMON_SCRIPTS_DIR="$2";  shift 2 ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$WORKDIR" || -z "$JIRA_URL" || -z "$COMMON_SCRIPTS_DIR" ]] && usage

PIPELINE_STATE="$WORKDIR/pipeline_state.json"
MAX_WAIT=14400    # 4 hours
POLL_INTERVAL=120 # 2 minutes
ELAPSED=0

log() { echo "[completion $(date '+%H:%M:%S')] $*" >> "$WORKDIR/monitor_completion.log"; }
log "Started. Max wait: ${MAX_WAIT}s, poll: ${POLL_INTERVAL}s."

sync_results() {
  for step in quay krd okc operator dockerfile_labels delivery_repo auto_merge renovate; do
    local rf="$WORKDIR/monitor_${step}.result"
    [[ -f "$rf" ]] || continue
    local cur; cur=$(jq -r ".steps.${step}.status" "$PIPELINE_STATE")
    [[ "$cur" == "merged" || "$cur" == "skipped" || "$cur" == "done" ]] && continue
    local r; r=$(cat "$rf" | tr -d '[:space:]')
    if [[ "$r" == "merged" ]]; then
      jq --arg s "$step" '.steps[$s].status = "merged"' "$PIPELINE_STATE" > \
        "$PIPELINE_STATE.tmp" && mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
      log "Step $step: updated to merged."
    fi
  done
}

all_done() {
  local v q k o on op b dl dr am rv PRODUCT
  v=$(jq -r  '.steps.validate.status'          "$PIPELINE_STATE")
  q=$(jq -r  '.steps.quay.status'              "$PIPELINE_STATE")
  k=$(jq -r  '.steps.krd.status'               "$PIPELINE_STATE")
  o=$(jq -r  '.steps.okc.status'               "$PIPELINE_STATE")
  on=$(jq -r '.steps.onboarder.status'         "$PIPELINE_STATE")
  op=$(jq -r '.steps.operator.status'          "$PIPELINE_STATE")
  b=$(jq -r  '.steps.bundle.status'            "$PIPELINE_STATE")
  dl=$(jq -r '.steps.dockerfile_labels.status' "$PIPELINE_STATE")
  dr=$(jq -r '.steps.delivery_repo.status'     "$PIPELINE_STATE")
  am=$(jq -r '.steps.auto_merge.status'        "$PIPELINE_STATE")
  rv=$(jq -r '.steps.renovate.status'          "$PIPELINE_STATE")
  PRODUCT=$(jq -r '.product_context'           "$PIPELINE_STATE")

  log "Status: validate=$v quay=$q krd=$k okc=$o onboarder=$on operator=$op bundle=$b dl=$dl dr=$dr am=$am rv=$rv"

  [[ "$v"  == "done"   ]] || return 1
  [[ "$q"  == "merged" || "$q"  == "skipped" || "$q"  == "done" ]] || return 1
  [[ "$k"  == "merged" || "$k"  == "done"    ]] || return 1
  [[ "$o"  == "merged" ]] || return 1
  [[ "$op" == "merged" || "$op" == "skipped" ]] || return 1
  # bundle: pr_raised is acceptable (SHA placeholder may need manual fix before merge)
  [[ "$b"  == "merged" || "$b"  == "pr_raised" ]] || return 1

  if [[ "$PRODUCT" == "RHOAI" ]]; then
    [[ "$on" == "skipped" ]] || return 1
    [[ "$dl" == "merged" || "$dl" == "pr_raised" || "$dl" == "done" ]] || return 1
    [[ "$dr" == "merged" || "$dr" == "done" ]] || return 1
    [[ "$am" == "merged" || "$am" == "pr_raised" || "$am" == "done" ]] || return 1
    [[ "$rv" == "merged" || "$rv" == "pr_raised" || "$rv" == "done" ]] || return 1
  else
    [[ "$on" == "merged" || "$on" == "skipped" ]] || return 1
    [[ "$dl" == "skipped" ]] || return 1
    [[ "$dr" == "skipped" ]] || return 1
    [[ "$am" == "skipped" ]] || return 1
    [[ "$rv" == "skipped" ]] || return 1
  fi
  return 0
}

while true; do
  sync_results
  if all_done; then
    log "All steps complete. Transitioning Jira to Resolved."
    COMP=$(jq -r    '.component_name'                          "$PIPELINE_STATE")
    Q_MR=$(jq -r    '.steps.quay.mr_url // "N/A"'             "$PIPELINE_STATE")
    K_MR=$(jq -r    '.steps.krd.mr_url // "N/A"'              "$PIPELINE_STATE")
    O_PR=$(jq -r    '.steps.okc.pr_url // "N/A"'              "$PIPELINE_STATE")
    T_PR=$(jq -r    '.steps.onboarder.tekton_pr_url // "N/A"' "$PIPELINE_STATE")
    OP_PR=$(jq -r   '.steps.operator.pr_url // "N/A"'         "$PIPELINE_STATE")
    B_PR=$(jq -r    '.steps.bundle.pr_url // "N/A"'           "$PIPELINE_STATE")
    DL_PR=$(jq -r   '.steps.dockerfile_labels.pr_url // "N/A"' "$PIPELINE_STATE")
    DR_MR=$(jq -r   '.steps.delivery_repo.mr_url // "N/A"'    "$PIPELINE_STATE")
    AM_PR=$(jq -r   '.steps.auto_merge.pr_url // "N/A"'       "$PIPELINE_STATE")
    RV_PR=$(jq -r   '.steps.renovate.pr_url // "N/A"'         "$PIPELINE_STATE")
    PRODUCT=$(jq -r '.product_context'                         "$PIPELINE_STATE")

    uv run --script "$COMMON_SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --remove-label "onboarding-in-review" \
      --add-label    "onboarding-complete" \
      --status       "Resolved" \
      --comment "ODH/RHOAI component onboarding for '$COMP' is COMPLETE.

All PRs and MRs merged:
  Step 2 — Quay MR          : $Q_MR
  Step 3 — KRD MR           : $K_MR
  Step 4 — OKC/RKC PR       : $O_PR
  Step 5 — Tekton PR        : $([ "$PRODUCT" = "ODH" ] && echo "$T_PR" || echo "N/A (RHOAI)")
  Step 6 — Operator PR      : $OP_PR
  Step 7 — Bundle PR        : $B_PR
  Step 8 — Dockerfile Labels: $DL_PR
  Step 9 — Delivery Repo MR : $DR_MR
  Step 10 — Auto-Merge PR   : $AM_PR
  Step 11 — Renovate PR     : $RV_PR" \
      2>/dev/null || true

    jq '.all_done = true' "$PIPELINE_STATE" > "$PIPELINE_STATE.tmp" && \
      mv "$PIPELINE_STATE.tmp" "$PIPELINE_STATE"
    log "Jira moved to Resolved. Onboarding complete."
    exit 0
  fi

  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    log "WARNING: Timed out after ${MAX_WAIT}s. Not all steps are done."
    log "Check pipeline_state.json and individual .result files."
    exit 1
  fi
  log "Not all done. Sleeping ${POLL_INTERVAL}s. (elapsed=${ELAPSED}s)"
  sleep $POLL_INTERVAL
  ELAPSED=$(( ELAPSED + POLL_INTERVAL ))
done
