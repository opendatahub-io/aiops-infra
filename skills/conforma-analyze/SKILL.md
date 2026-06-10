---
name: conforma-analyze
description: Fetch and expose RHOAI Conforma violation report data from conforma-reporter. Trace when specific violations appeared or disappeared via CSV git history. Knows about violations only -- not exceptions, policy files, Jira, or GitLab MRs.
allowed-tools: Bash(python3:*,gh:*,git:*)
user-invocable: true
---

# Conforma Analyze

Fetch and expose Conforma violation report data for RHOAI releases. This skill retrieves CSV violation reports from the private [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter) repository and parses them into a structured YAML index.

This skill knows about **violations** only. It has no knowledge of exceptions, policy files, Jira tickets, or GitLab Merge Requests. For exception management, see the `conforma-exception` skill. Output from this skill is consumed by `conforma-exception`'s `--assess-expired` mode -- see the "Managing Expired Exceptions" section in `conforma-exception`'s SKILL.md for the full cross-skill workflow.

## Violations-First Philosophy

When presenting violation data — whether standalone or when handing off to the `conforma-exception` skill — always frame violations as issues to be **resolved in component code first**. Conforma exceptions are a last resort for cases where the violation genuinely cannot be fixed within the release timeline (e.g., third-party RPM signing keys that Red Hat cannot control). Never default to suggesting "create an exception" without first acknowledging the code-fix path.

## Prerequisites

**Setup:** See [README.md](README.md) for installation and one-time authentication setup.

**Always run auth check first:**

```bash
gh auth status && gh api repos/red-hat-data-services/conforma-reporter --jq .full_name
```

**Component-maturity catalog** (optional, for Jira Component enrichment): Clone the catalog repo to enable Jira Component lookups in analysis output. Not required for basic violation analysis, but recommended for enriched output:

```bash
python3 scripts/component_catalog_ops.py ensure-repo
```

## Remote Data Access Policy

When fetching data from remote repositories (GitLab, GitHub):

- **ALWAYS** use the remote API directly (`gh api`, raw HTTP download via `curl`)
- **NEVER** use `find` to locate local clones, `cd` into them, or `git checkout`/`git show` on a local working tree
- **NEVER** assume a local clone is up-to-date or on the correct branch

Local clones on a dev workstation may be on a feature branch, days out of date, or modified with uncommitted changes. Using the remote API guarantees you always read the canonical, production state of the repository at the exact ref you specify.

```bash
# GOOD — fetch from GitHub
gh api "repos/org/repo/contents/path/to/file?ref=main" --jq '.content' | base64 -d

# BAD — using a local clone
cd ~/dev/github/org/repo && git show origin/main:path/to/file
```

## Data Source

Violation reports are fetched from:
- **Repo**: `red-hat-data-services/conforma-reporter` (private)
- **Branch per release**: `rhoai-2.25`, `rhoai-3.3`, `rhoai-3.4`, etc.
- **File**: `prod/release_day/conforma-violations-report.csv`
- **Columns**: `type`, `component_name`, `image`, `message`, `effective_on`, `code`, `title`, `description`, `solution`

Only rows with `type=violation` are included in the output. Warnings are excluded.

## Workflow

When the user asks to show violations, analyze violations, fetch conforma reports, or analyze a conforma report URL:

### Handling user-provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), extract the release branch from the URL path (the segment after `/blob/` and before the next `/`) and pass it to the fetch script via `--releases`. Example: from the URL above, extract `rhoai-3.4` and run with `--releases rhoai-3.4`.

### Steps

1. **Auth check**: Run `gh auth status && gh api repos/red-hat-data-services/conforma-reporter --jq .full_name`. Stop if either command fails.

