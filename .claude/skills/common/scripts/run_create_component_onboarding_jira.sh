#!/usr/bin/env bash
# Main script for the create-component-onboarding-jira skill.
# Interactively collects component onboarding parameters, generates a validated
# component_onboarding_details.yaml, and attaches it to the Jira ticket.
set -uo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_PATH="${SCRIPTS_DIR}/../../validate-component-onboarding-jira/assets/component_onboarding_details.schema.json"
TEMPLATE_JIRA_URL="https://redhat.atlassian.net/browse/RHOAIENG-35683"

# --- Step 0: Parse Inputs and Check Prerequisites ---
JIRA_URL="${1:-}"
JIRA_ID=""

if [[ -n "$JIRA_URL" ]]; then
  if [[ "$JIRA_URL" != *"/browse/"* ]]; then
    echo "ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
    exit 1
  fi
  JIRA_ID="${JIRA_URL##*/}"
fi

bash "$SCRIPTS_DIR/check_prerequisites.sh" --tools "uv"
if [[ -n "$JIRA_URL" ]]; then
  bash "$SCRIPTS_DIR/check_prerequisites.sh" --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
fi

# --- Step 1: Set Up Working Directory ---
if [[ -n "$JIRA_ID" ]]; then
  WORKDIR="$(pwd)/${JIRA_ID}"
else
  WORKDIR="$(pwd)"
fi
mkdir -p "$WORKDIR"
YAML_PATH="${WORKDIR}/component_onboarding_details.yaml"
echo "Working directory: $WORKDIR"

# --- Step 2: Fetch Jira Details (only when JIRA_URL is non-empty) ---
JIRA_SUMMARY=""
JIRA_DESCRIPTION=""

if [[ -n "$JIRA_URL" ]]; then
  if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$JIRA_URL"); then
    echo "ERROR in Step 2 (Fetch Jira): Could not fetch issue details. See above. Aborting." >&2
    exit 1
  fi
  JIRA_SUMMARY=$(python3 -c "
import json
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
print(d.get('fields', {}).get('summary', ''))
" 2>/dev/null || true)
  JIRA_DESCRIPTION=$(python3 -c "
import json
with open('$WORKDIR/component_onboarding_details.json') as f:
    d = json.load(f)
print(d.get('fields', {}).get('description', '') or '')
" 2>/dev/null || true)
  echo ""
  echo "Jira: $JIRA_ID"
  echo "Title: $JIRA_SUMMARY"
  if [[ -n "$JIRA_DESCRIPTION" ]]; then
    echo ""
    echo "Description:"
    echo "$JIRA_DESCRIPTION" | head -20
  fi
  echo ""
  echo "I've read the Jira ticket. I'll now ask you a few questions to collect the component onboarding details."
fi

# --- Step 3: Interactive Q&A ---

ask_product_context() {
  while true; do
    printf "\nWhich product is this component being onboarded for? (ODH/RHOAI): "
    read -r PRODUCT_CONTEXT
    PRODUCT_CONTEXT="${PRODUCT_CONTEXT^^}"
    case "$PRODUCT_CONTEXT" in
      ODH|RHOAI) return 0 ;;
      *) echo "  Invalid. Must be ODH or RHOAI." ;;
    esac
  done
}

ask_build_type() {
  while true; do
    printf "\nIs this a CI build or a Release build? (CI/Release): "
    read -r BUILD_TYPE
    case "$BUILD_TYPE" in
      CI|ci) BUILD_TYPE="CI"; return 0 ;;
      Release|release|RELEASE) BUILD_TYPE="Release"; return 0 ;;
      *) echo "  Invalid. Must be CI or Release." ;;
    esac
  done
}

