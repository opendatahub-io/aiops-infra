# Managing Exceptions Workflow

Exceptions can be assessed regardless of whether they have expired or are still active. Expired exceptions (whose `effectiveUntil` date has passed) must be extended or removed. Active exceptions where the violation has already been resolved can be proactively cleaned up before they expire.

This is a two-skill workflow involving `conforma-exception` (this skill) and the sibling `conforma-analyze` skill.

## Architecture

```
┌─ conforma-report-fetch skill ──────────────────────────────────────────────┐
│                                                                            │
│  ┌──────────────────────┐                                                  │
│  │ fetch_csv_reports.py │                                                  │
│  └──────────┬───────────┘                                                  │
│             │                                                              │
└─────────────┼──────────────────────────────────────────────────────────────┘
              │
┌─ conforma-analyze skill ───────────────────────────────────────────────────┐
│             ▼                                                              │
│  ┌──────────────────┐    ┌──────────────────────┐    ┌───────────────────┐ │
│  │ verify_auth.py   ├───▶│ parse_violations.py  ├───▶│ conforma-        │ │
│  └──────────────────┘    └──────────────────────┘    │ violations.yaml  │ │
│                                                      └────────┬──────────┘ │
└───────────────────────────────────────────────────────────────┼────────────┘
                                                                │
                                              --violations-input│
                                                                │
┌─ conforma-exception skill ────────────────────────────────────┼────────────┐
│                                                               │            │
│  ┌──────────────────────────────────┐                         │            │
│  │ manage_exceptions.py            │                         │            │
│  │ --find-expired / --find-all     ├──▶ exceptions.yaml      │            │
│  └──────────────────────────────────┘   (stdout)              │            │
│                                                               │            │
│  ┌──────────────────────────────────┐                         │            │
│  │ manage_exceptions.py            │◀─────────────────────────┘            │
│  │ --assess-expired / --assess-all │                                       │
│  └───────────────┬──────────────────┘                                      │
│                  ▼                                                          │
│  ┌──────────────────────────┐                                              │
│  │ assessed-exceptions.yaml │                                              │
│  └─────────────┬────────────┘                                              │
│                ▼                                                           │
│  ┌──────────────────────────┐                                              │
│  │ Agent presents to user   │                                              │
│  └──────┬────────────┬──────┘                                              │
│         │            │                                                     │
│    extend│       remove│                                                    │
│         ▼            ▼                                                     │
│  ┌────────────┐ ┌──────────────────────────────────┐                       │
│  │ create_    │ │ create_gitlab_mr.py              │                       │
│  │ exception  │ │ --remove-expired-exception       │                       │
│  │ .py        │ └──────────────────────────────────┘                       │
│  └────────────┘                                                            │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

**`conforma-analyze`** is a self-contained, user-invocable skill that fetches CSV violation reports from the private `red-hat-data-services/conforma-reporter` repository and parses them into a structured YAML index (`conforma-violations.yaml`). It knows about violations only -- not exceptions, policy files, or Jira.

**`conforma-exception`** (this skill) consumes the violations YAML via `manage_exceptions.py` to cross-reference exceptions against active violations, classify them, and recommend actions. Handling (extending, narrowing, or removing) is done via existing scripts after user confirmation.

## Discovery: `manage_exceptions.py --find-expired` / `--find-all`

Lists exceptions from policy files. No violations data needed.

```bash
python3 skills/conforma-exception/scripts/manage_exceptions.py --find-expired \
  --environment prod \
  --clone-dir .work/konflux-release-data

python3 skills/conforma-exception/scripts/manage_exceptions.py --find-all \
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

## Assessment: `manage_exceptions.py --assess-expired` / `--assess-all`

Cross-references exceptions against violations data to classify each.

```bash
python3 skills/conforma-exception/scripts/manage_exceptions.py --assess-expired \
  --violations-input "$RUN_DIR/conforma-violations.yaml" \
  --environment prod \
  --clone-dir .work/konflux-release-data \
  --output "$RUN_DIR/assessed-exceptions.yaml"

python3 skills/conforma-exception/scripts/manage_exceptions.py --assess-all \
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

## Handling: Extending Modern Exceptions (`extend`)

For modern exceptions (has `componentNames`) classified as `still_needed`, use the standard creation flow which auto-extends via deduplication:

```bash
python3 skills/conforma-exception/scripts/create_exception.py \
  --rule <rule> \
  --rhoai-version <version> \
  --components <components> \
  --effective-until-date <new-date> \
  --rhoaieng-url <approval-ticket>
