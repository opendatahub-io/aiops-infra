#!/usr/bin/env bash
# Main script for the create-quay-repo skill.
# Creates a Quay repository via a GitOps MR to app-interface.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Step 0: Parse Inputs ---
QUAY_REPO_ARG=""
JIRA_URL=""
VISIBILITY_OVERRIDE=""
WORKDIR_OVERRIDE=""
SPARSE_FILE_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jira-url)   JIRA_URL="$2"; shift 2 ;;
    --visibility) VISIBILITY_OVERRIDE="$2"; shift 2 ;;
    --workdir)    WORKDIR_OVERRIDE="$2"; shift 2 ;;
    --sparse-file) SPARSE_FILE_OVERRIDE="$2"; shift 2 ;;
    --*) echo "Unknown flag: $1" >&2; exit 1 ;;
    *)
      if [[ -z "$QUAY_REPO_ARG" ]]; then
        QUAY_REPO_ARG="$1"
      else
        echo "Unexpected positional argument: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$QUAY_REPO_ARG" ]]; then
  echo "Usage: $(basename "$0") <quay-repo> [--jira-url <url>] [--visibility public|private] [--workdir <path>] [--sparse-file <path>]" >&2
  echo "  Example: $(basename "$0") quay.io/opendatahub/my-component --jira-url https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

