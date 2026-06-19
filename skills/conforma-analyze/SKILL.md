---
name: conforma-analyze
description: Fetch and expose RHOAI Conforma violation report data from conforma-reporter. Trace when specific violations appeared or disappeared via CSV git history. Knows about violations only -- not exceptions, policy files, Jira, or GitLab Merge Requests.
allowed-tools: Bash(python3:*,bash:*,git:*)
user-invocable: true
---

# Conforma Analyze

Fetch and expose Conforma violation report data for RHOAI releases. This skill retrieves CSV violation reports from the private [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter) repository and parses them into a structured YAML index.

## HARD RULE: No Custom Analysis

**Every conforma report analysis MUST follow the complete deterministic workflow (steps 1–7) below. No exceptions.**

Prohibited actions — the agent MUST NEVER:
- Run `analyze_csv_report.py --csv <file>` directly to produce ad-hoc summaries
- Truncate script output (e.g. `| head`, `| tail`, `2>&1 | head -N`)
- Skip any workflow step (parse, analyze, coverage check, generate resolution guide)
- Summarize or paraphrase CSV contents manually instead of running the scripts
- Present partial results as a "quick summary" before completing all steps
- Invent or compose analysis output that was not produced by the deterministic scripts
- Interpret, reformat, or summarize script output

**Output presentation**: See [script-output-presentation.md](../references/script-output-presentation.md). In short: plain-text output goes in a code block (copy-to-clipboard), markdown output is rendered directly. Content is always verbatim — no LLM interpretation. If output is not informative enough, the fix belongs in the script.

If the user only asks "does a report exist?" — answer the existence question (branch check + fetch attempt) and then **ask** whether to run the full analysis. Never produce partial analysis output as a substitute for the full workflow.

**Violation of this rule is a hard failure.** If you catch yourself about to do any of the above, STOP immediately and follow the workflow from step 1.

---

This skill knows about **violations** only. It has no knowledge of exceptions, policy files, Jira tickets, or GitLab Merge Requests. For exception management, see the `conforma-exception` skill. Output from this skill is consumed by `conforma-exception`'s `--assess-expired` mode -- see the "Managing Expired Exceptions" section in `conforma-exception`'s SKILL.md for the full cross-skill workflow.

## Violations-First Philosophy

When presenting violation data — whether standalone or when handing off to the `conforma-exception` skill — always frame violations as issues to be **resolved in component code first**. Conforma exceptions are a last resort for cases where the violation genuinely cannot be fixed within the release timeline (e.g., third-party RPM signing keys that Red Hat cannot control). Never default to suggesting "create an exception" without first acknowledging the code-fix path.

## Prerequisites

**Setup:** See [README.md](README.md) for installation and one-time authentication setup.

