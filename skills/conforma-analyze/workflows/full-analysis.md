## References (load these before executing)

No additional references needed.

---

# Full Analysis Workflow

## Workflow

When the user asks to show violations, analyze violations, fetch conforma reports, or analyze a conforma report URL:

### Handling user-provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), extract the release branch from the URL path (the segment after `/blob/` and before the next `/`) and pass it to the fetch script via `--releases`. Example: from the URL above, extract `rhoai-3.4` and run with `--releases rhoai-3.4`.

### AskQuestion rule

**Every AskQuestion call MUST use `question_text` and `question_options` from script JSON output verbatim.** Never compose question text in the agent — if a script does not output these fields, fix the script. This ensures questions are self-contained and readable in the Claude Code CLI permission dialog without requiring the user to expand collapsed output.

**Bash description rule**: Every Bash tool call MUST use the exact description string specified in each step (e.g. `"Check Conforma prerequisites: GitHub, GitLab, Jira, Slack auth"`). The description appears in the Claude Code CLI permission dialog before the command runs — it must be informative enough to understand without expanding collapsed output.

### Steps

**Important**: Steps 1–10 use shared variables set in step 2: `$RUNDIR` (timestamped run directory), `$RELEASE` (release branch), and `$ENVIRONMENT` (`stage` or `prod`). All intermediate outputs live in `$RUNDIR`.

1. **Prerequisites check**: Run `python3 scripts/verify_conforma_prerequisites.py --format json` with Bash description: `"Check Conforma prerequisites: GitHub, GitLab, Jira, Slack auth"`. Parse the JSON output object. If exit code is non-zero, **stop immediately** — render the `display` field directly (not in a code block) and do not proceed. Do NOT interpret, reformat, or summarize — the script output is self-explanatory. The user must fix failures before the workflow can continue.

   **Slack is optional.** If exit code is 0 and the JSON contains a `user_question` key: render the `display` field directly, then use AskQuestion with `user_question.question_text` and `user_question.question_options` verbatim. If the user chooses "No, set up Slack first", follow the `slack-auth` skill. Otherwise continue — pass `--require-slack false` to `violations_coverage.py` in step 6.

2. **Resolve release context**: Run the context resolution script with Bash description: `"Resolve release context for <extracted_release_text>"`. Extract the release identifier from the user's query (e.g., "rhoai-3.5-ea.1", "3.4", "3.5 ea 1") and pass it to the script. If the user mentions an environment ("stage" or "prod"), **always pass it via `--environment`** — do not rely on keyword extraction from the query string. If the user provided a GitHub URL, extract the branch from the `/blob/<branch>/` segment and use that as the query. **Always pass `--output-dir ~/.conforma`** — the script creates a timestamped run directory, saves `context.yaml` inside it, and includes the `rundir` path in its JSON output.

   ```bash
   # Without explicit environment (defaults to prod):
   python3 scripts/resolve_release_context.py --query "<extracted_release_text>" --output-dir ~/.conforma

   # With explicit environment (stage or prod):
   python3 scripts/resolve_release_context.py --query "<extracted_release_text>" --environment stage --output-dir ~/.conforma
   ```

   Parse the JSON output. Present the `confirmation_display` field **verbatim as markdown** (NOT in a code block) so that embedded links are clickable.

   Then act on the `status` field:
   - **`"resolved"`**: Use AskQuestion with `question_text` and `question_options` from the resolved JSON verbatim. On "Yes", set: `RELEASE=<.release>`, `KONFLUX_APP=<.konflux_app>`, `RUNDIR=<.rundir>`, `ENVIRONMENT=<.environment>`. The script has already created the run directory and saved `context.yaml` inside it.

     **Upcoming release date (HARD REQUIREMENT):** Check the `upcoming_release_date` field in the resolved JSON. If it is `null` or missing, the workflow **MUST NOT proceed**. Ask the user to provide the upcoming release date manually (YYYY-MM-DD format). Once provided, update `context.yaml` by running:
     ```bash
     python3 scripts/conforma_context_ops.py put resolve.upcoming_release_date "<YYYY-MM-DD>" --run-dir "$RUNDIR"
     ```
     Downstream steps will read it from `context.yaml` automatically.
   - **`"ambiguous"`**: Use AskQuestion with the numbered candidates from `candidates[]`. After the user selects, re-run with `--query "<selected_version_dir>" --output-dir ~/.conforma` to get a "resolved" result.
   - **`"not_found"`** or **`"error"`**: Present the `confirmation_display` verbatim and **stop**. Do NOT attempt to guess or proceed without a resolved context. No run directory is created for non-resolved statuses.

   If the user did not mention any release and you cannot extract one from their query, use `--list` to show available versions and ask the user to pick:

   ```bash
   python3 scripts/resolve_release_context.py --list
   ```

