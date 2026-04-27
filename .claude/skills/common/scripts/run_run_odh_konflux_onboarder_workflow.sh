#!/usr/bin/env bash
# Main script for the run-odh-konflux-onboarder-workflow skill.
# Triggers the odh-konflux-onboarder GitHub Actions workflow, monitors it,
# extracts the Tekton PR URL, and optionally updates Jira.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Step 0: Parse Inputs and Resolve URLs ---
eval "$(bash "$SCRIPTS_DIR/setup_okc_workflow.sh" "${1:-}")"
# Sets: JIRA_URL, JIRA_ID, OKC_URL, OKC_PATH, OKC_REF, WORKFLOW_FILE

# --- Step 1: Check Prerequisites ---
bash "$SCRIPTS_DIR/check_prerequisites.sh" --env "GITHUB_USER GITHUB_TOKEN" --tools "uv"
if [[ -n "$JIRA_URL" ]]; then
  bash "$SCRIPTS_DIR/check_prerequisites.sh" --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi

# --- Step 2: Set Up Working Directory ---
eval "$(bash "$SCRIPTS_DIR/setup_workdir.sh" \
  --jira-id "${JIRA_ID:-}" \
  --yaml-filename "component_onboarding_details.yaml")"
# Sets: WORKDIR, YAML_PATH

# --- Step 3: Collect Component Inputs ---
PRODUCT_CONTEXT=""
COMPONENT=""
PR_TARGET_BRANCH=""
BUILD_TYPE=""
VERSION=""

if [[ -n "$JIRA_URL" ]]; then
  # Branch A — Jira URL provided
  if [[ ! -f "$WORKDIR/component_onboarding_details.json" ]]; then
    cd "$WORKDIR"
    uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$JIRA_URL" || {
      echo "ERROR in Step 3 (Fetch Jira): Could not fetch Jira issue. See above. Aborting." >&2
      exit 1
    }
  fi
  if [[ ! -f "$YAML_PATH" ]]; then
    cd "$WORKDIR"
    uv run --script "$SCRIPTS_DIR/download_jira_attachment.py" \
        "$JIRA_URL" component_onboarding_details.yaml || {
      echo "ERROR in Step 3 (Download YAML): 'component_onboarding_details.yaml' not found as Jira attachment." >&2
      echo "  Please attach the file to the Jira issue and re-run." >&2
      exit 1
    }
  fi
fi

