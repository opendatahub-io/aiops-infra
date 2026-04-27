#!/usr/bin/env bash
# Main script for the onboard-component-to-konflux-release-data skill.
# Creates Konflux Component resources by appending a YAML document to the
# konflux-release-data tenant config and raising a GitLab MR.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Step 0: Parse Inputs ---
JIRA_URL=""
WORKDIR_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workdir) WORKDIR_OVERRIDE="$2"; shift 2 ;;
    http*)     JIRA_URL="$1"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ -z "$JIRA_URL" || "$JIRA_URL" != *"/browse/"* ]]; then
  echo "Usage: $(basename "$0") <jira-url> [--workdir <path>]" >&2
  echo "  Example: $(basename "$0") https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL##*/}"
KRD_URL="${KONFLUX_RELEASE_DATA_REPO_URL:-https://gitlab.cee.redhat.com/releng/konflux-release-data.git}"

# --- Step 1: Check Prerequisites ---
bash "$SCRIPTS_DIR/check_prerequisites.sh" \
  --env   "GITLAB_USER GITLAB_TOKEN JIRA_USER_EMAIL JIRA_API_TOKEN" \
  --tools "uv oc yamllint kustomize"
KUSTOMIZE_BIN="kustomize"

# --- Step 2: Set Up Working Directory ---
if [[ -n "$WORKDIR_OVERRIDE" ]]; then
  WORKDIR="$WORKDIR_OVERRIDE"
else
  WORKDIR="$(pwd)/${JIRA_ID}"
fi
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"

# --- Step 3: Fetch Jira Details and Component YAML ---
if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
  if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$JIRA_URL"); then
    echo "ERROR in Step 3a (Fetch Jira details): Could not fetch Jira issue. See details above. Aborting." >&2
    exit 1
  fi
fi

YAML_PATH="$WORKDIR/component_onboarding_details.yaml"
if [[ ! -f "$YAML_PATH" ]]; then
  if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/download_jira_attachment.py" \
      "$JIRA_URL" component_onboarding_details.yaml); then
    echo "ERROR in Step 3b (Download YAML): Could not download 'component_onboarding_details.yaml' from Jira." >&2
    echo "  Ensure the attachment exists on the Jira issue before running this skill." >&2
    exit 1
  fi
fi

_parse() {
  python3 -c "
import yaml, sys
with open('$YAML_PATH') as f:
    d = yaml.safe_load(f)
inp = d.get('inputs', {})
print(inp.get('$1', ''))
" 2>/dev/null
}
COMPONENT_NAME="$(_parse component_name)"
REPO_URL="$(_parse repo_url)"
REPO_BRANCH="$(_parse repo_branch)"
CONTEXT_PATH="$(_parse context_path)"
DOCKERFILE_PATH="$(_parse dockerfile_path)"

for field_check in "COMPONENT_NAME:component_name" "REPO_URL:repo_url" "REPO_BRANCH:repo_branch" "CONTEXT_PATH:context_path" "DOCKERFILE_PATH:dockerfile_path"; do
  var="${field_check%%:*}"
  key="${field_check##*:}"
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR in Step 3c: Missing required field '${key}' in component_onboarding_details.yaml. Aborting." >&2
    exit 1
  fi
done

if [[ "$COMPONENT_NAME" == *"-ci" ]]; then
  KONFLUX_COMPONENT_NAME="$COMPONENT_NAME"
else
  KONFLUX_COMPONENT_NAME="${COMPONENT_NAME}-ci"
fi

# --- Step 4: Determine Product Context ---
PRODUCT_CONTEXT=""

if [[ "$JIRA_ID" == RHOAIENG* ]]; then
  PRODUCT_CONTEXT="RHOAI"
elif [[ "$JIRA_ID" == RHODS* ]]; then
  PRODUCT_CONTEXT="ODH"
fi

