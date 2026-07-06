# Create Workflow

## Prerequisites

**Setup:** See [README.md](README.md) for installation and one-time authentication setup.

**Always run preflight first** before creating any tickets or Merge Requests:

```bash
python3 skills/conforma-exception/scripts/verify_auth.py
```

**Component-maturity catalog** (required for RHOAIENG tickets): The Jira Component field is **mandatory** on all RHOAIENG tickets created by this skill. The catalog is auto-cloned by the orchestrator when needed. To set up manually:

```bash
python3 scripts/component_catalog_ops.py ensure-repo
```

Jira Component values are auto-resolved from the catalog by mapping Konflux component names to their corresponding Jira Component. If auto-resolution fails (component not found in the catalog), ticket creation is **blocked** and the agent must ask the user for the correct Jira Component name, then pass it via `--jira-components`. No RHOAIENG ticket is created without this field.


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


## Important: Human-in-the-Loop

Exception GitLab Merge Requests bypass policy enforcement. Engineer approval is **MANDATORY** before creation.
The RHOAIENG approval Jira ticket must be approved before ProdSec form submission / MR creation (see "RHOAIENG Approval Gate" above).

### No Agent Decisions Policy

**The agent MUST NOT make decisions about parameter values.** All parameters are resolved by deterministic scripts. The agent's ONLY role is:
1. Run `preflight_check.py --check-existing-exception` — Existing Exception Gate (hard prerequisite, must pass before continuing)
2. Run `preflight_check.py` (full) to resolve all values from authoritative sources
3. Present the script's output to the user as a structured questionnaire for confirmation
4. **Justification review**: Present the template-resolved justification text (scope, risk, remediation, impact) as a **draft for review** — not a finished product. Include this note: *"This justification is auto-generated from the violation template. It covers the general case but should be reviewed and enhanced with details specific to this exception request — for example, input from the component team explaining why the violation cannot be fixed in the component code, what has already been tried, upstream dependencies, timelines, etc."* The user must explicitly confirm or edit the text before proceeding. See `references/interactive-workflow.md` item 13 for the full questionnaire flow.
5. **Dry-run first**: Always run `create_exception.py` with `--dry-run` before the real execution and present the preview to the user. The dry-run output includes the full justification text — verify the user has reviewed it. Only proceed with the real execution after the user confirms the dry-run output. This is a standard safety step — never skip it unless the user explicitly asks to go straight to execution.
6. Execute the creation scripts with the confirmed values (remove `--dry-run`)
7. Report results

The agent MUST NEVER:
- Decide link types (enforced by `link_artifacts.py`)
- Split Merge Requests per version (hard rule: `one_mr_per_rule_all_versions` — always one consolidated Merge Request)
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
  --policy-files <file1,file2> \
  [--environment prod]
```

The script checks the GitLab repo deterministically and outputs JSON with a `status` field. Present the script's output to the user. If `status` is not `passed`, do NOT proceed with the create-exception workflow.

Coverage detection is fully deterministic — the script handles all matching logic:
- **componentNames-scoped exceptions**: exact overlap check between requested and listed componentNames
- **imageUrl-scoped exceptions**: base name matching (e.g. `quay.io/rhoai/odh-dashboard-rhel9` covers `odh-dashboard-v3-3`, `odh-dashboard-v3-4`, etc. by stripping the `-rhel9`/`-ubi9` suffix and the `-vX-Y` version suffix, then comparing base names)
- **Unscoped exceptions** (no componentNames, no imageUrl): covers all components for that rule

The agent MUST NOT perform its own imageUrl-to-componentName matching. The script output is authoritative.

The gate also searches for **open merge requests** in the `konflux-release-data` GitLab repo that mention the violation. If open Merge Requests are found, they are included in the `open_merge_requests` field. The agent MUST present them to the user with a note like: "There is already an open Merge Request for this violation: `[MR title](url)` by @author (created date). Check it before creating a new one." This is informational — it does not block the gate — but it prevents duplicate Merge Requests.

### Mandatory Pre-Flight Script

**After the existing exception gate passes**, run `preflight_check.py` to resolve all remaining parameters:

```bash
python3 skills/conforma-exception/scripts/preflight_check.py \
  --rhoaieng-url <url> \
  --versions rhoai-2.25,rhoai-3.3 \
  --image-bases odh-vllm-cpu,odh-vllm-gaudi