if [[ -f "$YAML_PATH" ]]; then
  # Parse YAML (Branch A, or YAML exists from prior run)
  if [[ -z "$JIRA_URL" ]]; then
    echo "Found component_onboarding_details.yaml in current directory. Reading inputs from file."
    echo "(Delete or rename it to use interactive mode instead.)"
  fi
  _parse() { python3 -c "
import yaml, sys
with open('$YAML_PATH') as f:
    d = yaml.safe_load(f)
inp = d.get('inputs', {})
print(inp.get('$1', ''))
" 2>/dev/null; }
  PRODUCT_CONTEXT="$(_parse product_context)"
  REPO_URL="$(_parse repo_url)"
  PR_TARGET_BRANCH="$(_parse repo_branch)"
  BUILD_TYPE="$(_parse build_type)"
  VERSION="$(_parse output_image_tag)"

  # Derive COMPONENT from REPO_URL
  REPO_NAME="${REPO_URL##*/}"
  COMPONENT="${REPO_NAME%.git}"

  # Normalize BUILD_TYPE
  BUILD_TYPE_LOWER="${BUILD_TYPE,,}"
  if [[ "$BUILD_TYPE_LOWER" == "ci" ]]; then
    BUILD_TYPE="CI"
  elif [[ "$BUILD_TYPE_LOWER" == "release" ]]; then
    BUILD_TYPE="Release"
  elif [[ -n "$BUILD_TYPE" ]]; then
    echo "ERROR in Step 3: Unknown build_type '${BUILD_TYPE}'. Expected CI or Release." >&2
    exit 1
  fi

  # Validate required fields
  for field_check in "PRODUCT_CONTEXT:product_context" "REPO_URL:repo_url" "PR_TARGET_BRANCH:repo_branch" "BUILD_TYPE:build_type"; do
    var="${field_check%%:*}"
    key="${field_check##*:}"
    if [[ -z "${!var:-}" ]]; then
      echo "ERROR in Step 3: Required field '${key}' is missing from component_onboarding_details.yaml." >&2
      exit 1
    fi
  done

  if [[ "$BUILD_TYPE" == "Release" && -z "$VERSION" ]]; then
    echo "ERROR in Step 3: build_type is Release but 'inputs.output_image_tag' is missing." >&2
    echo "  Add 'output_image_tag: <version>' under inputs: and re-run." >&2
    exit 1
  fi

else
  # Branch B — Interactive Q&A
  # B1: Product context
  while true; do
    printf "Which product is this component being onboarded for? (ODH/RHOAI): "
    read -r PRODUCT_CONTEXT
    PRODUCT_CONTEXT="${PRODUCT_CONTEXT^^}"
    case "$PRODUCT_CONTEXT" in
      ODH|RHOAI) break ;;
      *) echo "  Invalid. Must be ODH or RHOAI." ;;
    esac
  done

  # B2: Component (repo name)
  while true; do
    printf "What is the GitHub repository name of the component? (e.g. opendatahub-operator): "
    read -r COMPONENT
    if [[ "$COMPONENT" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
      break
    else
      echo "  Invalid: must match ^[a-z0-9]+(-[a-z0-9]+)*$ (kebab-case, lowercase only)."
    fi
  done

  # B3: PR target branch
  while true; do
    printf "What is the branch to onboard the component into? (e.g. main): "
    read -r PR_TARGET_BRANCH
    [[ -n "$PR_TARGET_BRANCH" ]] && break
    echo "  Branch cannot be empty."
  done

  # B4: Build type
  while true; do
    printf "Should this be a CI or Release build? (CI/Release): "
    read -r BUILD_TYPE
    case "$BUILD_TYPE" in
      CI|ci) BUILD_TYPE="CI"; break ;;
      Release|release|RELEASE) BUILD_TYPE="Release"; break ;;
      *) echo "  Invalid. Must be CI or Release." ;;
    esac
  done

  # B5: Version (Release only)
  if [[ "$BUILD_TYPE" == "Release" ]]; then
    while true; do
      printf "What is the version string for this release build? (e.g. 2.21.0): "
      read -r VERSION
      [[ -n "$VERSION" ]] && break
      echo "  Version cannot be empty for Release builds."
    done
  fi
fi

# Product context gate
if [[ "${PRODUCT_CONTEXT^^}" == "RHOAI" ]]; then
  echo "ERROR: This workflow is for ODH component onboarding only." >&2
  echo "  RHOAI onboarding uses a different process. Aborting." >&2
  exit 1
fi

# --- Step 4: Show Collected Inputs and Confirm ---
echo ""
echo "Workflow inputs collected:"
echo ""
echo "  OKC repo              : $OKC_URL"
echo "  Workflow file         : $WORKFLOW_FILE"
echo "  Dispatch ref          : $OKC_REF"
echo ""
echo "  component             : $COMPONENT"
echo "  pr_target_branch      : $PR_TARGET_BRANCH"
echo "  build_type            : $BUILD_TYPE"
echo "  version               : ${VERSION:-N/A}"
echo "  product_context       : $PRODUCT_CONTEXT"
echo ""

while true; do
  printf "Proceed? (yes/no): "
  read -r CONFIRM
  case "$CONFIRM" in
    yes|y) break ;;
    no|n)  echo "Aborted by user."; exit 0 ;;
    *)     echo "  Please answer yes or no." ;;
  esac
done

# --- Step 5: Idempotency Check (only when Jira URL provided) ---
TEKTON_PR_URL=""
RUN_ID=""

