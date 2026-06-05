---
name: onboarding-maturity-assessor
description: AI-powered onboarding readiness assessment for ODH/RHOAI components. Scans a Jira epic's full context (parent, siblings, linked issues, comments), uses NLP to extract onboarding fields, validates them against the schema, scores readiness across 6 rubric dimensions (0–2 each, max 12), and labels the epic as ready-for-human-review or not-ready-for-onboarding. Idempotent — safe to re-run.
allowed-tools: Bash
user-invocable: true
---

# Onboarding Maturity Assessor

Automated readiness assessment for ODH/RHOAI component onboarding. Given a Jira
onboarding epic, this skill:

1. **Stage A** — Extracts onboarding info from the epic's full context using AI/NLP
2. **Stage B** — Validates the extracted info against schema and cross-checks
3. **Stage C** — Scores readiness across 6 rubric dimensions (0–2 each, max 12)
4. **Stage D** — Evaluates the threshold and labels the epic

Idempotent — safe to re-run any number of times. Each run compares with the
previous assessment and only posts updates when scores change.

## Prerequisites

- `uv` must be installed and in PATH
- `jq` must be installed and in PATH
- `curl` must be installed and in PATH
- `JIRA_USER_EMAIL` — Atlassian account email (always required)
- `JIRA_API_TOKEN` — Atlassian Cloud API token (always required)
- `GITHUB_TOKEN` — GitHub personal access token (required for repo structure checks)

## Usage

```
/onboarding-maturity-assessor <jira-url>
```

Example:
```
/onboarding-maturity-assessor https://redhat.atlassian.net/browse/RHOAIENG-1234
```

## Implementation

---

## Step 0: Parse Inputs and Check Prerequisites

Extract the `<jira-url>` argument from the invocation.
If not provided or does not contain `/browse/` or a valid issue key pattern, stop with:
> ERROR: Jira URL is required. Usage: /onboarding-maturity-assessor <jira-url>

```bash
eval "$(bash "scripts/parse_jira_url.sh" "${1:-}")"
[[ -z "$JIRA_URL" ]] && {
  echo "ERROR: Jira URL is required."
  echo "  Usage: /onboarding-maturity-assessor <jira-url>"
  exit 1
}
echo "Jira ID  : $JIRA_ID"
echo "Jira URL : $JIRA_URL"
```

Check prerequisites:

```bash
bash "scripts/check_prerequisites.sh" \
  --env "JIRA_USER_EMAIL JIRA_API_TOKEN GITHUB_TOKEN" \
  --tools "uv jq curl"
```

---

## Step 1: Set Up Working Directory

```bash
eval "$(bash "scripts/init_workdir.sh" --jira-url "$JIRA_URL")"
echo "Working directory: $WORKDIR"
```

---

## Stage A: Onboarding Info Generator

**Goal:** Extract all onboarding fields from the Jira epic's context using AI/NLP
analysis of descriptions, comments, attachments, and sibling epics.

### Step A.1: Fetch Epic Details

```bash
(cd "$WORKDIR" && uv run --script scripts/fetch_jira_details.py "$JIRA_URL")
```

On exit 1: display stderr and stop with:
```
ERROR in Step A.1: Could not fetch Jira issue details. Aborting.
```

On success: `$WORKDIR/component_onboarding_details.json` is created.

### Step A.2: Scan Epic Context

Fetch the epic's parent feature, sibling epics, linked issues, and all comments:

```bash
(cd "$WORKDIR" && uv run --script scripts/scan_jira_context.py "$JIRA_URL")
```

On exit 1: print a warning and continue — the assessment can proceed with just
the epic's own data:
```
WARN in Step A.2: Could not scan full epic context. Proceeding with epic data only.
```

On success: `$WORKDIR/jira_context.json` is created.

### Step A.3: AI-Powered Info Extraction

Read the Jira context JSON file (`$WORKDIR/jira_context.json`) and the issue
details JSON (`$WORKDIR/component_onboarding_details.json`).

**Use natural language understanding to extract all onboarding fields from the
consolidated text.** Scan all of the following for field values:

- The epic's own description and summary
- All comments on the epic
- Descriptions AND comments of sibling epics under the same parent feature
- Attachments on sibling epics (note filenames for any structured data)
- Descriptions of linked issues
- Any existing attachments on the epic itself (note filenames — if
  `component_onboarding_details.yaml` already exists, this is a re-assessment)

**Fields to extract:**

