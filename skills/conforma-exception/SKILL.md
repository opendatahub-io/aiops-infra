---
name: conforma-exception
description: Manage RHOAI Conforma exceptions end-to-end — create, extend, check, and reconcile policy exceptions. Handles Jira tickets (RHOAIENG Jira, PSX Jira, OCPEXCEPT Jira), GitLab Merge Requests in konflux-release-data, deduplication of existing exceptions, and cross-linking of all artifacts.
allowed-tools: Bash(python3:*,acli:*,glab:*,git:*,docker:*,podman:*)
user-invocable: true
---

# Conforma Exception

End-to-end automation for RHOAI Conforma exception management: check existing exceptions, create new ones, extend effectiveUntil dates, validate inputs, create required Jira tickets, generate exception YAML, create GitLab Merge Requests, and cross-link all artifacts.

An exception is a YAML entry added to a release policy file in the `konflux-release-data` GitLab repository (hosted at `$GITLAB_HOST`), using the [VolatileCriteria](https://conforma.dev/docs/policy/packages/release_volatile_config.html) schema. It tells the [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy engine to waive a specific rule for listed components until a given date. Example:

```yaml
# https://redhat.atlassian.net/browse/RHOAIENG-12345
# impacted versions: rhoai-3.4
- value: hermetic_task.hermetic
  componentNames:
    - odh-model-server-v3-4
    - odh-modelmesh-serving-v3-4
  effectiveUntil: "2026-10-05T00:00:00Z"
  reference: https://redhat.atlassian.net/browse/PSX-1234
```

Key fields: `value` = the [Conforma rule](https://conforma.dev/docs/policy/release_policy.html) being waived, `componentNames` = Konflux component names (not container image names), `effectiveUntil` = expiry date in RFC3339 format, `reference` = the PSX/OCPEXCEPT Jira ticket URL.

## Violations-First Philosophy

**Conforma exceptions are a last resort, not the default resolution path.** When a violation is detected, the primary goal is to fix the underlying issue in the component code (e.g., enable hermetic builds, use signed RPMs, fix failing tests). An exception should only be created when a code fix is genuinely not feasible within the release timeline.

When presenting violations to the user:
- Frame next steps in terms of resolving the violation first
- Only suggest creating an exception when there's evidence the violation cannot be fixed in code (e.g., third-party RPM signing keys that Red Hat cannot control, upstream dependencies with known timelines)
- Never present "create exception" as the default or first-choice action for new violations without existing artifacts

## Prerequisites

**Setup:** See [README.md](README.md) for installation and one-time authentication setup.

**Always run preflight first** before creating any tickets or MRs:

```bash
python3 skills/conforma-exception/scripts/verify_auth.py
```

## Remote Data Access Policy

When fetching data from remote repositories (GitLab, GitHub):

- **ALWAYS** use the remote API directly (`glab api`, `gh api`, raw HTTP download via `curl`)
- **NEVER** use `find` to locate local clones, `cd` into them, or `git checkout`/`git show` on a local working tree
- **NEVER** assume a local clone is up-to-date or on the correct branch

Local clones on a dev workstation may be on a feature branch, days out of date, or modified with uncommitted changes. Using the remote API guarantees you always read the canonical, production state of the repository at the exact ref you specify.

```bash
# GOOD — fetch a file from GitLab
glab api "projects/releng%2Fkonflux-release-data/repository/files/path%2Fto%2Ffile.yaml/raw?ref=main" \
  --hostname $GITLAB_HOST

# BAD — using a local clone
cd ~/dev/gitlab/releng/konflux-release-data && git show origin/main:path/to/file.yaml
```

## RHOAIENG Approval Gate (Hard Prerequisite)

**The RHOAIENG approval Jira ticket is created by the DevOps engineer (typically using this skill) and then MUST be approved by Senior Management (Closed/Resolved) BEFORE creating the PSX/OCPEXCEPT Jira ticket and GitLab Merge Request.** This is a hard gate enforced by the orchestrator. When explaining this to the user, always make clear that the ticket is created first, then separately approved by Senior Management — never imply that Senior Management creates the ticket.

The orchestrator checks the RHOAIENG approval ticket status after creation (or when provided via `--rhoaieng-url`). If the ticket is not yet approved:

1. **The orchestrator halts** — PSX/OCPEXCEPT Jira and GitLab MR creation are blocked
2. **The user is instructed** to get Senior Management approval on the RHOAIENG ticket first
3. **Re-run** with `--rhoaieng-url <approved-ticket-url>` after approval is granted

Approval is detected by checking:
- Ticket status is Closed/Resolved/Done **AND** resolution is Done/Fixed/Approved/Complete
- **OR** a comment from a senior manager contains approval keywords (approved, LGTM, go ahead, etc.)

### User override

If the user explicitly requests to proceed without approval, the `--skip-approval-gate` flag bypasses the gate. The agent MUST:

1. **Warn the user clearly** that RHOAIENG approval is a hard prerequisite and PSX/OCPEXCEPT reviewers may reject the exception if approval is missing
2. **Ask for explicit confirmation** using the AskQuestion tool before passing `--skip-approval-gate`
3. **Never pass `--skip-approval-gate` without the user's explicit request** — the agent must not decide to skip the gate on its own

### Workflow behavior

The approval gate sits between the `rhoaieng_approval_jira` and `psx_exception_jira` workflow steps:

```
rhoaieng_resolution_plan_jira → rhoaieng_approval_jira → [APPROVAL GATE] → psx_exception_jira → exception_merge_request
```

In self-service workflows (no PSX step), the gate sits before the MR step:

```
rhoaieng_approval_jira → [APPROVAL GATE] → exception_merge_request (self-service)
```

### Preflight output

The `preflight_check.py` script includes an `rhoaieng_approval_status` field in its output:

```json
{
  "rhoaieng_approval_status": {
    "url": "https://redhat.atlassian.net/browse/RHOAIENG-12345",
    "key": "RHOAIENG-12345",
    "status": "Open",
    "resolution": null,
    "approved": false,
    "reason": "RHOAIENG-12345 is Open. RHOAIENG approval is required before creating PSX Jira ticket and GitLab Merge Request.",
    "approval_comment": null
  }
}
```

When `approved` is `false`, the agent MUST inform the user that they need to get approval first and MUST NOT proceed with PSX/MR creation unless the user explicitly overrides.

## Important: Human-in-the-Loop

Exception GitLab Merge Requests bypass policy enforcement. Engineer approval is **MANDATORY** before creation.
The RHOAIENG approval Jira ticket must be approved before PSX/MR creation (see "RHOAIENG Approval Gate" above).

### No Agent Decisions Policy

**The agent MUST NOT make decisions about parameter values.** All parameters are resolved by deterministic scripts. The agent's ONLY role is:
1. Run `preflight_check.py --check-existing-exception` — Existing Exception Gate (hard prerequisite, must pass before continuing)
2. Run `preflight_check.py` (full) to resolve all values from authoritative sources
3. Present the script's output to the user as a structured questionnaire for confirmation
4. **Dry-run first**: Always run `create_exception.py` with `--dry-run` before the real execution and present the preview to the user. Only proceed with the real execution after the user confirms the dry-run output. This is a standard safety step — never skip it unless the user explicitly asks to go straight to execution.
5. Execute the creation scripts with the confirmed values (remove `--dry-run`)
6. Report results

The agent MUST NEVER:
- Decide link types (enforced by `link_artifacts.py`)
- Split MRs per version (hard rule: `one_mr_per_rule_all_versions` — always one consolidated MR)
- Decide ticket handling (enforced by duplicate detection in `preflight_check.py`)
- Infer rules, components, dates, or any other values (resolved by `preflight_check.py`)
- Create links without the script's idempotency checks
- Override any value from `hard_rules` in the preflight output

### Existing Exception Gate (Hard Prerequisite)

**ALWAYS run the existing exception gate FIRST**, before Jira tickets, questionnaires, or the full preflight check. Run it as soon as the rule and component list are known:

```bash
python3 skills/conforma-exception/scripts/preflight_check.py --check-existing-exception \
  --rule <rule> \
  --components <comma-separated-components> \
  [--environment prod]
```

The script checks the GitLab repo deterministically and outputs JSON with a `status` field. Present the script's output to the user. If `status` is not `passed`, do NOT proceed with the create-exception workflow.

Coverage detection is fully deterministic — the script handles all matching logic:
- **componentNames-scoped exceptions**: exact overlap check between requested and listed componentNames
- **imageUrl-scoped exceptions**: base name matching (e.g. `quay.io/rhoai/odh-dashboard-rhel9` covers `odh-dashboard-v3-3`, `odh-dashboard-v3-4`, etc. by stripping the `-rhel9`/`-ubi9` suffix and the `-vX-Y` version suffix, then comparing base names)
- **Unscoped exceptions** (no componentNames, no imageUrl): covers all components for that rule

The agent MUST NOT perform its own imageUrl-to-componentName matching. The script output is authoritative.

The gate also searches for **open merge requests** in the `konflux-release-data` GitLab repo that mention the violation. If open MRs are found, they are included in the `open_merge_requests` field. The agent MUST present them to the user with a note like: "There is already an open MR for this violation: `[MR title](url)` by @author (created date). Check it before creating a new one." This is informational — it does not block the gate — but it prevents duplicate MRs.

### Mandatory Pre-Flight Script

**After the existing exception gate passes**, run `preflight_check.py` to resolve all remaining parameters:

```bash
python3 skills/conforma-exception/scripts/preflight_check.py \
  --rhoaieng-url <url> \
  --versions rhoai-2.25,rhoai-3.3 \
  --image-bases odh-vllm-cpu,odh-vllm-gaudi
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

## Workflow Routing

Workflow routing (which Jira projects, how many tickets, assignees, MR target) is defined per-category in `exception_templates.yaml`. The orchestrator reads the `workflow` steps from the matched category and executes them in order.

Each workflow step has a `track` field indicating which logical track it belongs to:

- **`track: remediation_plan`** — The resolution plan ticket. Created FIRST to establish the fix commitment (with a future target date). Its URL (`{remediation_plan_url}`) is referenced in the justification text of all downstream artifacts.
- **`track: exception_approval`** — The exception approval chain. These steps are sequential and block the release until the exception is granted: approval ticket -> ProdSec review -> policy MR.

The `--rule` flag determines which template category matches, and thus which workflow runs. There are no separate path flags -- the rule is the single input that drives routing.

Common workflow patterns:

| Pattern | Steps | Example rules |
|---------|-------|---------------|
| Standard | Resolution plan (team) -> Senior Management approval (RHOAIENG Jira) -> **[APPROVAL GATE]** -> PSX Jira -> GitLab Merge Request | `rpm_signature.allowed:*`, `hermetic_task.hermetic`, SBOM rules |
| FIPS | Resolution plan (team) -> Senior Management approval (RHOAIENG Jira) -> **[APPROVAL GATE]** -> OCPEXCEPT Jira -> GitLab Merge Request | `fips-check`, `fips_check` |
| Self-service | Senior Management approval (RHOAIENG Jira) -> **[APPROVAL GATE]** -> GitLab Merge Request (to `exceptions/` dir) | `schedule.weekday_restriction`, `test.no_failed_tests:fbc-target-index-pruning-check` |

**[APPROVAL GATE]** = Orchestrator checks that the RHOAIENG approval ticket is Closed/Resolved/Approved before proceeding. Halts if not approved. See "RHOAIENG Approval Gate" section above.

To see the full list of supported rules and their workflows, inspect `exception_templates.yaml` directly.

### Handling Non-Templated Violations ("other" category)

Not every Conforma violation has a pre-built template. The `other` catch-all category in `exception_templates.yaml` handles **any** rule from the [Conforma redhat collection](https://conforma.dev/docs/policy/release_policy.html) that doesn't match a specific category.

When `match_template_category()` returns `"other"`, the agent MUST follow an interactive flow to gather all exception details from the user, since there is no pre-written template text. The full catalog of known rules is in `references/conforma-release-policy-rules.yaml`.

**The agent MUST follow these steps for "other" category exceptions:**

1. **Validate the rule code**: Look up the `--rule` value in `references/conforma-release-policy-rules.yaml`. If found, show the user the official rule name and Conforma docs URL. If NOT found, warn the user that this may not be a valid Conforma rule and ask them to confirm.

2. **Check the Jira ticket** (if `--rhoaieng-url` provided): Read the ticket summary, description, and comments to extract context about what the violation is, which components are affected, and what the remediation plan looks like. Present findings to the user for confirmation.

3. **Determine the correct workflow**: The default workflow for `other` is the standard 4-step PSX Jira path (resolution plan -> Senior Management approval -> PSX Jira -> GitLab Merge Request). However, the agent MUST ask the user:
   - "Is this a FIPS-related violation?" — if yes, switch `psx_exception_jira` project to OCPEXCEPT Jira (task type)
   - "Is this a non-security, self-service exception?" — if yes, skip PSX/OCPEXCEPT Jira and use the 2-step self-service path (Senior Management approval -> self-service GitLab Merge Request)

   Present these as structured choices. The user's answer overrides the default workflow.

4. **Gather all exception text fields interactively**: Since there is no template text, the agent MUST collect each field from the user. Present them one batch at a time with examples drawn from similar templated categories. For each field, show:
   - The field name and purpose
   - An example from a related templated category (e.g., if the rule is `olm.unpinned_references`, show the OLM unmapped references template as a reference)
   - A text input for the user to provide their wording

   Required fields (all MUST be provided by the user or extracted from the Jira ticket):
   - **Scope**: What components are affected, how many versions, what the violation is
   - **Risk**: Why the violation is acceptable in this case
   - **Remediation**: What the plan is to fix the underlying issue
   - **Impact**: What happens if the exception is not granted (this can default to the standard Conforma blocking message)
   - **Summary context**: Brief description for ticket titles (e.g., "OLM unpinned images exception")

5. **Confirm all values**: Present the complete set of resolved values (rule, components, versions, dates, workflow, exception text) for user confirmation before proceeding. The user may edit any field.

6. **Execute**: Pass all user-provided text via `--exception-scope`, `--exception-risk`, `--exception-remediation`, `--exception-impact`, and `--summary-context` flags to override the template defaults (which are `USER_PROVIDED` placeholders).

**Important**: The `other` category still uses the same orchestration scripts (`create_exception.py`, `create_jira_ticket.py`, `create_gitlab_mr.py`). The only difference is that exception text comes from user input rather than from template resolution. All other validation, deduplication, linking, and verification logic applies identically.

## Exception Creation Workflow Diagram

The following mermaid diagram shows the end-to-end flow for creating a new Conforma exception. **The agent MUST render this diagram to the user** in the following situations:

1. **Generic questions** — When the user asks what a Conforma exception is, how exceptions work, or asks about the exception process (e.g. "what is a conforma exception", "explain conforma exceptions", "how does the exception workflow work", "what's the process for creating an exception")
2. **Before prompting for details** — When the user initiates exception creation (e.g. "create conforma exception", "I need a conforma exception", "create exception for componentA") the agent MUST show this diagram BEFORE presenting the entry-point choices or the questionnaire, so the user understands the full flow they are about to go through

```mermaid
flowchart TD
    Step1["① RHOAIENG component bugfix Jira\n(remediation plan — created first)"]
    Step2["② RHOAIENG Senior Management\napproval Jira"]
    Step3{{"③ APPROVAL GATE\nSenior Management\nmust approve"}}
    Halt([Halted — get approval,\nthen re-run])
    Step4["④ PSX or OCPEXCEPT Jira\n(skip for self-service rules)"]
    Step5["⑤ GitLab Merge Request\n(exception YAML in konflux-release-data)"]
    Step6["⑥ Link all artifacts\n(comments, labels, Jira links)"]

    Step1 --> Step2
    Step2 --> Step3
    Step3 -->|Not approved| Halt
    Step3 -->|Approved| Step4
    Step4 --> Step5
    Step5 --> Step6

    subgraph Review [External review — human]
        direction TB
        Step7["⑦ ProdSec reviews PSX Jira\n→ Ready for Verification"]
        Step8["⑧ Release Engineering\nmerges GitLab MR"]
    end

    Step6 --> Step7
    Step6 --> Step8
    Step7 --> Granted
    Step8 --> Granted

    Granted([Exception granted])
```

The exception is only granted when **both** conditions are met: the PSX Jira ticket reaches **Ready for Verification** and the GitLab Merge Request is **merged**. Steps ①–⑥ are automated by this skill; steps ⑦–⑧ require human review by ProdSec and Release Engineering respectively.

**Self-service variant** (for rules like `schedule.weekday_restriction`, `test.no_failed_tests:fbc-target-index-pruning-check`): Steps ① and ④ are skipped, and step ⑦ does not apply — the workflow is: Senior Management approval → Approval Gate → GitLab MR (to `exceptions/` directory) → MR merged → Exception granted.

## Explaining Conforma Exceptions

When the user asks what a Conforma exception is (e.g. "what is a conforma exception", "explain conforma exceptions"), always include the compact YAML example from the introduction above. This makes the concept concrete. Also link to the [Conforma redhat collection](https://conforma.dev/docs/policy/release_policy.html) and [VolatileCriteria schema](https://conforma.dev/docs/policy/packages/release_volatile_config.html).

**Additionally**, always render the workflow diagram from the "Exception Creation Workflow Diagram" section above when explaining Conforma exceptions, so the user can see the full process visually.

## Run Directory Convention

Every session that creates intermediate files (downloaded CSVs, parsed violations, coverage checks, assessed exceptions, reports, action plans) MUST use a timestamped run directory inside `.work/`. This prevents runs from clobbering each other's files and keeps the directory navigable.

At the start of each session, create the run directory:

```bash
RUN_DIR=".work/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
```

All intermediate files go inside `$RUN_DIR`. Example layout for a single run:

```
.work/
├── konflux-release-data/          # shared repo clone (persists across runs)
├── 20260603-112300/               # this run
│   ├── conforma-reports/
│   │   └── rhoai-3.4.csv
│   ├── conforma-violations.yaml
│   ├── coverage-check.json
│   ├── assessed-exceptions.yaml
│   ├── exceptions-report.md
│   └── action-plan.json
```

**Shared repo clone**: The `konflux-release-data` GitLab repo is large and slow to clone (~40s). To avoid re-cloning on every script invocation, maintain a shared clone at `.work/konflux-release-data` and pass `--clone-dir .work/konflux-release-data` to all commands that accept it (`preflight_check.py`, `manage_exceptions.py`, `create_gitlab_mr.py`). If the clone already exists, pull the latest before use:

```bash
if [ -d .work/konflux-release-data/.git ]; then
  git -C .work/konflux-release-data fetch origin main && git -C .work/konflux-release-data reset --hard origin/main
else
  GITLAB_TOKEN=$(glab config get token --host "$GITLAB_HOST")
  git clone --depth 1 "https://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}/releng/konflux-release-data.git" .work/konflux-release-data
fi
```

Script-internal temp directories (`conforma-exception-mr-*`, `conforma-exception-manage-*`, etc.) are created by Python scripts via `tempfile.mkdtemp()` and land directly in `.work/`. These are transient and self-cleaning — do not move them into run directories.

## Starting Without Details

When the user asks to create a Conforma exception but does not provide specific details (no rule, no version, no components, no Jira URL — e.g., "create conforma exception for componentA", "how do I create an exception", "I need a conforma exception"), the agent MUST:

1. **Show the workflow diagram first** — render the mermaid diagram from the "Exception Creation Workflow Diagram" section so the user understands the full flow before beginning
2. **Then present two entry points** using the AskQuestion tool:

   a. **Paste violation text**: The user pastes Conforma violation output (from a CI log, Conforma report, or error message) directly into the prompt. The agent extracts the rule code, component name(s), RHOAI version, and any other available details from the pasted text, then runs the Existing Exception Gate before proceeding with the normal preflight/questionnaire flow.

   b. **Provide a Conforma report URL**: The user provides a URL to a Conforma violation report (e.g., a `conforma-reporter` GitHub URL, a raw CSV link, or a CI artifact URL). The agent:
      i. Fetches the report content via raw download from `raw.githubusercontent.com` (using `curl` with the GitHub token from `gh auth token`)
      ii. Parses violations from the report using the `conforma-analyze` skill's `parse_violations.py`. The parser expects a directory of CSVs named `<release>.csv` (the release name is derived from the filename stem). Set up the directory inside `$RUN_DIR` and run:
      ```bash
      mkdir -p "$RUN_DIR/conforma-reports"
      cp <downloaded-csv> "$RUN_DIR/conforma-reports/rhoai-3.4.csv"
      python3 skills/conforma-analyze/scripts/parse_violations.py \
        --reports-dir "$RUN_DIR/conforma-reports" \
        --output "$RUN_DIR/conforma-violations.yaml"
      ```
      If the user provides URLs for multiple releases, save each as `<release>.csv` in the same directory — the parser processes all `*.csv` files in one pass.
      iii. Runs the batch coverage check and presents results. Read and follow [`references/coverage-check.md`](references/coverage-check.md) for the full workflow (clone setup, command, output handling). Pass the violations YAML from step (ii) as input.
      iv. Lets the user select which violation(s) to create exceptions for (using AskQuestion with multi-select)
      v. Proceeds with the normal preflight/questionnaire flow for each selected violation, pre-filling the violation code and component details from the parsed report. The per-violation Existing Exception Gate has already been checked in step (iii) — no need to re-run it.

The agent MUST NOT proceed with the creation workflow until it has a concrete rule and component list — either from user-provided details, pasted violation text, or a parsed report selection. The Existing Exception Gate must pass before proceeding — see "Existing Exception Gate (Hard Prerequisite)" above.

**Re-confirmation after interruptions**: If the user asks an unrelated or clarifying question between the AskQuestion violation-selection prompt and a "continue" / "proceed" instruction, the agent MUST re-present the selection for explicit confirmation before acting on it. A prior AskQuestion response that was followed by unrelated conversation MUST NOT be treated as a deliberate choice — the user may have dismissed the prompt without carefully selecting. Always re-confirm.

### Open MR Coverage Analysis

The `--check-existing-exception` and `--check-violations-coverage` script outputs include an `open_merge_requests` list for each violation. Each entry contains per-MR coverage data computed by `preflight_check.py` (the agent MUST NOT call `glab api` directly — all GitLab API interaction is encapsulated in the scripts):

- `mr_components`: components the MR already covers (extracted from the MR diff or description)
- `covered`: overlap between MR components and the requested components
- `missing`: requested components not yet in the MR
- `suggestion`: one of `"extend_mr"`, `"fully_covered"`, or `"no_overlap"`

Present these to the user as follows:

- **`extend_mr`**: "Open MR !{iid} already covers {N} of {M} components for this violation. Missing: {list}. Consider extending the existing MR rather than creating a new one."
- **`fully_covered`**: "Open MR !{iid} already covers all {M} requested components for this violation. Creating a new MR would be a duplicate."
- **`no_overlap`**: The MR is for the same violation but different components (likely a different RHOAI version). Proceed normally without referencing this MR.

When multiple open MRs exist for the same violation, present each independently. In the AskQuestion violation selection, annotate violations that have open MRs with partial coverage as `[open MR covers N/M]` next to the coverage indicator.

### Open Jira Ticket Coverage

The `--check-violations-coverage` script also searches for open Jira tickets (RHOAIENG, PSX, OCPEXCEPT) with the `conforma-violation` label that match each violation rule. This is a single batch query, not per-violation. Each violation entry includes:

- `open_jira_tickets`: list of matching tickets with `key`, `status`, `summary`, `url`
- `open_jira_label`: pre-formatted markdown links for display (empty if none)

When `open_jira_label` is non-empty, present it alongside the MR coverage in the violations table. This is informational — it does not block exception creation — but it prevents creating duplicate Jira tickets. If an open RHOAIENG or PSX ticket already exists for a violation, the agent should suggest reusing it (via `--rhoaieng-url` or `--psx-url`) rather than creating a new one.

## Listing Exception Types, Usage, and Questionnaire

For detailed instructions on listing exception types, CLI usage examples, required/optional flags, orchestration flow, and the interactive questionnaire, read `references/interactive-workflow.md`.

## Component Version Reconciliation

Component names are validated against `--rhoai-version`:
- `rhoai-3.3` + `odh-dashboard-v3-3` = valid
- `rhoai-3.5-ea.1` + `odh-dashboard-v3-5-ea-1` = valid
- `rhoai-3.3` + `odh-dashboard-v3-5` = ERROR (version mismatch)

**IMPORTANT: componentNames vs container image names** -- these are NOT the same thing:

| Type | Pattern | Example | Used in Merge Request? |
|------|---------|---------|-------------|
| Konflux component name | `{base}-v{major}-{minor}` | `odh-workbench-jupyter-pytorch-rocm-py312-v2-25` | YES |
| Container image name (not for MRs) | `{base}-rhel9` (no version) | `odh-workbench-jupyter-pytorch-rocm-py312-rhel9` | NO |

All Konflux component names include a version suffix (e.g. `-v2-25`, `-v3-3`, `-v3-5-ea-1`). Names ending in `-rhel9` or `-ubi9` without a version suffix are container image names produced by those components -- they must NOT be used in `componentNames` fields in exception GitLab Merge Requests. The validation script rejects container image names and suggests the correct Konflux component name format.

To find correct component names, check the ReleasePlanAdmission files:
`config/${KRD_CLUSTER_DOMAIN}/product/ReleasePlanAdmission/rhoai/rhoai-onprem-vX-Y-components-prod.yaml`

## Dry-Run Mode

`--dry-run` validates all inputs and outputs what would be created (YAML block, target file, Jira details) as structured JSON without submitting anything. Auth checks still run.

## Verification Contract

Every ticket creation or reconciliation ends with a **verification phase** that reads the ticket back via Jira REST API and checks:

| Field | Check |
|-------|-------|
| Labels | Contains both `conforma-exception-ai-skill` and `conforma-violation` |
| Issue links | Includes all expected targets (RHOAIENG, tracking ticket) |
| Description | ADF with >= 15 panel/paragraph nodes (PSX/OCPEXCEPT) |
| Authorized Party | `customfield_10938` is set (PSX/OCPEXCEPT) |

If any check fails, the script **retries the failed operation** (up to 2 attempts) and re-verifies. If it still fails, the script exits non-zero with structured JSON listing exactly what expectations are unmet.

All operations return structured dicts reporting what was attempted, what the actual state is, and what failed -- never silent True/False. This makes failures visible to both the agent and the user.

## Reconcile Mode

The `--reconcile TICKET_KEY` flag on `create_jira_ticket.py` enables idempotent re-runs:

```bash
python3 skills/conforma-exception/scripts/create_jira_ticket.py --project PSX \
  --reconcile PSX-1098 \
  --rule rpm_signature.allowed:9386b48a1a693c5c \
  --components odh-workbench-jupyter-pytorch-rocm-py312-v2-25 \
  --rhoai-version rhoai-2.25 \
  --effective-until 2027-05-03T00:00:00Z \
  --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38426 \
  --template rpm_signature_thirdparty \
  --vendor-tag AMD \
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

Consolidated MR commits list all versions in a single message:

```text
Add conforma exception: <rule> (<version-1>, <version-2>, ...)

Exception details:
  Rule: <rule>
  Policy file: <path>

  <version-1>:
    Components: <component-list>
    Effective until: <date>

  <version-2>:
    Components: <component-list>
    Effective until: <date>

RHOAIENG: <url>
Reference: <psx-url>
Spreadsheet: <url>

---
Generated by: conforma-exception-ai-skill
Source: https://github.com/opendatahub-io/aiops-infra
User: <user>@<hostname>
```

## Error Handling

Each script validates inputs and exits non-zero on failure. The orchestrator stops at the first failure, preserving partial results in the output JSON. Common errors:

- Invalid RHOAI version format
- Component name / version mismatch
- `--effective-until-date` not a future date
- `acli` or `glab` not authenticated
- GitLab Merge Request creation failure (permissions, branch conflict)
- Jira ticket creation failure (permissions, invalid project)
- Verification failure (labels, links, or fields not confirmed after retries)

## Listing, Searching, and Watchers

For instructions on listing current exceptions (`list_exceptions.py`), searching open MRs (`search_open_mrs.py`), and managing Jira watchers (`add_jira_watchers.py`), read `references/tool-reference.md`.

## Managing Exceptions

For the full workflow on discovering, assessing, and handling expired/active exceptions (extend, modernize, narrow, remove), read `references/managing-exceptions-workflow.md`.

## Reference Documentation

See `references/exception-process.md` for the full process documentation including:
- Jira project routing rules
- Senior manager approval requirements
- VolatileCriteria schema
- Upstream reference links (Konflux docs, PSX Confluence, conforma.dev)

See `references/conforma-release-policy-rules.yaml` for the complete catalog of enforced rules in the Conforma `redhat` collection, sourced from [conforma.dev/docs/policy/release_policy.html](https://conforma.dev/docs/policy/release_policy.html). Each entry includes the rule code, human-readable name, and documentation URL. Use this catalog to validate `--rule` values and provide context when handling non-templated ("other" category) exceptions.

## Pipeline Mode (Handover)

For backward compatibility with the `conforma-troubleshooter` agent, the orchestrator also accepts `--output` to write structured JSON results compatible with the handover document format.