```

The script outputs JSON containing:
- `hard_rules`: non-configurable behavior (link types, Merge Request strategy, dedup logic)
- `rhoaieng`: ticket metadata and type warnings
- `rule`: extracted or overridden rule value
- `versions`: resolved RHOAI versions
- `components`: per-version component names from RPA files
- `effective_until`: per-version dates from end-of-support defaults
- `related_psx`: auto-discovered related ProdSec/PSX tickets
- `existing_exceptions`: current state in konflux-release-data
- `duplicate_check`: existing tickets created by this skill
- `user_confirmation_required`: items that need user approval

The agent presents `user_confirmation_required` items to the user and waits for confirmation. It does NOT modify any resolved values.

### Decision Short-Circuit

The preflight output includes a `decision` field evaluated deterministically by `evaluate_decision()`. When `decision.proceed` is `false`, the agent MUST:
1. Report the `decision.reason` to the user
2. Stop immediately — do NOT present remaining questionnaire items
3. Do NOT create tickets, Merge Requests, or any other artifacts

The agent has NO discretion to override a `proceed: false` decision. Only the user can re-run with `--rule` override or manually modify the policy file.

**Output presentation**: See [script-output-presentation.md](../references/script-output-presentation.md).


## Workflow Routing

Workflow routing (which Jira projects, how many tickets, assignees, Merge Request target) is defined per-category in `exception_templates.yaml`. The orchestrator reads the `workflow` steps from the matched category and executes them in order.

Each workflow step has a `track` field indicating which logical track it belongs to:

- **`track: remediation_plan`** — The remediation ticket for the component team fix commitment. Its URL (`{rhoaieng_jira_violation_url}`) is referenced in the justification text of all downstream artifacts.
- **`track: exception_approval`** — The exception approval chain. These steps are sequential and block the release until the exception is granted: approval ticket -> ProdSec form (or OCPEXCEPT for FIPS) -> policy MR.

The `--rule` flag determines which template category matches, and thus which workflow runs. There are no separate path flags -- the rule is the single input that drives routing.

Common workflow patterns:

| Pattern | Steps | Example rules |
|---------|-------|---------------|
| Standard | Resolution plan (team) -> Senior Management approval (RHOAIENG Jira) -> **[APPROVAL GATE]** -> ProdSec form -> GitLab Merge Request | `rpm_signature.allowed:*`, `hermetic_task.hermetic`, SBOM rules |
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

3. **Determine the correct workflow**: The default workflow for `other` is the standard 4-step path (resolution plan -> Senior Management approval -> ProdSec form -> GitLab Merge Request). However, the agent MUST ask the user:
   - "Is this a FIPS-related violation?" — if yes, the `fips_check` category uses `psx_exception_jira` with OCPEXCEPT Jira (task type)
   - "Is this a non-security, self-service exception?" — if yes, skip ProdSec form/OCPEXCEPT and use the 2-step self-service path (Senior Management approval -> self-service GitLab Merge Request)

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

The following diagram shows the end-to-end flow for creating a new Conforma exception. **The agent MUST show this diagram verbatim to the user** (copy the code block exactly) in the following situations:

1. **Generic questions** — When the user asks what a Conforma exception is, how exceptions work, or asks about the exception process (e.g. "what is a conforma exception", "explain conforma exceptions", "how does the exception workflow work", "what's the process for creating an exception")
2. **Before prompting for details** — When the user initiates exception creation (e.g. "create conforma exception", "I need a conforma exception", "create exception for componentA") the agent MUST show this diagram BEFORE presenting the entry-point choices or the questionnaire, so the user understands the full flow they are about to go through

```
  ┌─────────────────────────────────────────────┐
  │ ① RHOAIENG component bugfix Jira            │
  │   (remediation plan — created first)        │
  └──────────────────────┬──────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────┐
  │ ② RHOAIENG Senior Management approval Jira │
  └──────────────────────┬──────────────────────┘
                         ▼
              ╔════════════════════╗
              ║ ③ APPROVAL GATE   ║
              ║ Senior Management ║
              ║ must approve      ║
              ╚═════╤════════╤════╝
                    │        │
               approved   not approved
                    │        │
                    ▼        ▼
                    │   ┌─────────────────────┐
                    │   │ HALTED — get        │
                    │   │ approval, then      │
                    │   │ re-run              │
                    │   └─────────────────────┘
                    ▼
  ┌─────────────────────────────────────────────┐
  │ ④ ProdSec form or OCPEXCEPT Jira            │
  │   (skip for self-service rules)             │
  └──────────────────────┬──────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────┐
  │ ⑤ GitLab Merge Request                      │
  │   (exception YAML in konflux-release-data)  │
  └──────────────────────┬──────────────────────┘
                         ▼
  ┌─────────────────────────────────────────────┐
  │ ⑥ Link all artifacts                        │
  │   (comments, labels, Jira links)            │
  └──────────┬───────────────────────┬──────────┘
             │                       │
             ▼                       ▼
  ┌─ External review — human ───────────────────┐
  │                                              │
  │  ┌────────────────────┐ ┌─────────────────┐  │
  │  │ ⑦ ProdSec reviews │ │ ⑧ Release Eng.  │  │
  │  │ exception ticket   │ │ merges GitLab   │  │
  │  │ → Ready for Verif. │ │ MR              │  │
  │  └─────────┬──────────┘ └────────┬────────┘  │
  │            │                     │           │
  └────────────┼─────────────────────┼───────────┘
               │                     │
               └──────────┬──────────┘
                          ▼
              ┌───────────────────────┐
              │  Exception granted    │
              └───────────────────────┘