3. **Check tooling health**: Before fetching reports, check the health of conforma infrastructure tools. The `$RUNDIR` was already created by step 2. Run the health check with Bash description: `"Check conforma-reporter workflow health for $RELEASE"`. **Always pass `--environment`** with the environment from step 2 (`stage` or `prod`):

```bash
python3 skills/conforma-tooling-health/scripts/check_tooling_health.py \
  --release "$RELEASE" \
  --environment "$ENVIRONMENT" \
  --output "$RUNDIR/tooling-health.json"
```

   Parse the JSON output and act on `overall_health`. For **all non-healthy states**, first render the `display` field from the JSON **as markdown** (not in a code block) — this shows a table with clickable links to the latest run and last success so the user can investigate before answering. Then act on the status:

   - **`"healthy"`** -- proceed silently to step 4 (fetch reports).
   - **`"unhealthy"` or `"error"`** -- render the `display` field as markdown, then use AskQuestion with `question_text` and `question_options` from the tooling health JSON verbatim. Only proceed to step 4 if the user confirms.
   - **`"in_progress"`** -- render the `display` field as markdown, then use AskQuestion with `question_text` and `question_options` from the tooling health JSON verbatim. If the user chooses to wait, monitor the run using `python3 scripts/run_github_workflow.py monitor --repo-url https://github.com/red-hat-data-services/conforma-reporter --run-id RUN_ID --timeout 60 --poll-interval 60`, then re-run `check_tooling_health.py` to refresh status. If the run fails after waiting, fall back to the unhealthy prompt.
   - **`"no_runs"`** -- render the `display` field as markdown, warn ("No conforma-reporter runs found for this branch -- report may not exist") and proceed.

   The `$RUNDIR` variable from step 2 is used by ALL subsequent steps — never change it mid-workflow.

4. **Fetch reports**: Fetch CSVs into the run directory created in step 3. **Always pass `--releases $RELEASE`** and **`--environment $ENVIRONMENT`** to scope the fetch to the target release and environment from step 2. Use Bash description: `"Fetch Conforma violation CSV reports for $RELEASE"`:

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases "$RELEASE" \
  --environment "$ENVIRONMENT" \
  --output-dir "$RUNDIR" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   To fetch multiple specific releases (e.g. for cross-release comparison):

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases rhoai-2.25,rhoai-3.4 \
  --environment "$ENVIRONMENT" \
  --output-dir "$RUNDIR" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   To fetch ALL supported releases (rare — only for full-portfolio audits):

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --all \
  --environment "$ENVIRONMENT" \
  --output-dir "$RUNDIR" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   The output directory will contain `{release}.csv` (violations) and `{release}-warnings.csv` (warnings) for each release. The `fetch-metadata.json` contains `source_path` and `created_at` per release — needed by steps 8-9. Some in-development/EA branches may not have report CSVs yet. The fetch script reports failures per release -- this is expected and not a blocker. The parse step will process whatever CSVs were successfully fetched.

5. **Parse violations and warnings**: Run on the **same timestamped directory from step 3** to produce the structured YAML. Use Bash description: `"Parse Conforma violations and warnings for $RELEASE"`. **Always pass `--release $RELEASE`** and **`--environment $ENVIRONMENT`** to ensure only the target release's CSVs are parsed and correct report URLs are generated. **Warnings CSVs are parsed by default** — any warning with an enforcement date within 21 days is included as a warning becoming a violation. The parse step also **enriches each component with its owning Jira Component** from the component-maturity catalog (requires VPN + GitLab auth). If the catalog is unreachable, the script fails hard — ensure VPN is active:

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir ~/.conforma/20260604-123000 \
  --release "$RELEASE" \
  --environment "$ENVIRONMENT" \
  --output ~/.conforma/20260604-123000/violations.yaml
```

   To customize the enforcement threshold:

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir ~/.conforma/20260604-123000 \
  --environment "$ENVIRONMENT" \
  --output ~/.conforma/20260604-123000/violations.yaml \
  --upcoming-threshold-days 14
```

   For CI/testing only (no catalog enrichment):

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir ~/.conforma/20260604-123000 \
  --environment "$ENVIRONMENT" \
  --output ~/.conforma/20260604-123000/violations.yaml \
  --no-catalog