if [[ -z "$PRODUCT_CONTEXT" && -f "$WORKDIR/component_onboarding_details.json" ]]; then
  JIRA_SUMMARY=$(python3 -c "
import json
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
print(d.get('fields', {}).get('summary', ''))
" 2>/dev/null || true)
  if echo "$JIRA_SUMMARY" | grep -qi "RHOAI"; then
    PRODUCT_CONTEXT="RHOAI"
  elif echo "$JIRA_SUMMARY" | grep -qi "ODH"; then
    PRODUCT_CONTEXT="ODH"
  fi
fi

if [[ -z "$PRODUCT_CONTEXT" ]]; then
  while true; do
    printf "I could not determine the product context from the Jira key or title.\nIs this onboarding for ODH or RHOAI? (ODH/RHOAI): "
    read -r PRODUCT_CONTEXT
    PRODUCT_CONTEXT="${PRODUCT_CONTEXT^^}"
    case "$PRODUCT_CONTEXT" in
      ODH|RHOAI) break ;;
      *) echo "  Invalid. Must be ODH or RHOAI." ;;
    esac
  done
fi

case "${PRODUCT_CONTEXT^^}" in
  ODH)
    CLUSTER_INSTANCE="external"
    KONFLUX_NAMESPACE="opendatahub-builds"
    SPARSE_PATHS="tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant tenants-config/auto-generated/cluster/stone-prd-rh01/tenants/open-data-hub-tenant"
    TARGET_YAML="tenants-config/cluster/stone-prd-rh01/tenants/open-data-hub-tenant/opendatahub-ci-components.yaml"
    KRD_APPLICATION="opendatahub-builds"
    QUAY_ORG="opendatahub"
    ;;
  RHOAI)
    CLUSTER_INSTANCE="internal"
    KONFLUX_NAMESPACE="rhoai-builds"
    SPARSE_PATHS="tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant tenants-config/auto-generated/cluster/stone-prod-p02/tenants/rhoai-tenant"
    TARGET_YAML="tenants-config/cluster/stone-prod-p02/tenants/rhoai-tenant/rhoai-ci-components.yaml"
    KRD_APPLICATION="rhoai-builds"
    QUAY_ORG="rhoai"
    ;;
  *)
    echo "ERROR in Step 4: Unknown PRODUCT_CONTEXT '${PRODUCT_CONTEXT}'. Expected ODH or RHOAI." >&2
    exit 1
    ;;
esac

# --- Step 5: Check If Konflux Component Already Exists ---
COMP_CHECK_EXIT=0
bash "$SCRIPTS_DIR/check_konflux_component.sh" \
  "$KONFLUX_COMPONENT_NAME" "$KONFLUX_NAMESPACE" "$CLUSTER_INSTANCE" || COMP_CHECK_EXIT=$?