ask_architectures() {
  while true; do
    printf "\nWhich CPU architectures should this component build for?\nOptions: x86_64, arm64, ppc64le, s390x\nPress Enter for defaults [x86_64, arm64], or enter comma-separated list: "
    read -r ARCH_INPUT
    if [[ -z "$ARCH_INPUT" ]]; then
      ARCHITECTURES=("x86_64" "arm64")
      return 0
    fi
    ARCHITECTURES=()
    IFS=',' read -ra _archs <<< "$ARCH_INPUT"
    local valid=true
    for _a in "${_archs[@]}"; do
      _a="${_a// /}"
      case "$_a" in
        x86_64|arm64|ppc64le|s390x) ARCHITECTURES+=("$_a") ;;
        *) echo "  Invalid architecture: '$_a'. Allowed: x86_64, arm64, ppc64le, s390x."; valid=false; break ;;
      esac
    done
    [[ "$valid" == "true" && ${#ARCHITECTURES[@]} -gt 0 ]] && return 0
  done
}

ask_component_name() {
  while true; do
    printf "\nWhat is the component name? (kebab-case, e.g. my-component): "
    read -r COMPONENT_NAME
    if [[ "$COMPONENT_NAME" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
      return 0
    else
      echo "  Invalid: must match ^[a-z0-9]+(-[a-z0-9]+)*$ (kebab-case, lowercase, digits, hyphens)."
    fi
  done
}

ask_repo_url() {
  while true; do
    printf "\nWhat is the full HTTPS URL of the component's GitHub repository?\n(e.g. https://github.com/opendatahub-io/my-component): "
    read -r REPO_URL
    if [[ "$REPO_URL" =~ ^https://github\.com/.+/.+$ ]]; then
      return 0
    else
      echo "  Invalid: must match ^https://github.com/org/repo$."
    fi
  done
}

ask_repo_branch() {
  while true; do
    printf "\nWhich branch should be built? (e.g. main): "
    read -r REPO_BRANCH
    [[ -n "$REPO_BRANCH" ]] && return 0
    echo "  Branch cannot be empty."
  done
}

ask_context_path() {
  while true; do
    printf "\nWhat is the Docker build context path, relative to the repo root?\nUse './' if the context is the repo root: "
    read -r CONTEXT_PATH
    [[ -n "$CONTEXT_PATH" ]] && return 0
    echo "  Context path cannot be empty."
  done
}

ask_dockerfile_path() {
  while true; do
    printf "\nWhat is the path to the Dockerfile, relative to the context path?\n(e.g. Dockerfile or docker/Dockerfile): "
    read -r DOCKERFILE_PATH
    [[ -n "$DOCKERFILE_PATH" ]] && return 0
    echo "  Dockerfile path cannot be empty."
  done
}

ask_is_operator() {
  while true; do
    printf "\nIs this component an operator or controller? (yes/no): "
    read -r IS_OPERATOR_RESP
    case "${IS_OPERATOR_RESP,,}" in
      yes|y) IS_OPERATOR="true"; return 0 ;;
      no|n)  IS_OPERATOR="false"; return 0 ;;
      *) echo "  Please answer yes or no." ;;
    esac
  done
}

ask_operator_src_path() {
  while true; do
    printf "\nWhat is the relative path to the component's manifests in the git repo?\n(e.g. config/manifests): "
    read -r OPERATOR_MANIFEST_SRC_PATH
    [[ -n "$OPERATOR_MANIFEST_SRC_PATH" ]] && return 0
    echo "  Path cannot be empty."
  done
}

ask_operator_dest_path() {
  while true; do
    printf "\nWhat is the destination path for the manifests in the odh-operator container image?\n(e.g. opt/manifests/my-component): "
    read -r OPERATOR_MANIFEST_DEST_PATH
    [[ -n "$OPERATOR_MANIFEST_DEST_PATH" ]] && return 0
    echo "  Path cannot be empty."
  done
}

# Collect all answers
PRODUCT_CONTEXT=""
BUILD_TYPE=""
ARCHITECTURES=()
COMPONENT_NAME=""
REPO_URL=""
REPO_BRANCH=""
CONTEXT_PATH=""
DOCKERFILE_PATH=""
IS_OPERATOR=""
OPERATOR_MANIFEST_SRC_PATH=""
OPERATOR_MANIFEST_DEST_PATH=""

ask_product_context

if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
  ask_build_type
else
  ask_architectures
fi

ask_component_name
ask_repo_url
ask_repo_branch
ask_context_path
ask_dockerfile_path
ask_is_operator

if [[ "$IS_OPERATOR" == "true" ]]; then
  ask_operator_src_path
  ask_operator_dest_path
fi

# --- Step 4: Show Summary and Confirm ---
_show_summary() {
  echo ""
  echo "Component onboarding details collected:"
  echo ""
  echo "  product_context              : $PRODUCT_CONTEXT"
  if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
    echo "  build_type                   : $BUILD_TYPE"
  else
    echo "  architectures                : ${ARCHITECTURES[*]}"
  fi
  echo "  component_name               : $COMPONENT_NAME"
  echo "  repo_url                     : $REPO_URL"
  echo "  repo_branch                  : $REPO_BRANCH"
  echo "  context_path                 : $CONTEXT_PATH"
  echo "  dockerfile_path              : $DOCKERFILE_PATH"
  echo "  is_operator                  : $IS_OPERATOR"
  echo "  operator_manifest_src_path   : ${OPERATOR_MANIFEST_SRC_PATH:-N/A}"
  echo "  operator_manifest_dest_path  : ${OPERATOR_MANIFEST_DEST_PATH:-N/A}"
  echo ""
}

while true; do
  _show_summary
  printf "Proceed? (yes / no / edit): "
  read -r CONFIRM
  case "${CONFIRM,,}" in
    yes|y) break ;;
    no|n)
      echo "Aborted by user."
      exit 0
      ;;
    edit)
      printf "Which field to edit? (product_context/build_type/architectures/component_name/repo_url/repo_branch/context_path/dockerfile_path/is_operator/operator_manifest_src_path/operator_manifest_dest_path): "
      read -r EDIT_FIELD
      case "$EDIT_FIELD" in
        product_context)              ask_product_context ;;
        build_type)                   [[ "$PRODUCT_CONTEXT" == "ODH" ]] && ask_build_type ;;
        architectures)                [[ "$PRODUCT_CONTEXT" == "RHOAI" ]] && ask_architectures ;;
        component_name)               ask_component_name ;;
        repo_url)                     ask_repo_url ;;
        repo_branch)                  ask_repo_branch ;;
        context_path)                 ask_context_path ;;
        dockerfile_path)              ask_dockerfile_path ;;
        is_operator)                  ask_is_operator; [[ "$IS_OPERATOR" == "true" ]] && { ask_operator_src_path; ask_operator_dest_path; } ;;
        operator_manifest_src_path)   [[ "$IS_OPERATOR" == "true" ]] && ask_operator_src_path ;;
        operator_manifest_dest_path)  [[ "$IS_OPERATOR" == "true" ]] && ask_operator_dest_path ;;
        *) echo "  Unknown field. Try again." ;;
      esac
      ;;
    *) echo "  Please answer yes, no, or edit." ;;
  esac
