#!/usr/bin/env bash
# Background script: waits for the delivery-repo MR to merge, then executes the
# update-rhoai-product-listing flow (fast-path check → clone → append → commit → raise MR → monitor).
# Usage: nohup bash deferred_product_listing.sh \
#          --workdir X --jira-url X --scripts-dir X --pyxis-url X --component-name X \
#          >> "$WORKDIR/deferred_product_listing.log" 2>&1 &
set -euo pipefail

WORKDIR=""
JIRA_URL=""
SCRIPTS_DIR=""
PYXIS_URL=""
COMPONENT_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir)        WORKDIR="$2";        shift 2 ;;
    --jira-url)       JIRA_URL="$2";       shift 2 ;;
    --scripts-dir)    SCRIPTS_DIR="$2";    shift 2 ;;
    --pyxis-url)      PYXIS_URL="$2";      shift 2 ;;
    --component-name) COMPONENT_NAME="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

for required in WORKDIR JIRA_URL SCRIPTS_DIR PYXIS_URL COMPONENT_NAME; do
  if [[ -z "${!required}" ]]; then
    echo "ERROR: --$(echo "$required" | tr '[:upper:]' '[:lower:]' | tr '_' '-') is required" >&2
    exit 1
  fi
done

PIPELINE_STATE="${WORKDIR}/pipeline_state.json"
DELIVERY_RESULT_FILE="${WORKDIR}/monitor_delivery_repo.result"
PRODUCT_LISTING_ENTRY="registry.access.redhat.com/rhoai/${COMPONENT_NAME}-rhel9"

echo "[deferred_product_listing] Starting. Waiting for delivery-repo MR to merge..."
echo "[deferred_product_listing] Watching: $DELIVERY_RESULT_FILE"
echo "[deferred_product_listing] Component: $COMPONENT_NAME"
echo "[deferred_product_listing] Entry: $PRODUCT_LISTING_ENTRY"

# Wait until the delivery-repo monitor writes a result
while true; do
  if [[ -f "$DELIVERY_RESULT_FILE" ]]; then
    DELIVERY_RESULT=$(cat "$DELIVERY_RESULT_FILE" | tr -d '[:space:]')
    if [[ "$DELIVERY_RESULT" == "merged" ]]; then
      echo "[deferred_product_listing] Delivery-repo MR merged. Proceeding with product listing update..."
      break
    elif [[ "$DELIVERY_RESULT" == "closed" || "$DELIVERY_RESULT" == "timeout" || "$DELIVERY_RESULT" == "pipeline_failed" ]]; then
      echo "[deferred_product_listing] Delivery-repo MR result: $DELIVERY_RESULT — aborting product listing." >&2
      bash "$SCRIPTS_DIR/pipeline_state.sh" set \
        --state "$PIPELINE_STATE" --step product_listing --field status --value "skipped_delivery_not_merged"
      exit 1
    fi
  fi
  echo "[deferred_product_listing] Delivery-repo not yet merged — waiting 60s..."
  sleep 60
done

# Derive URL-encoded path for the GitLab raw file API
PYXIS_PATH_ENCODED="product-listings%2Frhoai%2Frhoai.yaml"

# Fast-path: check if entry already exists in the remote file
RHOAI_YAML_TMPFILE=$(mktemp)
PYXIS_API_BASE=$(echo "$PYXIS_URL" | sed 's|\.git$||')
HTTP_STATUS=$(curl -sf --insecure \
  -H "PRIVATE-TOKEN: ${GITLAB_TOKEN:-}" \
  -o "$RHOAI_YAML_TMPFILE" \
  -w "%{http_code}" \
  "${PYXIS_API_BASE}/-/raw/main/product-listings/rhoai/rhoai.yaml" 2>/dev/null || echo "000")

if [[ "$HTTP_STATUS" == "200" ]] && grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML_TMPFILE" 2>/dev/null; then
  echo "[deferred_product_listing] '$PRODUCT_LISTING_ENTRY' already present in product-listings/rhoai/rhoai.yaml — skipping."
  rm -f "$RHOAI_YAML_TMPFILE"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "product-listing-exists" \
      --comment "Product listing entry for '${COMPONENT_NAME}' already present in product-listings/rhoai/rhoai.yaml. No action needed." || true
  fi
  bash "$SCRIPTS_DIR/pipeline_state.sh" set \
    --state "$PIPELINE_STATE" --step product_listing --field status --value "done" || true
  exit 0
fi
rm -f "$RHOAI_YAML_TMPFILE"

# Derive JIRA_ID from JIRA_URL
JIRA_ID="${JIRA_URL##*/}"

# Set up GitLab playpen (sparse clone of product-listings/rhoai/rhoai.yaml)
cd "$WORKDIR"
PLAYPEN_OUTPUT=$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/setup_gitlab_playpen.sh" \
  --src-url "$PYXIS_URL" \
  --dest-url "$PYXIS_URL" \
  --src-branch main \
  ${JIRA_ID:+--dest-branch "$JIRA_ID"} \
  --sparse-files "product-listings/rhoai/rhoai.yaml")

