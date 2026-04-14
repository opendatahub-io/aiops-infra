---
name: create-component-onboarding-jira
description: Interactively collects ODH/RHOAI component onboarding parameters from the user, generates a validated component_onboarding_details.yaml, and (when a Jira URL is given) uploads it as an attachment to the ticket. Use this before running other onboarding skills.
allowed-tools: Bash, Read, Write
user-invocable: true
---

# Create Component Onboarding Jira

Interactively collects all parameters needed to onboard an ODH or RHOAI component onto
the Konflux CI/build platform, produces a validated `component_onboarding_details.yaml`,
and attaches it to the Jira ticket.

## Prerequisites

- `uv` must be installed and in PATH
- `JIRA_USER_EMAIL` — set to your Atlassian account email (required when Jira URL is given)
- `JIRA_API_TOKEN` — Atlassian Cloud API token (required when Jira URL is given)
  - Create at: https://id.atlassian.com/manage-profile/security/api-tokens
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- The `validate-component-onboarding-jira` skill must be installed alongside this one

## Usage

```
/create-component-onboarding-jira [<jira-url>]
```

Examples:
```
/create-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
/create-component-onboarding-jira
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
VALIDATE_SKILL_DIR is `<SKILL_DIR>/../validate-component-onboarding-jira`.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.
SCHEMA_PATH is `<VALIDATE_SKILL_DIR>/assets/component_onboarding_details.schema.json`.

---

## Step 0: Parse inputs and check prerequisites

Extract the optional `<jira-url>` argument from the invocation.
If a value is present but does not contain `/browse/`, stop with:
> ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

Set `JIRA_URL` to the parsed URL, or empty string if omitted.
Set `JIRA_ID` to the last path segment of `JIRA_URL` (e.g. `RHOAIENG-1234`), or empty.

**Jira credentials check (only when JIRA_URL is non-empty):**
```bash
if [[ -n "$JIRA_URL" ]]; then
  if [[ -z "${JIRA_USER_EMAIL:-}" || -z "${JIRA_API_TOKEN:-}" ]]; then
    echo "ERROR: Jira credentials required when a Jira URL is provided."
    echo "  export JIRA_USER_EMAIL='you@example.com'"
    echo "  export JIRA_API_TOKEN='your-api-token'"
    exit 1
  fi
fi
```

**uv check:**
```bash
if ! command -v uv &>/dev/null; then
  echo "ERROR: uv is not installed. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
```

---

## Step 1: Set up working directory

```bash
if [[ -n "$JIRA_ID" ]]; then
  WORKDIR="$(pwd)/${JIRA_ID}"
else
  WORKDIR="$(pwd)"
fi
mkdir -p "$WORKDIR"
YAML_PATH="${WORKDIR}/component_onboarding_details.yaml"
echo "Working directory: $WORKDIR"
```

---

## Step 2: Fetch Jira details (only when JIRA_URL is non-empty)

**Skip this entire step if JIRA_URL is empty.**

```bash
(cd "$WORKDIR" && uv run --script <COMMON_SCRIPTS_DIR>/fetch_jira_details.py "$JIRA_URL")
```

On exit 1: display stderr and stop with:
```
ERROR in Step 2 (Fetch Jira): Could not fetch issue details. See above. Aborting.
```

On success: `$WORKDIR/component_onboarding_details.json` is created.

Use the Read tool to read `$WORKDIR/component_onboarding_details.json`. Extract:
- `JIRA_SUMMARY` = `fields.summary`
- `JIRA_DESCRIPTION` = `fields.description`

Print:
```
Jira: <JIRA_ID>
Title: <JIRA_SUMMARY>
```

---

## Step 3: Interactive Q&A

### 3a. Jira-specific questions (only when JIRA_URL is non-empty)

If `JIRA_DESCRIPTION` is non-empty, read it carefully to understand any additional
information the issue requests from the engineer (e.g. specific repo requirements,
version constraints, contacts). Ask the user for any such information now, before
the standard schema questions.

Acknowledge the Jira context to the user:
> I've read the Jira ticket. I'll now ask you a few questions to collect the
> component onboarding details.

### 3b. Standard Q&A — always run

Ask each question in sequence. Wait for the user's answer before asking the next.
Re-ask if the answer is invalid (explain why and show valid options).

**Q1 — Product context**
> Which product is this component being onboarded for?
> Options: ODH, RHOAI

→ Store in `product_context`. Must be exactly `ODH` or `RHOAI` (case-insensitive input, store uppercase).

**Q2 — Product-context-specific question**

_If `product_context == ODH`:_
> Is this a CI build or a Release build?
> Options: CI, Release

→ Store in `build_type`. Must be `CI` or `Release`.

_If `product_context == RHOAI`:_
> Which CPU architectures should this component build for?
> Options: x86_64, arm64, ppc64le, s390x
> Press Enter to accept the defaults [x86_64, arm64], or enter a comma-separated list.

→ Parse response into a list. Default if Enter is pressed: `["x86_64", "arm64"]`.
  Reject any value not in the allowed set and re-ask.
→ Store in `architectures` (list of strings).

**Q3 — Component name**
> What is the component name? (kebab-case, e.g. my-component)

→ Store in `component_name`.
  Validate: must match `^[a-z0-9]+(-[a-z0-9]+)*$`. Re-ask if invalid, showing the rule.

**Q4 — Repository URL**
> What is the full HTTPS URL of the component's GitHub repository?
> (e.g. https://github.com/opendatahub-io/my-component)

→ Store in `repo_url`.
  Validate: must match `^https://github\.com/.+/.+$`. Re-ask if invalid.