done

# --- Step 5: Generate YAML File ---
{
  echo "inputs:"
  echo "  product_context: $PRODUCT_CONTEXT"
  echo "  component_name: $COMPONENT_NAME"
  echo "  repo_url: $REPO_URL"
  echo "  repo_branch: $REPO_BRANCH"
  echo "  context_path: $CONTEXT_PATH"
  echo "  dockerfile_path: $DOCKERFILE_PATH"
  if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
    echo "  build_type: $BUILD_TYPE"
  else
    echo "  architectures:"
    for arch in "${ARCHITECTURES[@]}"; do
      echo "    - $arch"
    done
  fi
  echo "  is_operator: $IS_OPERATOR"
  if [[ "$IS_OPERATOR" == "true" ]]; then
    echo "  operator_manifest_src_path: $OPERATOR_MANIFEST_SRC_PATH"
    echo "  operator_manifest_dest_path: $OPERATOR_MANIFEST_DEST_PATH"
  fi
} > "$YAML_PATH"

echo "YAML written to: $YAML_PATH"

# --- Step 6: Validate YAML Against Schema ---
VALIDATION_ERRORS=""
if ! VALIDATION_ERRORS=$(uv run --script "$SCRIPTS_DIR/validate_yaml_schema.py" \
    "$YAML_PATH" "$SCHEMA_PATH" 2>&1); then
  echo ""
  echo "Validation failed with the following errors:"
  echo "$VALIDATION_ERRORS"
  echo ""
  while true; do
    printf "Would you like to correct the answers? (yes/no): "
    read -r RETRY
    case "${RETRY,,}" in
      yes|y)
        # Re-run all questions
        ask_product_context
        if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
          ask_build_type
        else
          ask_architectures
        fi
        ask_component_name
        ask_repo_url
        ask_repo_branch
        ask_context_path
        ask_dockerfile_path
        ask_is_operator
        if [[ "$IS_OPERATOR" == "true" ]]; then
          ask_operator_src_path
          ask_operator_dest_path
        fi
        # Regenerate
        {
          echo "inputs:"
          echo "  product_context: $PRODUCT_CONTEXT"
          echo "  component_name: $COMPONENT_NAME"
          echo "  repo_url: $REPO_URL"
          echo "  repo_branch: $REPO_BRANCH"
          echo "  context_path: $CONTEXT_PATH"
          echo "  dockerfile_path: $DOCKERFILE_PATH"
          if [[ "$PRODUCT_CONTEXT" == "ODH" ]]; then
            echo "  build_type: $BUILD_TYPE"
          else
            echo "  architectures:"
            for arch in "${ARCHITECTURES[@]}"; do
              echo "    - $arch"
            done
          fi
          echo "  is_operator: $IS_OPERATOR"
          if [[ "$IS_OPERATOR" == "true" ]]; then
            echo "  operator_manifest_src_path: $OPERATOR_MANIFEST_SRC_PATH"
            echo "  operator_manifest_dest_path: $OPERATOR_MANIFEST_DEST_PATH"
          fi
        } > "$YAML_PATH"
        if uv run --script "$SCRIPTS_DIR/validate_yaml_schema.py" "$YAML_PATH" "$SCHEMA_PATH" 2>/dev/null; then
          echo "Schema validation passed."
        else
          echo "ERROR: YAML failed schema validation. Aborting." >&2
          exit 1
        fi
        break
        ;;
      no|n)
        echo "ERROR: YAML failed schema validation. Aborting." >&2
        exit 1
        ;;
      *) echo "  Please answer yes or no." ;;
    esac
  done
