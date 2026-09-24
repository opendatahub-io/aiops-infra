## References (load these before executing)

No additional references needed.

---

# Full Analysis Workflow

## Workflow

When the user asks to show violations, analyze violations, fetch conforma reports, or analyze a conforma report URL:

### Handling user-provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), pass the complete user query unchanged to Step 0 (`init_conforma_run.py`). The deterministic release parser extracts the release from prose or a URL and the release context pipeline (Step 2) resolves it automatically from `context.yaml`. Do NOT pass `--releases` to the fetch script — all downstream steps read from `context.yaml`.

### Display-before-question rule (HARD REQUIREMENT)

**Whenever a step produces a `display` field AND a `user_question`, the agent MUST render the `display` content verbatim as markdown in the final user-visible response BEFORE calling AskQuestion.** Intermediate commentary and tool results may be collapsed or hidden by the client, so they are not sufficient. The script also makes confirmation questions self-contained where possible; the agent must still render the display explicitly. If the agent calls AskQuestion without first rendering the `display` content in a user-visible response, the user sees a question with no context. This is a hard failure.

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

**Filesystem permission prerequisite**: Before Step 0, ensure the command execution environment can write to `~/.conforma/` as well as the repository workspace. A deterministic script does not bypass the agent sandbox; if `~/.conforma/` is outside the active writable roots, request the platform's approved custom writable-root or elevated execution for the complete workflow. Do not run Step 0 in a restricted sandbox.

### Long-running steps (HARD REQUIREMENT)

Some steps exceed the agent's ~30s foreground command cap (fetching CSVs, and the `ec validate` coverage check most notably). **Do NOT run them as plain foreground commands** — they will time out — and **do NOT improvise a `nohup`/`sleep`/`ps` polling loop** — repeated identical poll commands trigger the harness "repeated identical call" loop detector and the task is aborted.

Instead, route them through the deterministic long-task runner, which owns both the background launch and the wait loop:

```bash
~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch <step> <script-path>
```

`launch` returns JSON with a `next_command` field. **Run that `next_command` verbatim.** It is a `wait` call that blocks up to ~25s, returns `status` (`running` / `done` / `failed`) plus a new `next_command` whose `--seq` has incremented. Repeat the returned `next_command` verbatim — never editing it — until `status` is `done` or `failed`. The incrementing `--seq` guarantees no two wait calls are byte-identical, so the loop detector cannot fire no matter how long the step runs.

State is persisted to `<run_dir>/<step>.state.json`, `<run_dir>/<step>.log`, and `<run_dir>/<step>.exit`, so a restarted agent can resume from the files. On `failed`, read `<run_dir>/<step>.log` and report the error before continuing. This mechanism is defined in `scripts/run_long_task.py` and applies to any conforma skill.

0. **Initialize conforma run (REQUIRED before any script)**: Run with Bash description: `"Initialize conforma run context"`:

```bash
[ -x ~/.conforma/bin/conforma_run.sh ] || { _R="${AIOPS_INFRA_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo $HOME/.local/share/aiops-infra)}"; mkdir -p ~/.conforma/bin; cp "$_R/scripts/conforma_run.sh.tpl" ~/.conforma/bin/conforma_run.sh; chmod +x ~/.conforma/bin/conforma_run.sh; }
~/.conforma/bin/conforma_run.sh scripts/init_conforma_run.py "<user_query>"
```

   This is the **only step where user input appears on the command line**. Pass the complete user query unchanged; the deterministic release parser extracts and normalizes any release embedded in prose. All subsequent steps use fixed commands that read parameters from context.yaml. The script creates a timestamped run directory under `~/.conforma/`, writes `aiops_infra_root` and `user_query` to `context.yaml`, and sets the `.conforma-active` symlink.

