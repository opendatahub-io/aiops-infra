---
name: create-component-onboarding-jira
description: Interactively collects ODH/RHOAI component onboarding parameters from the user, generates a validated component_onboarding_details.yaml, and creates or updates a Jira ticket with the YAML attached. When no Jira URL is provided, automatically creates a new ticket by cloning the product-specific onboarding template. Use this before running other onboarding skills.
allowed-tools: Bash
user-invocable: true
---

# Create Component Onboarding Jira

Interactively collects all parameters needed to onboard an ODH or RHOAI component onto
the Konflux CI/build platform, produces a validated `component_onboarding_details.yaml`,
and creates or updates a Jira ticket with the YAML attached. When no Jira URL is
provided, a new ticket is automatically created by cloning the product-specific
onboarding template (ODH: `RHOAIENG-35683`, RHOAI: `RHOAIENG-17225`).

## Prerequisites

- `uv` must be installed and in PATH
- `jq` must be installed and in PATH (needed for the template clone flow)
- `JIRA_USER_EMAIL` — set to your Atlassian account email (always required)
- `JIRA_API_TOKEN` — Atlassian Cloud API token (always required)
  - Create at: https://id.atlassian.com/manage-profile/security/api-tokens
- Optional: `JIRA_SERVER` (default: `https://redhat.atlassian.net`)
- The `validate-component-onboarding-jira` skill must be installed alongside this one

## Usage

```
/create-component-onboarding-jira
/create-component-onboarding-jira [<jira-url>]
```

The Jira URL is **optional**. Without it, the skill automatically creates a new Jira by
cloning the product-specific onboarding template, then attaches the YAML and updates the
ticket. Providing a URL skips template cloning and attaches directly to the given ticket.

| Invocation | ODH | RHOAI |
|---|---|---|
| No URL | Clones `RHOAIENG-35683`, attaches YAML, updates ticket | Clones `RHOAIENG-17225`, attaches YAML, updates ticket |
| With URL | Attaches YAML to given ticket, updates ticket | Attaches YAML to given ticket, updates ticket |

Examples:
```
# Primary usage — creates a new Jira from the template automatically
/create-component-onboarding-jira

# With an existing Jira ticket — attaches the YAML and updates the ticket
/create-component-onboarding-jira https://redhat.atlassian.net/browse/RHOAIENG-1234
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

**Tool check:**
```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" --tools "uv jq"
```

**Jira credentials check (always required):**
```bash
bash "$COMMON_SCRIPTS_DIR/check_prerequisites.sh" --env "JIRA_USER_EMAIL JIRA_API_TOKEN"
```

---

## Step 1: Set up working directory

```bash
eval "$(bash "$COMMON_SCRIPTS_DIR/init_workdir.sh" --jira-url "${JIRA_URL:-}")"
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

Extract Jira fields using jq:

```bash
JIRA_SUMMARY=$(jq -r '.fields.summary' "$WORKDIR/component_onboarding_details.json")
JIRA_DESCRIPTION=$(jq -r '.fields.description // ""' "$WORKDIR/component_onboarding_details.json")
```

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

**Q2a — Target RHOAI version**
> What is the target RHOAI version?
> Format: `x.y`, `x.y.0`, `x.y-eaN`, `x.y-ea-N`, `x.y-ea.N`, `x.y.0-eaN`, `x.y.0-ea-N`, or `x.y.0-ea.N`
> Examples: `3.4`, `3.4.0`, `3.4-ea2`, `3.4-ea-2`, `3.4-ea.2`, `3.4.0-ea2`, `3.4.0-ea-2`, `3.4.0-ea.2`

→ Validate against the regex: `^\d+\.\d+(?:\.0)?(?:-ea[-.]?\d+)?$`
  Re-ask if the input does not match, showing the valid examples above.

Transform the validated input to the canonical form and store in `target_rhoai_version`:
- Extract `VERSION_X` = first integer, `VERSION_Y` = second integer, `VERSION_N` = EA number (after `-ea`, `-ea-`, or `-ea.`), or empty if no EA suffix
- If `VERSION_N` is non-empty: `target_rhoai_version = "<VERSION_X>.<VERSION_Y>-ea-<VERSION_N>"` (e.g. `3.4-ea-2`)
- Otherwise: `target_rhoai_version = "<VERSION_X>.<VERSION_Y>"` (e.g. `3.4`)

