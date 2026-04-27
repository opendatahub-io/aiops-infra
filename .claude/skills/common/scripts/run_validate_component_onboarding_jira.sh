#!/usr/bin/env bash
# Main script for the validate-component-onboarding-jira skill.
# Fetches Jira issue details, downloads the YAML attachment, validates against schema,
# and updates the Jira issue with the result.
set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_PATH="${SCRIPTS_DIR}/../../validate-component-onboarding-jira/assets/component_onboarding_details.schema.json"

JIRA_URL="${1:-}"
if [[ -z "$JIRA_URL" || "$JIRA_URL" != *"/browse/"* ]]; then
  echo "Usage: $(basename "$0") <jira-url>" >&2
  echo "  Example: $(basename "$0") https://redhat.atlassian.net/browse/RHOAIENG-1234" >&2
  exit 1
fi

JIRA_ID="${JIRA_URL##*/}"
JIRA_SERVER="${JIRA_SERVER:-https://redhat.atlassian.net}"

# --- Step 0: Check prerequisites ---
if [[ -z "${JIRA_USER_EMAIL:-}" ]]; then
  echo "ERROR: JIRA_USER_EMAIL is not set." >&2
  echo "  Set it: export JIRA_USER_EMAIL='you@example.com'" >&2
  echo "  Then re-run: /validate-component-onboarding-jira $JIRA_URL" >&2
  exit 1
fi
if [[ -z "${JIRA_API_TOKEN:-}" ]]; then
  echo "ERROR: JIRA_API_TOKEN is not set." >&2
  echo "  Create a token at: https://id.atlassian.com/manage-profile/security/api-tokens" >&2
  echo "  Then: export JIRA_API_TOKEN='your-token'" >&2
  echo "  Then re-run: /validate-component-onboarding-jira $JIRA_URL" >&2
  exit 1
fi
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

# --- Step 2: Create working directory ---
WORKDIR="$(pwd)/${JIRA_ID}"
mkdir -p "$WORKDIR"
echo "Working directory: $WORKDIR"

ERR_TMP=$(mktemp)
trap 'rm -f "$ERR_TMP"' EXIT

# --- Step 3: Fetch Jira issue details ---
if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/fetch_jira_details.py" "$JIRA_URL") \
    2>"$ERR_TMP"; then
  cat "$ERR_TMP" >&2
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "validation-failed" \
    --remove-label "validation-successful" \
    --comment "Validation failed at Step 1 (Fetch Jira Details).

Could not fetch issue details. This is typically caused by:
- An invalid or expired JIRA_API_TOKEN
- An incorrect issue key
- A network or permissions issue

Please check your credentials and issue key, then re-run /validate-component-onboarding-jira." \
    2>/dev/null || true
  echo "ERROR in Step 1 (Fetch Jira Details): Could not fetch issue details. See above. Aborting." >&2
  exit 1
fi

# --- Step 4: Download YAML attachment ---
if ! (cd "$WORKDIR" && uv run --script "$SCRIPTS_DIR/download_jira_attachment.py" \
    "$JIRA_URL" component_onboarding_details.yaml) 2>"$ERR_TMP"; then
  cat "$ERR_TMP" >&2
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "validation-failed" \
    --remove-label "validation-successful" \
    --comment "Validation failed at Step 2 (Download Attachment).

The required attachment 'component_onboarding_details.yaml' was not found on this issue.

Please attach a valid 'component_onboarding_details.yaml' file to this ticket and re-run /validate-component-onboarding-jira."
  echo "ERROR in Step 2 (Download Attachment): Attachment not found. See above. Aborting." >&2
  exit 1
fi

# --- Step 5: Validate YAML against schema ---
VALIDATION_ERRORS=""
if ! VALIDATION_ERRORS=$(uv run --script "$SCRIPTS_DIR/validate_yaml_schema.py" \
    "${WORKDIR}/component_onboarding_details.yaml" \
    "$SCHEMA_PATH" 2>&1); then
  echo "$VALIDATION_ERRORS" >&2
  uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
    --add-label "validation-failed" \
    --remove-label "validation-successful" \
    --comment "Validation failed at Step 3 (Schema Validation).

The 'component_onboarding_details.yaml' attachment did not pass schema validation.

Errors found:
${VALIDATION_ERRORS}

Please fix the YAML, re-upload it as an attachment to this ticket, and re-run /validate-component-onboarding-jira."
  echo "ERROR in Step 3 (Schema Validation): The YAML failed validation. See errors above. Aborting." >&2
  exit 1
fi
echo "Validation passed."

# --- Step 6: Update Jira on success and report ---
uv run --script "$SCRIPTS_DIR/update_jira_issue.py" "$JIRA_URL" \
  --add-label "validation-successful" \
  --remove-label "validation-failed" \
  --comment "Validation passed for ${JIRA_ID}.

All pre-flight checks completed successfully:
- Jira issue details fetched
- component_onboarding_details.yaml attachment downloaded
- Schema validation passed

This ticket is ready for onboarding automation. Moving to In Progress." \
  --status "In Progress"

echo ""
echo "Validation complete for ${JIRA_ID}."
echo ""
echo "  component_onboarding_details.json  — Jira issue details saved"
echo "  component_onboarding_details.yaml  — Attachment downloaded"
echo "  Schema validation            — PASSED"
echo "  Jira issue updated           — label: validation-successful, status: In Progress"
echo ""
echo "The Jira ticket is valid and ready for onboarding automation."
echo "Output files are in: ${WORKDIR}/"