**Q5 — Branch**
> Which branch should be built? (e.g. main)

→ Store in `repo_branch`. Must be non-empty.

**Q6 — Build context path**
> What is the Docker build context path, relative to the repo root?
> Use `./` if the context is the repo root.

→ Store in `context_path`. Must be non-empty.

**Q7 — Dockerfile path**
> What is the path to the Dockerfile, relative to the context path?
> (e.g. Dockerfile or docker/Dockerfile)

→ Store in `dockerfile_path`. Must be non-empty.

**Q8 — Operator/controller**
> Is this component an operator or controller? (yes / no)

→ Convert: `yes` → `true`, `no` → `false`. Re-ask on any other input.
→ Store in `is_operator` (boolean).

**Q9 — Operator manifest paths (only when `is_operator == true`)**

_Q9a:_
> What is the relative path to the component's manifests in the git repo?
> (e.g. config/manifests)

→ Store in `operator_manifest_src_path`. Must be non-empty.

_Q9b:_
> What is the destination path for the manifests in the odh-operator container image?
> (e.g. opt/manifests/my-component)

→ Store in `operator_manifest_dest_path`. Must be non-empty.

---

## Step 4: Show collected values and confirm

Display a summary table of all collected values:

```
Component onboarding details collected:

  product_context              : <value>
  build_type / architectures   : <value>
  component_name               : <value>
  repo_url                     : <value>
  repo_branch                  : <value>
  context_path                 : <value>
  dockerfile_path              : <value>
  is_operator                  : <value>
  operator_manifest_src_path   : <value or N/A>
  operator_manifest_dest_path  : <value or N/A>

Proceed? (yes / no / edit)
```

- `yes` → continue to Step 5
- `no` → print `Aborted by user.` and stop
- `edit` → ask which field to change, update it, re-display summary, ask again

---

## Step 5: Generate YAML file

Use the Write tool to write `$YAML_PATH`.
Only include keys that are relevant — omit `build_type` for RHOAI, omit `architectures`
for ODH, omit operator fields when `is_operator == false`:

```yaml
inputs:
  product_context: <product_context>
  component_name: <component_name>
  repo_url: <repo_url>
  repo_branch: <repo_branch>
  context_path: <context_path>
  dockerfile_path: <dockerfile_path>
  build_type: <build_type>           # only when product_context == ODH
  architectures:                     # only when product_context == RHOAI
    - x86_64
    - arm64
  is_operator: <true|false>
  operator_manifest_src_path: <value>   # only when is_operator == true
  operator_manifest_dest_path: <value>  # only when is_operator == true
```

Print: `YAML written to: $YAML_PATH`

---

## Step 6: Validate YAML against schema

```bash
uv run --script <COMMON_SCRIPTS_DIR>/validate_yaml_schema.py \
  "$YAML_PATH" \
  <SCHEMA_PATH>
```

On success (exit 0): print `Schema validation passed.`

On failure (exit 1): capture stderr as `<validation_errors>`. Display the errors, then ask:
> Validation failed with the following errors:
> <validation_errors>
> Would you like to correct the answers? (yes / no)

- `yes` → return to Step 3b for the relevant fields, regenerate, re-validate
- `no` → stop with: `ERROR: YAML failed schema validation. Aborting.`

---

## Step 7: Upload to Jira (only when JIRA_URL is non-empty)

**Skip this entire step if JIRA_URL is empty.** Instead print:
```
No Jira URL was provided. YAML saved locally at: $YAML_PATH
To upload it, re-run: /create-component-onboarding-jira <jira-url>
```
and stop.

### 7a. Attach file, add label, and comment — single call

```bash
uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "$JIRA_URL" \
  --attach "$YAML_PATH" \
  --add-label "yaml-attached" \
  --comment "component_onboarding_details.yaml has been generated and attached to this ticket.

Component: <component_name>
Product: <product_context>
Repo: <repo_url> @ <repo_branch>
Operator: <is_operator>

This ticket is ready for onboarding automation. Run /validate-component-onboarding-jira to verify."
```

On exit 1: display stderr and stop with:
```
ERROR in Step 7a (Upload attachment): Could not attach YAML to Jira. See details above. Aborting.
```

---

## Step 8: Report completion

Print:
```
Done.

  component_onboarding_details.yaml  — generated and validated
  Jira attachment                    — uploaded to <JIRA_ID>      (if Jira URL was given)
  Jira comment                       — posted (label: yaml-attached)

  Output file: $YAML_PATH

Next step: /validate-component-onboarding-jira <JIRA_URL>
```

---

## Error reference

| Error | Step | Action |
|-------|------|--------|
| Invalid Jira URL format | 0 | Correct the URL and re-run |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` not set | 0 | Export the env vars |
| `uv` not installed | 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Jira fetch fails (401/403/404) | 2 | Check credentials and issue key |
| YAML validation fails | 6 | Correct the inputs and re-generate |
| Attach/upload fails | 7a | Check credentials; re-run the skill |
| `validate-component-onboarding-jira` skill not found | 6, 7 | Run its `install.sh` first |