# Strip quay.io/ prefix and split org/repo
QUAY_REPO_ARG="${QUAY_REPO_ARG#quay.io/}"
if [[ "$QUAY_REPO_ARG" != */* ]]; then
  echo "ERROR: Invalid quay repo format. Expected \`quay.io/<org>/<repo>\` or \`<org>/<repo>\`." >&2
  exit 1
fi
QUAY_ORG="${QUAY_REPO_ARG%%/*}"
QUAY_REPO="${QUAY_REPO_ARG#*/}"
if [[ -z "$QUAY_ORG" || -z "$QUAY_REPO" || "$QUAY_REPO" == */* ]]; then
  echo "ERROR: Invalid quay repo format. Expected \`quay.io/<org>/<repo>\` or \`<org>/<repo>\`." >&2
  exit 1
fi

# Determine visibility
if [[ -n "$VISIBILITY_OVERRIDE" ]]; then
  VISIBILITY="$VISIBILITY_OVERRIDE"
elif [[ "$QUAY_ORG" == "rhoai" ]]; then
  VISIBILITY="private"
else
  VISIBILITY="public"
fi

# Extract Jira ID
JIRA_ID=""
if [[ -n "$JIRA_URL" ]]; then
  if [[ "$JIRA_URL" != *"/browse/"* ]]; then
    echo "ERROR: Invalid Jira URL format. Expected https://redhat.atlassian.net/browse/JIRA-1234" >&2
    exit 1
  fi
  JIRA_ID="${JIRA_URL##*/}"
fi

APP_INTERFACE_URL="${APP_INTERFACE_REPO_URL:-https://gitlab.cee.redhat.com/service/app-interface}"

# --- Step 1: Check Prerequisites ---
bash "$SCRIPTS_DIR/check_prerequisites.sh" \
  --env   "GITLAB_USER GITLAB_TOKEN" \
  --tools "uv skopeo"

if [[ -n "$JIRA_URL" ]]; then
  bash "$SCRIPTS_DIR/check_prerequisites.sh" \
    --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi

# --- Step 2: Create Working Directory ---
if [[ -n "$WORKDIR_OVERRIDE" ]]; then
  WORKDIR="$WORKDIR_OVERRIDE"
elif [[ -n "$JIRA_ID" ]]; then
  WORKDIR="$(pwd)/${JIRA_ID}"
else
  WORKDIR="$(pwd)/quay-${QUAY_ORG}-${QUAY_REPO}"
fi
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"

# --- Step 3: Check If Quay Repo Already Exists ---
QUAY_CHECK_EXIT=0
bash "$SCRIPTS_DIR/check_quay_repo.sh" "quay.io/${QUAY_ORG}/${QUAY_REPO}" || QUAY_CHECK_EXIT=$?

if [[ "$QUAY_CHECK_EXIT" -eq 0 ]]; then
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "quay-repo-created" \
      --comment "Quay repo quay.io/${QUAY_ORG}/${QUAY_REPO} already exists. No action needed." || true
  fi
  echo "Quay repo quay.io/${QUAY_ORG}/${QUAY_REPO} already exists. Nothing to do."
  exit 0
elif [[ "$QUAY_CHECK_EXIT" -ge 2 ]]; then
  echo "ERROR in Step 3: Could not check Quay repo status. See output above." >&2
  exit 1
fi
# Exit 1 = repo does not exist, continue

# --- Step 4: Check for Existing Open MR in Jira Comments ---
MR_URL=""
JSON_FILE="$WORKDIR/component_onboarding_details.json"

if [[ -f "$JSON_FILE" ]]; then
  EXISTING_MRS=$(python3 -c "
import json, re
with open('$JSON_FILE') as f:
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
    if [[ "$STATE" == "opened" ]] && echo "$TITLE" | grep -qF "$QUAY_REPO"; then
      if [[ -n "$JIRA_URL" ]]; then
        uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
          --comment "Found existing open GitLab MR for quay.io/${QUAY_ORG}/${QUAY_REPO}: $mr_url. Monitoring it." || true
      fi
      echo "Found existing open MR: $mr_url. Skipping MR creation and jumping to monitor step."
      MR_URL="$mr_url"
      break
    fi
  done <<< "$EXISTING_MRS"
fi

# --- Steps 5–9: Fork, clone, edit, commit, raise MR (skip if resuming existing MR) ---
if [[ -z "$MR_URL" ]]; then

  # --- Step 5: Fork app-interface ---
  FORK_URL=$(uv run --script "$SCRIPTS_DIR/setup_gitlab_fork.py" \
    --gitlab-repo-url "$APP_INTERFACE_URL" 2>&1) || {
    echo "ERROR in Step 5 (Fork app-interface): Could not fork the repository. See details above. Aborting." >&2
    exit 1
  }

  # --- Step 6: Determine Sparse File Path ---
  if [[ -n "$SPARSE_FILE_OVERRIDE" ]]; then
    SPARSE_FILE="$SPARSE_FILE_OVERRIDE"
  else
    case "$QUAY_ORG" in
      opendatahub) SPARSE_FILE="data/services/rhoai/quay/opendatahub.yml" ;;
      rhoai)       SPARSE_FILE="data/services/rhoai/quay/rhoai.yml" ;;
      modh)        SPARSE_FILE="data/services/rhoai/quay/modh.yml" ;;
      *)
        while true; do
          printf "I need the path to the quay config YAML within app-interface for the org '%s'.\nThis is typically under data/services/rhoai/quay/%s.yml.\nWhat is the correct path? " "$QUAY_ORG" "$QUAY_ORG"
          read -r SPARSE_FILE
          [[ -n "$SPARSE_FILE" ]] && break
          echo "  Path cannot be empty."
        done
        ;;
    esac
  fi

  DEST_BRANCH="${JIRA_ID:-}"

  # --- Step 7: Set Up Playpen (Sparse Clone) ---
  eval "$(GITLAB_SSL_VERIFY=false bash "$SCRIPTS_DIR/run_gitlab_playpen.sh" \
    --src-url      "$APP_INTERFACE_URL" \
    --dest-url     "$FORK_URL" \
    --src-branch   master \
    --sparse-files "$SPARSE_FILE" \
    --dest-branch  "${DEST_BRANCH}" \
    --workdir      "$WORKDIR" \
    --scripts-dir  "$SCRIPTS_DIR")" || {
    echo "ERROR in Step 7 (Playpen setup): Clone or push failed. See details above. Aborting." >&2
    exit 1
  }

  # --- Step 8: Modify YAML File ---
  YAML_FILE="$CLONE_DIR/$SPARSE_FILE"
  if [[ ! -f "$YAML_FILE" ]]; then
    echo "ERROR in Step 8: $SPARSE_FILE not found in clone. Verify APP_INTERFACE_URL and sparse file path." >&2
    exit 1
  fi

  PUBLIC_VALUE="true"
  [[ "$VISIBILITY" == "private" ]] && PUBLIC_VALUE="false"

  uv run --script "$SCRIPTS_DIR/edit_yaml.py" append-items-array \
    "$YAML_FILE" \
    --name "$QUAY_REPO" \
    --description "${QUAY_ORG} ${QUAY_REPO} container image" \
    $([ "$PUBLIC_VALUE" == "true" ] && echo "--public" || true)

  # --- Step 9: Commit and Raise MR (up to 3 attempts) ---
  # Determine remote name
  if [[ "$FORK_URL" != "$APP_INTERFACE_URL" ]]; then
    DEST_REMOTE="dest"
  else
    DEST_REMOTE="origin"
  fi

  (cd "$CLONE_DIR" && git add "$SPARSE_FILE" && git commit -m "Add ${QUAY_REPO} to quay ${QUAY_ORG} config")

  PUSH_ERR=$(mktemp)
  if ! (cd "$CLONE_DIR" && git push "$DEST_REMOTE" "$DEST_BRANCH") 2>"$PUSH_ERR"; then
    if grep -q "already exists\|non-fast-forward\|rejected" "$PUSH_ERR"; then
      (cd "$CLONE_DIR" && git push --force-with-lease "$DEST_REMOTE" "$DEST_BRANCH")
    else
      cat "$PUSH_ERR" >&2
      rm -f "$PUSH_ERR"
      echo "ERROR in Step 9: Could not push branch '$DEST_BRANCH' to remote." >&2
      exit 1
    fi
  fi
  rm -f "$PUSH_ERR"

  MR_ATTEMPTS=0
  while [[ $MR_ATTEMPTS -lt 3 && -z "$MR_URL" ]]; do
    MR_ATTEMPTS=$((MR_ATTEMPTS + 1))
    MR_ERR=$(mktemp)
    MR_URL=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/raise_gitlab_mr.py" \
      --src-url "$FORK_URL" \
      --src-branch "$DEST_BRANCH" \
      --dest-url "$APP_INTERFACE_URL" \
      --dest-branch master \
      --title "Add ${QUAY_REPO} quay repository for ${QUAY_ORG}" \
      --description "Add quay.io/${QUAY_ORG}/${QUAY_REPO} to app-interface GitOps config.

