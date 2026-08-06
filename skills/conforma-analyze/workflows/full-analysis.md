## References (load these before executing)

No additional references needed.

---

# Full Analysis Workflow

## Workflow

When the user asks to show violations, analyze violations, fetch conforma reports, or analyze a conforma report URL:

### Handling user-provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), pass the full URL or the extracted release identifier (e.g. `rhoai-3.4`) as the query text to Step 0 (`init_conforma_run.py`). The release context pipeline (Step 2) will resolve it automatically from `context.yaml`. Do NOT pass `--releases` to the fetch script — all downstream steps read from `context.yaml`.

### Display-before-question rule (HARD REQUIREMENT)

**Whenever a step produces a `display` field AND a `user_question`, the agent MUST render the `display` content verbatim as markdown in the response text BEFORE calling AskQuestion.** Tool results are agent context and are NOT visible to the user — the user only sees text the agent writes in its response. If the agent calls AskQuestion without first rendering the `display` content, the user sees a question with no context. This is a hard failure.

The sequence is always: (1) render `display` as markdown → (2) call AskQuestion. Never combine these into the same tool-call batch — the display text must appear in the response before the question.

### AskQuestion rule

**Every AskQuestion call MUST use `question_text` and `question_options` from script JSON output verbatim.** Never compose question text in the agent — if a script does not output these fields, fix the script. This ensures questions are self-contained and readable in the Claude Code CLI permission dialog without requiring the user to expand collapsed output.

**Bash description rule**: Every Bash tool call MUST use the exact description string specified in each step (e.g. `"Check Conforma prerequisites: GitHub, GitLab, Jira, Slack auth"`). The description appears in the Claude Code CLI permission dialog before the command runs — it must be informative enough to understand without expanding collapsed output.

### Auto-continue on routine confirmations

Do not prompt the user for confirmation on:
1. **Optional prerequisite failures** (e.g. Slack auth) — show the prerequisites summary, then continue automatically.
2. **Release context resolution** — show the resolved release info, then continue automatically.

Still prompt for genuinely ambiguous situations (e.g. multiple candidate releases returned by `--list`).

### Steps

**Script path convention**: Every command below uses `~/.conforma/bin/conforma_run.sh` to resolve the aiops-infra repo root and dispatch to the target Python script. Do NOT use bare `python3` paths — always use the wrapper.

**Important**: Step 0 creates a `context.yaml` file in a timestamped run directory under `~/.conforma/` and sets it as the active run via a `.conforma-active` symlink. Step 1 persists prerequisite results (including Slack availability) to context.yaml. Step 2 enriches the context with release and environment data. All subsequent scripts auto-discover the active run directory and read `release`, `environment`, output paths, and intermediate results from `context.yaml`. **Do NOT pass `--release`, `--releases`, `--environment`, `--run-dir`, `--require-slack`, or output paths as CLI arguments** — the scripts resolve them automatically. Only pass arguments that represent behavioral choices not stored in context.yaml (e.g. `--format markdown`, `--dry-run`).

0. **Initialize conforma run (REQUIRED before any script)**: Run with Bash description: `"Initialize conforma run context for <extracted_release_text>"`:

```bash
[ -x ~/.conforma/bin/conforma_run.sh ] || { _R="${AIOPS_INFRA_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo $HOME/.local/share/aiops-infra)}"; mkdir -p ~/.conforma/bin; cp "$_R/scripts/conforma_run.sh.tpl" ~/.conforma/bin/conforma_run.sh; chmod +x ~/.conforma/bin/conforma_run.sh; }
~/.conforma/bin/conforma_run.sh scripts/init_conforma_run.py "<extracted_release_text>"
```

   This is the **only step where user input appears on the command line**. All subsequent steps use fixed commands that read parameters from context.yaml. The script creates a timestamped run directory under `~/.conforma/`, writes `aiops_infra_root` and `user_query` to `context.yaml`, and sets the `.conforma-active` symlink.