2. **Releases**: If the user provided a URL, extract the release branch from it (see above). Otherwise, the script auto-detects supported releases by fetching [`rhoai-release-data.yaml`](https://github.com/red-hat-data-services/rhods-devops-infra/blob/main/src/config/rhoai-release-data.yaml) from `rhods-devops-infra`. This is the single source of truth for which RHOAI versions are currently supported, including EA/in-development releases. No static release list is maintained in this skill.

   If auto-detection fails (e.g. network issue, repo access), the script errors out and instructs the user to provide `--releases` manually.

3. **Fetch reports**: CSV fetching is provided by the **`conforma-report-fetch`** skill. Create a timestamped output directory under this skill's `.work/` and pass it via `--output-dir` to keep all data local:

```bash
mkdir -p .work
RUNDIR=".work/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUNDIR"
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --output-dir "$RUNDIR"
```

   Override with explicit releases only if needed for a one-off check:

```bash
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases rhoai-2.25,rhoai-3.4 \
  --output-dir "$RUNDIR"
```

   Some in-development/EA branches may not have a violations report CSV yet. The fetch script reports failures per release -- this is expected and not a blocker. The parse step will process whatever CSVs were successfully fetched.

4. **Parse violations**: Run on the **same timestamped directory from step 3** to produce the structured YAML:

```bash
python3 skills/conforma-analyze/scripts/parse_violations.py \
  --reports-dir .work/20260604-123000 \
  --output .work/20260604-123000/violations.yaml
```

5. **Analyze and present**: Run the CSV analysis script on the **run directory created by step 3** (printed in its stderr output). Never use `.work/latest` — always use the specific timestamped directory to avoid analyzing stale data:

```bash
# Text summary (default):
python3 skills/conforma-analyze/scripts/analyze_csv_report.py --reports-dir .work/20260604-123000

# Markdown report:
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --reports-dir .work/20260604-123000 \
  --format markdown \
  --output .work/20260604-123000/conforma-analysis.md

# JSON (for programmatic consumption):
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --reports-dir .work/20260604-123000 \
  --format json \
  --output .work/20260604-123000/conforma-analysis.json

# Analyze a single CSV directly:
python3 skills/conforma-analyze/scripts/analyze_csv_report.py \
  --csv .work/20260604-123000/rhoai-3.5-ea.1.csv
```

   The analysis script covers:
   - Totals and breakdown by violation code (count, %, affected components)
   - Root cause extraction (untrusted task names, signing keys)
   - Per-component violation patterns (code combinations)
   - Effective date enforcement deadlines
   - Prioritized remediation recommendations with resolution %

   Present the output to the user. For the `--format text` output, display it directly. For markdown, render it as the response.

   **Report header**: Always present the report source as a clickable GitHub URL at the top of your output. Construct it from the branch and CSV path: `https://github.com/red-hat-data-services/conforma-reporter/blob/{branch}/{csv_path}`. Example:

   > **Report**: [`prod/release_day/conforma-violations-report.csv`](https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.5-ea.1/prod/release_day/conforma-violations-report.csv) (generated 2026-06-03)

6. **Cross-reference with exceptions, open MRs, open Jira, and Slack**: After the analysis, **always** run the violations coverage check. This produces a unified table showing each violation alongside its existing exception status, open merge requests, open Jira tickets, Slack threads, and recommended next steps — which is the **primary output** the user expects when asking to "analyze" a report.

   Read and follow [`skills/conforma-exception/references/coverage-check.md`](../conforma-exception/references/coverage-check.md). In particular, follow the **"Auth Availability — Inform the User"** section: check all auth sources (GitLab, Jira, Slack) before running, tell the user which sources are unavailable and how to fix them, then proceed with whatever sources are available. Never silently skip a data source.

   Pass the violations YAML from step 4 as input. The coverage table is the primary deliverable; the statistical breakdown from step 5 can be presented as supplementary detail below it.

7. **Violation Resolution Guide**: After presenting the coverage table, read [`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml) and present a **"Violation Resolution Guide"** section with per-violation details. For each violation in the report:

   - Look up the violation by its `conforma_rule_codes` in the catalog
   - Check `known_false_alerts` — if the violation matches a known false alert AND the condition applies, flag it as "likely a false positive"
   - Supplement the generic `next_steps` from the coverage check with type-specific guidance from the catalog's `fix_steps`
   - Note the `classification.typical_owner` and `requires_rebuild` fields to give actionable context
   - For violations with `resolution_path: code_fix`, point the user to the `conforma-remedy` skill for detailed fix procedures
   - For violations with `resolution_path: mixed`, present both the fix path and the exception path
   - Include the full `next_steps` detail (from the coverage check JSON output, not the abbreviated table version) as part of each violation's entry

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

1. **Auth check**: Run `gh auth status && gh api repos/red-hat-data-services/conforma-reporter --jq .full_name`. Stop if either command fails.

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

See `parse_violations.py` for the complete output schema.

## Rule Code Extraction

The CSV `code` column contains base rules only (e.g. `rpm_signature.allowed`), while policy files use full rules with suffixes (e.g. `rpm_signature.allowed:9386b48a1a693c5c`). The `parse_violations.py` script deterministically extracts the full rule code from the `message` column using regex patterns per rule family. If no suffix can be extracted, the base code is used as-is.

## CSV Fetch Mechanism

CSV fetching is delegated to the **`conforma-report-fetch`** skill (`fetch_csv_reports.py`). See that skill's SKILL.md for data source details, fallback paths, and release auto-detection.

This skill's parsing layer (`parse_violations.py`) is decoupled from the fetch layer and accepts any directory of CSV files via `--reports-dir`, making it compatible with any fetch method.
