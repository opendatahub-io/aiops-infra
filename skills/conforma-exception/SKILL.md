---
name: conforma-exception
description: Manage RHOAI Conforma exceptions end-to-end — create, extend, check, and reconcile policy exceptions. Handles Jira tickets (RHOAIENG Jira, PSX Jira, OCPEXCEPT Jira), GitLab Merge Requests in konflux-release-data, deduplication of existing exceptions, and cross-linking of all artifacts.
allowed-tools: Bash(python3:*,acli:*,glab:*,git:*,docker:*,podman:*)
user-invocable: true
---

# Conforma Exception

End-to-end automation for RHOAI Conforma exception management: check existing exceptions, create new ones, extend effectiveUntil dates, validate inputs, create required Jira tickets, generate exception YAML, create GitLab Merge Requests, and cross-link all artifacts.

An exception is a YAML entry added to a release policy file in the [konflux-release-data](https://gitlab.cee.redhat.com/releng/konflux-release-data) GitLab repository, using the [VolatileCriteria](https://conforma.dev/docs/policy/packages/release_volatile_config.html) schema. It tells the [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy engine to waive a specific rule for listed components until a given date. Example:

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

The skill requires `acli` (Atlassian CLI) and `glab` (GitLab CLI). **`acli` is auto-installed** to `~/.local/bin/` on first use if not already on PATH — the download-from-CDN logic is built into `cli_runner.py` and triggers transparently whenever any script calls `run_acli()`. `glab` must be installed manually.

**Always run preflight first** before creating any tickets or MRs:

```bash
python3 scripts/verify_auth.py
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

## Remote Data Access Policy

When fetching data from remote repositories (GitLab, GitHub):

- **ALWAYS** use the remote API directly (`glab api`, `gh api`, raw HTTP download via `curl`)
- **NEVER** use `find` to locate local clones, `cd` into them, or `git checkout`/`git show` on a local working tree
- **NEVER** assume a local clone is up-to-date or on the correct branch

Local clones on a dev workstation may be on a feature branch, days out of date, or modified with uncommitted changes. Using the remote API guarantees you always read the canonical, production state of the repository at the exact ref you specify.

```bash
# GOOD — fetch a file from GitLab
glab api "projects/releng%2Fkonflux-release-data/repository/files/path%2Fto%2Ffile.yaml/raw?ref=main" \
  --hostname gitlab.cee.redhat.com

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
python3 scripts/preflight_check.py --check-existing-exception \
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

The gate also searches for **open merge requests** in the `konflux-release-data` GitLab repo that mention the violation. If open MRs are found, they are included in the `open_merge_requests` field. The agent MUST present them to the user with a note like: "There is already an open MR for this violation: [MR title](url) by @author (created date). You may want to check it before creating a new one." This is informational — it does not block the gate — but it prevents duplicate MRs.

### Mandatory Pre-Flight Script

**After the existing exception gate passes**, run `preflight_check.py` to resolve all remaining parameters:

```bash
python3 scripts/preflight_check.py \
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
  GITLAB_TOKEN=$(glab config get token --host gitlab.cee.redhat.com)
  git clone --depth 1 "https://oauth2:${GITLAB_TOKEN}@gitlab.cee.redhat.com/releng/konflux-release-data.git" .work/konflux-release-data
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
      python3 ../conforma-analyze/scripts/parse_violations.py \
        --reports-dir "$RUN_DIR/conforma-reports" \
        --output "$RUN_DIR/conforma-violations.yaml"
      ```
      If the user provides URLs for multiple releases, save each as `<release>.csv` in the same directory — the parser processes all `*.csv` files in one pass.
      iii. Runs the batch coverage check BEFORE presenting violations (pass `--clone-dir` to reuse the shared repo clone):
      ```bash
      python3 scripts/preflight_check.py \
        --check-violations-coverage "$RUN_DIR/conforma-violations.yaml" \
        --clone-dir .work/konflux-release-data \
        --environment prod
      ```
      This checks all violations against existing exceptions in the policy file in one pass.
      iv. Presents violations as a summary table by printing `result["markdown_table"]` verbatim. The script pre-renders a complete markdown table with columns: #, Rule, Components, Open MRs, Open Jira, Next Steps.

      **Do NOT include a Coverage column.** The `coverage_label` field exists in the JSON output for programmatic use but is misleading when shown to users — it can give the impression that a conforma exception is the default resolution. Instead, the `next_steps` column is the single source of guidance for the user.

      The `markdown_table` field is a complete, ready-to-display markdown string. The agent MUST print it as-is without modification. Do NOT reconstruct the table from individual fields — always use the pre-rendered version.
      v. Lets the user select which violation(s) to create exceptions for (using AskQuestion with multi-select)
      vi. Proceeds with the normal preflight/questionnaire flow for each selected violation, pre-filling the violation code and component details from the parsed report. The per-violation Existing Exception Gate has already been checked in step (iii) — no need to re-run it.

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

## Listing Exception Types

When the user asks about Conforma exception types (e.g. "what are the conforma exception types", "list exception types", "show me conforma violations"), always:

1. Run `python3 scripts/create_exception.py --list-exception-types` (from this skill directory). This returns JSON with:
   - `common`: the 7 most common RHOAI exception types (full details)
   - `common_count`, `non_common_count`, `total_catalog_rules`, `conforma_rules_url`: counts and links for the summary

2. Render the `common` array as a table with these columns:

| Column | Source field |
|--------|-------------|
| # | sequential number |
| Category ID | `id` |
| Display Name | `display_name` |
| Workflow | `workflow_summary` |
| Search: Jira | `links.jira` entries as `[label](url)`, comma-separated |
| Search: GitLab Merge Requests | `links.gitlab_mrs` entries as `[label](url)`, comma-separated |

3. After the table, use `non_common_count`, `total_catalog_rules`, and `conforma_rules_url` from the JSON to state:

   > The skill also supports **{non_common_count} more** templated exception types and can handle **any** of the **{total_catalog_rules}** rules in the [Conforma redhat collection]({conforma_rules_url}) (via the interactive "other" catch-all category).

   Then add a brief note suggesting the user can ask to see more details on the remaining templated types or the full list of all supported types if they're interested. Do NOT use the AskQuestion tool here -- just mention it conversationally in the response text.

4. If the user asks to see remaining types, run `python3 scripts/create_exception.py --list-exception-types --all` and render the `non_common` array plus the `catch_all` entry in the same table format.

5. If the user asks for the rule reference, read `references/conforma-release-policy-rules.yaml` and display the rules grouped by category heading (the `# ---` comment sections) as a compact table with columns: Rule Code, Name, Docs (link).

6. After any table, add a brief legend explaining:
   - The workflow track abbreviations (remediation_plan vs exception_approval)
   - The step names used (Resolution plan, Senior Management approval, RHOAIENG Jira, PSX Jira, OCPEXCEPT Jira, GitLab Merge Request, self-service)
   - That the `other` category is a catch-all for any Conforma rule not covered by a specific template, and requires interactive input for all exception text fields. Reference `references/conforma-release-policy-rules.yaml` for the full list of known rules.
   - Always include a link to the [Conforma redhat collection](https://conforma.dev/docs/policy/release_policy.html) for the full rule reference.

## Usage

### Standalone mode (user-provided details)

```bash
python3 scripts/create_exception.py \
  --rhoai-version rhoai-3.3 \
  --rule hermetic_task.hermetic \
  --components odh-mlflow-v3-3,odh-another-v3-3 \
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
  --effective-until-date 2026-10-03 \
  --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38414 \
  --psx-url https://redhat.atlassian.net/browse/PSX-1089
```

### Self-service (auto-detected from rule)

```bash
python3 scripts/create_exception.py \
  --rhoai-version rhoai-3.4 \
  --rule schedule.weekday_restriction \
  --components rhoai-fbc-fragment-v3-4 \
  --image-ref sha256:abc123...
```

## Required Information

| Detail | Flag | Notes |
|--------|------|-------|
| RHOAI version | `--rhoai-version` | e.g., `rhoai-3.3`, `rhoai-3.5-ea.1` |
| Policy rule | `--rule` | Full rule value (e.g., `hermetic_task.hermetic`). Determines workflow and justification from templates. |
| Component names | `--components` | Comma-separated Konflux component names |
| Expiry date | `--effective-until-date` | YYYY-MM-DD (used as-is; +7 day buffer only applies to end-of-support sourced dates) |

Exception text (scope, risk, remediation, impact) is derived from `exception_templates.yaml`. Scope and impact come from the matched category. Risk and remediation come from a justification template selected via `--justification <id>` (e.g., `--justification dev_preview`). If omitted, the first entry in the category's `applicable_justifications` list is used as default.

The `--vendor-tag` flag fills the `{vendor}` placeholder in templates. The `--exception-scope`, `--exception-risk`, `--exception-remediation`, `--exception-impact` flags override template-resolved values when custom wording is needed.

The resolved exception text flows into all workflow artifacts: RHOAIENG Jira resolution plan ticket, RHOAIENG Jira approval ticket, PSX/OCPEXCEPT Jira ticket, and GitLab Merge Request commit message. The `{remediation_plan_url}` placeholder in justification text is auto-filled with the resolution plan ticket URL (created first in the workflow).

### Optional flags

| Flag | Default | Description |
|------|---------|-------------|
| `--environment` | `prod` | `prod` or `stage` |
| `--rhoaieng-url` | *(creates new)* | Existing RHOAIENG Jira ticket URL |
| `--psx-url` | *(creates new)* | Existing PSX/OCPEXCEPT Jira ticket URL |
| `--related-psx` | none | Pre-existing PSX Jira ticket to link as "Related" only (a new PSX Jira is still created) |
| `--link-to` | none | Tracking ticket key to link all tickets to (e.g. `RHAISTRAT-576`) |
| `--summary-context` | none | Brief description for ticket titles (auto-filled from template if matched) |
| `--vendor-tag` | none | Vendor/distinguisher tag prepended to titles (e.g. `AMD`, `Intel`, `FIPS`). Also fills `{vendor}` in templates. |
| `--spreadsheet-url` | none | Tracking spreadsheet URL (added as YAML comment in MR and commit message) |
| `--authorized-party` | none | Senior manager accepting risk (Authorized Party in PSX workflow) |
| `--watchers` | none | Comma-separated display names to add as watchers (any project; PSX/OCPEXCEPT mandatory watchers are prepended automatically) |
| `--image-ref` | none | SHA digest (only for `schedule.weekday_restriction`) |
| `--reconcile` | none | Existing ticket key to reconcile (idempotent re-run) |
| `--skip-approval-gate` | false | Override the RHOAIENG approval gate -- proceed with PSX/MR creation even if approval Jira is not approved. **NOT RECOMMENDED.** Agent MUST ask for explicit user confirmation before using. |
| `--dry-run` | false | Preview without creating anything |
| `--output` | stdout | Write result JSON to file |

## Orchestration Flow

1. **Validate** (`validate_inputs.py`): version parsing, component-version reconciliation (rejects container image names like `-rhel9`), date calculation (user-provided dates used as-is; +7 day buffer only for EOS-sourced dates), workflow determination from `exception_templates.yaml`
2. **Auth check** (`verify_auth.py`): auto-install `acli` if needed, verify `acli` and `glab` are available and authenticated -- **stop here if any check fails**
3. **Execute workflow steps** (from `exception_templates.yaml`): the orchestrator iterates through the matched category's `workflow` list and executes each step:
   - `rhoaieng_resolution_plan_jira` *(track: remediation_plan)*: Creates a Bug in RHOAIENG Jira assigned to the component team documenting the fix commitment. Created FIRST so its URL can be referenced in downstream justification text.
   - `rhoaieng_approval_jira` *(track: exception_approval)*: Creates a Blocker Bug in RHOAIENG Jira for Senior Management approval (skipped if `--rhoaieng-url` provided). Assigned to `default_assignee` from template if set. References the resolution plan URL in its description.
   - **APPROVAL GATE**: After the RHOAIENG approval step, the orchestrator checks whether the approval ticket is Closed/Resolved with an approved resolution or has an approval comment. **If not approved, the orchestrator halts here.** The user must get Senior Management approval and re-run. Use `--skip-approval-gate` to override (requires explicit user confirmation).
   - `psx_exception_jira` *(track: exception_approval)*: Creates a PSX Jira (PSRD Exception) or OCPEXCEPT Jira (Task) ticket (skipped if `--psx-url` provided). Project determined by template. References the resolution plan URL in justification. **Blocked until RHOAIENG approval gate passes.**
   - `exception_merge_request` *(track: exception_approval)*: Creates the exception GitLab Merge Request. If `self_service: true` in template, targets `exceptions/` dir. **Blocked until RHOAIENG approval gate passes.**
4. **Link artifacts** (`link_artifacts.py`): comment GitLab Merge Request URL on Jira tickets, add provenance label, create Jira links between all tickets (including `--link-to` tracking ticket)

All created tickets receive the `conforma-exception-ai-skill` and `conforma-violation` Jira labels and a provenance footer in the description.

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

2. **RHOAIENG Jira ticket type check**: If the ticket is not a Blocker Bug, present options:
   - "Create a proper Blocker Bug and link to this Epic/Story"
   - "Use this ticket as-is (non-standard)"

3. **RHOAI versions**: Present all versions found in the ticket as multi-select. Example:
   - [ ] rhoai-2.25
   - [ ] rhoai-3.3
   - [ ] rhoai-3.4
   - [ ] rhoai-3.5-ea.1

   **Note**: All selected versions are handled in a **single consolidated MR** (hard rule: `one_mr_per_rule_all_versions`). The agent uses `--version-specs-json` to pass all versions to `create_gitlab_mr.py` in one call.

**Batch 2 — Components and identifiers:**

5. **Component name lookup and confirmation**: Look up Konflux componentNames from ReleasePlanAdmission files, then present the resolved names for confirmation. Example:
   - "Confirm these are the correct Konflux component names for rhoai-3.3: `odh-vllm-cpu-v3-3`, `odh-vllm-gaudi-v3-3`"
   - "Yes, correct"
   - "No, let me specify different names"

   Never use a container image name (e.g. `-rhel9`) in a Merge Request without the user confirming the translation to a Konflux component name.

6. **Vendor tag**: Present common options plus free text:
   - "Fedora/EPEL"
   - "AMD"
   - "Intel"
   - "Mellanox"
   - "FIPS"
   - "Other (let me specify)"
   - "None / skip"

7. **Tracking ticket**: Present options:
   - "Yes, link to: [ticket key from Jira context if found]"
   - "Yes, let me provide a ticket key"
   - "No tracking ticket"

8. **Related PSX (existing)**: Auto-discover by searching Jira: `project = PSX AND text ~ '<signing_key_or_rule>'`. If found, present the result(s) for confirmation:
   - "Found PSX-XXXX: <title> [status]. Link as Related?"
   - "Yes, link as Related"
   - "No, skip"

   If no results found, silently skip (do not ask the user). This removes a manual lookup step.

9. **Exception template confirmation**: The script auto-detects the template category from the rule (via `match_template_category()`). Present the detected category for the user to confirm:
    - "Detected category: Third-party RPM signing key"
    - "Template will use `--vendor-tag` value to fill the `{vendor}` placeholder"

    The template fills all exception text fields (scope, risk, remediation, impact, summary context) deterministically from `exception_templates.yaml`. The `--exception-scope`, `--exception-risk`, etc. flags override template values if the user provides custom wording. The `--justification` flag selects a justification template (e.g., `dev_preview`, `code_frozen`) for the risk/remediation text.

    **If the detected category is `other` (catch-all)**: The agent must inform the user that no specific template exists for this rule and switch to the interactive flow described in "Handling Non-Templated Violations" above. All exception text fields (scope, risk, remediation, impact, summary context) must be gathered from the user or extracted from the Jira ticket. The agent should:
    - Look up the rule in `references/conforma-release-policy-rules.yaml` and show the official name and docs URL
    - Search existing Jira tickets (`labels = "conforma-violation" AND summary ~ "<rule>"`) for precedent
    - Search existing GitLab Merge Requests for the same rule to show the user what similar exceptions look like
    - Present examples from the closest related templated category as reference
    - Ask the user to provide or confirm each text field
    - Ask the user to confirm the workflow (PSX vs OCPEXCEPT vs self-service)

**Batch 3 — Approval and PSX details:**

10. **PSX Jira ticket visibility / watchers (MANDATORY)**: PSX tickets are restricted — **watchers are a hard requirement, not optional**. The script always adds the mandatory watchers (Jay Koehler, Lindani Phiri) even if `--watchers` is omitted, but the full team should be included for proper visibility.

    The agent MUST follow this flow:
    1. **Automatically run team discovery** by calling `add_jira_watchers.discover_team()` (or `python3 scripts/add_jira_watchers.py --tickets <placeholder> --auto-discover --dry-run`) to find the caller's team from Jira groups ≤ 100 members.
    2. **Present the full watcher list** (mandatory watchers + discovered team) to the user for confirmation:
       - "The following people will be added as Additional watchers on the PSX ticket: [full name list]. Confirm?"
       - "Yes, add all"
       - "Let me remove some from the list"
       - "Let me add more names"
    3. **Pass confirmed names** via `--watchers 'Name1,Name2,Name3'` to `create_jira_ticket.py`.

    The mandatory watchers are always added by the script regardless — the confirmation step is for the team members. The watcher addition is idempotent (skips users already present).

11. **Authorized Party**: Free text prompt:
    - "Who is the senior manager accepting risk? (e.g., Lindani Phiri, Jay Koehler)"

12. **Effective-until date**: Resolved by `preflight_check.py` from its `DEFAULT_EOS_DATES` table (with +7 day buffer pre-calculated for EOS-sourced dates). User-provided or Jira-sourced dates are used as-is without any buffer. The script outputs per-version dates in `effective_until` and flags any versions without defaults in `user_confirmation_required`. Present the script's output for user confirmation.

13. **Template review** (confirm the resolved text): After template resolution, present the filled-in scope/risk/remediation/impact text for user confirmation:
    - "Here is the pre-filled PSX text from the template (with `{vendor}` replaced by your `--vendor-tag` value). Confirm or edit:"
    - Show each field with its resolved value
    - "Confirm all"
    - "Edit one or more fields"

    The resolved text is deterministic (from `exception_templates.yaml`) and NOT generated by the LLM. The user may override individual fields via `--exception-scope`, `--exception-risk`, etc. if the template doesn't perfectly match their case.

**After all batches**: Present a final summary of all confirmed values and ask for a single "Proceed" / "Edit something" confirmation before executing.

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
`config/stone-prod-p02.hjvn.p1/product/ReleasePlanAdmission/rhoai/rhoai-onprem-vX-Y-components-prod.yaml`

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
python3 scripts/create_jira_ticket.py --project PSX \
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

## Listing Current Exceptions

When the user asks to see current Conforma exceptions (e.g. "show me current exceptions", "list exceptions", "what exceptions exist"), use the deterministic `list_exceptions.py` script. **Do NOT manually parse policy files or format output yourself** — the script produces a complete, ready-to-display Markdown report.

1. **Ensure the clone is fresh** (or let the script clone a temp copy):

```bash
if [ -d .work/konflux-release-data/.git ]; then
  git -C .work/konflux-release-data fetch origin main && git -C .work/konflux-release-data reset --hard origin/main
else
  GITLAB_TOKEN=$(glab config get token --host gitlab.cee.redhat.com)
  git clone --depth 1 "https://oauth2:${GITLAB_TOKEN}@gitlab.cee.redhat.com/releng/konflux-release-data.git" .work/konflux-release-data
fi
```

2. **Run the script** (from the skill directory):

```bash
python3 scripts/list_exceptions.py --clone-dir .work/konflux-release-data
```

3. **Print the output verbatim** — do NOT modify, reformat, or summarize the Markdown. The script produces a deterministic report with consistent table columns across all sections (Rule, Component / Image, RHOAI Version, Effective Until, Reference). RHOAI versions are derived from the actual data (componentName version suffixes like `-v3-4` → `3.4`, or `all` for imageUrl-scoped / unscoped exceptions) — never from YAML comments. All Jira ticket IDs and policy file names are rendered as clickable Markdown links.

**Only analyze prod by default.** If the user specifically asks for stage exceptions, add `--environment stage`. Never show both environments unless the user explicitly asks.

The `--soon-days` flag controls the "expiring soon" threshold (default: 14 days). Example: `--soon-days 30` includes exceptions expiring within 30 days in the "expiring soon" section rather than in per-date sections.

The report groups exceptions into sections by expiry status:
- **Expired** — `effectiveUntil` is in the past (need cleanup)
- **Expiring within N days** — approaching deadline
- **Expiring YYYY-MM-DD** — one section per remaining date, sorted chronologically

## Adding Jira Watchers

When the user asks to add watchers to Jira tickets (e.g. "add Akshay Ghodake as watcher to PSX-1040", "add watchers to these tickets"), use the deterministic `add_jira_watchers.py` script. **Do NOT use the Jira REST API directly or write inline watcher logic** — the script handles all project-specific differences.

The script auto-selects the correct mechanism per project:

| Project | Mechanism | Notes |
|---------|-----------|-------|
| PSX, OCPEXCEPT | `customfield_10705` ("Additional watchers" custom field) | Standard watcher API fails because users lack PSX view permissions. Editing the custom field requires the caller to be the reporter or assignee. |
| RHOAIENG, others | Standard Jira watchers API (`POST /issue/{key}/watchers`) | Works for any user with project access. |

### Automatic team discovery

The `--auto-discover` flag discovers the caller's Jira group members and adds them as watchers automatically. The script:

1. Calls GET /myself to identify the caller
2. Fetches the caller's Jira groups
3. **Skips groups with > 100 members** (org-wide groups like `jira-users`, `employee`, etc.)
4. Fetches members only from small team-sized groups (≤ 100 members)
5. Adds all discovered team members (excluding the caller) as watchers

When creating PSX/OCPEXCEPT tickets, the agent MUST run `discover_team()` during the questionnaire, present the discovered team to the user for confirmation, then pass the confirmed names via `--watchers`. The mandatory watchers (Jay Koehler, Lindani Phiri) are always included. See the questionnaire "Batch 3, item 10" for the exact agent flow.

### Usage

Add explicit watchers:

```bash
python3 scripts/add_jira_watchers.py \
  --tickets PSX-1038,PSX-1039,PSX-1040 \
  --watchers 'Akshay Ghodake,Jane Doe' \
  --dry-run
```

Auto-discover team and add them:

```bash
python3 scripts/add_jira_watchers.py \
  --tickets PSX-1040 \
  --auto-discover \
  --dry-run
```

Combine both — explicit names plus auto-discovered team:

```bash
python3 scripts/add_jira_watchers.py \
  --tickets PSX-1040 \
  --watchers 'Akshay Ghodake' \
  --auto-discover
```

Mixed projects in a single call are supported — the script routes each ticket to the correct mechanism:

```bash
python3 scripts/add_jira_watchers.py \
  --tickets PSX-1040,RHOAIENG-38414 \
  --watchers 'Akshay Ghodake'
```

### Flags

| Flag | Required | Description |
|------|----------|-------------|
| `--tickets` | yes | Comma-separated ticket keys (e.g. `PSX-1038,RHOAIENG-38414`) |
| `--watchers` | no | Comma-separated Jira display names (must match exactly). Required if `--auto-discover` is not set. |
| `--auto-discover` | no | Discover caller's team from Jira groups and add as watchers. Can combine with `--watchers`. |
| `--dry-run` | no | Preview what would change without writing |

### Output

Structured JSON with per-ticket results. Each ticket reports:
- `method`: `custom_field` or `standard_api`
- `status`: `updated`, `no_change`, `dry_run`, or `error`
- `added` / `already_present`: which names were added vs already there
- `errors`: detailed error messages (e.g. permission issues with reporter/assignee context)

When `--auto-discover` is used, the output includes a `team_discovery` section showing which groups were checked, which were included vs skipped (with member counts), and how many team members were discovered.

### Integration

Other scripts in this skill (e.g. `create_jira_ticket.py`) import `add_jira_watchers.add_watchers_to_tickets()` as a library function instead of implementing their own watcher logic. For PSX/OCPEXCEPT tickets, `create_jira_ticket.py` passes `auto_discover=True` so the caller's team is added automatically at ticket creation time. When adding watcher support to new scripts, import from `add_jira_watchers` — do not duplicate the logic.

### Known limitations

- **PSX/OCPEXCEPT custom field**: Only the reporter or assignee on the ticket can edit `customfield_10705`. If the caller is neither, the script reports the error with the reporter/assignee names so the user knows who to ask.
- **Display name matching**: User lookup requires an exact match on the Jira display name. The script fails early if any name cannot be resolved, before modifying any ticket.
- **Team discovery group threshold**: Groups with > 100 members are skipped. If the caller's team group happens to be larger than 100, team discovery won't find it. The threshold is `MAX_TEAM_GROUP_SIZE` in `add_jira_watchers.py`.

## Managing Exceptions

Exceptions can be assessed regardless of whether they have expired or are still active. Expired exceptions (whose `effectiveUntil` date has passed) must be extended or removed. Active exceptions where the violation has already been resolved can be proactively cleaned up before they expire.

This is a two-skill workflow involving `conforma-exception` (this skill) and the sibling `conforma-analyze` skill.

### Architecture

```mermaid
flowchart TD
    subgraph analyze [conforma-analyze skill]
        A1[verify_auth.py] --> A2[fetch_conforma_reports.py]
        A2 --> A3[parse_violations.py]
        A3 --> VY[conforma-violations.yaml]
    end
    subgraph exception [conforma-exception skill]
        M1["manage_exceptions.py --find-expired / --find-all"] --> EY[exceptions.yaml stdout]
        M2["manage_exceptions.py --assess-expired / --assess-all"] --> AY[assessed-exceptions.yaml]
        AY --> UserReview[Agent presents to user]
        UserReview -->|extend| CE[create_exception.py]
        UserReview -->|remove| GM["create_gitlab_mr.py --remove-expired-exception"]
    end
    VY -->|"--violations-input"| M2
```

**`conforma-analyze`** is a self-contained, user-invocable skill that fetches CSV violation reports from the private `red-hat-data-services/conforma-reporter` repository and parses them into a structured YAML index (`conforma-violations.yaml`). It knows about violations only -- not exceptions, policy files, or Jira.

**`conforma-exception`** (this skill) consumes the violations YAML via `manage_exceptions.py` to cross-reference exceptions against active violations, classify them, and recommend actions. Handling (extending, narrowing, or removing) is done via existing scripts after user confirmation.

### Discovery: `manage_exceptions.py --find-expired` / `--find-all`

Lists exceptions from policy files. No violations data needed.

```bash
python3 scripts/manage_exceptions.py --find-expired \
  --environment prod \
  --clone-dir .work/konflux-release-data

python3 scripts/manage_exceptions.py --find-all \
  --environment prod \
  --clone-dir .work/konflux-release-data
```

`--find-expired` returns only exceptions where `effectiveUntil < now`. `--find-all` returns both expired and active exceptions with expiry metadata.

Output is structured YAML to stdout listing each exception with metadata:
- `file`: policy file path (e.g. `EnterpriseContractPolicy/registry-rhoai-prod.yaml`)
- `rule`: full rule code
- `effective_until`: the date
- `is_expired`: true if expired, false if still active
- `expired_days_ago` (expired only): how long ago it expired
- `expires_in_days` (active only): days until expiry
- `is_unscoped`: true if the exception has no `componentNames` (uses containerImage refs instead of component names)
- `comment_header_lines`: preceding YAML comments (Jira URLs, version notes)

### Assessment: `manage_exceptions.py --assess-expired` / `--assess-all`

Cross-references exceptions against violations data to classify each.

```bash
python3 scripts/manage_exceptions.py --assess-expired \
  --violations-input "$RUN_DIR/conforma-violations.yaml" \
  --environment prod \
  --clone-dir .work/konflux-release-data \
  --output "$RUN_DIR/assessed-exceptions.yaml"

python3 scripts/manage_exceptions.py --assess-all \
  --violations-input "$RUN_DIR/conforma-violations.yaml" \
  --environment prod \
  --clone-dir .work/konflux-release-data \
  --output "$RUN_DIR/assessed-exceptions.yaml"
```

`--assess-expired` assesses only expired exceptions (backward compatible). `--assess-all` assesses all exceptions including active ones, identifying those that can be proactively removed or narrowed.

Requires `conforma-violations.yaml` from the `conforma-analyze` skill.

**Classification logic (deterministic, same for expired and active):**

| Exception type | Violations found? | Classification |
|---|---|---|
| Has `componentNames` | All listed components still violate | `still_needed` |
| Has `componentNames` | Some components still violate | `partially_needed` |
| Has `componentNames` | No component violates | `no_longer_needed` |
| Unscoped (no `componentNames`, uses containerImage refs) | Any component violates for this rule | `still_needed` |
| Unscoped (no `componentNames`, uses containerImage refs) | No violations found | `no_longer_needed` |
| Either type | Rule not in violations index | `no_longer_needed` |

**Recommended actions (deterministic):**

| Classification | Expired | Unscoped (no componentNames) | `recommended_action` |
|---|---|---|---|
| `still_needed` | yes | no | `extend` |
| `still_needed` | yes | yes | `extend_and_modernize` |
| `still_needed` | no | either | `keep` |
| `partially_needed` | yes | no | `narrow_and_extend` |
| `partially_needed` | yes | yes | `modernize_and_narrow` |
| `partially_needed` | no | no | `narrow` |
| `partially_needed` | no | yes | `modernize_and_narrow` |
| `no_longer_needed` | either | either | `remove` |

Key actions for active exceptions:
- **`keep`**: still needed and not expired -- no action required
- **`narrow`**: active exception where some components no longer violate -- trim scope now
- **`remove`**: violation fully resolved before expiry -- clean up proactively

The agent presents the assessment to the user with:
- Why each exception is still needed or not (citing specific releases and components)
- Suggested new `effectiveUntil` date for extensions
- For unscoped exceptions (no componentNames): recommend modernizing to componentNames-scoped blocks
- Priority ordering: oldest expiry first

### Handling: Extending Modern Exceptions (`extend`)

For modern exceptions (has `componentNames`) classified as `still_needed`, use the standard creation flow which auto-extends via deduplication:

```bash
python3 scripts/create_exception.py \
  --rule <rule> \
  --rhoai-version <version> \
  --components <components> \
  --effective-until-date <new-date> \
  --rhoaieng-url <approval-ticket>
```

### Handling: Modernizing Unscoped Exceptions (`extend_and_modernize`)

**Never blindly extend an unscoped exception by bumping its `effectiveUntil` date.** Unscoped exceptions use containerImage refs instead of `componentNames` — they cover all components for a rule rather than specific ones. When an unscoped exception is still needed, it MUST be replaced with properly-scoped entries: per-componentName, per-version.

The assessment evidence provides exactly which components still violate per release (in `evidence.still_violating_components` and `evidence.still_violating_releases`). Use this to create targeted replacements.

Steps:
1. **Remove the old unscoped block**:

```bash
python3 scripts/create_gitlab_mr.py --remove-expired-exception \
  --rule <rule> \
  --effective-until <current-expired-date> \
  --rhoai-version <version> \
  --environment prod
```

2. **Create new scoped exception(s)** per version with the correct `componentNames`, using the standard flow:

```bash
python3 scripts/create_exception.py \
  --rule <rule> \
  --rhoai-version <version> \
  --components <still-violating-component-1>,<still-violating-component-2> \
  --effective-until-date <new-date> \
  --rhoaieng-url <approval-ticket>
```

   Repeat for each version that still has violations. Only include the components that are actually violating in each version -- do NOT carry over the unscoped "all components" coverage.

Both the removal and the new entries can be combined into a single consolidated MR if convenient.

### Handling: Narrowing Exceptions (`narrow`, `narrow_and_extend`, `modernize_and_narrow`)

For exceptions classified as `partially_needed`, some components no longer violate. The old block must be replaced with a narrower one covering only the components that still need coverage.

Steps:
1. Remove the old block (`create_gitlab_mr.py --remove-expired-exception`)
2. Create a new exception with only the still-violating components (`create_exception.py`)

For active exceptions (`narrow`), the same steps apply but the new exception keeps the original `effectiveUntil` date rather than extending it. For unscoped exceptions (`modernize_and_narrow`), this is the same as `extend_and_modernize` above -- the old unscoped block (no componentNames) is replaced with per-componentName entries, scoped to only the components that still violate.

### Handling: Removing Exceptions (`remove`)

For exceptions classified as `no_longer_needed`, use the removal flag on `create_gitlab_mr.py`:

```bash
python3 scripts/create_gitlab_mr.py --remove-expired-exception \
  --rule <rule> \
  --effective-until <current-expired-date> \
  --rhoai-version <version> \
  --environment prod \
  [--components <components>] \
  [--reference-url <psx-ticket-url>]
```

This creates a GitLab MR that removes the expired exception block and its preceding comment header entirely from the policy file. Block identification uses `--rule` + `--effective-until` (+ `--components` for modern exceptions).

### Full Workflow

When the user asks to handle expired exceptions (or analyze all exceptions):

1. **Run `conforma-analyze`**: Invoke the sibling skill to fetch and parse violation reports. Releases are auto-detected from `rhods-devops-infra/rhoai-release-data.yaml` (all supported versions including EA/in-development). An exception is still needed if the violation persists in any release, even if resolved in older versions.

2. **Find exceptions**: Run `manage_exceptions.py --find-expired` (expired only) or `--find-all` (expired + active) to list exceptions.

3. **Assess**: Run `manage_exceptions.py --assess-expired` or `--assess-all` with `--violations-input <path>` to classify each exception.

4. **Generate report and action plan**:

```bash
python3 scripts/generate_report.py \
  --assessed-input "$RUN_DIR/assessed-exceptions.yaml" \
  --output "$RUN_DIR/exceptions-report.md" \
  --action-plan-output "$RUN_DIR/action-plan.json"
```

Present the markdown report to the user. The action plan JSON contains a sorted list of actionable items (removals first, then narrows, then extensions, then modernizations) with all data needed to create MRs. Exceptions with `keep` action are excluded from the action plan since they require no MR.

5. **Interactive action loop**: After presenting the report, announce that you will walk through each exception one by one for user confirmation. Read the action plan JSON and iterate over each action item in order.

**For each exception:**

   a. **Present summary**: Show the rule, classification, recommended action, affected releases, components, policy file, and existing reference URL.

   b. **Ask the user** (using AskQuestion) with three options:
      - "Create MR" -- proceed with the recommended action
      - "Skip" -- move to the next exception
      - "Other" -- await free-form user instructions

   c. **If "Create MR":**

      **i. Resolve `effectiveUntil` dates**: Use `preflight_check.resolve_effective_until_dates()` to look up end-of-support dates (with +7 day buffer) for each affected RHOAI version. Present the resolved dates to the user for confirmation before proceeding. If any version has no EOS date, ask the user to provide one.

      **ii. RHOAIENG approval gate (hard requirement)**: Ask the user for an existing RHOAIENG approval Jira URL, or offer to search for one. This is a **hard gate** -- no MR can be created without an approved RHOAIENG ticket. This follows the same requirements as creating a new exception from scratch: check the ticket status with `preflight_check.check_rhoaieng_approval_status()`. If not approved, halt and inform the user. `--skip-approval-gate` requires explicit user confirmation.

      **iii. Execute the action** based on the recommended action type:

      - **`extend_and_modernize` / `modernize_and_narrow`**: Create a single consolidated MR that removes the unscoped block (no componentNames) and adds new per-componentName/per-version entries:

      ```bash
      python3 scripts/create_gitlab_mr.py \
        --modernize-expired-exception \
        --rule <rule> \
        --effective-until <old-expired-date> \
        --policy-file <file-from-assessment> \
        --reference-url <psx-or-reference-url> \
        --rhoaieng-url <approval-jira-url> \
        --environment prod \
        --version-specs-json '[{"version":"rhoai-3.3","components":["comp-v3-3"],"effective_until":"2026-10-05T00:00:00Z"}, ...]'
      ```

      Build `--version-specs-json` from the action plan's `versions` field (release -> components mapping) combined with the resolved `effectiveUntil` dates.

      - **`remove`**: Remove the exception block:

      ```bash
      python3 scripts/create_gitlab_mr.py \
        --remove-expired-exception \
        --rule <rule> \
        --effective-until <old-expired-date> \
        --rhoai-version <version> \
        --policy-file <file-from-assessment> \
        --environment prod
      ```

      - **`extend`** (componentNames-scoped only): Use the standard creation flow with the new effectiveUntil date:

      ```bash
      python3 scripts/create_exception.py \
        --rule <rule> \
        --rhoai-version <version> \
        --components <still-violating-components> \
        --effective-until-date <new-date> \
        --rhoaieng-url <approval-jira-url>
      ```

      - **`narrow`** (componentNames-scoped, active): Remove the old block, then create a new exception with only the still-violating components, keeping the original `effectiveUntil` date. Use `--remove-expired-exception` followed by `create_exception.py`.

      - **`narrow_and_extend`** (componentNames-scoped, expired): Same as `narrow` but with an extended `effectiveUntil` date.

   d. **Report result**: After each MR creation, print the MR URL and move to the next exception.

   e. **If "Skip"**: Move to the next exception without action.

   f. **If "Other"**: Await free-form user instructions, then proceed accordingly.

**Discovery and handling are always separate steps.** The agent MUST present the assessment and get user confirmation before performing any modifications. The action loop MUST use the `--policy-file` flag from the assessment's `file` field to ensure the correct policy file is targeted (especially important for FBC exceptions in `fbc-rhoai-prod.yaml`).

## Reference Documentation

See `references/exception-process.md` for the full process documentation including:
- Jira project routing rules
- Senior manager approval requirements
- VolatileCriteria schema
- Upstream reference links (Konflux docs, PSX Confluence, conforma.dev)

See `references/conforma-release-policy-rules.yaml` for the complete catalog of enforced rules in the Conforma `redhat` collection, sourced from [conforma.dev/docs/policy/release_policy.html](https://conforma.dev/docs/policy/release_policy.html). Each entry includes the rule code, human-readable name, and documentation URL. Use this catalog to validate `--rule` values and provide context when handling non-templated ("other" category) exceptions.

## Pipeline Mode (Handover)

For backward compatibility with the `conforma-troubleshooter` agent, the orchestrator also accepts `--output` to write structured JSON results compatible with the handover document format.
