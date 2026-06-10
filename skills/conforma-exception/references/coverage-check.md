# Violations Coverage Check

Cross-reference parsed Conforma violations against existing policy exceptions, open GitLab Merge Requests, open Jira tickets, and Slack discussions — producing a single unified summary table.

This reference is the canonical source for the coverage check workflow. It is used by both `conforma-analyze` (report analysis) and `conforma-exception` (exception creation from a report URL).

## Prerequisites

- Violations must already be parsed into a YAML file via `parse_violations.py` (see conforma-analyze workflow steps 1–4)
- GitLab auth must be working (`glab auth status`)
- The `konflux-release-data` repo clone must be available (see "Shared Repo Clone" below)
- Slack auth must be working (`python3 scripts/slack_ops.py verify-auth`) — required by default; disable with `--require-slack false`

**Site config**: If this is your first run, the skill will walk you through setup. See [site-config-setup.md](../../references/site-config-setup.md).

## Auth Availability — Inform the User

Before running the coverage check, probe all auth sources. If any are unavailable, **always tell the user** which data sources will be skipped and how to enable them. Present this as a compact notice before the results, not buried in a footnote. Prefer asking the user to set up auth so the analysis is complete.

Check order and compact setup instructions to show the user:

| Source | Check command | If missing, tell the user |
|--------|--------------|--------------------------|
| GitLab | `glab auth status --hostname "$GITLAB_HOST"` | `glab auth login --hostname "$GITLAB_HOST"` (VPN required) |
| Jira | `python3 scripts/jira_ops.py verify-auth` | `export JIRA_EMAIL=you@redhat.com JIRA_API_TOKEN=ATATT3x...` |
| Slack | `python3 scripts/slack_ops.py verify-auth` | `./scripts/install_slackdump.sh && slackdump login` |
| GitHub | `gh auth status` | `gh auth login` |

Example notice (adapt to actual failures):

> **Note**: Slack search skipped (slackdump not authenticated). For full coverage including Slack threads, run: `./scripts/install_slackdump.sh && slackdump login`

Rules:
- If GitLab auth fails → the coverage check cannot run at all (exception data lives in GitLab). Stop and tell the user.
- If Jira auth fails → the coverage check cannot run (open tickets are essential context). Stop and tell the user.
- If Slack auth fails → the coverage check cannot run. Stop and tell the user to run `./scripts/install_slackdump.sh && slackdump login`.
- If GitHub auth fails → the CSV fetch in earlier steps already failed; should not reach here.
- **Never silently skip** a data source. All three (GitLab, Jira, Slack) are required by default. The script enforces this with `--require-jira true` and `--require-slack true` (defaults).

## Shared Repo Clone

The `konflux-release-data` GitLab repo is large and slow to clone (~40s). Reuse `.work/konflux-release-data` across runs:

```bash
if [ -d .work/konflux-release-data/.git ]; then
  git -C .work/konflux-release-data fetch origin main && git -C .work/konflux-release-data reset --hard origin/main
else
  GITLAB_TOKEN=$(glab config get token --host "$GITLAB_HOST")
  git clone --depth 1 "https://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}/releng/konflux-release-data.git" .work/konflux-release-data
fi
```

## Running the Coverage Check

```bash
python3 skills/conforma-exception/scripts/preflight_check.py \
  --check-violations-coverage "$RUN_DIR/violations.yaml" \
  --clone-dir .work/konflux-release-data \
  --environment prod
```

To disable Slack search (e.g. in CI or environments without Slack access):

```bash
python3 skills/conforma-exception/scripts/preflight_check.py \
  --check-violations-coverage "$RUN_DIR/violations.yaml" \
  --clone-dir .work/konflux-release-data \
  --environment prod \
  --require-slack false
```

This checks all violations against existing exceptions in the policy file, searches for open MRs, open Jira tickets, and Slack threads — all in one pass.

## Presenting Results

The JSON output contains a `markdown_table` field — a pre-rendered markdown table with columns: `#`, `Rule`, `Components`, `Open MRs`, `Open Jira`, `Slack`, `Next Steps`.

When `--require-slack false` is used, the `Slack` column is omitted and the table has the same 6 columns as before.

**Print `markdown_table` verbatim as the primary output to the user.** This is the main deliverable when analyzing a report.

The `Next Steps` column is intentionally abbreviated — it shows only the primary action with a *(details below)* pointer to the **Violation Resolution Guide** section. Full resolution details (including all approval steps, MR actions, and linked Jira tickets) are in each violation's `next_steps` field in the JSON output and should be presented in the Violation Resolution Guide section that follows the table.

Rules:
- Do NOT reconstruct the table from individual JSON fields — always use the pre-rendered `markdown_table`
- Do NOT include a Coverage column — the `coverage_label` field exists in the JSON for programmatic use but is misleading when shown to users (it implies exceptions are the default resolution). The `next_steps` column is the single source of guidance.
- Present a **Violation Resolution Guide** section after the table with full per-violation details (from `next_steps` JSON field + violation catalog enrichment)
- Statistical breakdowns (violation counts, signing keys, per-component patterns) from `analyze_csv_report.py` can be presented as supplementary detail below the Violation Resolution Guide if useful.

## Search Query Links

Every data source column (Open MRs, Open Jira, Slack) includes a clickable `[search](url)` link that opens the same query in the corresponding web UI:

- **Open MRs**: Links to GitLab MR search filtered by the rule code
- **Open Jira**: Links to a JQL search for conforma-violation tickets matching the rule
- **Slack**: Links to the workspace search for the rule code

When results exist, the search link is appended after them. When no results exist, the search link replaces the bare dash, so the user can always click through to verify.

The JSON output includes `open_mr_search_url`, `open_jira_search_url`, and `open_slack_search_url` fields for each violation.

## Open MR Coverage Analysis

The output includes an `open_merge_requests` list for each violation. Each entry contains per-MR coverage data (the agent MUST NOT call `glab api` directly — all GitLab API interaction is encapsulated in the scripts):

- `mr_components`: components the MR already covers
- `covered`: overlap between MR components and the requested components
- `missing`: requested components not yet in the MR
- `suggestion`: one of `"extend_mr"`, `"fully_covered"`, or `"no_overlap"`

Present these as:
- **`extend_mr`**: "Open MR !{iid} covers {N} of {M} components. Missing: {list}. Consider extending the existing MR."
- **`fully_covered`**: "Open MR !{iid} covers all {M} components. Creating a new MR would be a duplicate."
- **`no_overlap`**: The MR is for a different set of components (likely a different RHOAI version). Proceed normally.

## Open Jira Ticket Coverage

The output also includes `open_jira_tickets` for each violation — open RHOAIENG, PSX, or OCPEXCEPT tickets with the `conforma-violation` label that match the violation rule. When present, show them alongside the MR coverage. This is informational (does not block exception creation) but prevents creating duplicate Jira tickets.

## Slack Thread Coverage

The output includes `open_slack_threads` for each violation (when `--require-slack true`) — Slack messages from the last 30 days that mention the violation rule code. Results are grouped by thread; the permalink points to the specific matching message.

Slack threads are informational only — they do not affect `coverage`, `next_steps`, or `status` fields. They show that someone is already discussing or working on the violation, which helps avoid duplicate effort.
