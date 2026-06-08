# Interactive Workflow Reference

## Listing Exception Types

When the user asks about Conforma exception types (e.g. "what are the conforma exception types", "list exception types", "show me conforma violations"), always:

1. Run `python3 skills/conforma-exception/scripts/create_exception.py --list-exception-types` (from this skill directory). This returns JSON with:
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

   > The skill also supports **{non_common_count} more** templated exception types and can handle **any** of the **{total_catalog_rules}** rules in the Conforma redhat collection (link from `conforma_rules_url` field) via the interactive "other" catch-all category.

   Then add a brief note suggesting the user can ask to see more details on the remaining templated types or the full list of all supported types if they're interested. Do NOT use the AskQuestion tool here -- just mention it conversationally in the response text.

4. If the user asks to see remaining types, run `python3 skills/conforma-exception/scripts/create_exception.py --list-exception-types --all` and render the `non_common` array plus the `catch_all` entry in the same table format.

5. If the user asks for the rule reference, read `references/conforma-release-policy-rules.yaml` and display the rules grouped by category heading (the `# ---` comment sections) as a compact table with columns: Rule Code, Name, Docs (link).

6. After any table, add a brief legend explaining:
   - The workflow track abbreviations (remediation_plan vs exception_approval)
   - The step names used (Resolution plan, Senior Management approval, RHOAIENG Jira, PSX Jira, OCPEXCEPT Jira, GitLab Merge Request, self-service)
   - That the `other` category is a catch-all for any Conforma rule not covered by a specific template, and requires interactive input for all exception text fields. Reference `references/conforma-release-policy-rules.yaml` for the full list of known rules.
   - Always include a link to the [Conforma redhat collection](https://conforma.dev/docs/policy/release_policy.html) for the full rule reference.

## Usage

### Standalone mode (user-provided details)

```bash
python3 skills/conforma-exception/scripts/create_exception.py \
  --rhoai-version rhoai-3.3 \
  --rule hermetic_task.hermetic \
  --components odh-mlflow-v3-3,odh-another-v3-3 \
  --effective-until-date 2026-10-03 \
  --environment prod \
  --dry-run
```

### With existing Jira tickets

```bash
python3 skills/conforma-exception/scripts/create_exception.py \
  --rhoai-version rhoai-3.3 \
  --rule hermetic_task.hermetic \
  --components odh-mlflow-v3-3 \
  --effective-until-date 2026-10-03 \
  --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38414 \
  --psx-url https://redhat.atlassian.net/browse/PSX-1089
```

### Self-service (auto-detected from rule)

```bash
python3 skills/conforma-exception/scripts/create_exception.py \
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

## Questionnaire

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

   Always translate container image names to Konflux component names (remove the `-rhel9` suffix, append the RHOAI version, e.g. `odh-dashboard-rhel9` becomes `odh-dashboard-v3-4`) and confirm the result with the user before using it in a Merge Request.

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
    1. **Automatically run team discovery** by calling `add_jira_watchers.discover_team()` (or `python3 skills/conforma-exception/scripts/add_jira_watchers.py --tickets <placeholder> --auto-discover --dry-run`) to find the caller's team from Jira groups ≤ 100 members.
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