**Always run the unified prerequisite check first:**

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```

This single command verifies:
- Python dependencies installed
- `.work/.env` exists with tokens
- Infrastructure discovered (GITLAB_HOST, KONFLUX_CLUSTER_DOMAIN)
- GitHub authentication (conforma-reporter access)
- GitLab authentication (VPN + token)
- Jira authentication (token + email)
- Slack authentication (slackdump + session)

**All checks must pass** before proceeding to the workflow. If any fail, the `--fix` flag shows remediation instructions. For first-time setup, the primary path is infrastructure discovery (GITLAB_HOST + TENANT) — see the conforma [README.md](README.md).

**Component-maturity catalog** (required for Jira Component enrichment): The parse step enriches every component with its owning Jira Component from the component-maturity catalog. This requires VPN and GitLab auth. The parse script will clone/refresh the catalog automatically and fail hard if the catalog is unreachable:

```bash
python3 scripts/component_catalog_ops.py ensure-repo
```

## Remote Data Access Policy

When fetching data from remote repositories (GitLab, GitHub):

- **ALWAYS** use the skill scripts (which use Python `requests` + API tokens internally)
- **NEVER** use `find` to locate local clones, `cd` into them, or `git checkout`/`git show` on a local working tree
- **NEVER** assume a local clone is up-to-date or on the correct branch
- **NEVER** shell out to `gh`, `curl`, or `glab` — all API access is handled by Python scripts

Local clones on a dev workstation may be on a feature branch, days out of date, or modified with uncommitted changes. The scripts use remote APIs to guarantee you always read the canonical, production state of the repository.

## Data Sources

Reports are fetched from:
- **Repo**: `red-hat-data-services/conforma-reporter` (private)
- **Branch per release**: `rhoai-2.25`, `rhoai-3.3`, `rhoai-3.4`, etc.
- **Violations file**: `prod/release_day/conforma-violations-report.csv`
- **Warnings file**: `prod/release_day/conforma-warnings-report.csv`
- **Columns**: `type`, `component_name`, `image`, `message`, `effective_on`, `code`, `title`, `description`, `solution`

Both files are fetched and analyzed by default:

- **Violations CSV**: rows with `type=violation` — current policy violations.
- **Warnings CSV**: rows with `type=warning` — policies not yet enforced. Once a warning's `effective_on` enforcement date passes, it becomes an enforced violation. Warnings enforced **within 3 weeks** (21 days) are surfaced as **warnings becoming violations**, giving teams time to act before enforcement begins.

## Workflow

When the user asks to show violations, analyze violations, fetch conforma reports, or analyze a conforma report URL:

### Handling user-provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), extract the release branch from the URL path (the segment after `/blob/` and before the next `/`) and pass it to the fetch script via `--releases`. Example: from the URL above, extract `rhoai-3.4` and run with `--releases rhoai-3.4`.

### Steps

**Important**: Steps 1–10 use a shared `$RUNDIR` variable set in step 3. All intermediate outputs live in this directory. The `$RELEASE` variable is determined in step 2.

1. **Prerequisites check**: Run `python3 scripts/verify_conforma_prerequisites.py --format markdown`. If exit code is non-zero, **stop immediately** — do not proceed with partial auth. Render the script's markdown output **directly** (not in a code block) — it contains individually-copyable fix commands. Do NOT interpret, reformat, summarize, or add your own explanation of the failures — the script output is self-explanatory and designed to be user-facing. The user must fix failures before the workflow can continue.

   **Slack is optional.** If the script exits 0 but shows a Slack warning, render the script output directly (which already explains the situation) and ask "Proceed without Slack?" If the user wants Slack, follow the `slack-auth` skill's Agent Workflow. Otherwise, continue — pass `--require-slack false` to `violations_coverage.py` in step 6.

2. **Resolve release context**: Run the context resolution script. Extract the release identifier from the user's query (e.g., "rhoai-3.5-ea.1", "3.4", "3.5 ea 1") and pass it to the script. If the user provided a GitHub URL, extract the branch from the `/blob/<branch>/` segment and use that as the query.

   ```bash
   python3 scripts/resolve_release_context.py --query "<extracted_release_text>"
   ```

   Parse the JSON output. Present the `confirmation_display` field **verbatim as markdown** (NOT in a code block) so that embedded links are clickable.

   Then act on the `status` field:
   - **`"resolved"`**: Use AskQuestion to confirm: "Proceed with these details?" (options: Yes / No, change something). On "Yes", set: `RELEASE=<.release>`, `KONFLUX_APP=<.konflux_app>`.
   - **`"ambiguous"`**: Use AskQuestion with the numbered candidates from `candidates[]`. After the user selects, re-run with `--query "<selected_version_dir>"` to get a "resolved" result.
   - **`"not_found"`** or **`"error"`**: Present the `confirmation_display` verbatim and **stop**. Do NOT attempt to guess or proceed without a resolved context.

   If the user did not mention any release and you cannot extract one from their query, use `--list` to show available versions and ask the user to pick:

   ```bash
   python3 scripts/resolve_release_context.py --list
   ```

3. **Check tooling health**: Before fetching reports, check the health of conforma infrastructure tools. Create the `$RUNDIR` first (needed for output), then run the health check:

```bash
mkdir -p .work
RUNDIR=".work/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUNDIR"
python3 skills/conforma-tooling-health/scripts/check_tooling_health.py \
  --release "$RELEASE" \
  --output "$RUNDIR/tooling-health.json"
