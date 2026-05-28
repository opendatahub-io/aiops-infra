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
  WORKDIR="$(pwd)/.work/${JIRA_ID}"
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

  # krd depends on quay (both); also delivery_repo for RHOAI
  KRD_DEPENDS_ON='["quay"]'
  if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
    KRD_DEPENDS_ON='["quay", "delivery_repo"]'
  fi

  # okc depends on krd for RHOAI; no dependency for ODH
  OKC_DEPENDS_ON="[]"
  if [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
    OKC_DEPENDS_ON='["krd"]'
  fi

  # pull_pipelines depends on krd (RHOAI-only step, so no conditional needed)
  PULL_PIPELINES_DEPENDS_ON='["krd"]'

  # bundle depends on onboarder_workflow (ODH) or okc (RHOAI)
  BUNDLE_DEPENDS_ON="[]"
  if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
    BUNDLE_DEPENDS_ON='["onboarder_workflow"]'
  elif [[ "$PRODUCT_CONTEXT" == "RHOAI" ]]; then
    BUNDLE_DEPENDS_ON='["okc"]'
  fi

  # operator depends on bundle (both products)
  OPERATOR_DEPENDS_ON='["bundle"]'

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
      "depends_on": ${KRD_DEPENDS_ON},
      "label_raised": "krd-mr-raised",
      "label_done": "krd-mr-merged"
    },
    "okc": {
      "status": "pending",
      "pr_url": "",
      "depends_on": ${OKC_DEPENDS_ON},
      "label_raised": "${OKC_LABEL_RAISED}",
      "label_done": "${OKC_LABEL_DONE}"
    },
    "pull_pipelines": {
      "status": "${SKIP_RHOAI_ONLY}",
      "pr_url": "",
      "depends_on": ${PULL_PIPELINES_DEPENDS_ON},
      "label_raised": "rkc-pull-pr-raised",
      "label_done": "rkc-pull-changes-done"
    },
    "operator": {
      "status": "${OP_STATUS}",
      "pr_url": "",
      "depends_on": ${OPERATOR_DEPENDS_ON},
      "label_raised": "operator-pr-raised",
      "label_done": "operator-pr-merged"
    },
    "bundle": {
      "status": "pending",
      "pr_url": "",
      "depends_on": ${BUNDLE_DEPENDS_ON},
      "label_raised": "bundle-pr-raised",
      "label_done": "bundle-changes-done"
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
      "pr_url": "",
      "depends_on": ["krd", "okc"],
      "label_raised": "tekton-pr-raised",
      "label_done": "tekton-pr-merged"
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

  # Fix operator step: the initial init (Step 2) runs before IS_OPERATOR is
  # known, so it defaults to "skipped". Once Step 4 re-invokes with the real
  # value, correct the status if needed.
  if [[ "$IS_OPERATOR" == "true" ]]; then
    CURRENT_OP=$(jq -r '.steps.operator.status // "pending"' "$PIPELINE_STATE")
    if [[ "$CURRENT_OP" == "skipped" ]]; then
      TMP=$(mktemp)
      jq '.steps.operator.status = "pending"' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  operator step: skipped → pending (is_operator=true)" >&2
    fi
    # Also ensure is_operator is set correctly in state
    CURRENT_IS_OP=$(jq -r '.is_operator // false' "$PIPELINE_STATE")
    if [[ "$CURRENT_IS_OP" != "true" ]]; then
      TMP=$(mktemp)
      jq '.is_operator = true' "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    fi
  fi

  # Backward-compat: patch depends_on arrays for old state files.
  CURRENT_PC=$(jq -r '.product_context // ""' "$PIPELINE_STATE")

  # krd: add "delivery_repo" if missing (RHOAI only)
  if [[ "$CURRENT_PC" == "RHOAI" ]]; then
    if ! jq -e '.steps.krd.depends_on | index("delivery_repo") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
      TMP=$(mktemp)
      jq '.steps.krd.depends_on = ((.steps.krd.depends_on // []) + ["delivery_repo"] | unique)' \
        "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  krd.depends_on: added delivery_repo (RHOAI prerequisite)" >&2
    fi
  fi

  # krd: add "quay" if missing (both products)
  if ! jq -e '.steps.krd.depends_on | index("quay") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
    TMP=$(mktemp)
    jq '.steps.krd.depends_on = ((.steps.krd.depends_on // []) + ["quay"] | unique)' \
      "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    echo "  krd.depends_on: added quay (prerequisite)" >&2
  fi

  # okc: add "krd" if missing (RHOAI only)
  if [[ "$CURRENT_PC" == "RHOAI" ]]; then
    if ! jq -e '.steps.okc.depends_on | index("krd") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
      TMP=$(mktemp)
      jq '.steps.okc.depends_on = ((.steps.okc.depends_on // []) + ["krd"] | unique)' \
        "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  okc.depends_on: added krd (RHOAI prerequisite)" >&2
    fi
  fi

  # pull_pipelines: add "krd" if missing (RHOAI only — step is skipped for ODH)
  if [[ "$CURRENT_PC" == "RHOAI" ]]; then
    if ! jq -e '.steps.pull_pipelines.depends_on | index("krd") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
      TMP=$(mktemp)
      jq '.steps.pull_pipelines.depends_on = ((.steps.pull_pipelines.depends_on // []) + ["krd"] | unique)' \
        "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  pull_pipelines.depends_on: added krd (prerequisite)" >&2
    fi
  fi

  # bundle: add "onboarder_workflow" (ODH) or "okc" (RHOAI) if missing
  if [[ "$CURRENT_PC" == "ODH" ]]; then
    if ! jq -e '.steps.bundle.depends_on | index("onboarder_workflow") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
      TMP=$(mktemp)
      jq '.steps.bundle.depends_on = ((.steps.bundle.depends_on // []) + ["onboarder_workflow"] | unique)' \
        "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  bundle.depends_on: added onboarder_workflow (ODH prerequisite)" >&2
    fi
  elif [[ "$CURRENT_PC" == "RHOAI" ]]; then
    if ! jq -e '.steps.bundle.depends_on | index("okc") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
      TMP=$(mktemp)
      jq '.steps.bundle.depends_on = ((.steps.bundle.depends_on // []) + ["okc"] | unique)' \
        "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
      echo "  bundle.depends_on: added okc (RHOAI prerequisite)" >&2
    fi
  fi

  # operator: add "bundle" if missing (both products)
  if ! jq -e '.steps.operator.depends_on | index("bundle") != null' "$PIPELINE_STATE" > /dev/null 2>&1; then
    TMP=$(mktemp)
    jq '.steps.operator.depends_on = ((.steps.operator.depends_on // []) + ["bundle"] | unique)' \
      "$PIPELINE_STATE" > "$TMP" && mv "$TMP" "$PIPELINE_STATE"
    echo "  operator.depends_on: added bundle (prerequisite)" >&2
  fi
fi

printf 'JIRA_ID=%q\n' "$JIRA_ID"
printf 'WORKDIR=%q\n' "$WORKDIR"
printf 'PIPELINE_STATE=%q\n' "$PIPELINE_STATE"
