---
name: conforma-analyze
description: Fetch and expose RHOAI Conforma violation report data from conforma-reporter. Knows about violations only -- not exceptions, policy files, Jira, or GitLab MRs.
allowed-tools: Bash(python3:*,gh:*,git:*)
user-invocable: true
---

# Conforma Analyze

Fetch and expose Conforma violation report data for RHOAI releases. This skill retrieves CSV violation reports from the private [conforma-reporter](https://github.com/red-hat-data-services/conforma-reporter) repository and parses them into a structured YAML index.

This skill knows about **violations** only. It has no knowledge of exceptions, policy files, Jira tickets, or GitLab Merge Requests. For exception management, see the `conforma-exception` skill. Output from this skill is consumed by `conforma-exception`'s `--assess-expired` mode -- see the "Managing Expired Exceptions" section in `conforma-exception`'s SKILL.md for the full cross-skill workflow.

## Prerequisites

- **`gh` CLI** authenticated (`gh auth login`)
- **`GITHUB_TOKEN`** with read access to `red-hat-data-services/conforma-reporter` (private repo)

**Always run auth check first:**

```bash
python3 scripts/verify_auth.py
```

## Data Source

Violation reports are fetched from:
- **Repo**: `red-hat-data-services/conforma-reporter` (private)
- **Branch per release**: `rhoai-2.25`, `rhoai-3.3`, `rhoai-3.4`, etc.
- **File**: `prod/release_day/conforma-violations-report.csv`
- **Columns**: `type`, `component_name`, `image`, `message`, `effective_on`, `code`, `title`, `description`, `solution`

Only rows with `type=violation` are included in the output. Warnings are excluded.

## Workflow

When the user asks to show violations, analyze violations, or fetch conforma reports:

1. **Auth check**: Run `python3 scripts/verify_auth.py`. Stop if any check fails.

2. **Releases**: The script auto-detects supported releases by fetching [`rhoai-release-data.yaml`](https://github.com/red-hat-data-services/rhods-devops-infra/blob/main/src/config/rhoai-release-data.yaml) from `rhods-devops-infra`. This is the single source of truth for which RHOAI versions are currently supported, including EA/in-development releases. No static release list is maintained in this skill.

   If auto-detection fails (e.g. network issue, repo access), the script errors out and instructs the user to provide `--releases` manually.

3. **Fetch reports**: Run to auto-detect releases and fetch violation CSVs:

```bash
python3 scripts/fetch_conforma_reports.py \
  --output-dir /tmp/conforma-reports
```

   Override with explicit releases only if needed for a one-off check:

```bash
python3 scripts/fetch_conforma_reports.py \
  --releases rhoai-2.25,rhoai-3.4 \
  --output-dir /tmp/conforma-reports
```

   Some in-development/EA branches may not have a violations report CSV yet. The fetch script reports failures per release -- this is expected and not a blocker. The parse step will process whatever CSVs were successfully fetched.

4. **Parse violations**: Run to produce the structured YAML:

```bash
python3 scripts/parse_violations.py \
  --reports-dir /tmp/conforma-reports \
  --output /tmp/conforma-violations.yaml
```

5. **Present results**: Read the output YAML and present to the user as summary tables (per-release totals, per-rule breakdowns, per-component lists). Use the `summary` section for the overview and `violations_by_rule` for detail.

## Output Format

The output is a YAML file (human-reviewable, supports inline comments for annotation between skill runs). It is wrapped in a `violation_data` top-level key for future handover document embedding.

The `violations_by_rule` index uses **full rule codes** (with extracted suffixes, e.g. `rpm_signature.allowed:9386b48a1a693c5c`) as keys. Each rule entry includes a `base_code` field to support fallback prefix matching by downstream consumers.

See `parse_violations.py` for the complete output schema.

## Rule Code Extraction

The CSV `code` column contains base rules only (e.g. `rpm_signature.allowed`), while policy files use full rules with suffixes (e.g. `rpm_signature.allowed:9386b48a1a693c5c`). The `parse_violations.py` script deterministically extracts the full rule code from the `message` column using regex patterns per rule family. If no suffix can be extracted, the base code is used as-is.

## CSV Fetch Mechanism

The fetch script downloads reports via **raw download** from `raw.githubusercontent.com` (using `curl` with the GitHub token from `gh auth token`). This avoids the GitHub Contents API entirely, handling multi-megabyte report files reliably without JSON/base64 overhead or API size limits.

The script tries multiple paths within the `prod/` directory in order:
1. `prod/release_day/conforma-violations-report.csv` (primary)
2. `prod/future/build_type_latest/conforma-violations-report.csv`
3. `prod/future/build_type_nightly/conforma-violations-report.csv`

If `release_day` is unavailable (e.g. for in-development versions), the script automatically falls back to the next available report.

## Alternative Fetch Mechanism

If GitHub access is unreliable or the report production pipeline changes, a separate `conforma-report-fetch` skill can be created to provide an alternative fetch mechanism (e.g. direct clone, CI artifact download, or internal API). This skill's parsing layer (`parse_violations.py`) is decoupled from the fetch layer and accepts any directory of CSV files via `--reports-dir`, making it compatible with any fetch method.