```

   Parse the JSON output and act on `overall_health`:

   - **`"healthy"`** -- proceed silently to step 4 (fetch reports).
   - **`"unhealthy"` or `"error"`** -- present the tooling health data (tool name, status, consecutive failures, last success URL) and use AskQuestion: "The conforma-reporter workflow is failing for this release (last success: DATE). The violation report may be stale or incomplete. Proceed with analysis anyway?" (options: "Yes, continue" / "No, stop here"). Only proceed to step 4 if the user confirms.
   - **`"in_progress"`** -- present the in-progress run details and use AskQuestion: "A conforma-reporter run is currently in progress for this release. Options:" (choices: "Use the last completed report (generated DATE)" / "Wait for the current run to finish (up to 40 minutes)"). If the user chooses to wait, monitor the run using `python3 scripts/run_github_workflow.py monitor --repo-url https://github.com/red-hat-data-services/conforma-reporter --run-id RUN_ID --timeout 40 --poll-interval 60`, then re-run `check_tooling_health.py` to refresh status. If the run fails after waiting, fall back to the unhealthy prompt.
   - **`"no_runs"`** -- warn ("No conforma-reporter runs found for this branch -- report may not exist") and proceed.

   The `$RUNDIR` variable created here is used by ALL subsequent steps — never change it mid-workflow.

4. **Fetch reports**: Fetch CSVs into the run directory created in step 3. **Always pass `--releases $RELEASE`** to scope the fetch to the target release from step 2:

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases "$RELEASE" \
  --output-dir "$RUNDIR" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   To fetch multiple specific releases (e.g. for cross-release comparison):

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases rhoai-2.25,rhoai-3.4 \
  --output-dir "$RUNDIR" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   To fetch ALL supported releases (rare — only for full-portfolio audits):

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --all \
  --output-dir "$RUNDIR" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   The output directory will contain `{release}.csv` (violations) and `{release}-warnings.csv` (warnings) for each release. The `fetch-metadata.json` contains `source_path` and `created_at` per release — needed by steps 8-9. Some in-development/EA branches may not have report CSVs yet. The fetch script reports failures per release -- this is expected and not a blocker. The parse step will process whatever CSVs were successfully fetched.

5. **Parse violations and warnings**: Run on the **same timestamped directory from step 3** to produce the structured YAML. **Always pass `--release $RELEASE`** to ensure only the target release's CSVs are parsed (defense in depth — even if extra CSVs exist in the directory, they are ignored). **Warnings CSVs are parsed by default** — any warning with an enforcement date within 21 days is included as a warning becoming a violation. The parse step also **enriches each component with its owning Jira Component** from the component-maturity catalog (requires VPN + GitLab auth). If the catalog is unreachable, the script fails hard — ensure VPN is active:

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir .work/20260604-123000 \
  --release "$RELEASE" \
  --output .work/20260604-123000/violations.yaml
```

   To customize the enforcement threshold:

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir .work/20260604-123000 \
  --output .work/20260604-123000/violations.yaml \
  --upcoming-threshold-days 14
```

   For CI/testing only (no catalog enrichment):

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir .work/20260604-123000 \
  --output .work/20260604-123000/violations.yaml \
  --no-catalog
```

6. **Analyze and present**: Run the CSV analysis script on the **run directory created by step 3** (printed in its stderr output). Never use `.work/latest` — always use the specific timestamped directory to avoid analyzing stale data. Pass `--violations-yaml` for ownership, `--metadata-file` and `--release` for the report header and staleness check:

```bash
# Text summary with ownership + report header (default):
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --reports-dir "$RUNDIR" \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --metadata-file "$RUNDIR/fetch-metadata.json" \
  --release "$RELEASE"

# Markdown report with ownership + report header:
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --reports-dir "$RUNDIR" \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --metadata-file "$RUNDIR/fetch-metadata.json" \
  --release "$RELEASE" \
  --format markdown \
  --output "$RUNDIR/conforma-analysis.md"

# JSON (for programmatic consumption):
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --reports-dir "$RUNDIR" \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --format json \
  --output "$RUNDIR/conforma-analysis.json"