```

## Handling: Modernizing Unscoped Exceptions (`extend_and_modernize`)

**Never blindly extend an unscoped exception by bumping its `effectiveUntil` date.** Unscoped exceptions use containerImage refs instead of `componentNames` — they cover all components for a rule rather than specific ones. When an unscoped exception is still needed, it MUST be replaced with scoped entries: per-componentName, per-version.

The assessment evidence provides exactly which components still violate per release (in `evidence.still_violating_components` and `evidence.still_violating_releases`). Use this to create targeted replacements.

Steps:
1. **Remove the old unscoped block**:

```bash
python3 skills/conforma-exception/scripts/create_gitlab_mr.py --remove-expired-exception \
  --rule <rule> \
  --effective-until <current-expired-date> \
  --rhoai-version <version> \
  --environment prod
```

2. **Create new scoped exception(s)** per version with the correct `componentNames`, using the standard flow:

```bash
python3 skills/conforma-exception/scripts/create_exception.py \
  --rule <rule> \
  --rhoai-version <version> \
  --components <still-violating-component-1>,<still-violating-component-2> \
  --effective-until-date <new-date> \
  --rhoaieng-url <approval-ticket>
```

   Repeat for each version that still has violations. Only include the components that are actually violating in each version -- do NOT carry over the unscoped "all components" coverage.

Both the removal and the new entries can be combined into a single consolidated MR if convenient.

## Handling: Narrowing Exceptions (`narrow`, `narrow_and_extend`, `modernize_and_narrow`)

For exceptions classified as `partially_needed`, some components no longer violate. The old block must be replaced with a narrower one covering only the components that still need coverage.

Steps:
1. Remove the old block (`create_gitlab_mr.py --remove-expired-exception`)
2. Create a new exception with only the still-violating components (`create_exception.py`)

For active exceptions (`narrow`), the same steps apply but the new exception keeps the original `effectiveUntil` date rather than extending it. For unscoped exceptions (`modernize_and_narrow`), this is the same as `extend_and_modernize` above -- the old unscoped block (no componentNames) is replaced with per-componentName entries, scoped to only the components that still violate.

## Handling: Removing Exceptions (`remove`)

For exceptions classified as `no_longer_needed`, use the removal flag on `create_gitlab_mr.py`:

```bash
python3 skills/conforma-exception/scripts/create_gitlab_mr.py --remove-expired-exception \
  --rule <rule> \
  --effective-until <current-expired-date> \
  --rhoai-version <version> \
  --policy-file <file-from-assessment> \
  --environment prod \
  [--components <components>] \
  [--reference-url <psx-ticket-url>]
```

This creates a GitLab MR that removes the expired exception block and its preceding comment header entirely from the policy file. Block identification uses `--rule` + `--effective-until` (+ `--components` for modern exceptions).

## Full Workflow

When the user asks to handle expired exceptions (or analyze all exceptions):

1. **Run `conforma-analyze`**: Invoke the sibling skill to fetch and parse violation reports. Releases are auto-detected from `rhods-devops-infra/rhoai-release-data.yaml` (all supported versions including EA/in-development). An exception is still needed if the violation persists in any release, even if resolved in older versions.

2. **Find exceptions**: Run `manage_exceptions.py --find-expired` (expired only) or `--find-all` (expired + active) to list exceptions.

3. **Assess**: Run `manage_exceptions.py --assess-expired` or `--assess-all` with `--violations-input <path>` to classify each exception.

4. **Generate report and action plan**:

```bash
python3 skills/conforma-exception/scripts/generate_report.py \
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
      python3 skills/conforma-exception/scripts/create_gitlab_mr.py \
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
      python3 skills/conforma-exception/scripts/create_gitlab_mr.py \
        --remove-expired-exception \
        --rule <rule> \
        --effective-until <old-expired-date> \
        --rhoai-version <version> \
        --policy-file <file-from-assessment> \
        --environment prod
      ```

      - **`extend`** (componentNames-scoped only): Use the standard creation flow with the new effectiveUntil date:

      ```bash
      python3 skills/conforma-exception/scripts/create_exception.py \
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