if [[ -n "$JIRA_URL" && -f "$WORKDIR/component_onboarding_details.json" ]]; then
  EXISTING_PRS=$(python3 -c "
import json, re
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
comments = d.get('fields', {}).get('comment', {}).get('comments', [])
pattern = re.compile(r'https://github\.com/[^/\s]+/[^/\s]+/pull/\d+')
urls = []
for c in comments:
    urls.extend(pattern.findall(c.get('body', '')))
print(' '.join(set(urls)))
" 2>/dev/null || true)

  for pr_url in $EXISTING_PRS; do
    CHECK_OUT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
      --pr-url "$pr_url" --check-only 2>/dev/null || true)
    STATE=$(echo "$CHECK_OUT" | grep -o 'state=[a-z_]*' | cut -d= -f2)
    if [[ "$STATE" == "open" || "$STATE" == "merged" ]]; then
      echo "Found existing Tekton PR: $pr_url (state=$STATE)"
      echo "This PR appears to be from a previous workflow run for this component."
      while true; do
        printf "Jump to monitoring this PR instead of triggering a new run? (yes/no): "
        read -r JUMP
        case "$JUMP" in
          yes|y) TEKTON_PR_URL="$pr_url"; break 2 ;;
          no|n)  break ;;
          *)     echo "  Please answer yes or no." ;;
        esac
      done
    fi
  done
fi

# If we jumped to Step 9 via idempotency check, skip triggering
if [[ -z "$TEKTON_PR_URL" ]]; then
  # --- Step 6: Trigger the Workflow ---
  cd "$WORKDIR"
  TRIGGER_INPUTS=(
    "--input" "component=${COMPONENT}"
    "--input" "pr_target_branch=${PR_TARGET_BRANCH}"
    "--input" "build_type=${BUILD_TYPE}"
  )
  [[ "$BUILD_TYPE" == "Release" ]] && TRIGGER_INPUTS+=("--input" "version=${VERSION}")

  TRIGGER_ERR=$(mktemp)
  if ! RUN_ID=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" trigger \
      --repo-url "$OKC_URL" \
      --workflow "$WORKFLOW_FILE" \
      --ref "$OKC_REF" \
      "${TRIGGER_INPUTS[@]}" 2>"$TRIGGER_ERR"); then
    ERR_BODY=$(cat "$TRIGGER_ERR")
    rm -f "$TRIGGER_ERR"
    if echo "$ERR_BODY" | grep -q "422\|inputs"; then
      echo "ERROR in Step 6 (Trigger): Workflow dispatch rejected (HTTP 422)." >&2
      echo "  Most likely: '$COMPONENT' is not yet in the workflow's component options list." >&2
      echo "  Ensure the Step 4 PR (add-component-to-odh-konflux-central) is merged first." >&2
    elif echo "$ERR_BODY" | grep -q "403"; then
      echo "ERROR in Step 6 (Trigger): Permission denied (HTTP 403)." >&2
      echo "  GITHUB_TOKEN needs 'actions:write' scope." >&2
    else
      echo "$ERR_BODY" >&2
      echo "ERROR in Step 6 (Trigger): Could not dispatch workflow. See above. Aborting." >&2
    fi
    exit 1
  fi
  rm -f "$TRIGGER_ERR"

  echo "Workflow run triggered."
  echo "  Run ID   : $RUN_ID"
  echo "  Run URL  : https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}"

  if [[ -n "$JIRA_URL" ]]; then
    uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --comment "odh-konflux-onboarder workflow triggered (Run #${RUN_ID}).

Component       : $COMPONENT
PR target branch: $PR_TARGET_BRANCH
Build type      : $BUILD_TYPE${VERSION:+
Version         : $VERSION}

Workflow run: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Monitoring in progress (max 30 minutes)..." || true
  fi

  # --- Step 7: Monitor Workflow (30 minutes max) ---
  _retrigger_count=0
  while true; do
    MONITOR_OUTPUT=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" monitor \
      --repo-url "$OKC_URL" \
      --run-id "$RUN_ID" \
      --timeout 30 \
      --poll-interval 60 2>/dev/null || true)
    WORKFLOW_STATUS="${MONITOR_OUTPUT#status=}"

    if [[ "$WORKFLOW_STATUS" == "success" ]]; then
      echo "Workflow run $RUN_ID completed successfully."
      break
    elif [[ "$WORKFLOW_STATUS" == "cancelled" ]]; then
      echo "ERROR in Step 7: Workflow run $RUN_ID was cancelled." >&2
      echo "Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}" >&2
      exit 1
    elif [[ "$WORKFLOW_STATUS" == "timeout" ]]; then
      echo "WARNING: Workflow run $RUN_ID has not completed after 30 minutes."
      echo "Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}"
      echo "The run may still be in progress. Re-run this skill to resume."
      if [[ -n "$JIRA_URL" ]]; then
        uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
          --comment "odh-konflux-onboarder workflow run #${RUN_ID} monitoring timed out after 30 minutes.