```

   The script automatically prepends a report header (source CSV URL + generation date) and a staleness warning (if the report is >3 days old) when `--metadata-file` is provided.

   The analysis covers:
   - Totals and breakdown by violation code (count, %, affected components)
   - Root cause extraction (untrusted task names, signing keys)
   - Per-component violation patterns (code combinations)
   - **Warnings becoming violations** — policies nearing their enforcement date (within 21 days by default)
   - Prioritized remediation recommendations with resolution %
   - **Jira Component ownership** — when `--violations-yaml` is provided, component names are annotated with their owning Jira Component (e.g. `odh-vllm-rhel9 (vLLM)`)

   **Presentation**: `--format text` output → present in a code block. `--format markdown` output → render as markdown (not in a code block).

7. **Cross-reference with exceptions, open Merge Requests, open Jira, and Slack**: After the analysis, **always** run the violations coverage check. This produces a unified table showing each violation alongside its existing exception status, open Merge Requests (classified as *exception* or *remedy*), open Jira tickets, Slack threads (if available), and recommended next steps — which is the **primary output** the user expects when asking to "analyze" a report.

   **Target version checking (HARDCODED — always performed)**: Every Jira ticket found is automatically classified by its `fixVersion` relevance to the currently-analyzed release. Tickets are annotated as:
   - (no annotation) — fixVersion targets the currently analyzed release
   - `⚠️ targets {version}` — fixVersion is set but targets a different/future release (fix exists but won't land in the analyzed release)
   - `⚠️ no fixVersion` — no fixVersion set (unclear which release the fix targets)

   This ensures the user can distinguish between "this violation has a fix landing in the current release" vs "there's a Jira for this but it targets a future release and is NOT a solution for the current report".

   All required auth (GitLab, Jira) was already verified in step 1. Slack is optional — if not configured, pass `--require-slack false`.

   The script manages the `.work/konflux-release-data` clone (fresh fetch + reset). It enforces the repo clone policy: it will `git fetch` any existing `--clone-dir` and abort if the remote is unreachable (e.g. VPN down). Never silently use stale data.

   **Save the output to a JSON file** for use by the resolution guide generator (step 8):

```bash
# Extract policy file names from step 2 resolve output
POLICY_FILES=$(python3 -c "import json; print(','.join(f['name'] for f in json.loads('$RESOLVE_JSON').get('links',{}).get('policy_files',[])))")

# With Slack (when configured):
python3 skills/conforma-analyze/scripts/violations_coverage.py \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --clone-dir .work/konflux-release-data \
  --environment prod \
  --release "$RELEASE" \
  --policy-files "$POLICY_FILES" \
  --metadata-file "$RUNDIR/fetch-metadata.json" > "$RUNDIR/coverage.json"

# Without Slack (when not configured):
python3 skills/conforma-analyze/scripts/violations_coverage.py \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --clone-dir .work/konflux-release-data \
  --environment prod \
  --release "$RELEASE" \
  --require-slack false \
  --policy-files "$POLICY_FILES" \
  --metadata-file "$RUNDIR/fetch-metadata.json" > "$RUNDIR/coverage.json"
```

   Pass the violations YAML from step 4 as input. The coverage table is the primary deliverable; the statistical breakdown from step 5 can be presented as supplementary detail below it.

   To extract the coverage table for display:

```bash
python3 -c "import json,sys; print(json.load(sys.stdin)['markdown_table'])" < "$RUNDIR/coverage.json"
```

   **Presentation**: The `markdown_table` is markdown — render it directly (not in a code block).

8. **Resolution Guide**: After presenting the coverage table, the resolution guide is generated deterministically by script. The guide is both presented to the user and saved to a file for submission (step 10). See step 9 for the generation command. While the guide is being generated, present the coverage table `markdown_table` from step 7 to the user as the immediate output.

9. **Generate the resolution guide**: Run the resolution guide generator on the intermediate outputs from steps 3-7. This produces a unified markdown file combining tooling health, coverage, per-violation resolution guidance (from [`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml) with fallback references for uncataloged violations), warnings, and statistical analysis:

```bash
# Extract metadata from fetch output
SOURCE_PATH=$(python3 -c "import json; d=json.load(open('$RUNDIR/fetch-metadata.json')); print(d['releases']['$RELEASE']['source_path'])")
CREATED_AT=$(python3 -c "import json; d=json.load(open('$RUNDIR/fetch-metadata.json')); print(d['releases']['$RELEASE']['created_at'])")
SOURCE_SHA=$(python3 -c "import json; d=json.load(open('$RUNDIR/fetch-metadata.json')); print(d['releases']['$RELEASE'].get('source_sha', ''))")

# Extract policy config links from step 2 resolve output (RESOLVE_JSON)
POLICY_DIR_URL=$(python3 -c "import json; print(json.loads('$RESOLVE_JSON').get('links',{}).get('policy_dir',''))")
POLICY_FILES_JSON=$(python3 -c "import json; print(json.dumps(json.loads('$RESOLVE_JSON').get('links',{}).get('policy_files',[])))")

python3 skills/conforma-analyze/scripts/generate_resolution_guide.py \
  --violations-yaml "$RUNDIR/violations.yaml" \
  --coverage-json "$RUNDIR/coverage.json" \
  --reports-dir "$RUNDIR" \
  --release "$RELEASE" \
  --source-path "$SOURCE_PATH" \
  --source-created-at "$CREATED_AT" \
  --source-sha "$SOURCE_SHA" \
  --policy-dir-url "$POLICY_DIR_URL" \
  --policy-files-json "$POLICY_FILES_JSON" \
  --tooling-health-json "$RUNDIR/tooling-health.json" \
  --output "$RUNDIR/conforma-resolution-guide.md"
```

   **Present the generated guide content to the user.** This MUST happen before step 10 — the user must see the full report before being asked about submission. Never run step 10 in parallel with presenting the guide.

   **Presentation**: The guide is a `.md` file — render it as markdown (not in a code block).

10. **Submit to GitHub** *(requires user confirmation)*: After presenting the full guide to the user, **ask whether they want to submit it** to the conforma-reporter repo. Do NOT auto-submit. Use the AskQuestion tool to offer: "Submit this resolution guide to the conforma-reporter GitHub repository (red-hat-data-services/conforma-reporter)?" with options like "Yes, submit" and "No, skip". Only proceed if the user confirms. The guide is committed to the **root of the release branch** (e.g. `conforma-resolution-guide.md` at the repo root). Pass `--metadata-file` so the script can automatically clean up any legacy guide from the old `prod/release_day/` location:

```bash
python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \
  --guide-file "$RUNDIR/conforma-resolution-guide.md" \
  --release "$RELEASE" \
  --metadata-file "$RUNDIR/fetch-metadata.json"
```

   The script commits directly to the release branch. If submission fails (e.g. auth issue, branch protection), report the error but do not treat it as a workflow failure — the local guide file is still the primary deliverable.

   To preview without committing:

```bash
python3 skills/conforma-analyze/scripts/submit_resolution_guide.py \
  --guide-file "$RUNDIR/conforma-resolution-guide.md" \
  --release "$RELEASE" \
  --dry-run
```

## Violation History

Trace when a specific violation type last appeared (or disappeared) in the CSV git history for a release branch. Use this when the user asks questions like:
- "When was the last time we saw X violation?"
- "When did X violation disappear for release Y?"
- "Has X violation ever appeared for release Y?"
- "Show me the history of X violation"

### Violation Code Alias Table