1. **Prerequisites check**: Run `~/.conforma/bin/conforma_run.sh scripts/verify_conforma_prerequisites.py --format json` with Bash description: `"Check Conforma prerequisites: GitHub, GitLab, Jira, Slack auth"`. Parse the JSON output object.

   If the command exits non-zero, this is a required presentation sequence, not a plain failure message:

   1. Render the JSON `display` field directly as markdown, verbatim and in full. This includes the exact remediation instructions produced by the prerequisite script, including credential URLs and the designated environment-file path. Do not replace it with a paraphrase such as “fix authentication”.
   2. After the display, report the exact failing check and error from the JSON `checks` field.
   3. Stop the workflow and ask the user to choose among the three Script Failure Policy options. Never proceed with a partial report.

   Do not interpret, reformat, or summarize the `display` field. The user must fix failures before the workflow can continue.

   **Slack is optional.** If exit code is 0 and the JSON contains a `user_question` key: render the `display` field directly, then use AskQuestion with `user_question.question_text` and `user_question.question_options` verbatim. If the user chooses "No, set up Slack first", follow the `slack-auth` skill. Otherwise continue — Slack availability is persisted to `steps.prerequisites.slack_available` in context.yaml for explicit opt-in coverage runs.

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

4. **Fetch reports** *(long-running step)*: Fetch CSVs into the active run directory. **This step can take several minutes** and exceeds the ~30s foreground command cap, so it MUST run through the long-task runner (see the "Long-running steps" rule below) — do NOT run it as a plain foreground command, and do NOT improvise a `nohup`/`sleep`/`ps` polling loop.

   ```bash
   # 1. Launch the fetch in the background (Bash description: "Fetch Conforma violation CSV reports"):
   ~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch fetch skills/conforma-report-fetch/scripts/fetch_csv_reports.py
   ```

   Then run the **exact `next_command` string from the JSON output** (a `wait` call). Each round blocks up to ~25s and returns `status` plus a new `next_command` whose `--seq` has incremented. Repeat the returned `next_command` verbatim until `status` is `done` or `failed`:

   ```bash
   # 2. Repeat the returned next_command verbatim until status becomes "done":
   ~/.conforma/bin/conforma_run.sh scripts/run_long_task.py wait fetch --seq 1 --timeout 25
   ```

   If `status` is `failed`, read `<run_dir>/fetch.log` and report the error before continuing.

    The script reads release, environment, output directory, and metadata file path from `context.yaml` automatically.

   **Do NOT pass `--releases`** for the standard single-release workflow — the script reads the release from `context.yaml` automatically. The `--releases` flag is ONLY for the rare cross-release comparison use case (when the user explicitly asks to compare multiple releases side by side):

```bash
# ONLY for cross-release comparison — never for the standard workflow:
# (long-running: launch + repeat next_command, as above)
~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch fetch skills/conforma-report-fetch/scripts/fetch_csv_reports.py -- --releases rhoai-2.25,rhoai-3.4
```

   To fetch ALL supported releases (rare — only for full-portfolio audits). Use the `--all` target arg (note the `--` separator before the target) and a distinct step name so it does not collide with a standard `fetch`:

```bash
~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch fetch-all skills/conforma-report-fetch/scripts/fetch_csv_reports.py -- --all
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

6. **Analyze and save**: Use Bash description: `"Analyze Conforma violations"`. **Save the output to a file** — do NOT present the analysis in the chat (the complete TODO/DONE preview in step 10 shows the resolution status; the full analysis is in the resolution guide):

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

7. **Cross-reference with exceptions, open Merge Requests, open Jira, and Slack**: Use Bash description: `"Cross-reference violations with exceptions, Merge Requests, Jira, Slack"`. After the analysis, run the exception and cross-reference coverage check. This produces a unified table showing each violation alongside its existing exception status, open Merge Requests (classified as *exception* or *remedy*), open Jira tickets, Slack threads (if available), and recommended next steps — which is the **primary output** the user expects when asking to "analyze" a report. The expensive current-policy Conforma engine (`ec`) coverage comparison is opt-in and is not performed by the standard workflow.

   **Target version checking (HARDCODED — always performed)**: Every Jira ticket found is automatically classified by its `fixVersion` relevance to the currently-analyzed release. Tickets are annotated as:
   - (no annotation) — fixVersion targets the currently analyzed release
   - `⚠️ targets {version}` — fixVersion is set but targets a different/future release (fix exists but won't land in the analyzed release)
   - `⚠️ no fixVersion` — no fixVersion set (unclear which release the fix targets)

   This ensures the user can distinguish between "this violation has a fix landing in the current release" vs "there's a Jira for this but it targets a future release and is NOT a solution for the current report".

   All required auth (GitLab, Jira) was already verified in step 1. Slack coverage is disabled by default. The coverage script retains the opt-in `--require-slack true` flag for runs that explicitly request Slack cross-referencing.

   The script reads violations YAML, CSV path, release, environment, clone directory, metadata file, and output path from `context.yaml` automatically. The script manages the `~/.conforma/konflux-release-data` clone (fresh fetch + reset). It enforces the repo clone policy: it will `git fetch` any existing clone and abort if the remote is unreachable (e.g. VPN down). Never silently use stale data.

    The default coverage check uses the existing policy exception gate and does not invoke the current-policy `ec validate` comparison. To run that comparison, only when the user explicitly requests Conforma engine coverage, add `--run-ec-validation` to the target script command; that mode can take several minutes and MUST use the long-task runner (see the "Long-running steps" rule below) — do NOT run it as a plain foreground command, and do NOT improvise a `nohup`/`sleep`/`ps` polling loop.

    ```bash
    # 1. Launch the coverage check in the background (Bash description: "Cross-reference violations with exceptions, Merge Requests, Jira, Slack"):
    ~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch coverage skills/conforma-analyze/scripts/violations_coverage.py
    ```

    Then run the **exact `next_command` string from the JSON output**. Each round blocks up to ~25s and returns `status` plus a new `next_command` whose `--seq` has incremented — run the returned command verbatim, and **do NOT stop or change it**, until `status` is `done` or `failed`. The incrementing `--seq` is what keeps this from tripping a harness "repeated identical command" loop detector:

    ```bash
    # 2. Repeat the returned next_command verbatim until status becomes "done":
    ~/.conforma/bin/conforma_run.sh scripts/run_long_task.py wait coverage --seq 1 --timeout 25
    ```

    If `status` is `failed`, read `<run_dir>/coverage.log` and report the error before continuing.

    The coverage table is the primary deliverable and is included in the complete TODO/DONE preview (step 11). If needed separately, read `coverage.json` from the run directory and extract the `markdown_table` field — render it directly as markdown (not in a code block).

8. **Plan independent Conforma Jira labelling**: Use Bash description: `"Plan independent Conforma Jira labelling"`. This action is independent of ticket creation and Jira sync. It discovers the currently available Conforma-related tickets, plans additive `conforma` and `conforma-violation` labels, and writes `jira_labelling.json` plus `steps.jira_labelling` to the run context. It is read-only until the user confirms the exact `user_question` emitted by the script.

```bash
~/.conforma/bin/conforma_run.sh scripts/conforma_jira_ticket_ops.py label-conforma-tickets
```

   Render the script's `display` field. If the result contains `user_question`, relay its `question_text` and `question_options` verbatim. When no `user_question` is present, there are no label changes to confirm; continue with the remaining analysis. If the user confirms, run the apply command with Bash description: `"Apply confirmed Conforma Jira labels"`:

```bash
~/.conforma/bin/conforma_run.sh scripts/conforma_jira_ticket_ops.py label-conforma-tickets --apply
```

   If the user declines, continue with the remaining analysis. Label planning and application errors must be reported independently and must not prevent the Jira ticket step from running.

9. **Create or update Jira tickets for Conforma violations**: Use Bash description: `"Create or update Jira tickets for Conforma violations"`. After the independent labelling action, run the Jira ticket step. This performs label-first discovery of existing Jira tickets across the discovery projects, self-heals missing labels, and matches tickets to uncovered violations by violation code + component. For each uncovered violation with no open ticket it either **creates** a pre-filled Jira ticket (TargetVersion, Jira component, team) or records a **Create** pre-fill URL. The result is written to `jira_sync.json` in the run directory, which the resolution-guide step (step 11) reads to surface Jira tickets in the TODO tables, the components table, and the per-violation Jira blocks.

```bash
~/.conforma/bin/conforma_run.sh scripts/conforma_jira_ticket_ops.py create-jiras-for-conforma-violations
```

   The script reads release, environment, coverage violations, and output path from `context.yaml` automatically. To run discovery without any Jira writes (creates are planned but not written and `jira_sync.json` is not written, so the guide falls back to the pre-sync rendering), add `--dry-run`.

10. **Resolution Guide**: The resolution guide is generated deterministically by script and saved to a file. The complete **TODO and DONE preview** is presented in the chat — the full guide is submitted to GitHub. See step 11 for the generation command and presentation rules.

11. **Generate the resolution guide**: Use Bash description: `"Generate Conforma Status and Resolution Guide"`. Run the resolution guide generator on the intermediate outputs from steps 3-9. This produces a unified markdown file combining tooling health, coverage, per-violation resolution guidance (from [`skills/references/violation-catalog.yaml`](../../references/violation-catalog.yaml) with fallback references for uncataloged violations), warnings, and statistical analysis:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/generate_resolution_guide.py
```

   The script reads all inputs (violations YAML, coverage JSON, reports directory, release, metadata file, tooling health JSON, analysis output file) and output paths (guide file, TODO file) from `context.yaml` automatically.

   ---

   **⛔ HARD FAILURE RULES FOR STEP 11 — READ THESE BEFORE PROCEEDING:**

   **RULE 1 — COMPLETE TODO/DONE PREVIEW (no full guide in chat):**
   The agent MUST run the deterministic presentation command below and relay the content between `BEGIN_VERBATIM_TODO_AND_DONE` and `END_VERBATIM_TODO_AND_DONE` **verbatim into the response text**. The presentation script validates every stable section marker, both status groups, independent numbering, complete section inventory, and the source-identity accounting gate before emitting anything. It also emits the mandatory submission question between `BEGIN_SUBMISSION_QUESTION` and `END_SUBMISSION_QUESTION`. The agent MUST relay that question and its options verbatim after the complete report block. The agent MUST NOT read and reconstruct the file manually, omit DONE sections, summarize, paraphrase, abbreviate, or create its own tables.
   - Paste the full resolution guide (`conforma-resolution-guide.md`) into the chat
   - Paste the full analysis output (`conforma-analysis.md`) into the chat
   - Add commentary between generated sections

   The full resolution guide and analysis output are saved to the run directory — the user can open them directly for the complete reference. The preview is saved as `conforma-todo-and-done.md` and contains the same complete TODO/DONE block plus the informational `## WARNINGS` section as the guide, not an actionable-only subset.

   Run the presentation command with Bash description: `"Present validated Conforma TODO/DONE preview verbatim"`:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/present_conforma_report.py