if [[ "$COMP_CHECK_EXIT" -eq 0 ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "konflux-component-created" \
    --comment "Konflux Component '$KONFLUX_COMPONENT_NAME' already exists in namespace '$KONFLUX_NAMESPACE'. No action needed." || true
  echo "Konflux Component already exists. Nothing to do."
  exit 0
elif [[ "$COMP_CHECK_EXIT" -eq 2 ]]; then
  echo "ERROR in Step 5: Could not check Konflux component status. Check VPN and OC_TOKEN." >&2
  exit 1
fi
# Exit 1 = component does not exist, continue

# --- Step 6: Check for Existing Open MR in Jira Comments ---
MR_URL=""
EXISTING_MRS=$(python3 -c "
import json, re
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
comments = d.get('fields', {}).get('comment', {}).get('comments', [])
pattern = re.compile(r'https://gitlab\.cee\.redhat\.com/[^/\s]+/[^/\s]+/-/merge_requests/\d+')
urls = []
for c in comments:
    urls.extend(pattern.findall(c.get('body', '')))
seen = set()
for u in urls:
    if u not in seen:
        seen.add(u)
        print(u)
" 2>/dev/null || true)

while IFS= read -r mr_url; do
  [[ -z "$mr_url" ]] && continue
  CHECK_OUT=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/monitor_gitlab_mr.py" \
    --mr-url "$mr_url" --check-only 2>/dev/null || true)
  STATE=$(echo "$CHECK_OUT" | grep -o 'state=[a-z_]*' | cut -d= -f2 || true)
  TITLE=$(echo "$CHECK_OUT" | grep '^title=' | cut -d= -f2- || true)
  if [[ "$STATE" == "opened" ]] && \
     (echo "$TITLE" | grep -qF "$KONFLUX_COMPONENT_NAME" || echo "$TITLE" | grep -qF "$COMPONENT_NAME"); then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "Found existing open GitLab MR for $KONFLUX_COMPONENT_NAME: $mr_url. Monitoring it." || true
    echo "Found existing open MR: $mr_url. Skipping MR creation and jumping to monitor."
    MR_URL="$mr_url"
    break
  fi
done <<< "$EXISTING_MRS"

# --- Steps 7–9: Set up playpen, edit YAML, raise MR (skip if resuming existing MR) ---
if [[ -z "$MR_URL" ]]; then

  # --- Step 7: Set Up Playpen (Sparse Clone) ---
  eval "$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/run_gitlab_playpen.sh" \
    --src-url      "$KRD_URL" \
    --src-branch   main \
    --dest-branch  "${JIRA_ID}" \
    --sparse-files "$SPARSE_PATHS" \
    --workdir      "$WORKDIR" \
    --scripts-dir  "$SCRIPTS_DIR")" || {
    echo "ERROR in Step 7 (Playpen setup): Clone or push failed. See details above." >&2
    echo "  Check VPN connectivity and GITLAB_TOKEN write_repository scope." >&2
    exit 1
  }

  # --- Step 8: Modify the Target YAML File ---
  TARGET_FILE="$CLONE_DIR/$TARGET_YAML"

  if grep -qF "name: $KONFLUX_COMPONENT_NAME" "$TARGET_FILE" 2>/dev/null; then
    echo "Component entry '$KONFLUX_COMPONENT_NAME' already present in $TARGET_YAML — skipping append."
  else
    YAML_DOC="apiVersion: appstudio.redhat.com/v1alpha1
kind: Component
metadata:
  annotations:
    build.appstudio.openshift.io/request: configure-pac-no-mr
    mintmaker.appstudio.redhat.com/disabled: \"true\"
    build.appstudio.openshift.io/pipeline: '{\"name\":\"docker-build-multi-platform-oci-ta\",\"bundle\":\"latest\"}'
  name: ${KONFLUX_COMPONENT_NAME}
spec:
  application: ${KRD_APPLICATION}
  componentName: ${KONFLUX_COMPONENT_NAME}
  containerImage: quay.io/${QUAY_ORG}/${COMPONENT_NAME}
  source:
    git:
      context: ${CONTEXT_PATH}
      dockerfileUrl: ${DOCKERFILE_PATH}
      revision: ${REPO_BRANCH}
      url: ${REPO_URL}"

    uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-yaml-doc \
      "$TARGET_FILE" \
      --yaml-string "$YAML_DOC"
  fi

  # 8d. Run build-manifests.sh
  (cd "$CLONE_DIR/tenants-config" && ./build-manifests.sh "$KUSTOMIZE_BIN") || {
    echo "ERROR in Step 8d (build-manifests): Manifest generation failed. See output above." >&2
    exit 1
  }

  # 8e. Run yamllint
  (cd "$CLONE_DIR" && yamllint -s -f colored .gitlab-ci.yml .gitlab tenants-config/cluster) || {
    echo "ERROR in Step 8e (yamllint): YAML lint failed in $TARGET_FILE. Fix the errors above and re-run." >&2
    exit 1
  }

  # 8f. Stage and commit
  (cd "$CLONE_DIR" && git add -A && git commit -m "Add $KONFLUX_COMPONENT_NAME Component to konflux-release-data")

  # 8g. Run verify-manifests.sh
  (cd "$CLONE_DIR/tenants-config" && ./verify-manifests.sh "$KUSTOMIZE_BIN") || {
    echo "ERROR in Step 8g (verify-manifests): Manifest verification failed. Fix the errors above and re-run." >&2
    exit 1
  }

  # 8h. Push
  PUSH_ERR=$(mktemp)
  if ! (cd "$CLONE_DIR" && git push origin "$DEST_BRANCH") 2>"$PUSH_ERR"; then
    if grep -q "shallow update not allowed" "$PUSH_ERR"; then
      (cd "$CLONE_DIR" && git fetch --unshallow origin && git push origin "$DEST_BRANCH")
    else
      cat "$PUSH_ERR" >&2
      rm -f "$PUSH_ERR"
      echo "ERROR in Step 8h: Could not push branch '$DEST_BRANCH' to origin." >&2
      exit 1
    fi
  fi
  rm -f "$PUSH_ERR"

  # --- Step 9: Raise MR (up to 3 attempts) ---
  MR_ATTEMPTS=0
  while [[ $MR_ATTEMPTS -lt 3 && -z "$MR_URL" ]]; do
    MR_ATTEMPTS=$((MR_ATTEMPTS + 1))
    MR_ERR=$(mktemp)
    MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
      --src-url "$KRD_URL" \
      --src-branch "$DEST_BRANCH" \
      --dest-url "$KRD_URL" \
      --dest-branch main \
      --title "Add $KONFLUX_COMPONENT_NAME Component for $COMPONENT_NAME" \
      --description "Add Konflux Component '$KONFLUX_COMPONENT_NAME' to $TARGET_YAML.

Product: $PRODUCT_CONTEXT
Application: $KRD_APPLICATION
Container image: quay.io/$QUAY_ORG/$COMPONENT_NAME
Source repo: $REPO_URL @ $REPO_BRANCH
Jira: $JIRA_URL" 2>"$MR_ERR") || {
      cat "$MR_ERR" >&2
      rm -f "$MR_ERR"
      MR_URL=""
      if [[ $MR_ATTEMPTS -lt 3 ]]; then
        echo "MR creation attempt $MR_ATTEMPTS failed. Retrying..."
        sleep 5
      fi
      continue
    }
    rm -f "$MR_ERR"
  done

  if [[ -z "$MR_URL" ]]; then
    echo "ERROR in Step 9 (Raise MR): Could not create MR after 3 attempts. See errors above. Aborting." >&2
    exit 1
  fi

  echo "MR raised: $MR_URL"
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "konflux-mr-raised" \
    --comment "GitLab MR raised to create Konflux Component '$KONFLUX_COMPONENT_NAME'.