**Q2b — CPU architectures**
> Which CPU architectures should this component build for?
> Options: x86_64, arm64, ppc64le, s390x
> Press Enter to accept the defaults [x86_64, arm64], or enter a comma-separated list.

→ Parse response into a list. Default if Enter is pressed: `["x86_64", "arm64"]`.
  Reject any value not in the allowed set and re-ask.
→ Store in `architectures` (list of strings).

**Q3 — Component name**
> What is the component name?
> Must start with `odh-`, followed by lowercase letters, numbers, and hyphens only.
> (e.g. odh-my-component)

→ Store in `component_name`.
  Validate: must match `^odh-[a-z0-9]+(-[a-z0-9]+)*$`. Re-ask if invalid, showing the rule:
  - Must start with `odh-`
  - Remaining characters: lowercase letters, numbers, and hyphens only
  - No consecutive or trailing hyphens

**Q4 — Repository URL**
> What is the full HTTPS URL of the component's GitHub repository?
> (e.g. https://github.com/opendatahub-io/my-component)

→ Store in `repo_url`.
  Validate: must match `^https://github\.com/.+/.+$`. Re-ask if invalid.

**Q4.5 — Component descriptions (RHOAI only)**

_Execute only when `product_context == RHOAI`. Skip entirely for ODH._

Immediately after receiving `repo_url`, attempt to auto-suggest descriptions by fetching
the repository README (try `main` branch, then `master` as fallback):

```bash
REPO_RAW_BASE="${repo_url/github.com/raw.githubusercontent.com}"
README_CONTENT=$(curl -sf "${REPO_RAW_BASE}/main/README.md" 2>/dev/null \
  || curl -sf "${REPO_RAW_BASE}/main/README.rst" 2>/dev/null \
  || curl -sf "${REPO_RAW_BASE}/master/README.md" 2>/dev/null \
  || echo "")
```

**If `README_CONTENT` is non-empty:**

Read the README and extract a suggested `long_description` (one to two sentences
describing what the component does) and a suggested `short_description` (a noun phrase
of a few words summarizing the component).

Present each suggestion and ask the user to confirm or edit:

```
Fetched README from $repo_url.

Suggested long description:
  <suggested_long_description>

Accept? (yes / edit)
```

- `yes` → store as `long_description`
- `edit` → display the suggestion as pre-filled text, let the user modify it, then store

```
Suggested short description:
  <suggested_short_description>

Accept? (yes / edit)
```

- `yes` → store as `short_description`
- `edit` → display the suggestion as pre-filled text, let the user modify it, then store

**If `README_CONTENT` is empty (all fetches failed):**

Ask directly:
> Please provide a long description for this component (one or two sentences describing what it does):

→ Store in `long_description`. Must be non-empty.

Then summarize `long_description` into a short noun phrase (a few words) and offer it
as the suggested `short_description`:

```
Suggested short description:
  <summarized_short_description>

Accept? (yes / edit)
```

→ Confirm or modify, store in `short_description`. Must be non-empty.

---

**Q5 — Branch**

_If `product_context == ODH`:_
> Which branch should be built? (e.g. main)

→ Store in `repo_branch`. Must be non-empty.

_If `product_context == RHOAI`:_

Derive `repo_branch` automatically from `target_rhoai_version` — do NOT ask the user:
- If `target_rhoai_version` has no EA suffix (e.g. `3.5`): `repo_branch = "rhoai-<VERSION_X>.<VERSION_Y>"` (e.g. `rhoai-3.5`)
- If `target_rhoai_version` has an EA suffix (e.g. `3.5-ea-1`): `repo_branch = "rhoai-<VERSION_X>.<VERSION_Y>-ea.<VERSION_N>"` (e.g. `rhoai-3.5-ea.1`)

Print: `repo_branch auto-set to: <repo_branch>`

**Q6 — Build context path**
> What is the Docker build context path, relative to the repo root?
> Use `./` if the context is the repo root.

→ Store in `context_path`. Must be non-empty.

**Q7 — Dockerfile path**
> What is the path to the Dockerfile, relative to the context path?
> (e.g. Dockerfile or docker/Dockerfile)

→ Store in `dockerfile_path`. Must be non-empty.
  If `product_context == RHOAI`: validate that the filename portion (basename) starts with
  `Dockerfile.konflux`. Re-ask if invalid, showing the rule:
  > For RHOAI components, the Dockerfile name must contain the string `Dockerfile.konflux`
  > (e.g. `Dockerfile.konflux`, `docker/Dockerfile.konflux.cuda`)

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
  target_rhoai_version         : <value or N/A>   # only shown for RHOAI
  component_name               : <value>
  repo_url                     : <value>
  repo_branch                  : <value>
  context_path                 : <value>
  dockerfile_path              : <value>
  long_description             : <value or N/A>   # only shown for RHOAI
  short_description            : <value or N/A>   # only shown for RHOAI
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

Build the argument list from collected values, then call:

```bash
YAML_ARGS=(
  --output "$YAML_PATH"
  --product-context "$product_context"
  --component-name "$component_name"
  --repo-url "$repo_url"
  --repo-branch "$repo_branch"
  --context-path "$context_path"
  --dockerfile-path "$dockerfile_path"
)

# ODH-only
[[ "$product_context" == "ODH" ]] && YAML_ARGS+=(--build-type "$build_type")

# RHOAI-only
if [[ "$product_context" == "RHOAI" ]]; then
  YAML_ARGS+=(
    --target-rhoai-version "$target_rhoai_version"
    --architectures "$(IFS=,; echo "${architectures[*]}")"
    --long-description "$long_description"
    --short-description "$short_description"
  )
fi

# Operator fields
[[ "$is_operator" == "true" ]] && YAML_ARGS+=(
  --is-operator
  --operator-manifest-src-path "$operator_manifest_src_path"
  --operator-manifest-dest-path "$operator_manifest_dest_path"
)

uv run --script <COMMON_SCRIPTS_DIR>/generate_onboarding_yaml.py "${YAML_ARGS[@]}"
```

On exit 1: display stderr and stop with:
```
ERROR in Step 5 (Generate YAML): Could not write YAML file. See above. Aborting.
```

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

## Step 6b: Dockerfile digest check

**Skip this entire step if `product_context == "ODH"`.** Digest pinning is only required
for RHOAI components. If ODH, print:
```
Dockerfile digest check skipped (not required for ODH components).
```
and proceed to Step 7.

Construct the raw GitHub URL for the Dockerfile and check that every `FROM` instruction
pins its image with a `@sha256:` digest:

```bash
# Build raw URL: replace github.com with raw.githubusercontent.com, append branch + path
REPO_RAW_BASE="${repo_url/github.com/raw.githubusercontent.com}"
CLEAN_CTX="${context_path%/}"; CLEAN_CTX="${CLEAN_CTX#./}"
if [[ -z "$CLEAN_CTX" || "$CLEAN_CTX" == "." ]]; then
  DOCKERFILE_RAW_URL="${REPO_RAW_BASE}/${repo_branch}/${dockerfile_path}"
else
  DOCKERFILE_RAW_URL="${REPO_RAW_BASE}/${repo_branch}/${CLEAN_CTX}/${dockerfile_path}"
fi

uv run --script <COMMON_SCRIPTS_DIR>/check_dockerfile_digests.py \
  --dockerfile-url "$DOCKERFILE_RAW_URL" 2>&1
DIGEST_EXIT=$?
```

**If exit 2** (Dockerfile not reachable — branch or file may not exist yet): print a notice
and continue. Do not block — the Dockerfile may be created after the Jira is raised:
```
NOTICE: Could not fetch Dockerfile at $DOCKERFILE_RAW_URL — skipping digest check.
         Ensure all FROM images use @sha256 digests before running /validate-component-onboarding-jira.
```

**If exit 1** (violations found): display the stderr output, then warn the user:
```
WARN: The Dockerfile contains FROM instructions that do not use @sha256 digests (see above).
      This will block /validate-component-onboarding-jira.
      Please update the Dockerfile to pin all base and builder images with SHA digests before validating.
```
Do not abort — continue to Step 7 so the Jira is still created and the YAML attached.

**If exit 0**: print `Dockerfile digest check passed.`

---

## Step 7: Jira integration

Two paths depending on whether a Jira URL was provided.

---

### Path A — Jira URL was provided

> `update_jira_issue.py --attach` already deletes any existing attachment with the same
> filename before uploading, so no explicit pre-delete step is needed.

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
ERROR in Step 7 (Upload attachment): Could not attach YAML to Jira. See details above. Aborting.
```

Continue to Step 7c.

---

### Path B — No Jira URL provided

#### Step 7b-1: Ask for parent feature ID

> What is the Jira ID of the parent feature? (e.g. RHAISTRAT-1234)

→ Validate: must match `^[A-Z]+-\d+$`. Re-ask if invalid, showing the expected format.
→ Store in `PARENT_FEATURE_ID`.

#### Step 7b-2: Clone the product-specific template Jira

Select the template based on `product_context`:
- `ODH`  → clone `RHOAIENG-35683`
- `RHOAI` → clone `RHOAIENG-17225`

```bash
if [[ "$product_context" == "ODH" ]]; then
  TEMPLATE_ID="RHOAIENG-35683"
else
  TEMPLATE_ID="RHOAIENG-17225"
fi

NEW_JIRA_URL=$(uv run --script <COMMON_SCRIPTS_DIR>/update_jira_issue.py "new" \
  --clone-from "$TEMPLATE_ID" \
  --remove-label "template" \
  --link-related "$PARENT_FEATURE_ID" \
  --set-reporter-to-current)
```

On exit 1: display stderr and stop with:
```
ERROR in Step 7b-2: Could not clone Jira template ($TEMPLATE_ID). See details above. Aborting.
```

On success: capture `NEW_JIRA_URL` from stdout.

```bash
JIRA_URL="$NEW_JIRA_URL"
JIRA_ID="${NEW_JIRA_URL##*/}"
echo "New Jira created: $NEW_JIRA_URL"
```

#### Step 7b-3: Attach YAML to the new Jira

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
ERROR in Step 7b-3 (Upload attachment): Could not attach YAML to new Jira. See details above. Aborting.
```

Continue to Step 7c.

---

### Step 7c: Update Jira metadata (shared — all cases where JIRA_URL is set)

**Skip this entire step if `JIRA_URL` is empty.**

Applies to both ODH and RHOAI, and to both Path A (existing Jira) and Path B (newly
created Jira). Delegates all Jira metadata work to `update_onboarding_jira.py`, which
handles: title cleanup, description table replacement, and label addition.

```bash
UPDATE_JIRA_ARGS=(
  --component-name "$component_name"
  --product-context "$product_context"
  --repo-url "$repo_url"
  --repo-branch "$repo_branch"
  --context-path "$context_path"
  --dockerfile-path "$dockerfile_path"
)

# RHOAI-only: pass description and architectures to populate the template table
if [[ "$product_context" == "RHOAI" ]]; then
  UPDATE_JIRA_ARGS+=(
    --short-description "$short_description"
    --architectures "$(IFS=,; echo "${architectures[*]}")"
  )
fi

uv run --script <COMMON_SCRIPTS_DIR>/update_onboarding_jira.py "$JIRA_URL" "${UPDATE_JIRA_ARGS[@]}"
```

On exit 1: print a warning and continue — metadata updates are non-critical:
```
WARN in Step 7c: Could not update Jira metadata. See above. Update manually.
```

---

## Step 8: Report completion

Print:
```
Done.

  component_onboarding_details.yaml  — generated and validated
  Jira                               — <JIRA_ID> (<JIRA_URL>)
                                       (created from template <TEMPLATE_ID>, or provided by user)
  Jira attachment                    — uploaded (label: yaml-attached)
  Jira comment                       — posted

  Output file: $YAML_PATH

Next step: /validate-component-onboarding-jira <JIRA_URL>
```

If `TEMPLATE_ID` was not used (i.e. the user provided a Jira URL directly), omit the
`(created from template ...)` parenthetical.

---

## Error reference

| Error | Step | Action |
|-------|------|--------|
| Invalid Jira URL format | 0 | Correct the URL and re-run |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` not set | 0 | Export the env vars |
| `uv` not installed | 0 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `jq` not installed | 2 | `brew install jq` or `sudo dnf install jq` |
| Jira fetch fails (401/403/404) | 2 | Check credentials and issue key |
| YAML generation fails | 5 | Check arguments; see stderr from `generate_onboarding_yaml.py` |
| YAML validation fails | 6 | Correct the inputs and re-generate |
| Clone fails (ODH: `RHOAIENG-35683`, RHOAI: `RHOAIENG-17225`) | 7b-2 | Check `JIRA_USER_EMAIL` / `JIRA_API_TOKEN`; verify create permission |
| "relates to" link type not found | 7b-2 | Check available link types with a Jira admin |
| Attach/upload fails | 7, 7b-3 | Check credentials; re-run the skill |
| Metadata update fails | 7c | Warnings printed; update title/description/label manually in Jira |
