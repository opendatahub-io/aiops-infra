#!/usr/bin/env bash
# Usage: eval "$(bash init_pipeline.sh --jira-url <url> [--workdir-override <path>] [--product-context ODH|RHOAI] [--component-name <name>] [--is-operator true|false])"
# Extends init_workdir.sh: also creates/resumes pipeline_state.json and sets PIPELINE_STATE.
set -euo pipefail

JIRA_URL=""
WORKDIR_OVERRIDE=""
PRODUCT_CONTEXT=""
COMPONENT_NAME=""
IS_OPERATOR="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url)         JIRA_URL="$2";         shift 2 ;;
    --workdir-override) WORKDIR_OVERRIDE="$2"; shift 2 ;;
    --product-context)  PRODUCT_CONTEXT="$2";  shift 2 ;;
    --component-name)   COMPONENT_NAME="$2";   shift 2 ;;
    --is-operator)      IS_OPERATOR="$2";      shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$JIRA_URL" ]]; then
  echo "ERROR: --jira-url is required" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL%/}"
JIRA_ID="${JIRA_ID##*/}"

if [[ -z "$JIRA_ID" ]]; then
  echo "ERROR: Could not extract issue ID from URL: $JIRA_URL" >&2
  exit 1
fi

if [[ -n "$WORKDIR_OVERRIDE" ]]; then
  WORKDIR="$WORKDIR_OVERRIDE"
else
  WORKDIR="$(pwd)/${JIRA_ID}"
fi

mkdir -p "$WORKDIR"

PIPELINE_STATE="${WORKDIR}/pipeline_state.json"

if [[ ! -f "$PIPELINE_STATE" ]]; then
  # Determine which steps to skip based on product context
  # RHOAI skips: onboarder_workflow
  # ODH skips: pull_pipelines, delivery_repo, product_listing, auto_merge, renovate, renovate_sync
  # okc labels differ by context (rkc-* for RHOAI, okc-* for ODH)
  OKC_LABEL_RAISED="okc-pr-raised"
  OKC_LABEL_DONE="okc-pr-merged"
  if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
    OKC_LABEL_RAISED="rkc-pr-raised"
    OKC_LABEL_DONE="rkc-pr-merged"
  fi

  SKIP_RHOAI_ONLY="pending"
  SKIP_ODH_ONLY="pending"
  if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
    SKIP_RHOAI_ONLY="skipped"
  elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
    SKIP_ODH_ONLY="skipped"
  fi

  # Write operator step as skipped if is_operator=false
  OP_STATUS="pending"
  if [[ "$IS_OPERATOR" != "true" ]]; then
    OP_STATUS="skipped"
  fi

  cat > "$PIPELINE_STATE" <<EOF
{
  "component_name": "${COMPONENT_NAME}",
  "product_context": "${PRODUCT_CONTEXT}",
  "is_operator": ${IS_OPERATOR},
  "last_status_change_at": "",
  "steps": {
    "validate": {
      "status": "pending",
      "depends_on": []
    },
    "quay": {
      "status": "pending",
      "mr_url": "",
      "depends_on": [],
      "label_raised": "quay-mr-raised",
      "label_done": "quay-mr-merged"
    },
    "krd": {
      "status": "pending",
      "mr_url": "",
      "depends_on": [],
      "label_raised": "konflux-mr-raised",
      "label_done": "konflux-mr-merged"
    },
    "okc": {
      "status": "pending",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "${OKC_LABEL_RAISED}",
      "label_done": "${OKC_LABEL_DONE}"
    },
    "pull_pipelines": {
      "status": "${SKIP_RHOAI_ONLY}",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "rkc-pull-pr-raised",
      "label_done": "rkc-pull-changes-done"
    },
    "operator": {
      "status": "${OP_STATUS}",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "operator-pr-raised",
      "label_done": "operator-pr-merged"
    },
    "bundle": {
      "status": "pending",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "bundle-pr-raised",
      "label_done": "obc-changes-done"
    },
    "delivery_repo": {
      "status": "${SKIP_RHOAI_ONLY}",
      "mr_url": "",
      "depends_on": [],
      "label_raised": "delivery-repo-mr-raised",
      "label_done": "delivery-repo-created"
    },
    "product_listing": {
      "status": "${SKIP_RHOAI_ONLY}",
      "mr_url": "",
      "depends_on": ["delivery_repo"],
      "label_raised": "product-listing-mr-raised",
      "label_done": "product-listing-created"
    },
    "auto_merge": {
      "status": "${SKIP_RHOAI_ONLY}",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "auto-merge-pr-raised",
      "label_done": "auto-merge-setup-done"
    },
    "renovate": {
      "status": "${SKIP_RHOAI_ONLY}",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "renovate-pr-raised",
      "label_done": "renovate-changes-done"
    },
    "renovate_sync": {
      "status": "${SKIP_RHOAI_ONLY}",
      "depends_on": ["renovate"],
      "label_done": "renovate-sync-triggered"
    },
    "onboarder_workflow": {
      "status": "${SKIP_ODH_ONLY}",
      "depends_on": ["krd", "okc"],
      "label_done": "onboarder-workflow-triggered"
    }
  }
}
EOF
  echo "Created pipeline state: $PIPELINE_STATE" >&2
else
  echo "Resuming from existing pipeline state: $PIPELINE_STATE" >&2
  jq '.steps | to_entries[] | "\(.key): \(.value.status)"' -r "$PIPELINE_STATE" >&2

  # Update top-level fields if they were not set (backward-compat with old state files)
  if [[ -n "$COMPONENT_NAME" ]] && [[ "$(jq -r '.component_name // ""' "$PIPELINE_STATE")" == "" ]]; then
    TMP=$(mktemp)
    jq --arg v "$COMPONENT_NAME" '.component_name = $v' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
  fi
  if [[ -n "$PRODUCT_CONTEXT" ]] && [[ "$(jq -r '.product_context // ""' "$PIPELINE_STATE")" == "" ]]; then
    TMP=$(mktemp)
    jq --arg v "$PRODUCT_CONTEXT" '.product_context = $v' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
  fi
fi

printf 'JIRA_ID=%q\n' "$JIRA_ID"
printf 'WORKDIR=%q\n' "$WORKDIR"
printf 'PIPELINE_STATE=%q\n' "$PIPELINE_STATE"