1. **Prerequisites check**: Run `~/.conforma/bin/conforma_run.sh scripts/verify_conforma_prerequisites.py --format json` with Bash description: `"Check Conforma prerequisites: GitHub, GitLab, Jira, Slack auth"`. Parse the JSON output object. If exit code is non-zero, **stop immediately** — render the `display` field directly (not in a code block) and do not proceed. Do NOT interpret, reformat, or summarize — the script output is self-explanatory. The user must fix failures before the workflow can continue.

   **Slack is optional.** If exit code is 0 and the JSON contains a `user_question` key: render the `display` field directly, then use AskQuestion with `user_question.question_text` and `user_question.question_options` verbatim. If the user chooses "No, set up Slack first", follow the `slack-auth` skill. Otherwise continue — Slack availability is automatically persisted to `steps.prerequisites.slack_available` in context.yaml via `update_step()` and auto-detected by downstream scripts (e.g. `violations_coverage.py`).

2. **Resolve release context**: Run with Bash description: `"Resolve release context"`. The script reads `user_query` from context.yaml automatically (written by Step 0). Environment is auto-detected from the query text by `extract_environment()` (parses "stage"/"prod" keywords, defaults to "prod"). The script enriches the existing context.yaml in merge mode (since Step 0 already created it).

   ```bash
   ~/.conforma/bin/conforma_run.sh scripts/resolve_release_context.py
   ```

   Parse the JSON output. Present the `confirmation_display` field **verbatim as markdown** (NOT in a code block) so that embedded links are clickable.

   Then act on the `status` field:
   - **`"resolved"`**: Use AskQuestion with `question_text` and `question_options` from the resolved JSON verbatim. On "Yes", proceed to step 3. The script has enriched the existing context.yaml with release and environment data — all downstream scripts auto-discover these.

     **Upcoming release date (HARD REQUIREMENT):** Check the `upcoming_release_date` field in the resolved JSON. If it is `null` or missing, the workflow **MUST NOT proceed**. Ask the user to provide the upcoming release date manually (YYYY-MM-DD format). Once provided, update `context.yaml` by running:
     ```bash
     ~/.conforma/bin/conforma_run.sh scripts/conforma_context_ops.py put resolve.upcoming_release_date "<YYYY-MM-DD>"
     ```
     Downstream steps will read it from `context.yaml` automatically.
   - **`"ambiguous"`**: Use AskQuestion with the numbered candidates from `candidates[]`. After the user selects, update `user_query` in context.yaml and re-run the resolve script:
     ```bash
     ~/.conforma/bin/conforma_run.sh scripts/conforma_context_ops.py put user_query "<selected_version_dir>"
     ~/.conforma/bin/conforma_run.sh scripts/resolve_release_context.py
     ```
   - **`"not_found"`** or **`"error"`**: Present the `confirmation_display` verbatim and **stop**. Do NOT attempt to guess or proceed without a resolved context.

   If the user did not mention any release and you cannot extract one from their query, use `--list` to show available versions and ask the user to pick:

   ```bash
   ~/.conforma/bin/conforma_run.sh scripts/resolve_release_context.py --list
   ```

3. **Check tooling health**: Before fetching reports, check the health of conforma infrastructure tools. Run the health check with Bash description: `"Check conforma-reporter workflow health"`:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-tooling-health/scripts/check_tooling_health.py
```

   The script reads release, environment, and output path from `context.yaml` automatically.

   Parse the JSON output and act on `overall_health`. For **all non-healthy states**, first render the `display` field from the JSON **as markdown** (not in a code block) — this shows a table with clickable links to the latest run and last success so the user can investigate before answering. Then act on the status:

   - **`"healthy"`** -- proceed silently to step 4 (fetch reports).
   - **`"unhealthy"` or `"error"`** -- render the `display` field as markdown, then use AskQuestion with `question_text` and `question_options` from the tooling health JSON verbatim. Only proceed to step 4 if the user confirms.
   - **`"in_progress"`** -- render the `display` field as markdown, then use AskQuestion with `question_text` and `question_options` from the tooling health JSON verbatim. If the user chooses to wait, monitor the run using `~/.conforma/bin/conforma_run.sh scripts/run_github_workflow.py monitor --repo-url https://github.com/red-hat-data-services/conforma-reporter --run-id RUN_ID --timeout 60 --poll-interval 60`, then re-run the tooling health check. If the run fails after waiting, fall back to the unhealthy prompt.
   - **`"no_runs"`** -- render the `display` field as markdown, warn ("No conforma-reporter runs found for this branch -- report may not exist") and proceed.