Users refer to violations by natural-language phrases. **Always resolve the phrase to an exact `code` value before invoking the script.** Read [`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml) and match the user's phrase against the `aliases` field of each violation entry.

If the user's phrase does not match any alias in the catalog, first run `analyze_csv_report.py` (see Workflow step 5) to list all violation codes in the current report, then pick the matching code.

### Extracting release from user input

- If the user provides a release name like `3.5-ea.1`, prepend `rhoai-` to get the branch: `rhoai-3.5-ea.1`.
- If the user provides a GitHub URL (e.g. `https://github.com/.../blob/rhoai-3.5-ea.1/prod/future/...`), extract the branch (`rhoai-3.5-ea.1`) and the CSV path after it (`prod/future/build_type_latest/conforma-violations-report.csv`). Pass the branch via `--release` and the path via `--csv-path`.
- If no URL is provided and no `--csv-path` is given, the script auto-detects which CSV path exists on the branch (same fallback order as the fetch script).

### Steps

1. **Prerequisites check**: Run `python3 scripts/verify_conforma_prerequisites.py --format markdown`. If exit code is non-zero, render the markdown output directly and stop. Do not interpret or reformat.

2. **Resolve the violation code**: Map the user's phrase to an exact `--code` value using the `aliases` field in [`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml).

3. **Run the history script**:

```bash
python3 skills/conforma-analyze/scripts/violation_history.py \
  --release rhoai-3.5-ea.1 \
  --code prefetch_dependencies.mode_not_permissive \
  --format text
```

   Use `--format text` when presenting results to the user. Use `--format json` when piping output to another tool or for programmatic consumption.

   Optional flags:
   - `--csv-path <path>` — override CSV path (use when the user provides a URL containing the path)
   - `--component <name>` — filter to a specific component
   - `--until-found` — stop after finding the first commit where the violation is present (fastest for "when last seen" queries)
   - `--max-commits <N>` — limit history depth (default: 100)

### Examples

**"When was the last time we saw permissive prefetch mode for 3.5-ea.1?"**

```bash
python3 skills/conforma-analyze/scripts/violation_history.py \
  --release rhoai-3.5-ea.1 \
  --code prefetch_dependencies.mode_not_permissive \
  --format text
```

**"When did rpm signature violations disappear for rhoai-3.4?"** (with `--until-found` for speed)

```bash
python3 skills/conforma-analyze/scripts/violation_history.py \
  --release rhoai-3.4 \
  --code rpm_signature.allowed \
  --until-found \
  --format text
```

**From a URL with a specific CSV path:**

Given URL `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.5-ea.1/prod/future/build_type_latest/conforma-violations-report.csv`:

```bash
python3 skills/conforma-analyze/scripts/violation_history.py \
  --release rhoai-3.5-ea.1 \
  --code prefetch_dependencies.mode_not_permissive \
  --csv-path prod/future/build_type_latest/conforma-violations-report.csv \
  --format text
```

### Interpreting Output

The text output includes:

| Field | Meaning |
|---|---|
| **STATUS** | Whether the violation is present in the latest (HEAD) report |
| **Last seen** | Most recent commit date where the violation was present |
| **Disappeared** | First commit after "last seen" where the violation is absent |
| **First seen** | Oldest commit in checked history where the violation appeared |
| **TIMELINE** | Visual commit-by-commit view: `██` = present, `··` = absent |

## Output Format

The output is a YAML file (human-reviewable, supports inline comments for annotation between skill runs). It is wrapped in a `violation_data` top-level key for future handover document embedding.

The `violations_by_rule` index uses **full rule codes** (with extracted suffixes, e.g. `rpm_signature.allowed:9386b48a1a693c5c`) as keys. Each rule entry includes a `base_code` field to support fallback prefix matching by downstream consumers.

Each entry in `violations_by_component` includes a `jira_component` field (string or null) mapping the Konflux component to its owning Jira Component from the component-maturity catalog. A top-level `catalog_enriched: true/false` flag indicates whether catalog enrichment was performed. This data is consumed by `analyze_csv_report.py` (via `--violations-yaml`) and `violations_coverage.py` to annotate outputs with ownership information.

When warnings CSVs are present, the output also includes an `upcoming_violations` section with `by_rule`, `by_component`, and `summary` sub-keys. These are warnings that will become enforced violations once their `effective_on` date passes. Each rule entry includes `effective_on` (the enforcement deadline) and `days_until_effective` (countdown to enforcement). Upcoming `by_component` entries also carry `jira_component` when catalog enrichment is active.

See `parse_violations.py` for the complete output schema.

## Rule Code Extraction

The CSV `code` column contains base rules only (e.g. `rpm_signature.allowed`), while policy files use full rules with suffixes (e.g. `rpm_signature.allowed:9386b48a1a693c5c`). The `parse_violations.py` script deterministically extracts the full rule code from the `message` column using regex patterns per rule family. If no suffix can be extracted, the base code is used as-is.

## CSV Fetch Mechanism

CSV fetching is delegated to the **`conforma-report-fetch`** skill (`fetch_csv_reports.py`). See that skill's SKILL.md for data source details, fallback paths, and release auto-detection.

This skill's parsing layer (`parse_violations.py`) is decoupled from the fetch layer and accepts any directory of CSV files via `--reports-dir`, making it compatible with any fetch method.
