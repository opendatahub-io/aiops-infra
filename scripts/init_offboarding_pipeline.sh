#!/usr/bin/env bash
# Usage: eval "$(bash init_offboarding_pipeline.sh --jira-url <url> [--workdir-override <path>] [--product-context ODH|RHOAI] [--component-name <name>] [--is-operator true|false])"
# Creates/resumes pipeline_state.json for component offboarding and sets PIPELINE_STATE.
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
  # All offboarding steps are independent (no dependency chains).
  # RHOAI skips: (none specific to ODH)
  # ODH skips: remove_pull_pipelines (RHOAI-only)
  SKIP_RHOAI_ONLY="pending"
  if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
    SKIP_RHOAI_ONLY="skipped"
  fi

  OP_STATUS="pending"
  if [[ "$IS_OPERATOR" != "true" ]]; then
    OP_STATUS="skipped"
  fi

  cat > "$PIPELINE_STATE" <<EOF
{
  "pipeline_type": "offboarding",
  "component_name": "${COMPONENT_NAME}",
  "product_context": "${PRODUCT_CONTEXT}",
  "is_operator": ${IS_OPERATOR},
  "last_status_change_at": "",
  "steps": {
    "validate": {
      "status": "pending",
      "depends_on": []
    },
    "remove_krd": {
      "status": "pending",
      "mr_url": "",
      "depends_on": [],
      "label_raised": "offboard-krd-mr-raised",
      "label_done": "offboard-krd-mr-merged"
    },
    "remove_okc": {
      "status": "pending",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "offboard-okc-pr-raised",
      "label_done": "offboard-okc-pr-merged"
    },
    "remove_pull_pipelines": {
      "status": "${SKIP_RHOAI_ONLY}",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "offboard-pull-pipelines-pr-raised",
      "label_done": "offboard-pull-pipelines-pr-merged"
    },
    "remove_bundle": {
      "status": "pending",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "offboard-bundle-pr-raised",
      "label_done": "offboard-bundle-pr-merged"
    },
    "remove_operator": {
      "status": "${OP_STATUS}",
      "pr_url": "",
      "depends_on": [],
      "label_raised": "offboard-operator-pr-raised",
      "label_done": "offboard-operator-pr-merged"
    },
    "remove_product_listing": {
      "status": "${SKIP_RHOAI_ONLY}",
      "mr_url": "",
      "depends_on": [],
      "label_raised": "offboard-product-listing-mr-raised",
      "label_done": "offboard-product-listing-done"
    }
  }
}
EOF
  echo "Created offboarding pipeline state: $PIPELINE_STATE" >&2
else
  echo "Resuming from existing pipeline state: $PIPELINE_STATE" >&2
  jq '.steps | to_entries[] | "\(.key): \(.value.status)"' -r "$PIPELINE_STATE" >&2

  # Update top-level fields if they were not set
  if [[ -n "$COMPONENT_NAME" ]] && [[ "$(jq -r '.component_name // ""' "$PIPELINE_STATE")" == "" ]]; then
    TMP=$(mktemp)
    jq --arg v "$COMPONENT_NAME" '.component_name = $v' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
  fi
  if [[ -n "$PRODUCT_CONTEXT" ]] && [[ "$(jq -r '.product_context // ""' "$PIPELINE_STATE")" == "" ]]; then
    TMP=$(mktemp)
    jq --arg v "$PRODUCT_CONTEXT" '.product_context = $v' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
  fi

  # Fix product-context-specific skip statuses
  if [[ -n "$PRODUCT_CONTEXT" ]]; then
    TMP=$(mktemp)
    if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
      jq '
        .steps |= with_entries(
          if (.key == "remove_pull_pipelines" or .key == "remove_product_listing")
             and .value.status == "pending"
          then .value.status = "skipped"
          else .
          end
        )' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    fi
    rm -f "$TMP"
  fi

  # Fix operator step if is_operator was updated
  if [[ "$IS_OPERATOR" == "true" ]]; then
    CURRENT_OP=$(jq -r '.steps.remove_operator.status // "pending"' "$PIPELINE_STATE")
    if [[ "$CURRENT_OP" == "skipped" ]]; then
      TMP=$(mktemp)
      jq '.steps.remove_operator.status = "pending"' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  remove_operator step: skipped → pending (is_operator=true)" >&2
    fi
    CURRENT_IS_OP=$(jq -r '.is_operator // false' "$PIPELINE_STATE")
    if [[ "$CURRENT_IS_OP" != "true" ]]; then
      TMP=$(mktemp)
      jq '.is_operator = true' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    fi
  fi
fi

printf 'JIRA_ID=%q\n' "$JIRA_ID"
printf 'WORKDIR=%q\n' "$WORKDIR"
printf 'PIPELINE_STATE=%q\n' "$PIPELINE_STATE"