Visibility: $VISIBILITY
Jira: ${JIRA_URL:-N/A}" 2>"$MR_ERR") || {
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
    echo "ERROR in Step 9 (Raise MR): Could not create merge request after 3 attempts. See errors above. Aborting." >&2
    exit 1
  fi

  echo "MR raised: $MR_URL"
  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --add-label "quay-mr-raised" \
      --comment "GitLab MR raised to create quay.io/${QUAY_ORG}/${QUAY_REPO}.

MR URL: $MR_URL

The Quay repo will be created automatically once this MR is merged." || true
  fi

  # Write MR URL for parent orchestrator
  echo "$MR_URL" > "$WORKDIR/quay_mr_url"

fi  # end of Steps 5–9

# --- Step 10: Monitor MR ---
MONITOR_RESULT=$(GITLAB_SSL_VERIFY=false uv run --script "$SCRIPTS_DIR/monitor_gitlab_mr.py" \
  --mr-url "$MR_URL" \
  --timeout 60 2>/dev/null || echo "timeout")

case "$MONITOR_RESULT" in
  *merged*)
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --remove-label "quay-mr-raised" \
        --comment "MR merged: $MR_URL

app-interface GitOps reconciliation is in progress. Monitoring quay.io/${QUAY_ORG}/${QUAY_REPO} for creation..." || true
    fi
    echo "MR merged: $MR_URL"
    echo "Proceeding to monitor Quay repo creation..."
    ;;
  *closed*)
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "GitLab MR was closed without merging: $MR_URL

Please review the MR and re-run /create-quay-repo if needed." || true
    fi
    echo "ERROR in Step 10 (Monitor MR): MR was closed without merging. Check the MR: $MR_URL. Aborting." >&2
    exit 1
    ;;
  *pipeline_failed*|*pipeline_canceled*)
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "Pipeline failed on GitLab MR: $MR_URL

Check the pipeline failures reported above and fix them, then re-run /create-quay-repo." || true
    fi
    echo "ERROR in Step 10 (Monitor MR): Pipeline failed. Fix the pipeline issues and retry. MR: $MR_URL. Aborting." >&2
    exit 1
    ;;
  *)
    # timeout
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "Monitoring timed out after 60 minutes. MR is still open: $MR_URL

Please check the MR status manually and re-run /create-quay-repo if needed." || true
    fi
    echo "WARNING: MR monitoring timed out after 60 minutes."
    echo "The MR is still open: $MR_URL"
    echo "Check it manually and re-run this skill when the MR is merged (it will short-circuit at Step 3)."
    exit 1
    ;;
esac

# --- Step 11: Monitor Quay Repo Creation ---
bash "$SCRIPTS_DIR/monitor_quay_repo.sh" \
  --quay-repo   "quay.io/${QUAY_ORG}/${QUAY_REPO}" \
  --scripts-dir "$SCRIPTS_DIR" \
  --jira-url    "${JIRA_URL:-}" \
  --mr-url      "$MR_URL"
