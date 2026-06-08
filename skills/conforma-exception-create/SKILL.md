---
name: conforma-exception-create
description: Create Jira tickets and a GitLab MR to add a Conforma exception/waiver policy when a violation cannot or should not be fixed. Handles RHOAIENG, PSX/OCPEXCEPT tickets, and exception MR creation with validation and dry-run support.
allowed-tools: Bash(python3:*,acli:*,glab:*,git:*,docker:*,podman:*)
user-invocable: true
---

# Conforma Exception Create

End-to-end automation for RHOAI Conforma exception requests: validates inputs, creates required Jira tickets, generates the exception YAML, creates a GitLab MR, and cross-links all artifacts.

## Prerequisites

The skill requires `acli` (Atlassian CLI) and `glab` (GitLab CLI). **`acli` is auto-installed** to `~/.local/bin/` on first use if not already on PATH. `glab` must be installed manually.

**Always run preflight first** before creating any tickets or MRs:

```bash
python3 scripts/verify_auth.py --path A
```

### Install glab

On Fedora/RHEL:

```bash
sudo dnf install glab
```

On macOS:

```bash
brew install glab
```

### One-time authentication

After tools are available, authenticate once (credentials persist across sessions):

1. **Jira**: generate an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens), then:

```bash
echo "YOUR_TOKEN" | acli jira auth login --site redhat.atlassian.net --email "$USER@redhat.com" --token
```

