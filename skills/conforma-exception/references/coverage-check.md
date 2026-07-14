# Violations Coverage Check

Cross-reference parsed Conforma violations against existing policy exceptions, open GitLab Merge Requests, open Jira tickets, and Slack discussions — producing a single unified summary table.

This reference is the canonical source for the coverage check workflow. It is used by both `conforma-analyze` (report analysis) and `conforma-exception` (exception creation from a report URL).

## Prerequisites

All auth is verified upfront by `_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py`" (conforma-analyze workflow step 1). If that passed, the coverage check has everything it needs:

- Violations parsed into a YAML file via `parse_violations.py` (steps 1–4)
- GitLab auth (token in `~/.conforma/.env`, VPN active)
- Jira auth (token + email in `~/.conforma/.env`)
- Slack auth (slackdump installed + logged in)
- The `konflux-release-data` repo clone (managed automatically by the script)

**Do not re-check auth here.** If step 1 passed, proceed. If step 1 failed, the workflow should not have reached this point.

## Shared Repo Clone

The `konflux-release-data` GitLab repo is large and slow to clone (~40s). The `violations_coverage.py` script manages this automatically via `--clone-dir`:

- If the directory exists, the script runs `git fetch` and resets to `origin/main`
- If the fetch fails (VPN down), the script aborts with a clear error
- If the directory doesn't exist, the script clones it using `GITLAB_TOKEN` from the environment

No manual clone management is needed — just pass `--clone-dir ~/.conforma/konflux-release-data`.

## Running the Coverage Check

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-analyze/scripts/violations_coverage.py" \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --clone-dir ~/.conforma/konflux-release-data \
  --environment prod > "$RUNDIR/coverage.json"
```

This checks all violations against existing exceptions in the policy file, searches for open Merge Requests, open Jira tickets, and Slack threads — all in one pass.

For CI-only environments (no Slack access), disable with `--require-slack false`. In the interactive conforma-analyze workflow, Slack availability is auto-detected from `steps.prerequisites.slack_available` in context.yaml — no manual flag needed.

## Presenting Results

The JSON output contains a `markdown_table` field — a pre-rendered markdown table with columns: `#`, `Violation`, `Count`, `Status`, `Next Steps`.

**Print `markdown_table` verbatim as the primary output to the user.** This is the main deliverable when analyzing a report.

The `Status` column shows coverage-ratio text (e.g. "Exception granted (2/2 components covered)") and the `Next Steps` column shows a concise action (from the `next_steps_short` field). Detailed cross-reference data (components, open Merge Requests, open Jira tickets, Slack threads) is presented in the **Resolution Guide** section below the table, where each violation has a property table with full details.

Rules:
- Do NOT reconstruct the table from individual JSON fields — always use the pre-rendered `markdown_table`
- Do NOT include a Coverage column — the `coverage_label` field exists in the JSON for programmatic use but is misleading when shown to users (it implies exceptions are the default resolution).
- Present a **Resolution Guide** section after the table with full per-violation details (from `next_steps` JSON field + violation catalog enrichment)
- Statistical breakdowns (violation counts, signing keys, per-component patterns) from `analyze_csv_report.py` can be presented as supplementary detail below the Resolution Guide if useful.

## Search Query Links

Search links for each data source (GitLab Merge Requests, Jira, Slack) are rendered in the **Resolution Guide** property tables, not in the summary table:

- **Open MRs**: Links to GitLab Merge Request search filtered by the rule code
- **Open Jira**: Links to a JQL search for conforma-violation tickets matching the rule
- **Slack**: Links to the workspace search for the rule code

When results exist, the search link is appended after them. When no results exist, the search link is shown as a fallback (e.g. `[search GitLab](url)`).

The JSON output includes `open_mr_search_url`, `open_jira_search_url`, and `open_slack_search_url` fields for each violation.

## Open Merge Request Coverage Analysis

The output includes an `open_merge_requests` list for each violation. Each entry contains per-Merge Request coverage data (the agent MUST NOT call `glab api` directly — all GitLab API interaction is encapsulated in the scripts):

- `mr_components`: components the Merge Request already covers
- `covered`: overlap between Merge Request components and the requested components
- `missing`: requested components not yet in the Merge Request
- `suggestion`: one of `"extend_mr"`, `"fully_covered"`, or `"no_overlap"`

Present these as:
- **`extend_mr`**: "Open Merge Request !{iid} covers {N} of {M} components. Missing: {list}. Consider extending the existing Merge Request."
- **`fully_covered`**: "Open Merge Request !{iid} covers all {M} components. Creating a new Merge Request would be a duplicate."
- **`no_overlap`**: The Merge Request is for a different set of components (likely a different RHOAI version). Proceed normally.

## Open Jira Ticket Coverage

The output also includes `open_jira_tickets` for each violation — open RHOAIENG, PSX, OCPEXCEPT, or PRODSECRM tickets with the `conforma-violation` label that match the violation rule. When present, show them alongside the Merge Request coverage. This is informational (does not block exception creation) but prevents creating duplicate Jira tickets.

## Slack Thread Coverage

The output includes `open_slack_threads` for each violation (when `--require-slack true`) — Slack messages from the last 30 days that mention the violation rule code. Results are grouped by thread; the permalink points to the specific matching message.

Slack threads are informational only — they do not affect `coverage`, `next_steps`, or `status` fields. They show that someone is already discussing or working on the violation, which helps avoid duplicate effort.
