---
name: create-component-offboarding-jira
description: Interactively collects ODH/RHOAI component offboarding parameters from the user, generates a validated component_offboarding_details.yaml, and creates or updates a Jira ticket with the YAML attached. When no Jira URL is provided, automatically creates a new ticket by cloning the offboarding template. Use this before running the offboarding automation.
allowed-tools: Bash
user-invocable: true
---

# Create Component Offboarding Jira

Interactively collects parameters needed to offboard an ODH or RHOAI component from
the Konflux CI/build platform, produces a validated `component_offboarding_details.yaml`,
and creates or updates a Jira ticket with the YAML attached. When no Jira URL is
provided, a new ticket is automatically created by cloning the offboarding template
(`RHOAIENG-32534`).

## Prerequisites

- `uv` must be installed and in PATH
- `jq` must be installed and in PATH
- `JIRA_USER_EMAIL` — set to your Atlassian account email (always required)
- `JIRA_API_TOKEN` — Atlassian Cloud API token (always required)
  - Create at: https://id.atlassian.com/manage-profile/security/api-tokens
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- The `validate-component-offboarding-jira` skill must be installed alongside this one

## Usage

```
/create-component-offboarding-jira
/create-component-offboarding-jira [<jira-url>]
```

The Jira URL is **optional**. Without it, the skill automatically creates a new Jira by
cloning the offboarding template (`RHOAIENG-32534`), then attaches the YAML and updates
the ticket. Providing a URL skips template cloning and attaches directly to the given ticket.

## Implementation

---

## Step 0: Parse inputs and check prerequisites

Extract the optional `<jira-url>` argument from the invocation.
If a value is present but does not contain `/browse/`, stop with:
> ERROR: Invalid Jira URL. Expected format: https://redhat.atlassian.net/browse/RHOAIENG-1234

Set `JIRA_URL` to the parsed URL, or empty string if omitted.
Set `JIRA_ID` to the last path segment of `JIRA_URL` (e.g. `RHOAIENG-1234`), or empty.

**Tool check:**
```bash
bash "scripts/check_prerequisites.sh" --tools "uv jq"
```

**Jira credentials check (always required):**
```bash
bash "scripts/check_prerequisites.sh" --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
```

---

## Step 1: Set up working directory

```bash
eval "$(bash "scripts/init_workdir.sh" --jira-url "${JIRA_URL:-}")"
YAML_PATH="${WORKDIR}/component_offboarding_details.yaml"
echo "Working directory: $WORKDIR"
```

---

## Step 2: Fetch Jira details (only when JIRA_URL is non-empty)

**Skip this entire step if JIRA_URL is empty.**

```bash
(cd "$WORKDIR" && uv run --script scripts/fetch_jira_details.py "$JIRA_URL")
```

On exit 1: display stderr and stop with:
```
ERROR in Step 2 (Fetch Jira): Could not fetch issue details. See above. Aborting.
```

On success: `$WORKDIR/component_offboarding_details.json` is created.

Extract Jira fields using jq:

```bash
JIRA_SUMMARY=$(jq -r '.fields.summary' "$WORKDIR/component_offboarding_details.json")
```

Print:
```
Jira: <JIRA_ID>
Title: <JIRA_SUMMARY>
```

---

## Step 3: Interactive Q&A

### 3a. Jira-specific context (only when JIRA_URL is non-empty)

Acknowledge the Jira context to the user:
> I've read the Jira ticket. I'll now ask you a few questions to collect the
> component offboarding details.

### 3b. Standard Q&A — always run

Ask each question in sequence. Wait for the user's answer before asking the next.
Re-ask if the answer is invalid.

**Q1 — Product context**
> Which product is this component being offboarded from?
> Options: ODH, RHOAI

→ Store in `product_context`. Must be exactly `ODH` or `RHOAI`.

**Q2 — Product-context-specific question**

_If `product_context == ODH`:_
> Is this a CI build or a Release build?
> Options: CI, Release

→ Store in `build_type`.

_If `product_context == RHOAI`:_

**Q2a — Target RHOAI version**
> What is the target RHOAI version being offboarded?
> Format: `x.y`, `x.y.0`, `x.y-eaN`, `x.y-ea-N`, `x.y-ea.N`, `x.y.0-eaN`, `x.y.0-ea-N`, or `x.y.0-ea.N`
> Examples: `3.4`, `3.4.0`, `3.4-ea2`, `3.4-ea-2`, `3.4-ea.2`, `3.4.0-ea2`, `3.4.0-ea-2`, `3.4.0-ea.2`

→ Validate against regex: `^\d+\.\d+(?:\.0)?(?:-?ea[-.]?\d+)?$`
  Re-ask if the input does not match, showing the valid examples above.

Transform the validated input to canonical form and store in `target_rhoai_version`:
- Extract `VERSION_X` = first integer, `VERSION_Y` = second integer, `VERSION_N` = EA number (after `-ea`, `-ea-`, or `-ea.`), or empty if no EA suffix
- If `VERSION_N` is non-empty: `target_rhoai_version = "<VERSION_X>.<VERSION_Y>-ea-<VERSION_N>"` (e.g. `3.4-ea-2`)
- Otherwise: `target_rhoai_version = "<VERSION_X>.<VERSION_Y>"` (e.g. `3.4`)

