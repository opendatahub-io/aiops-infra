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

### No Agent Decisions Policy

**The agent MUST NOT make decisions about parameter values.** All parameters are resolved by deterministic scripts. The agent's ONLY role is:
1. Run `preflight_check.py` to resolve all values from authoritative sources
2. Present the script's output to the user as a structured questionnaire for confirmation
3. Execute the creation scripts with the confirmed values
4. Report results

The agent MUST NEVER:
- Decide link types (enforced by `link_artifacts.py`)
- Decide MR split strategy (enforced by `preflight_check.py` → `hard_rules.mr_strategy`)
- Decide ticket handling (enforced by duplicate detection in `preflight_check.py`)
- Infer rules, components, dates, or any other values (resolved by `preflight_check.py`)
- Create links without the script's idempotency checks
- Override any value from `hard_rules` in the preflight output

### Mandatory Pre-Flight Script

**ALWAYS run `preflight_check.py` FIRST** before any other action:

```bash
python3 scripts/preflight_check.py \
  --rhoaieng-url <url> \
  --versions rhoai-2.25,rhoai-3.3 \
  --image-bases odh-vllm-cpu,odh-vllm-gaudi \
  --clone-dir /tmp/conforma-check
```

The script outputs JSON containing:
- `hard_rules`: non-configurable behavior (link types, MR strategy, dedup logic)
- `rhoaieng`: ticket metadata and type warnings
- `rule`: extracted or overridden rule value
- `versions`: resolved RHOAI versions
- `components`: per-version component names from RPA files
- `effective_until`: per-version dates from end-of-support defaults
- `related_psx`: auto-discovered related PSX tickets
- `existing_exceptions`: current state in konflux-release-data
- `duplicate_check`: existing tickets created by this skill
- `user_confirmation_required`: items that need user approval

The agent presents `user_confirmation_required` items to the user and waits for confirmation. It does NOT modify any resolved values.

### Decision Short-Circuit

The preflight output includes a `decision` field evaluated deterministically by `evaluate_decision()`. When `decision.proceed` is `false`, the agent MUST:
1. Report the `decision.reason` to the user
2. Stop immediately — do NOT present remaining questionnaire items
3. Do NOT create tickets, MRs, or any other artifacts

The agent has NO discretion to override a `proceed: false` decision. Only the user can re-run with `--rule` override or manually modify the policy file.

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

**Linking rules**: Enforced deterministically by `link_artifacts.py`. The agent does not choose link types — the script applies them based on the relationship between tickets. Run `preflight_check.py` to see the `hard_rules` that govern linking behavior. Only create links between tickets that the script explicitly creates or that the user explicitly provides via `--link-to`, `--rhoaieng-url`, or `--psx-url`. Do NOT auto-infer links from descriptions/comments/conversation context.

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
   - "One PSX + RHOAIENG ticket per version (default, recommended)"
   - "Single consolidated PSX + RHOAIENG ticket covering all versions (once-off deviation)"

   MR split strategy is enforced by `preflight_check.py` → `hard_rules.mr_strategy`. The agent reads this value and follows it without modification.

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

12. **Effective-until date**: Resolved by `preflight_check.py` from its `DEFAULT_EOS_DATES` table. The script outputs per-version dates in `effective_until` and flags any versions without defaults in `user_confirmation_required`. Present the script's output for user confirmation.

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

Handled deterministically by `create_gitlab_mr.py` → `apply_exception_to_policy_file()`. The behavior is governed by `preflight_check.py` → `hard_rules.old_style_exception_handling` and `hard_rules.matching_componentNames_exception_handling`. The agent does not make deduplication decisions — the script detects existing exceptions and applies the correct action automatically.

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