```

   If this command exits non-zero, stop and report the validation error. Do NOT present a partial preview. Do NOT rely on the tool result alone — the marked TODO/DONE content must appear as literal text in the agent's response. Render it as markdown (not in a code block), preserving every marker, heading, table, link, and line exactly.

   **RULE 2 — ORDERING (present THEN ask):**
   The complete TODO/DONE content must appear in the agent's response text BEFORE the submission question. Never call AskQuestion in the same tool-call batch that runs the presentation command. The sequence is: (a) run the presentation command → (b) paste the complete marked report block verbatim into the response → (c) relay the emitted submission question and options verbatim in the subsequent user-visible turn. This ensures the user sees every action and completion section before being asked to submit.

   **RULE 3 — MUST PROCEED TO STEP 12:**
   After rendering the TODO, the agent MUST immediately proceed to step 12 (submission) in the same response — do NOT stop, wait for user input, or end the turn after presenting the TODO. The workflow is not complete until the user has been asked about submission. Stopping after the TODO without proceeding to step 12 is a hard failure.

   **Violating any of these rules is a hard failure regardless of model size, context window, or token budget.**

   ---

12. **Submit to GitHub** *(requires user confirmation — MUST be a separate turn after step 11)*: The presentation command has already generated the exact submission question and options from the active run context. Relay those emitted values verbatim and wait for the user's confirmation. Do NOT auto-submit. Only run the submit script without `--dry-run` if the user confirms.

   The dry-run command remains available when the submission prompt must be regenerated or inspected independently:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/submit_resolution_guide.py --dry-run
```

   The script reads guide file path, release, environment, and metadata file from `context.yaml` automatically.

   Use the `question_text` and `question_options` from the dry-run JSON output for AskQuestion verbatim. If the user declines, render the `skip_display` field from the dry-run JSON verbatim as markdown (it contains a clickable link to the local guide file). If the user confirms, run without `--dry-run`:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/submit_resolution_guide.py
```

   The script commits directly to the release branch. If submission fails (e.g. auth issue, branch protection), report the error but do not treat it as a workflow failure — the local guide file is still the primary deliverable.