```

6. **Analyze and save**: Use Bash description: `"Analyze Conforma violations for $RELEASE"`. Run the CSV analysis script on the **run directory created by step 3** (printed in its stderr output). Never use `~/.conforma/latest` — always use the specific timestamped directory to avoid analyzing stale data. Pass `--violations-yaml` for ownership, `--metadata-file` and `--release` for the report header and staleness check. **Save the output to a file** — do NOT present the analysis in the chat (the executive summary in step 9 covers the key data; the full analysis is linked as a detailed document):

```bash
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --reports-dir "$RUNDIR" \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --metadata-file "$RUNDIR/fetch-metadata.json" \
  --release "$RELEASE" \
  --format markdown \
  --output "$RUNDIR/conforma-analysis.md"
```

   The script automatically prepends a report header (source CSV URL + generation date) and a staleness warning (if the report is >3 days old) when `--metadata-file` is provided.

   The analysis covers:
   - Totals and breakdown by violation code (count, %, affected components)
   - Root cause extraction (untrusted task names, signing keys)
   - Per-component violation patterns (code combinations)
   - **Warnings becoming violations** — policies nearing their enforcement date (within 21 days by default)
   - Prioritized remediation recommendations with resolution %
   - **Jira Component ownership** — when `--violations-yaml` is provided, component names are annotated with their owning Jira Component (e.g. `odh-vllm-rhel9 (vLLM)`)

   **No chat output from this step.** The analysis is saved to `$RUNDIR/conforma-analysis.md` and linked in the executive summary (step 9).

7. **Cross-reference with exceptions, open Merge Requests, open Jira, and Slack**: Use Bash description: `"Cross-reference violations with exceptions, Merge Requests, Jira, Slack for $RELEASE"`. After the analysis, **always** run the violations coverage check. This produces a unified table showing each violation alongside its existing exception status, open Merge Requests (classified as *exception* or *remedy*), open Jira tickets, Slack threads (if available), and recommended next steps — which is the **primary output** the user expects when asking to "analyze" a report.

   **Target version checking (HARDCODED — always performed)**: Every Jira ticket found is automatically classified by its `fixVersion` relevance to the currently-analyzed release. Tickets are annotated as:
   - (no annotation) — fixVersion targets the currently analyzed release
   - `⚠️ targets {version}` — fixVersion is set but targets a different/future release (fix exists but won't land in the analyzed release)
   - `⚠️ no fixVersion` — no fixVersion set (unclear which release the fix targets)

   This ensures the user can distinguish between "this violation has a fix landing in the current release" vs "there's a Jira for this but it targets a future release and is NOT a solution for the current report".

   All required auth (GitLab, Jira) was already verified in step 1. Slack is optional — if not configured, pass `--require-slack false`.

   The script manages the `~/.conforma/konflux-release-data` clone (fresh fetch + reset). It enforces the repo clone policy: it will `git fetch` any existing `--clone-dir` and abort if the remote is unreachable (e.g. VPN down). Never silently use stale data.

   **Save the output to a JSON file** for use by the resolution guide generator (step 8):

```bash
# With Slack (when configured):
python3 skills/conforma-analyze/scripts/violations_coverage.py \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --csv "$RUNDIR/$RELEASE.csv" \
  --clone-dir ~/.conforma/konflux-release-data \
  --environment "$ENVIRONMENT" \
  --release "$RELEASE" \
  --metadata-file "$RUNDIR/fetch-metadata.json" \
  --output "$RUNDIR/coverage.json"

# Without Slack (when not configured):
python3 skills/conforma-analyze/scripts/violations_coverage.py \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --csv "$RUNDIR/$RELEASE.csv" \
  --clone-dir ~/.conforma/konflux-release-data \
  --environment "$ENVIRONMENT" \
  --release "$RELEASE" \
  --require-slack false \
  --metadata-file "$RUNDIR/fetch-metadata.json" \
  --output "$RUNDIR/coverage.json"