4. **Fetch reports**: Fetch CSVs into the active run directory. Use Bash description: `"Fetch Conforma violation CSV reports"`:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-report-fetch/scripts/fetch_csv_reports.py
```

   The script reads release, environment, output directory, and metadata file path from `context.yaml` automatically.

   **Do NOT pass `--releases`** for the standard single-release workflow — the script reads the release from `context.yaml` automatically. The `--releases` flag is ONLY for the rare cross-release comparison use case (when the user explicitly asks to compare multiple releases side by side):

```bash
# ONLY for cross-release comparison — never for the standard workflow:
~/.conforma/bin/conforma_run.sh skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases rhoai-2.25,rhoai-3.4
```

   To fetch ALL supported releases (rare — only for full-portfolio audits):

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-report-fetch/scripts/fetch_csv_reports.py --all
```

   The output directory will contain `{release}.csv` (violations) and `{release}-warnings.csv` (warnings) for each release. The `fetch-metadata.json` contains `source_path` and `created_at` per release — needed by downstream steps. Some in-development/EA branches may not have report CSVs yet. The fetch script reports failures per release -- this is expected and not a blocker. The parse step will process whatever CSVs were successfully fetched.

5. **Parse violations and warnings**: Parse the fetched CSVs into a structured YAML. Use Bash description: `"Parse Conforma violations and warnings"`. **Warnings CSVs are parsed by default** — any warning with an enforcement date within 21 days is included as a warning becoming a violation. The parse step also **enriches each component with its owning Jira Component** from the component-maturity catalog (requires VPN + GitLab auth). If the catalog is unreachable, the script fails hard — ensure VPN is active:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/parse_violations.py
```

   The script reads release, environment, reports directory, and output path from `context.yaml` automatically.

   To customize the enforcement threshold:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/parse_violations.py --upcoming-threshold-days 14
```

   For CI/testing only (no catalog enrichment):

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/parse_violations.py --no-catalog
```

6. **Analyze and save**: Use Bash description: `"Analyze Conforma violations"`. **Save the output to a file** — do NOT present the analysis in the chat (the TODO preview in step 9 shows the action items; the full analysis is in the resolution guide):

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/analyze_csv_report.py --format markdown
```

   The script reads reports directory, violations YAML, metadata file, release, and output path from `context.yaml` automatically. The only required CLI arg is `--format markdown` (default is `text`).

   The script automatically prepends a report header (source CSV URL + generation date) and a staleness warning (if the report is >3 days old).

   The analysis covers:
   - Totals and breakdown by violation code (count, %, affected components)
   - Root cause extraction (untrusted task names, signing keys)
   - Per-component violation patterns (code combinations)
   - **Warnings becoming violations** — policies nearing their enforcement date (within 21 days by default)
   - Prioritized remediation recommendations with resolution %
   - **Jira Component ownership** — component names are annotated with their owning Jira Component (e.g. `odh-vllm-rhel9 (vLLM)`)

   **No chat output from this step.** The analysis is saved to the run directory and included in the full resolution guide.