```

The exception is only granted when **both** conditions are met: the ProdSec/OCPEXCEPT Jira ticket reaches **Ready for Verification** and the GitLab Merge Request is **merged**. Steps ①–⑥ are automated by this skill; steps ⑦–⑧ require human review by ProdSec and Release Engineering respectively.

**Self-service variant** (for rules like `schedule.weekday_restriction`, `test.no_failed_tests:fbc-target-index-pruning-check`): Steps ① and ④ are skipped, and step ⑦ does not apply — the workflow is: Senior Management approval → Approval Gate → GitLab Merge Request (to `exceptions/` directory) → Merge Request merged → Exception granted.


## Explaining Conforma Exceptions

When the user asks what a Conforma exception is (e.g. "what is a conforma exception", "explain conforma exceptions"), always include the compact YAML example from the introduction above. This makes the concept concrete. Also link to the [Conforma redhat collection](https://conforma.dev/docs/policy/release_policy.html) and [VolatileCriteria schema](https://conforma.dev/docs/policy/packages/release_volatile_config.html).

**Additionally**, always show the workflow diagram from the "Exception Creation Workflow Diagram" section above verbatim (copy the code block exactly) when explaining Conforma exceptions, so the user can see the full process visually.


## Run Directory Convention

Every session that creates intermediate files (downloaded CSVs, parsed violations, coverage checks, assessed exceptions, reports, action plans) MUST use a timestamped run directory inside `~/.conforma/`. This prevents runs from clobbering each other's files and keeps the directory navigable.

At the start of each session, create the run directory:

```bash
RUN_DIR="$HOME/.conforma/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN_DIR"
```

All intermediate files go inside `$RUN_DIR`. Example layout for a single run:

```
~/.conforma/
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

**Shared repo clone**: The `konflux-release-data` GitLab repo is large and slow to clone (~40s). To avoid re-cloning on every script invocation, maintain a shared clone at `~/.conforma/konflux-release-data` and pass `--clone-dir ~/.conforma/konflux-release-data` to all commands that accept it (`preflight_check.py`, `manage_exceptions.py`, `create_gitlab_mr.py`). **Always fetch before use and abort if the fetch fails** — never use stale data:

```bash
if [ -d ~/.conforma/konflux-release-data/.git ]; then
  git -C ~/.conforma/konflux-release-data fetch origin main || { echo "ERROR: git fetch failed — remote unreachable (VPN down?). Aborting." >&2; exit 1; }
  git -C ~/.conforma/konflux-release-data reset --hard origin/main
else
  GITLAB_TOKEN=$(glab config get token --host "$GITLAB_HOST")
  git -c "http.extraheader=Authorization: Bearer ${GITLAB_TOKEN}" clone --depth 1 "https://${GITLAB_HOST}/releng/konflux-release-data.git" ~/.conforma/konflux-release-data || { echo "ERROR: git clone failed. Aborting." >&2; exit 1; }
fi
```

**Note**: The Python scripts (`violations_coverage.py`, `conforma_policy_ops.py`, `manage_exceptions.py`) now enforce this policy internally — they will refresh any `--clone-dir` via `git fetch` and abort if the remote is unreachable.