```

   Pass the violations YAML from step 4 as input. The coverage table is the primary deliverable; the statistical breakdown from step 5 can be presented as supplementary detail below it.

   The coverage table is included in the executive summary (step 9). If needed separately, use the Read tool on `$RUNDIR/coverage.json` and extract the `markdown_table` field — render it directly as markdown (not in a code block).

8. **Resolution Guide**: The resolution guide is generated deterministically by script and saved to a file. Only the **executive summary** is presented in the chat — the full guide is linked as a detailed document. See step 9 for the generation command and presentation rules.

9. **Generate the resolution guide**: Use Bash description: `"Generate Conforma Status and Resolution Guide for $RELEASE"`. Run the resolution guide generator on the intermediate outputs from steps 3-7. This produces a unified markdown file combining tooling health, coverage, per-violation resolution guidance (from [`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml) with fallback references for uncataloged violations), warnings, and statistical analysis. **Pass `--executive-summary-file`** to also generate a compact summary for chat display, and **`--analysis-output-file`** to link the analysis output from step 6:

```bash
python3 skills/conforma-analyze/scripts/generate_resolution_guide.py \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --coverage-json "$RUNDIR/coverage.json" \
  --reports-dir "$RUNDIR" \
  --release "$RELEASE" \
  --metadata-file "$RUNDIR/fetch-metadata.json" \
  --tooling-health-json "$RUNDIR/tooling-health.json" \
  --output "$RUNDIR/conforma-status-and-resolution-guide.md" \
  --executive-summary-file "$RUNDIR/executive-summary.md" \
  --analysis-output-file "$RUNDIR/conforma-analysis.md"
```

   ---

   **⛔ HARD FAILURE RULES FOR STEP 9 — READ THESE BEFORE PROCEEDING:**

   **RULE 1 — EXECUTIVE SUMMARY ONLY (no full guide in chat):**
   The agent MUST read `$RUNDIR/executive-summary.md` with the Read tool and then **copy its ENTIRE content verbatim into the response text**. This file contains the metadata header, tooling health warning, key takeaways, summary metrics, and links to the detailed documents. The agent MUST NOT:
   - Paste the full resolution guide (`conforma-status-and-resolution-guide.md`) into the chat
   - Paste the full analysis output (`conforma-analysis.md`) into the chat
   - Summarize, paraphrase, or abbreviate the executive summary content
   - Add its own commentary between sections of the executive summary
   - Create its own tables or summaries instead of the script-generated content

   The executive summary file includes a **Detailed Documents** section with file paths to the full resolution guide and analysis output. These are the user's entry points to the detailed content — they can click to open the files.

   Do NOT rely on the Read tool result alone — tool results are agent context and may not be displayed to the user. The executive summary content must appear as literal text in the agent's response. Render as markdown (not in a code block).

   **RULE 2 — ORDERING (present THEN ask):**
   The executive summary content must appear in the agent's response text BEFORE the AskQuestion call for step 10. Never call AskQuestion in the same tool-call batch that reads the file. The sequence is: (a) read executive summary file → (b) paste its content into response → (c) THEN in a SEPARATE subsequent turn, ask about submission. This ensures the user sees the summary before being asked to act on it.

   **RULE 3 — MUST PROCEED TO STEP 10:**
   After rendering the executive summary, the agent MUST immediately proceed to step 10 (submission) in the same response — do NOT stop, wait for user input, or end the turn after presenting the summary. The workflow is not complete until the user has been asked about submission. Stopping after the executive summary without proceeding to step 10 is a hard failure.

   **Violating any of these rules is a hard failure regardless of model size, context window, or token budget.**

   ---

10. **Submit to GitHub** *(requires user confirmation — MUST be a separate turn after step 9)*: After the executive summary has been rendered in the previous response, run the submit script in dry-run mode with Bash description: `"Preview submission of resolution guide for $RELEASE (dry run)"`, then use AskQuestion with `question_text` and `question_options` from the dry-run JSON verbatim. Do NOT auto-submit. Only run without `--dry-run` if the user confirms.

```bash
python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \
  --guide-file "$RUNDIR/conforma-status-and-resolution-guide.md" \
  --release "$RELEASE" \
  --environment "$ENVIRONMENT" \
  --dry-run
```

   Use the `question_text` and `question_options` from the dry-run JSON output for AskQuestion verbatim. If the user confirms, run without `--dry-run` and pass `--metadata-file` so the script can automatically clean up any legacy guide from the old `prod/release_day/` location and from the repo root:

```bash
python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \
  --guide-file "$RUNDIR/conforma-status-and-resolution-guide.md" \
  --release "$RELEASE" \
  --environment "$ENVIRONMENT" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   The script commits directly to the release branch. If submission fails (e.g. auth issue, branch protection), report the error but do not treat it as a workflow failure — the local guide file is still the primary deliverable.