MR URL: $MR_URL

The Component will be provisioned on the Konflux cluster once this MR is merged." || true

fi  # end of Steps 7–9

# Write MR URL for parent orchestrator
echo "$MR_URL" > "$WORKDIR/krd_mr_url"

# --- Step 10: Monitor MR ---
MONITOR_RESULT=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/monitor_gitlab_mr.py" \
  --mr-url "$MR_URL" \
  --timeout 60 2>/dev/null || echo "timeout")

case "$MONITOR_RESULT" in
  *merged*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --remove-label "konflux-mr-raised" \
      --comment "MR merged: $MR_URL

Konflux GitOps pipeline is provisioning Component '$KONFLUX_COMPONENT_NAME' on the cluster.
Monitoring for creation..." || true
    echo "MR merged. Proceeding to verify Konflux Component creation..."
    ;;
  *closed*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "GitLab MR was closed without merging: $MR_URL

Please review the MR and re-run /onboard-component-to-konflux-release-data if needed." || true
    echo "ERROR in Step 10 (Monitor MR): MR was closed without merging. Check the MR: $MR_URL." >&2
    exit 1
    ;;
  *pipeline_failed*|*pipeline_canceled*)
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "Pipeline failed on MR $MR_URL.

Please review the MR pipeline and re-run /onboard-component-to-konflux-release-data if the issue persists." || true
    echo "ERROR in Step 10 (Monitor MR): Pipeline failed. Manual intervention needed." >&2
    echo "  MR: $MR_URL" >&2
    exit 1
    ;;
  *)
    # timeout
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "MR monitoring timed out after 60 minutes. MR is still open: $MR_URL

Please check the MR status manually. Re-run /onboard-component-to-konflux-release-data
to resume — it will skip MR creation and jump straight to monitoring." || true
    echo "WARNING: MR monitoring timed out after 60 minutes."
    echo "The MR is still open: $MR_URL"
    echo "Re-run this skill when the MR is merged (it will short-circuit at Step 6)."
    exit 1
    ;;
esac

# --- Step 11: Monitor Konflux Component Creation ---
bash "$SCRIPTS_DIR/monitor_konflux_component.sh" \
  --component-name   "$KONFLUX_COMPONENT_NAME" \
  --namespace        "$KONFLUX_NAMESPACE" \
  --cluster-instance "$CLUSTER_INSTANCE" \
  --scripts-dir      "$SCRIPTS_DIR" \
  --jira-url         "$JIRA_URL" \
  --mr-url           "$MR_URL"