2. **GitLab**: go to [gitlab.cee.redhat.com/-/user_settings/personal_access_tokens](https://gitlab.cee.redhat.com/-/user_settings/personal_access_tokens), create a token named `glab-cli` with `api` scope and 1 year expiration, then:

```bash
glab auth login --hostname gitlab.cee.redhat.com --token "YOUR_TOKEN"
```

### Container fallback (advanced)

If auto-install fails (restricted network, unsupported platform), the scripts fall back to container images via docker/podman:

| Tool | Default image | Override env var |
|------|--------------|------------------|
| acli | `docker.io/davidsmith3/acli:latest` | `ACLI_IMAGE` |
| glab | `docker.io/gitlab/glab:latest` | `GLAB_IMAGE` |

Container mode requires API token authentication since `--web` OAuth cannot open the host browser from inside a container. See `verify_auth.py` output for container-specific auth instructions.

## Important: Human-in-the-Loop

Exception MRs bypass policy enforcement. Engineer approval is **MANDATORY** before creation.
For versions >= rhoai-3.5-ea.1, senior manager approval on the RHOAIENG ticket is also required.

### No Guessing Policy

**NEVER assume, infer, or hallucinate details.** Every piece of information used in tickets or MRs MUST be either:
- Explicitly stated by the user, OR
- Read directly from an authoritative source (Jira ticket, ReleasePlanAdmission file, policy file)

When uncertain about ANY detail (signing key ID, component names, versions, dates, relationships):
1. **Stop and ask the user** -- present what you found and ask them to confirm or correct.
2. **Persist confirmed details in Jira/skill** -- do not rely on agent conversation context alone. All confirmed details must be recorded in the Jira ticket (comment or description) and/or the skill files so they survive session boundaries.
3. **Show your work** -- before executing, show the user the exact values that will be used (rule, components, dates, links) and wait for explicit approval.

Gaps or ambiguities discovered during execution MUST be:
- Surfaced to the user immediately (not papered over with assumptions)
- Added to this skill's pre-flight checklist so future runs catch them earlier

## Three Exception Paths

| Path | When | Jira tickets | MR target |
|------|------|--------------|-----------|
| A (Standard) | Security exceptions (hermetic, RPM, SBOM) | RHOAIENG + PSX | `config/.../registry-rhoai-{env}.yaml` or `fbc-rhoai-{env}.yaml` |
| B (FIPS) | FIPS-related exceptions | RHOAIENG + OCPEXCEPT | Same as Path A |
| C (Self-service) | `schedule.weekday_restriction` or `test.no_failed_tests:fbc-target-index-pruning-check` | RHOAIENG only | `exceptions/fbc-rhoai-prod.yaml` |

Path is auto-detected from `--rule` and `--fips`/`--self-service` flags.

## Usage

### Standalone mode (user-provided details)

```bash
python3 scripts/create_exception.py \
  --rhoai-version rhoai-3.3 \
  --rule hermetic_task.hermetic \
  --components odh-mlflow-v3-3,odh-another-v3-3 \
  --justification 2 \
  --effective-until-date 2026-10-03 \
  --environment prod \
  --dry-run
```

### With existing Jira tickets

```bash
python3 scripts/create_exception.py \
  --rhoai-version rhoai-3.3 \
  --rule hermetic_task.hermetic \
  --components odh-mlflow-v3-3 \
  --justification 2 \
  --effective-until-date 2026-10-03 \
  --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38414 \
  --psx-url https://redhat.atlassian.net/browse/PSX-1089
```

### Self-service (Path C)

```bash
python3 scripts/create_exception.py \
  --rhoai-version rhoai-3.4 \
  --rule schedule.weekday_restriction \
  --components rhoai-fbc-fragment-v3-4 \
  --self-service \
  --image-ref sha256:abc123...
```

## Required Information

| Detail | Flag | Notes |
|--------|------|-------|
| RHOAI version | `--rhoai-version` | e.g., `rhoai-3.3`, `rhoai-3.5-ea.1` |
| Policy rule | `--rule` | Full rule value (e.g., `hermetic_task.hermetic`) |
| Component names | `--components` | Comma-separated Konflux component names |
| Justification | `--justification` | `1` or `2` (required for Paths A/B, see below) |
| Base expiry date | `--effective-until-date` | YYYY-MM-DD (script adds +7 days buffer) |

### Justification values

- `1`: "violation was not fixed in time before code-freeze of the current rhoai release, it is planned to be fixed in the next release"
- `2`: "violation can't be fixed in this rhoai release as it's already been code-frozen/released and major code changes are not allowed in subreleases/z-stream releases"

### Optional flags

| Flag | Default | Description |
|------|---------|-------------|
| `--environment` | `prod` | `prod` or `stage` |
| `--rhoaieng-url` | *(creates new)* | Existing RHOAIENG ticket URL |
| `--psx-url` | *(creates new)* | Existing PSX/OCPEXCEPT ticket URL |
| `--related-psx` | none | Pre-existing PSX ticket to link as "Related" only (a new PSX is still created) |
| `--link-to` | none | Tracking ticket key to link all tickets to (e.g. `RHAISTRAT-576`) |
| `--summary-context` | none | Brief description for ticket titles (appended after rule and version) |
| `--vendor-tag` | none | Vendor/distinguisher tag prepended to titles (e.g. `AMD`, `Intel`, `FIPS`) |
| `--spreadsheet-url` | none | Tracking spreadsheet URL (added as YAML comment in MR and commit message) |
| `--authorized-party` | none | Senior manager accepting risk (Authorized Party in PSX workflow) |
| `--fips` | false | Routes to OCPEXCEPT instead of PSX |
| `--self-service` | false | Forces Path C |
| `--image-ref` | none | SHA digest (only for `schedule.weekday_restriction`) |
| `--reconcile` | none | Existing ticket key to reconcile (idempotent re-run) |
| `--dry-run` | false | Preview without creating anything |
| `--output` | stdout | Write result JSON to file |

## Orchestration Flow

1. **Validate** (`validate_inputs.py`): version parsing, component-version reconciliation (rejects image names like `-rhel9`), date+7 calculation, justification check, path detection
2. **Auth check** (`verify_auth.py`): auto-install `acli` if needed, verify `acli` and `glab` are available and authenticated — **stop here if any check fails**
3. **RHOAIENG ticket** (`create_jira_ticket.py --project RHOAIENG`): template-based create from RHOAIENG-62569 (skipped if `--rhoaieng-url` provided)
4. **Approval reminder**: for rhoai-3.5-ea.1+, reminds user to get senior manager approval
5. **PSX/OCPEXCEPT ticket** (`create_jira_ticket.py --project PSX|OCPEXCEPT`): Paths A/B only (skipped if `--psx-url` provided or Path C)
6. **GitLab MR** (`create_gitlab_mr.py`): clone from `main`, create branch, append exception YAML block (with PSX title as inline comment, spreadsheet URL as YAML comment), commit, push, create MR. Auto-fetches the PSX ticket title for the `reference:` line comment. Use `--update-mr <branch>` to recreate an existing MR branch from current `main` (avoids disconnected-history issues).
7. **Link artifacts** (`link_artifacts.py`): comment MR URL on both Jira tickets, add provenance label, create Jira links between all tickets (including `--link-to` tracking ticket)

All created tickets receive the `conforma-exception-create-ai-skill` and `conforma-violation` Jira labels and a provenance footer in the description.

**Linking rules**: Only create Jira links between tickets that the script explicitly creates or that the user explicitly provides via `--link-to`, `--rhoaieng-url`, or `--psx-url`. Do NOT auto-infer or auto-create links to other tickets found in descriptions, comments, or conversation context. If a potential relationship is noticed, suggest it to the user and wait for confirmation before linking.

**Before running**, gather the following from the user using structured questionnaires. Present questions as **multiple-choice** selections (using AskQuestion tool in Cursor, or structured options in Claude Code) wherever possible. Do NOT present questions as plain text expecting free-form answers unless the answer genuinely requires free text input. Batch related questions together to minimize back-and-forth. Do NOT proceed until all items are confirmed.

**Questionnaire presentation rules:**
- Use the `AskQuestion` tool (Cursor) or equivalent structured prompts (Claude Code) for all questions that have a finite set of valid answers
- Group questions into logical batches (e.g., batch 1: rule/ticket/version basics; batch 2: components; batch 3: PSX details)
- For questions with known options, always present them as selectable choices (never ask the user to type "a" or "b")
- For questions requiring free text (dates, names, URLs), present them as individual prompts with clear examples
- After each batch, summarize confirmed answers before moving to the next batch
- If a question's options depend on earlier answers (e.g., component names depend on version), resolve dependencies first then present options

**Batch 1 — Rule and ticket basics:**

1. **Conforma rule confirmation**: Extract the rule from the RHOAIENG Jira ticket and present as a confirmation choice. Example options:
   - "Yes, the rule is `rpm_signature.allowed:8a3872bf3228467c`"
   - "No, the rule is different (let me specify)"

2. **RHOAIENG ticket type check**: If the ticket is not a Blocker Bug, present options:
   - "Create a proper Blocker Bug and link to this Epic/Story"
   - "Use this ticket as-is (non-standard)"

3. **RHOAI versions**: Present all versions found in the ticket as multi-select. Example:
   - [ ] rhoai-2.25
   - [ ] rhoai-3.3
   - [ ] rhoai-3.4
   - [ ] rhoai-3.5-ea.1

4. **Multi-version handling** (if multiple versions selected):
   - "One PSX + RHOAIENG ticket per version (recommended, standard)"
   - "Single consolidated ticket covering all versions"

5. **Justification**:
   - "1 — Violation not fixed in time before code-freeze, planned for next release"
   - "2 — Can't be fixed in this release (already code-frozen/released)"

**Batch 2 — Components and identifiers:**

6. **Component name lookup and confirmation**: Look up Konflux componentNames from ReleasePlanAdmission files, then present the resolved names for confirmation. Example:
   - "Confirm these are the correct Konflux component names for rhoai-3.3: `odh-vllm-cpu-v3-3`, `odh-vllm-gaudi-v3-3`"
   - "Yes, correct"
   - "No, let me specify different names"

   Never use a container image name (e.g. `-rhel9`) in an MR without the user confirming the translation.

7. **Vendor tag**: Present common options plus free text:
   - "Fedora/EPEL"
   - "AMD"
   - "Intel"
   - "Mellanox"
   - "FIPS"
   - "Other (let me specify)"
   - "None / skip"

8. **Tracking ticket**: Present options:
   - "Yes, link to: [ticket key from Jira context if found]"
   - "Yes, let me provide a ticket key"
   - "No tracking ticket"

9. **Related PSX (existing)**: Auto-discover by searching Jira: `project = PSX AND text ~ '<signing_key_or_rule>'`. If found, present the result(s) for confirmation:
   - "Found PSX-XXXX: <title> [status]. Link as Related?"
   - "Yes, link as Related"
   - "No, skip"

   If no results found, silently skip (do not ask the user). This removes a manual lookup step.

10. **Summary context**: Free text prompt with example:
    - Example: "long-standing Fedora/EPEL RPM signing key exception"

**Batch 3 — Approval and PSX details:**

11. **Authorized Party**: Free text prompt:
    - "Who is the senior manager accepting risk? (e.g., Lindani Phiri, Jay Koehler)"

12. **Effective-until date**: When multiple versions are involved, present per-version dates based on end-of-support/EUS deadlines. Always confirm with the user before using.

    Default end-of-support dates (use as starting point, confirm with user):

    | RHOAI Version | End of Support / EUS | Default effectiveUntil |
    |---|---|---|
    | rhoai-2.25 | 2027-04-19 | 2027-04-26 (+7 days) |
    | rhoai-3.3 | 2026-09-28 | 2026-10-05 (+7 days) |
    | rhoai-3.4 | 2026-08-05 | 2026-08-12 (+7 days) |
    | rhoai-3.5-ea.1 | 2026-06-12 | 2026-06-19 (+7 days) |

    The skill should ask/query: "What are the end-of-support / end-of-EUS dates for each release?" and present the known defaults for confirmation. Script adds +7 days buffer automatically, so the dates above already include that buffer.

    Present as: "Confirm per-version effectiveUntil dates (end-of-support + 7 days buffer):" with each version as a confirmation item.

13. **PSX template details** (needed to fill the PSRD Exception form after ticket creation). Present as individual prompts:
    - **Scope**: "What specific components/images are affected? How many instances?"
    - **Risk acceptance**: "What is the risk being accepted? Why is it acceptable?"
    - **Remediation plan**: "How and when will the violation be permanently fixed?"
    - **Impact if denied**: "What breaks if the exception is not approved?"

    These details MUST come from the user or be explicitly present in the RHOAIENG Jira. If not clearly available, ask the user -- do NOT fabricate or generalize.

**After all batches**: Present a final summary of all confirmed values and ask for a single "Proceed" / "Edit something" confirmation before executing.

## Component Version Reconciliation

Component names are validated against `--rhoai-version`:
- `rhoai-3.3` + `odh-dashboard-v3-3` = valid
- `rhoai-3.5-ea.1` + `odh-dashboard-v3-5-ea-1` = valid
- `rhoai-3.3` + `odh-dashboard-v3-5` = ERROR (version mismatch)

**IMPORTANT: componentNames vs container image names** -- these are NOT the same thing:

| Type | Pattern | Example | Used in MR? |
|------|---------|---------|-------------|
| Konflux component name | `{base}-v{major}-{minor}` | `odh-workbench-jupyter-pytorch-rocm-py312-v2-25` | YES |
| Container image name | `{base}-rhel9` (no version) | `odh-workbench-jupyter-pytorch-rocm-py312-rhel9` | NO |

All Konflux component names include a version suffix (e.g. `-v2-25`, `-v3-3`, `-v3-5-ea-1`). Names ending in `-rhel9` or `-ubi9` without a version suffix are container image names produced by those components -- they must NOT be used in `componentNames` fields in exception MRs. The validation script rejects image names and suggests the correct format.

To find correct component names, check the ReleasePlanAdmission files:
`config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-vX-Y-components-prod.yaml`

## Dry-Run Mode

`--dry-run` validates all inputs and outputs what would be created (YAML block, target file, Jira details) as structured JSON without submitting anything. Auth checks still run.

## Verification Contract

Every ticket creation or reconciliation ends with a **verification phase** that reads the ticket back via Jira REST API and checks:

| Field | Check |
|-------|-------|
| Labels | Contains both `conforma-exception-create-ai-skill` and `conforma-violation` |
| Issue links | Includes all expected targets (RHOAIENG, tracking ticket) |
| Description | ADF with >= 15 panel/paragraph nodes (PSX/OCPEXCEPT) |
| Authorized Party | `customfield_10938` is set (PSX/OCPEXCEPT) |

If any check fails, the script **retries the failed operation** (up to 2 attempts) and re-verifies. If it still fails, the script exits non-zero with structured JSON listing exactly what expectations are unmet.

All operations return structured dicts reporting what was attempted, what the actual state is, and what failed -- never silent True/False. This makes failures visible to both the agent and the user.

## Reconcile Mode

The `--reconcile TICKET_KEY` flag on `create_jira_ticket.py` enables idempotent re-runs:

```bash
python3 scripts/create_jira_ticket.py --project PSX \
  --reconcile PSX-1098 \
  --rule rpm_signature.allowed:9386b48a1a693c5c \
  --components odh-workbench-jupyter-pytorch-rocm-py312-v2-25 \
  --justification "..." --rhoai-version rhoai-2.25 \
  --effective-until 2027-05-03T00:00:00Z \
  --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38426 \
  --authorized-party "Len DiMaggio"
```

Behavior:
- Reads the ticket's current state via REST API
- Computes what's missing (labels, links, description, authorized party)
- Applies **only** the needed changes
- Ends with full verification
- Returns `"status": "reconciled"` if all checks pass, `"status": "partial"` if unmet expectations remain

This handles cases where a previous run partially succeeded (ticket created but fields missing).

## Existing Exception Deduplication

When creating an MR, the script checks the target policy file for existing exceptions matching the same rule (`- value: <rule>`). The behavior depends on whether the existing exception uses `componentNames`:

| Existing exception style | Behavior |
|---|---|
| No existing exception for this rule | Append new block (standard behavior) |
| Uses `componentNames` and components match | **Extend**: update `effectiveUntil` date in-place (no new block created) |
| Uses `componentNames` but different components | Append new block alongside existing |
| Old-style (no `componentNames`) | Leave intact, append a **new** block using `componentNames` |

This ensures:
- Version-scoped exceptions (using `componentNames`) are extended rather than duplicated when only the expiry date changes
- Legacy exceptions without `componentNames` are never modified (they may apply broadly); a new version-scoped block is added instead
- The commit message reflects whether the exception was "extended" vs. "added"

## Commit Message Structure

MR commits follow a structured multi-line format with provenance:

```text
Add conforma exception: <rule> (<rhoai-version>)

Exception details:
  Rule: <rule>
  RHOAI version: <rhoai-version>
  Effective until: <date>
  Components: <component-list>
  Policy file: <path>

RHOAIENG: <url>
Reference: <psx-url>
Spreadsheet: <url>

---
Generated by: conforma-exception-create-ai-skill
Source: https://github.com/opendatahub-io/ai-helpers
User: <user>@<hostname>
```

## Error Handling

Each script validates inputs and exits non-zero on failure. The orchestrator stops at the first failure, preserving partial results in the output JSON. Common errors:

- Invalid RHOAI version format
- Component name / version mismatch
- `--effective-until-date` not a future date
- `acli` or `glab` not authenticated
- GitLab MR creation failure (permissions, branch conflict)
- Jira ticket creation failure (permissions, invalid project)
- Verification failure (labels, links, or fields not confirmed after retries)

## Reference Documentation

See `references/exception-process.md` for the full process documentation including:
- Jira project routing rules
- Senior manager approval requirements
- VolatileCriteria schema
- Upstream reference links (Konflux docs, PSX Confluence, conforma.dev)

## Pipeline Mode (Handover)

For backward compatibility with the `conforma-troubleshooter` agent, the orchestrator also accepts `--output` to write structured JSON results compatible with the handover document format.