| Field | Required | Source Hints |
|-------|----------|--------------|
| `product_context` | Always | Infer from epic key prefix (RHOAIENG→RHOAI, RHODS→ODH), parent feature name, or explicit mentions |
| `component_name` | Always | Must match `^odh-[a-z0-9]+(-[a-z0-9]+)*$`; look for "component name", "odh-" prefixed names |
| `repo_url` | Always | Look for GitHub URLs (https://github.com/...) in descriptions and comments |
| `repo_branch` | Always | For ODH: look for branch name mentions; For RHOAI: derive from `target_rhoai_version` |
| `context_path` | Always | Docker build context; default `./` if not mentioned |
| `dockerfile_path` | Always | Look for Dockerfile references; RHOAI requires `Dockerfile.konflux` prefix |
| `is_operator` | Always | Look for "operator", "controller", "CRD" mentions; default `false` |
| `build_type` | ODH only | "CI" or "Release"; look for build type mentions |
| `target_rhoai_version` | RHOAI only | Version like "3.5", "3.4-ea-2"; look for version references |
| `architectures` | RHOAI only | CPU architectures; default `["x86_64", "arm64"]` |
| `long_description` | RHOAI only | One or two sentences describing the component |
| `short_description` | RHOAI only | Short noun phrase summary |
| `release_category` | RHOAI only | "Generally Available", "Tech Preview", or "Beta" |
| `operator_manifest_src_path` | If operator | Path to manifests in the git repo |
| `operator_manifest_dest_path` | If operator | Destination path in odh-operator image |

**Important extraction guidelines:**
- If a field is found in multiple sources with conflicting values, prefer the epic's
  own description over sibling epics, and newer comments over older ones.
- If a field cannot be extracted with confidence, mark it as `UNKNOWN` and note the
  ambiguity — do NOT guess.
- For `repo_branch` when `product_context == RHOAI`: derive automatically from
  `target_rhoai_version` following the convention:
  - No EA suffix (e.g. `3.5`): `repo_branch = "rhoai-3.5"`
  - EA suffix (e.g. `3.5-ea-1`): `repo_branch = "rhoai-3.5-ea.1"`

Store the extracted values. Track which fields were found and which remain unknown.

### Step A.4: Check for Existing Attachment

Read the issue JSON to check if `component_onboarding_details.yaml` is already
attached to the epic:

```bash
HAS_YAML=$(jq -r '[.fields.attachment[]? | select(.filename == "component_onboarding_details.yaml")] | length > 0' \
  "$WORKDIR/component_onboarding_details.json" 2>/dev/null || echo "false")
```

If `HAS_YAML == "true"`: download the existing attachment to compare:
```bash
(cd "$WORKDIR" && uv run --script scripts/download_jira_attachment.py "$JIRA_URL" component_onboarding_details.yaml)
```

Read the downloaded YAML and merge: keep existing values for any fields that were
extracted as `UNKNOWN` in Step A.3. For fields where a new value was extracted,
prefer the new value.

### Step A.5: Generate YAML

Only proceed if at least `component_name`, `repo_url`, and `product_context` were
extracted (or exist in the existing attachment). If these critical fields are all
`UNKNOWN`, stop with:
```
ERROR in Step A.5: Cannot generate YAML — critical fields (component_name, repo_url,
product_context) could not be determined from the epic's context.
Please add this information to the Jira epic description and re-run.
```

Build the argument list from extracted values and call:

```bash
YAML_PATH="${WORKDIR}/component_onboarding_details.yaml"

YAML_ARGS=(
  --output "$YAML_PATH"
  --product-context "$product_context"
  --component-name "$component_name"
  --repo-url "$repo_url"
  --repo-branch "$repo_branch"
  --context-path "$context_path"
  --dockerfile-path "$dockerfile_path"
)

# Add product-specific args based on product_context
# Add operator args if is_operator is true
# (see create-component-onboarding-jira/SKILL.md Step 5 for the full pattern)

uv run --script scripts/generate_onboarding_yaml.py "${YAML_ARGS[@]}"
```

On exit 1: display stderr and stop with:
```
ERROR in Step A.5: Could not generate YAML file. Aborting.
```

### Step A.6: Upload YAML and Update Jira

Upload the generated YAML to the Jira epic:

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --attach "$YAML_PATH" \
  --add-label "info-generated"
```

Count how many fields are `UNKNOWN` or missing. If any required fields are missing:

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "info-incomplete" \
  --comment "Onboarding Info Generator: Generated component_onboarding_details.yaml with partial information.

Missing fields: <list of UNKNOWN fields>

Please add the missing information to this epic's description or comments, then re-run the assessment."
```

If all fields are populated:

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --remove-label "info-incomplete" \
  --comment "Onboarding Info Generator: All onboarding fields extracted successfully from epic context.

Component: <component_name>
Product: <product_context>
Repo: <repo_url> @ <repo_branch>"
```

---

## Stage B: Onboarding Info Validator

**Goal:** Validate all extracted fields meet schema requirements, format
constraints, and cross-check product-specific rules.

### Step B.1: Validate Against Schema

```bash
uv run --script scripts/validate_yaml_schema.py \
  "$YAML_PATH" \
  schemas/component_onboarding_details.schema.json
```

On exit 0: print `Schema validation passed.` — record `SCHEMA_VALID=true`.

On exit 1: capture stderr as `SCHEMA_ERRORS`. Record `SCHEMA_VALID=false`.
Print the errors but continue — Stage C will use this result for scoring.

### Step B.2: AI-Powered Format and Cross-Validation

Read the YAML file content and perform these checks using natural language
understanding:

1. **Name format:** Verify `component_name` matches `^odh-[a-z0-9]+(-[a-z0-9]+)*$`
2. **URL format:** Verify `repo_url` matches `^https://github\.com/.+/.+$`
3. **Branch naming:** For RHOAI, verify `repo_branch` follows the `rhoai-X.Y` or
   `rhoai-X.Y-ea.N` convention and matches `target_rhoai_version`
4. **Dockerfile naming:** For RHOAI, verify `dockerfile_path` basename contains
   `Dockerfile.konflux`
5. **Product-specific required fields:** ODH needs `build_type`; RHOAI needs
   `architectures`, `target_rhoai_version`, `long_description`, `short_description`,
   `release_category`

Record all violations as a list: `VALIDATION_VIOLATIONS`.

### Step B.3: Dockerfile Checks

Read `repo_url`, `repo_branch`, `context_path`, and `dockerfile_path` from the YAML.

Check Dockerfile exists:

```bash
REPO_SLUG=$(echo "$repo_url" | sed 's|https://github.com/||;s|\.git$||')
CLEAN_CTX="${context_path%/}"; CLEAN_CTX="${CLEAN_CTX#./}"
if [[ -z "$CLEAN_CTX" || "$CLEAN_CTX" == "." ]]; then
  DF_FILE_PATH="$dockerfile_path"
else
  DF_FILE_PATH="${CLEAN_CTX}/${dockerfile_path}"
fi

bash scripts/check_github_file.sh \
  --repo-path "$REPO_SLUG" \
  --file-path "$DF_FILE_PATH" \
  --ref "$repo_branch"
DF_EXISTS=$?
```

Record: `DOCKERFILE_EXISTS` (0=yes, 1=no, 2=error).

If Dockerfile exists and `product_context == RHOAI`, check digest pinning:

```bash
REPO_RAW_BASE="${repo_url/github.com/raw.githubusercontent.com}"
if [[ -z "$CLEAN_CTX" || "$CLEAN_CTX" == "." ]]; then
  DOCKERFILE_RAW_URL="${REPO_RAW_BASE}/${repo_branch}/${dockerfile_path}"
else
  DOCKERFILE_RAW_URL="${REPO_RAW_BASE}/${repo_branch}/${CLEAN_CTX}/${dockerfile_path}"
fi

uv run --script scripts/check_dockerfile_digests.py \
  --dockerfile-url "$DOCKERFILE_RAW_URL" 2>&1
DIGEST_EXIT=$?
```

Record: `DIGEST_PINNED` (0=all pinned, 1=violations, 2=not reachable).

### Step B.4: Record Validation Status on Jira

Compile all validation results (schema, format, Dockerfile) and post to Jira:

If all validations passed:
```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "validation-successful" \
  --remove-label "validation-failed"
```

If any validation failed:
```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "validation-failed" \
  --remove-label "validation-successful" \
  --comment "Onboarding Info Validator: Validation issues found.

<list all violations with details>

These issues will affect the readiness score. Fix the issues and re-run the assessment."
```

---

## Stage C: Onboarding Readiness Rubric Score

**Goal:** Score 6 dimensions (0–2 each, max 12) using a combination of
script-based checks and AI analysis.

### Step C.1: Run Repo Structure Checks

Read `repo_url`, `repo_branch`, `product_context`, `context_path`, and
`dockerfile_path` from the YAML.

Determine which branches to check:
- Always check the branch specified in `repo_branch`
- For ODH: also check `main`
- For RHOAI: also check `main` and the product-specific branch pattern

```bash
BRANCHES_TO_CHECK="$repo_branch,main"

REPO_STRUCTURE=$(bash scripts/check_repo_structure.sh \
  --repo-url "$repo_url" \
  --branches "$BRANCHES_TO_CHECK" \
  --check-tests \
  --check-ci \
  --check-dockerfile \
  --context-path "$context_path" \
  --dockerfile-path "$dockerfile_path" \
  --ref "$repo_branch")
```

Save the JSON output for scoring.

### Step C.2: Fetch Dependency Files

Attempt to fetch common dependency manifest files from the repo to assess
dependency resolution:

```bash
REPO_SLUG=$(echo "$repo_url" | sed 's|https://github.com/||;s|\.git$||')
```

Try each of these files (non-blocking — exit 1 just means file doesn't exist):
- `go.mod`
- `go.sum`
- `requirements.txt`
- `pyproject.toml`
- `package.json`
- `Cargo.toml`

```bash
for dep_file in go.mod go.sum requirements.txt pyproject.toml package.json Cargo.toml; do
  bash scripts/check_github_file.sh \
    --repo-path "$REPO_SLUG" \
    --file-path "$dep_file" \
    --ref "$repo_branch" \
    --output "$WORKDIR/deps_${dep_file}" 2>/dev/null || true
done
```

### Step C.3: AI-Powered Rubric Scoring

Using the repo structure report from C.1, the dependency files from C.2,
the validation results from Stage B, and the YAML content, score each dimension.

**Scoring rules:**

**1. Code Completeness (0–2):**
- Score 0: `repo_exists == false` OR `has_source_code == false`
- Score 1: `has_source_code == true` BUT (`has_test_dir == false` OR `test_file_count < 3`)
- Score 2: `has_source_code == true` AND `has_test_dir == true` AND `test_file_count >= 3`

**2. Repository Setup (0–2):**
- Score 0: `repo_exists == false`
- Score 1: `repo_exists == true` BUT one or more required branches do not exist
- Score 2: `repo_exists == true` AND all checked branches exist

**3. Dockerfile Readiness (0–2):**
- Score 0: `DOCKERFILE_EXISTS != 0` (Dockerfile not found)
- Score 1: Dockerfile exists BUT `DIGEST_PINNED != 0` (not digest-pinned, or ODH where digests aren't required)
- Score 2: Dockerfile exists AND (`DIGEST_PINNED == 0` for RHOAI, or ODH where digests are not checked)
- Note: For ODH components, if the Dockerfile exists, score 2 is given (digest pinning not required)

**4. Dependency Resolution (0–2):**
- Score 0: No dependency files found (none of go.mod, requirements.txt, etc. exist)
- Score 1: Dependency file(s) found but **AI analysis determines** they are incomplete
  (e.g., go.mod exists but has replace directives pointing to local paths, or
  requirements.txt has unpinned versions, or imports in code reference packages
  not listed in dependency files)
- Score 2: Dependency file(s) found AND AI analysis determines they are complete and
  well-structured (pinned versions, no local path replacements, consistent with
  language ecosystem best practices)

**5. Info Completeness (0–2):**
- Score 0: `SCHEMA_VALID == false` AND 3 or more required fields are missing
- Score 1: `SCHEMA_VALID == false` BUT only 1-2 required fields missing, OR
  `SCHEMA_VALID == true` BUT `info-incomplete` label exists
- Score 2: `SCHEMA_VALID == true` AND no `info-incomplete` label

**6. CI/CD Prerequisites (0–2):**
- Score 0: `has_github_actions == false` AND `has_tekton == false` AND `has_makefile == false`
- Score 1: At least one CI indicator exists BUT not a complete setup (e.g., Makefile
  but no GitHub Actions or Tekton)
- Score 2: `has_github_actions == true` OR `has_tekton == true` (proper CI pipeline in place)

Compute the total score (sum of all 6 dimensions).
Store a reason string for each dimension explaining the score.

### Step C.4: Save Assessment Results

Write `maturity_assessment.json` to the working directory:

```json
{
  "component_name": "<component_name>",
  "product_context": "<product_context>",
  "timestamp": "<ISO 8601 timestamp>",
  "scores": {
    "code_completeness": <0-2>,
    "repository_setup": <0-2>,
    "dockerfile_readiness": <0-2>,
    "dependency_resolution": <0-2>,
    "info_completeness": <0-2>,
    "cicd_prerequisites": <0-2>
  },
  "total_score": <0-12>,
  "ready": <true|false>,
  "reasons": {
    "code_completeness": "<reason>",
    "repository_setup": "<reason>",
    "dockerfile_readiness": "<reason>",
    "dependency_resolution": "<reason>",
    "info_completeness": "<reason>",
    "cicd_prerequisites": "<reason>"
  }
}
```

Write this JSON to `$WORKDIR/maturity_assessment.json`.

### Step C.5: Post Score to Jira

Upload the assessment JSON and post a structured score comment:

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --attach "$WORKDIR/maturity_assessment.json" \
  --comment "Onboarding Readiness Assessment — <component_name>
═══════════════════════════════════════════════════
  Code Completeness      : <X>/2  — <reason>
  Repository Setup       : <X>/2  — <reason>
  Dockerfile Readiness   : <X>/2  — <reason>
  Dependency Resolution  : <X>/2  — <reason>
  Info Completeness      : <X>/2  — <reason>
  CI/CD Prerequisites    : <X>/2  — <reason>
  ─────────────────────────────────────────
  Total                  : <XX>/12

Threshold: ≥ 9/12 AND no dimension = 0
Result: <READY / NOT READY>"
```

---

## Stage D: Onboarding Readiness Evaluator

**Goal:** Evaluate the readiness threshold and label the epic accordingly,
with remediation hints for failed dimensions.

### Step D.1: Evaluate Threshold

Check two conditions:
1. `total_score >= 9`
2. No dimension has a score of 0

Both must be true for the component to be considered ready.

### Step D.2: Update Jira Labels

**If READY (both conditions met):**

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "ready-for-human-review" \
  --remove-label "not-ready-for-onboarding" \
  --add-label "maturity-assessed"
```

**If NOT READY:**

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --add-label "not-ready-for-onboarding" \
  --remove-label "ready-for-human-review" \
  --add-label "maturity-assessed"
```

### Step D.3: Generate Remediation Hints (NOT READY only)

For each dimension that scored less than 2, generate a specific, actionable
remediation hint using AI/NLP. The hints should be concrete and reference the
actual repo/component details.

Post remediation hints as a Jira comment:

```bash
uv run --script scripts/update_jira_issue.py "$JIRA_URL" \
  --comment "Remediation Required — <component_name>
═══════════════════════════════════════

<For each dimension scoring < 2, include:>

N. <Dimension Name> (scored <X>/2):
   → <Specific, actionable remediation step>
   → <Example or reference if applicable>

Re-run /onboarding-maturity-assessor after addressing these items."
```

**Example remediation hints by dimension:**

- **Code Completeness:** "Add unit tests to cover core functionality. Create a
  `tests/` directory with test files for the main packages."
- **Repository Setup:** "Create branch `rhoai-3.5` from `main` in the GitHub repo."
- **Dockerfile Readiness:** "Pin all FROM instructions with @sha256 digests. Example:
  `FROM registry.access.redhat.com/ubi9/ubi-minimal@sha256:<hex>`"
- **Dependency Resolution:** "Add a `go.sum` file by running `go mod tidy`. Remove
  local `replace` directives from `go.mod`."
- **Info Completeness:** "Add `target_rhoai_version` and `release_category` to the
  epic description."
- **CI/CD Prerequisites:** "Add GitHub Actions workflows under `.github/workflows/`
  with at least build and test jobs."

---

## Step Final: Report Completion

Print a summary:
```
Onboarding Maturity Assessment Complete
═══════════════════════════════════════

  Epic          : <JIRA_ID> (<JIRA_URL>)
  Component     : <component_name>
  Product       : <product_context>
  Total Score   : <XX>/12
  Result        : <READY / NOT READY>
  Labels Set    : <list of labels added>

  Assessment file: $WORKDIR/maturity_assessment.json

<If READY:>
  Next step: This epic is ready for human review. After approval,
  run /create-component-onboarding-jira to create the onboarding tickets.

<If NOT READY:>
  Next step: Address the remediation items above and re-run:
  /onboarding-maturity-assessor <JIRA_URL>
```

---

## Error Reference

| Error | Stage | Action |
|-------|-------|--------|
| Jira URL not provided | Step 0 | Provide the epic URL as an argument |
| `JIRA_USER_EMAIL` / `JIRA_API_TOKEN` not set | Step 0 | Export the env vars |
| `GITHUB_TOKEN` not set | Step 0 | Export `GITHUB_TOKEN` with repo scope |
| Jira fetch fails (401/403/404) | A.1 | Check credentials and issue key |
| Critical fields cannot be extracted | A.5 | Add info to the epic description |
| Schema validation fails | B.1 | Fix YAML fields (may be auto-fixed on re-run) |
| Dockerfile not found | B.3 | Create the Dockerfile at the specified path |
| Digest pinning violations | B.3 | Pin all FROM instructions with @sha256 digests |
| Repo not accessible | C.1 | Check repo URL and GITHUB_TOKEN permissions |
| Score below threshold | D.1 | Follow the remediation hints posted on Jira |