else
  echo "Schema validation passed."
fi

# --- Step 7: Jira Integration ---

if [[ -n "$JIRA_URL" ]]; then
  # Path A — Jira URL was provided
  if ! uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --attach "$YAML_PATH" \
    --add-label "yaml-attached" \
    --comment "component_onboarding_details.yaml has been generated and attached to this ticket.

Component: $COMPONENT_NAME
Product: $PRODUCT_CONTEXT
Repo: $REPO_URL @ $REPO_BRANCH
Operator: $IS_OPERATOR

This ticket is ready for onboarding automation. Run /validate-component-onboarding-jira to verify."; then
    echo "ERROR in Step 7 (Upload attachment): Could not attach YAML to Jira. See details above. Aborting." >&2
    exit 1
  fi

else
  # Path B — No Jira URL provided

  # Step 7b-1: Ask for parent feature ID
  while true; do
    printf "\nWhat is the Jira ID of the parent feature? (e.g. RHOAIENG-12345): "
    read -r PARENT_FEATURE_ID
    if [[ "$PARENT_FEATURE_ID" =~ ^[A-Z]+-[0-9]+$ ]]; then
      break
    else
      echo "  Invalid: must match ^[A-Z]+-[0-9]+$ (e.g. RHOAIENG-12345)."
    fi
  done

  # Step 7b-2: ODH — clone template Jira
  if [[ "$PRODUCT_CONTEXT" != "ODH" ]]; then
    echo ""
    echo "No Jira URL provided for RHOAI context."
    echo "YAML saved locally at: $YAML_PATH"
    echo "Create a Jira ticket and re-run with its URL to attach the YAML:"
    echo "  /create-component-onboarding-jira <jira-url>"
    # Step 8 (JIRA_URL remains empty)
  else
    # Fetch template and compute new title
    bash "$SCRIPTS_DIR/check_prerequisites.sh" --tools "jq"

    if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$TEMPLATE_JIRA_URL"); then
      echo "ERROR in Step 7b-2: Could not fetch template Jira RHOAIENG-35683. Check Jira credentials and VPN." >&2
      exit 1
    fi

    TEMPLATE_TITLE=$(jq -r '.fields.summary' "$WORKDIR/component_onboarding_details.json" 2>/dev/null || true)
    if [[ -z "$TEMPLATE_TITLE" ]]; then
      echo "ERROR in Step 7b-2: Could not extract template title from Jira. Aborting." >&2
      exit 1
    fi
    echo "Template title: $TEMPLATE_TITLE"

    NEW_TITLE="${TEMPLATE_TITLE//\[Template\] /}"
    NEW_TITLE="${NEW_TITLE//\[Component Name\]/$COMPONENT_NAME}"
    echo "New title: $NEW_TITLE"

    # Step 7b-3: Clone template and apply updates
    NEW_JIRA_URL=$(uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "new" \
      --clone-from "RHOAIENG-35683" \
      --set-title "$NEW_TITLE" \
      --remove-label "template" \
      --link-related "$PARENT_FEATURE_ID" \
      --set-reporter-to-current 2>&1) || {
      echo "ERROR in Step 7b-3: Could not clone Jira template. See details above. Aborting." >&2
      exit 1
    }

    JIRA_URL="$NEW_JIRA_URL"
    JIRA_ID="${NEW_JIRA_URL##*/}"
    echo "New Jira created: $NEW_JIRA_URL"

    # Step 7b-4: Attach YAML to the new Jira
    if ! uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
      --attach "$YAML_PATH" \
      --add-label "yaml-attached" \
      --comment "component_onboarding_details.yaml has been generated and attached to this ticket.

Component: $COMPONENT_NAME
Product: $PRODUCT_CONTEXT
Repo: $REPO_URL @ $REPO_BRANCH
Operator: $IS_OPERATOR

This ticket is ready for onboarding automation. Run /validate-component-onboarding-jira to verify."; then
      echo "ERROR in Step 7b-4 (Upload attachment): Could not attach YAML to new Jira. See details above. Aborting." >&2
      exit 1
    fi
  fi
fi

# --- Step 8: Report Completion ---
echo ""
echo "Done."
echo ""
echo "  component_onboarding_details.yaml  — generated and validated"
if [[ -n "$JIRA_URL" ]]; then
  echo "  Jira                               — $JIRA_ID ($JIRA_URL)"
  echo "  Jira attachment                    — uploaded (label: yaml-attached)"
  echo "  Jira comment                       — posted"
fi
echo ""
echo "  Output file: $YAML_PATH"
echo ""
if [[ -n "$JIRA_URL" ]]; then
  echo "Next step: /validate-component-onboarding-jira $JIRA_URL"
else
  echo "Attach the YAML to a Jira ticket and run:"
  echo "  /create-component-onboarding-jira <jira-url>"
fi