CLONE_DIR=$(echo "$PLAYPEN_OUTPUT" | head -1)
DEST_BRANCH=$(echo "$PLAYPEN_OUTPUT" | tail -1)

echo "[deferred_product_listing] Cloned to: $CLONE_DIR (branch: $DEST_BRANCH)"

RHOAI_YAML="$CLONE_DIR/product-listings/rhoai/rhoai.yaml"
[[ -f "$RHOAI_YAML" ]] || {
  echo "ERROR: product-listings/rhoai/rhoai.yaml not found in $CLONE_DIR." >&2
  echo "  Verify PYXIS_URL points to the correct pyxis-repo-configs repository." >&2
  exit 1
}

if grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML"; then
  echo "[deferred_product_listing] Entry already present in cloned file — skipping edit."
else
  python3 - "$RHOAI_YAML" "$PRODUCT_LISTING_ENTRY" <<'PYEOF'
import sys

rhoai_yaml = sys.argv[1]
entry_line = "- " + sys.argv[2] + "\n"

with open(rhoai_yaml, "r") as f:
    lines = f.readlines()

in_repos = False
last_repo_idx = None
for i, line in enumerate(lines):
    if line.strip().startswith("repositories:"):
        in_repos = True
    elif in_repos and line.lstrip().startswith("- "):
        last_repo_idx = i
    elif in_repos and line.strip() and not line.lstrip().startswith("- ") and not line.strip().startswith("#"):
        in_repos = False

if last_repo_idx is not None:
    lines.insert(last_repo_idx + 1, entry_line)
else:
    lines.append(entry_line)

with open(rhoai_yaml, "w") as f:
    f.writelines(lines)
print("Entry added.")
PYEOF

  grep -qF "$PRODUCT_LISTING_ENTRY" "$RHOAI_YAML" || {
    echo "ERROR: Verification failed — '$PRODUCT_LISTING_ENTRY' not found after append." >&2
    exit 1
  }
  echo "[deferred_product_listing] Entry '$PRODUCT_LISTING_ENTRY' added to product-listings/rhoai/rhoai.yaml."
fi

# Commit and push
bash "$SCRIPTS_DIR/git_commit_push.sh" \
  --clone-dir "$CLONE_DIR" \
  --files     "product-listings/rhoai/rhoai.yaml" \
  --message   "Add ${COMPONENT_NAME} to RHOAI product listing

Adds registry path to product-listings/rhoai/rhoai.yaml:
  ${PRODUCT_LISTING_ENTRY}

Related: ${JIRA_ID:-no-jira}" \
  --branch    "$DEST_BRANCH"

# Raise MR
MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
  --src-url "$PYXIS_URL" \
  --src-branch "$DEST_BRANCH" \
  --dest-url "$PYXIS_URL" \
  --dest-branch main \
  --title "Add ${COMPONENT_NAME} to RHOAI product listing" \
  --description "Adds registry path to product-listings/rhoai/rhoai.yaml:

\`${PRODUCT_LISTING_ENTRY}\`

| Field | Value |
|-------|-------|
| Component | \`${COMPONENT_NAME}\` |
| Entry | \`${PRODUCT_LISTING_ENTRY}\` |
| File | \`product-listings/rhoai/rhoai.yaml\` |

**Jira:** ${JIRA_URL:-(none)}")

echo "[deferred_product_listing] MR raised: $MR_URL"

bash "$SCRIPTS_DIR/pipeline_state.sh" set \
  --state "$PIPELINE_STATE" --step product_listing --field mr_url --value "$MR_URL"
bash "$SCRIPTS_DIR/pipeline_state.sh" set \
  --state "$PIPELINE_STATE" --step product_listing --field status --value "mr_raised"

if [[ -n "$JIRA_URL" ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "product-listing-mr-raised" \
    --comment "GitLab MR raised to add '${COMPONENT_NAME}' to RHOAI product listing.

MR URL: $MR_URL
File: product-listings/rhoai/rhoai.yaml
Entry: ${PRODUCT_LISTING_ENTRY}" || true
fi

# Launch background monitor for the product listing MR
bash "$SCRIPTS_DIR/launch_monitor.sh" \
  --step         "product_listing" \
  --url          "$MR_URL" \
  --type         "gitlab" \
  --jira-url     "$JIRA_URL" \
  --label-remove "product-listing-mr-raised" \
  --comment      "$(printf 'Product listing MR merged: %s\n\nRegistry path for '\''%s'\'' is now present in product-listings/rhoai/rhoai.yaml:\n  %s' "$MR_URL" "$COMPONENT_NAME" "$PRODUCT_LISTING_ENTRY")" \
  --workdir      "$WORKDIR" \
  --scripts-dir  "$SCRIPTS_DIR"

echo "[deferred_product_listing] Done. Monitor launched for MR: $MR_URL"