Script-internal temp directories (`conforma-exception-mr-*`, `conforma-exception-manage-*`, etc.) are created by Python scripts via `tempfile.mkdtemp()` and land directly in `~/.conforma/`. These are transient and self-cleaning — do not move them into run directories.


## Starting Without Details

When the user asks to create a Conforma exception but does not provide specific details (no rule, no version, no components, no Jira URL — e.g., "create conforma exception for componentA", "how do I create an exception", "I need a conforma exception"), the agent MUST:

1. **Show the workflow diagram first** — copy the diagram from the "Exception Creation Workflow Diagram" section verbatim so the user understands the full flow before beginning
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

When multiple open Merge Requests exist for the same violation, present each independently. In the AskQuestion violation selection, annotate violations that have open Merge Requests with partial coverage as `[open MR covers N/M]` next to the coverage indicator.

### Open Jira Ticket Coverage

The `--check-violations-coverage` script also searches for open Jira tickets (RHOAIENG, PSX, OCPEXCEPT, PRODSECRM) with the `conforma-violation` label that match each violation rule. This is a single batch query, not per-violation. Each violation entry includes:

- `open_jira_tickets`: list of matching tickets with `key`, `status`, `summary`, `url`
- `open_jira_label`: pre-formatted markdown links for display (empty if none)

When `open_jira_label` is non-empty, present it alongside the MR coverage in the violations table. This is informational — it does not block exception creation — but it prevents creating duplicate Jira tickets. If an open RHOAIENG or ProdSec ticket already exists for a violation, the agent should suggest reusing it (via `--rhoaieng-url` or `--prodsec-ticket-url`) rather than creating a new one.


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
| Container image name (not for Merge Requests) | `{base}-rhel9` (no version) | `odh-workbench-jupyter-pytorch-rocm-py312-rhel9` | NO |

All Konflux component names include a version suffix (e.g. `-v2-25`, `-v3-3`, `-v3-5-ea-1`). Names ending in `-rhel9` or `-ubi9` without a version suffix are container image names produced by those components -- they must NOT be used in `componentNames` fields in exception GitLab Merge Requests. The validation script rejects container image names and suggests the correct Konflux component name format.

To find correct component names, check the ReleasePlanAdmission files:
`config/${KONFLUX_CLUSTER_DOMAIN}/product/ReleasePlanAdmission/rhoai/rhoai-onprem-vX-Y-components-prod.yaml`


## Dry-Run Mode

`--dry-run` validates all inputs and outputs what would be created (YAML block, target file, Jira details) as structured JSON without submitting anything. Auth checks still run.


## Verification Contract

Every ticket creation or reconciliation ends with a **verification phase** that reads the ticket back via Jira REST API and checks:

| Field | Check |
|-------|-------|
| Labels | Contains both `conforma-exception-ai-skill` and `conforma-violation` |
| Issue links | Includes all expected targets (RHOAIENG, tracking ticket) |
| Description | ADF with >= 15 panel/paragraph nodes (OCPEXCEPT) |
| Authorized Party | `customfield_10938` is set (OCPEXCEPT) |
| Jira Component | Set on RHOAIENG tickets (auto-resolved from component-maturity catalog) |

If any check fails, the script **retries the failed operation** (up to 2 attempts) and re-verifies. If it still fails, the script exits non-zero with structured JSON listing exactly what expectations are unmet.

All operations return structured dicts reporting what was attempted, what the actual state is, and what failed -- never silent True/False. This makes failures visible to both the agent and the user.


## Jira Component Audit

To bulk-audit and fix Jira Component fields on all RHOAIENG tickets created by this skill:

```bash
# Ensure catalog is fresh
python3 scripts/component_catalog_ops.py ensure-repo

# Audit: show what would change
python3 scripts/component_catalog_ops.py audit-jira-components

# Fix: update Jira tickets with resolved components
python3 scripts/component_catalog_ops.py audit-jira-components --fix
```

The audit extracts component/image names from each ticket's labels (`Exception-<rule>:<component>`) and description text (regex patterns for `odh-*-rhel9`, `quay.io/rhoai/<name>` URLs), resolves them via the catalog, and proposes updates. Existing components are preserved (new ones are merged in).

The `reconcile_ticket()` function uses the same extraction logic as a fallback when the `--components` arg doesn't resolve -- it parses the ticket's own content to find image names.


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