The run may still be completing. Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Re-run /run-odh-konflux-onboarder-workflow — it will detect the existing PR and resume." || true
      fi
      exit 1
    else
      # failure
      FAILURE_LOGS=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" get-step-logs \
        --repo-url "$OKC_URL" \
        --run-id "$RUN_ID" \
        --step "Run onboarder" 2>/dev/null || true)

      echo "Workflow run $RUN_ID FAILED."
      echo "Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}"
      echo ""
      echo "Log excerpt:"
      if [[ -n "$FAILURE_LOGS" ]]; then
        echo "$FAILURE_LOGS" | head -60
      else
        echo "(could not fetch logs)"
      fi
      echo ""

      if [[ "$_retrigger_count" -ge 1 ]]; then
        if [[ -n "$JIRA_URL" ]]; then
          uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
            --comment "odh-konflux-onboarder workflow run #${RUN_ID} FAILED on second attempt.

Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Please inspect the run logs and re-run /run-odh-konflux-onboarder-workflow to retry." || true
        fi
        echo "ERROR in Step 7: Workflow failed on second attempt. Manual investigation required." >&2
        echo "Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}" >&2
        exit 1
      fi

      while true; do
        printf "Would you like to re-trigger the workflow with the same inputs? (yes/no): "
        read -r RETRIGGER
        case "$RETRIGGER" in
          yes|y)
            _retrigger_count=$((_retrigger_count + 1))
            RUN_ID=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" trigger \
              --repo-url "$OKC_URL" \
              --workflow "$WORKFLOW_FILE" \
              --ref "$OKC_REF" \
              "${TRIGGER_INPUTS[@]}")
            echo "Re-triggered workflow. New run ID: $RUN_ID"
            break
            ;;
          no|n)
            if [[ -n "$JIRA_URL" ]]; then
              uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
                --comment "odh-konflux-onboarder workflow run #${RUN_ID} FAILED.

Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}