7. **Cross-reference with exceptions, open Merge Requests, open Jira, and Slack**: Use Bash description: `"Cross-reference violations with exceptions, Merge Requests, Jira, Slack"`. After the analysis, **always** run the violations coverage check. This produces a unified table showing each violation alongside its existing exception status, open Merge Requests (classified as *exception* or *remedy*), open Jira tickets, Slack threads (if available), and recommended next steps — which is the **primary output** the user expects when asking to "analyze" a report.

   **Target version checking (HARDCODED — always performed)**: Every Jira ticket found is automatically classified by its `fixVersion` relevance to the currently-analyzed release. Tickets are annotated as:
   - (no annotation) — fixVersion targets the currently analyzed release
   - `⚠️ targets {version}` — fixVersion is set but targets a different/future release (fix exists but won't land in the analyzed release)
   - `⚠️ no fixVersion` — no fixVersion set (unclear which release the fix targets)

   This ensures the user can distinguish between "this violation has a fix landing in the current release" vs "there's a Jira for this but it targets a future release and is NOT a solution for the current report".

   All required auth (GitLab, Jira) was already verified in step 1. Slack availability is auto-detected from `steps.prerequisites.slack_available` in context.yaml (persisted by step 1) — no manual `--require-slack` flag needed.

   The script reads violations YAML, CSV path, release, environment, clone directory, metadata file, and output path from `context.yaml` automatically. The script manages the `~/.conforma/konflux-release-data` clone (fresh fetch + reset). It enforces the repo clone policy: it will `git fetch` any existing clone and abort if the remote is unreachable (e.g. VPN down). Never silently use stale data.

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/violations_coverage.py
```

   The coverage table is the primary deliverable and is included in the TODO preview (step 9). If needed separately, read `coverage.json` from the run directory and extract the `markdown_table` field — render it directly as markdown (not in a code block).

8. **Resolution Guide**: The resolution guide is generated deterministically by script and saved to a file. Only the **TODO preview** is presented in the chat — the full guide is submitted to GitHub. See step 9 for the generation command and presentation rules.

9. **Generate the resolution guide**: Use Bash description: `"Generate Conforma Status and Resolution Guide"`. Run the resolution guide generator on the intermediate outputs from steps 3-7. This produces a unified markdown file combining tooling health, coverage, per-violation resolution guidance (from [`skills/references/violation-catalog.yaml`](../../references/violation-catalog.yaml) with fallback references for uncataloged violations), warnings, and statistical analysis:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/generate_resolution_guide.py
```

   The script reads all inputs (violations YAML, coverage JSON, reports directory, release, metadata file, tooling health JSON, analysis output file) and output paths (guide file, TODO file) from `context.yaml` automatically.

   ---

   **⛔ HARD FAILURE RULES FOR STEP 9 — READ THESE BEFORE PROCEEDING:**

   **RULE 1 — TODO PREVIEW ONLY (no full guide in chat):**
   The agent MUST read `conforma-todo.md` from the active run directory (printed by the script) with the Read tool and then **copy its ENTIRE content verbatim into the response text**. This file contains the metadata header (context confirmation) and the TODO section with summary preamble and all TODO #N subsections. The agent MUST NOT:
   - Paste the full resolution guide (`conforma-resolution-guide.md`) into the chat
   - Paste the full analysis output (`conforma-analysis.md`) into the chat
   - Summarize, paraphrase, or abbreviate the TODO content
   - Add its own commentary between sections
   - Create its own tables or summaries instead of the script-generated content

   The full resolution guide and analysis output are saved to the run directory — the user can open them directly for the complete reference.

   Do NOT rely on the Read tool result alone — tool results are agent context and may not be displayed to the user. The TODO content must appear as literal text in the agent's response. Render as markdown (not in a code block).

   **RULE 2 — ORDERING (present THEN ask):**
   The TODO content must appear in the agent's response text BEFORE the AskQuestion call for step 10. Never call AskQuestion in the same tool-call batch that reads the file. The sequence is: (a) read TODO file → (b) paste its content into response → (c) THEN in a SEPARATE subsequent turn, ask about submission. This ensures the user sees the action items before being asked to submit.

   **RULE 3 — MUST PROCEED TO STEP 10:**
   After rendering the TODO, the agent MUST immediately proceed to step 10 (submission) in the same response — do NOT stop, wait for user input, or end the turn after presenting the TODO. The workflow is not complete until the user has been asked about submission. Stopping after the TODO without proceeding to step 10 is a hard failure.

   **Violating any of these rules is a hard failure regardless of model size, context window, or token budget.**

   ---

10. **Submit to GitHub** *(requires user confirmation — MUST be a separate turn after step 9)*: After the TODO has been rendered in the previous response, run the submit script in dry-run mode with Bash description: `"Preview submission of resolution guide (dry run)"`, then use AskQuestion with `question_text` and `question_options` from the dry-run JSON verbatim. Do NOT auto-submit. Only run without `--dry-run` if the user confirms.

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/submit_resolution_guide.py --dry-run
```

   The script reads guide file path, release, environment, and metadata file from `context.yaml` automatically.

   Use the `question_text` and `question_options` from the dry-run JSON output for AskQuestion verbatim. If the user declines, render the `skip_display` field from the dry-run JSON verbatim as markdown (it contains a clickable link to the local guide file). If the user confirms, run without `--dry-run`:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/submit_resolution_guide.py
```

   The script commits directly to the release branch. If submission fails (e.g. auth issue, branch protection), report the error but do not treat it as a workflow failure — the local guide file is still the primary deliverable.