**Q3 — Component name**
> What is the component name?
> Must start with `odh-`, followed by lowercase letters, numbers, and hyphens only.

→ Store in `component_name`.
  Validate: must match `^odh-[a-z0-9]+(-[a-z0-9]+)*$`.

**Q4 — Repository URL**
> What is the full HTTPS URL of the component's GitHub repository?

→ Store in `repo_url`.
  Validate: must match `^https://github\.com/.+/.+$`.

**Q5 — Operator/controller**
> Is this component an operator or controller? (yes / no)

→ Convert: `yes` → `true`, `no` → `false`.
→ Store in `is_operator` (boolean).

---

## Step 4: Show collected values and confirm

Display a summary table:

```
Component offboarding details collected:

  product_context          : <value>
  build_type               : <value or N/A>   # only shown for ODH
  target_rhoai_version     : <value or N/A>   # only shown for RHOAI
  component_name           : <value>
  repo_url                 : <value>
  is_operator              : <value>

Proceed? (yes / no / edit)
```

- `yes` → continue to Step 5
- `no` → print `Aborted by user.` and stop
- `edit` → ask which field to change, update it, re-display summary, ask again

---

## Step 5: Generate YAML file

```bash
YAML_ARGS=(
  --output "$YAML_PATH"
  --product-context "$product_context"
  --component-name "$component_name"
  --repo-url "$repo_url"
)

if [[ "$product_context" == "ODH" ]]; then
  YAML_ARGS+=(--build-type "$build_type")
fi

if [[ "$product_context" == "RHOAI" ]]; then
  YAML_ARGS+=(--target-rhoai-version "$target_rhoai_version")
fi

[[ "$is_operator" == "true" ]] && YAML_ARGS+=(--is-operator)

uv run --script scripts/generate_offboarding_yaml.py "${YAML_ARGS[@]}"
```

On exit 1: display stderr and stop.

---

## Step 6: Validate YAML against schema

```bash
uv run --script scripts/validate_yaml_schema.py \
  "$YAML_PATH" \
  schemas/component_offboarding_details.schema.json
```

On success: print `Schema validation passed.`
On failure: display errors, ask user to correct, or stop.

---

## Step 7: Jira integration

### Step 7-pre: Ask for parent feature ID (always)

> What is the Jira ID of the parent feature? (e.g. RHAISTRAT-1234)

→ Validate: must match `^[A-Z]+-\d+$`.
→ Store in `PARENT_FEATURE_ID`.

---

### Path A — Jira URL was provided

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --attach "$YAML_PATH" \
  --add-label "offboarding-yaml-attached" \
  --link-related "$PARENT_FEATURE_ID" \
  --comment "component_offboarding_details.yaml has been generated and attached to this ticket.

Component: <component_name>
Product: <product_context>
Repo: <repo_url>
Operator: <is_operator>

This ticket is ready for offboarding automation. Run /validate-component-offboarding-jira to verify."
```

Continue to Step 7c.

---

### Path B — No Jira URL provided

#### Step 7b-1: Clone the offboarding template

```bash
TEMPLATE_ID="RHOAIENG-32534"

NEW_JIRA_URL=$(uv run --script scripts/update_jira_issue.py "new" \
  --clone-from "$TEMPLATE_ID" \
  --remove-label "template" \
  --link-related "$PARENT_FEATURE_ID" \
  --set-reporter-to-current)
```

On success:
```bash
JIRA_URL="$NEW_JIRA_URL"
JIRA_ID="${NEW_JIRA_URL##*/}"
echo "New Jira created: $NEW_JIRA_URL"
```

#### Step 7b-2: Attach YAML to the new Jira

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --attach "$YAML_PATH" \
  --add-label "offboarding-yaml-attached" \
  --comment "component_offboarding_details.yaml has been generated and attached to this ticket.

Component: <component_name>
Product: <product_context>
Repo: <repo_url>
Operator: <is_operator>

This ticket is ready for offboarding automation. Run /validate-component-offboarding-jira to verify."
```

Continue to Step 7c.

---

### Step 7c: Update Jira metadata (shared)

**Skip if JIRA_URL is empty.**

Update the Jira summary to include the component name:

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --summary "[Offboarding] Konflux Offboarding ${component_name} (${product_context})"
```

On exit 1: print warning and continue (non-critical).

---

## Step 8: Report completion

Print:
```
Done.

  component_offboarding_details.yaml — generated and validated
  Jira                               — <JIRA_ID> (<JIRA_URL>)
  Parent feature link                — <PARENT_FEATURE_ID> (relates to)
  Jira attachment                    — uploaded (label: offboarding-yaml-attached)

  Output file: $YAML_PATH

Next step: /offboard-konflux-components-for-odh-and-rhoai <JIRA_URL>
```

---

## Error reference

| Error | Step | Action |
|-------|------|--------|
| Invalid Jira URL format | 0 | Correct the URL and re-run |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` not set | 0 | Export the env vars |
| `uv` not installed | 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Jira fetch fails (401/403/404) | 2 | Check credentials and issue key |
| YAML generation fails | 5 | Check arguments; see stderr |
| YAML validation fails | 6 | Correct the inputs and re-generate |
| Clone fails (`RHOAIENG-32534`) | 7b-1 | Check Jira credentials and permissions |
| Attach/upload fails | 7, 7b-2 | Check credentials; re-run |