Please inspect the run logs and re-run /run-odh-konflux-onboarder-workflow to retry." || true
            fi
            echo "ERROR in Step 7: Workflow run $RUN_ID failed. See logs above." >&2
            exit 1
            ;;
          *) echo "  Please answer yes or no." ;;
        esac
      done
    fi
  done

  # --- Step 8: Extract Tekton PR URL from Workflow Logs ---
  _step_names=("Create pull request" "create-pull-request" "Create PR" "pull request")
  STEP_LOGS=""
  for step_name in "${_step_names[@]}"; do
    STEP_LOGS=$(uv run --script "$SCRIPTS_DIR/run_github_workflow.py" get-step-logs \
      --repo-url "$OKC_URL" \
      --run-id "$RUN_ID" \
      --step "$step_name" 2>/dev/null || true)
    [[ -n "$STEP_LOGS" ]] && break
  done

  if [[ -n "$STEP_LOGS" ]]; then
    TEKTON_PR_URL=$(echo "$STEP_LOGS" \
      | grep -oE 'https://github\.com/[^/]+/[^/]+/pull/[0-9]+' \
      | head -1 || true)
  fi

  if [[ -z "$TEKTON_PR_URL" ]]; then
    if [[ -n "$STEP_LOGS" ]]; then
      echo "Could not auto-extract a PR URL from the step logs:"
      echo "$STEP_LOGS"
    else
      echo "WARNING: Could not locate the 'Create pull request' step in run $RUN_ID."
      echo "Run URL: https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}"
      echo ""
      echo "Please open the run in GitHub and locate the PR URL from the step logs."
    fi
    while true; do
      printf "Paste the PR URL here (or type 'skip' to exit): "
      read -r USER_PR_URL
      if [[ "$USER_PR_URL" == "skip" ]]; then
        echo "Stopped at Step 8. Re-run /run-odh-konflux-onboarder-workflow when you have the PR URL."
        exit 0
      elif [[ "$USER_PR_URL" =~ ^https://github\.com/.+/pull/[0-9]+$ ]]; then
        TEKTON_PR_URL="$USER_PR_URL"
        break
      else
        echo "  Invalid URL format. Expected: https://github.com/org/repo/pull/123"
      fi
    done
  fi

  echo "Tekton PR URL: $TEKTON_PR_URL"
fi  # end of trigger+monitor block

# --- Step 9: Update Jira with PR URL ---
if [[ -n "$JIRA_URL" ]]; then
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "tekton-pr-raised" \
    --comment "odh-konflux-onboarder workflow completed successfully.

Tekton PR raised: $TEKTON_PR_URL

Component        : $COMPONENT
PR target branch : $PR_TARGET_BRANCH
Build type       : $BUILD_TYPE${VERSION:+
Version          : $VERSION}
Workflow run     : ${RUN_ID:+https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}}

Monitoring the PR for merge..." || echo "WARNING: Could not update Jira — continuing." >&2
fi

# --- Step 10: Monitor the Tekton PR ---
PR_RESULT=$(uv run --script "$SCRIPTS_DIR/monitor_github_pr.py" \
  --pr-url "$TEKTON_PR_URL" \
  --timeout 60 2>/dev/null || echo "timeout")

case "$PR_RESULT" in
  *merged*)
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --remove-label "tekton-pr-raised" \
        --add-label "tekton-pr-merged" \
        --comment "Tekton PR merged: $TEKTON_PR_URL

Konflux CI pipeline definitions for '$COMPONENT' are now live on '$PR_TARGET_BRANCH'.

Step 6 (Run CI/Nightly Build) is complete." || true
    fi
    echo "PR merged. Step 6 (Run CI/Nightly Build) complete."
    ;;
  *closed*)
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "Tekton PR was closed without merging: $TEKTON_PR_URL

Please review and re-trigger if needed." || true
    fi
    echo "ERROR in Step 10: PR was closed without merging." >&2
    echo "PR: $TEKTON_PR_URL" >&2
    exit 1
    ;;
  *pipeline_failed*|*pipeline_canceled*)
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "CI checks failed on Tekton PR: $TEKTON_PR_URL

Please review the PR checks and push a fix, then re-run this skill to resume monitoring." || true
    fi
    echo "ERROR in Step 10: CI checks failed on PR $TEKTON_PR_URL." >&2
    echo "Manual intervention required — review the PR and push a fix, then re-run." >&2
    exit 1
    ;;
  *)
    # timeout
    if [[ -n "$JIRA_URL" ]]; then
      uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
        --comment "PR monitoring timed out after 60 minutes. PR is still open: $TEKTON_PR_URL

Re-run /run-odh-konflux-onboarder-workflow to resume — at Step 5 it will detect the existing PR and jump straight to monitoring." || true
    fi
    echo "WARNING: PR monitoring timed out after 60 minutes."
    echo "PR is still open: $TEKTON_PR_URL"
    echo "Re-run this skill to resume monitoring (Step 5 will skip triggering a new run)."
    ;;
esac

# --- Step 11: Final Status Report ---
echo ""
echo "=== run-odh-konflux-onboarder-workflow complete ==="
echo ""
echo "  Component             : $COMPONENT"
echo "  PR target branch      : $PR_TARGET_BRANCH"
echo "  Build type            : $BUILD_TYPE"
[[ -n "$VERSION" ]] && echo "  Version               : $VERSION"
echo ""
[[ -n "$RUN_ID" ]] && echo "  Workflow run          : https://github.com/${OKC_PATH}/actions/runs/${RUN_ID}"
echo "  Tekton PR             : $TEKTON_PR_URL (merged)"
echo "  Jira updated          : ${JIRA_URL:-(no Jira URL provided)}"
echo ""
echo "Step 6 (Run CI/Nightly Build) complete."
