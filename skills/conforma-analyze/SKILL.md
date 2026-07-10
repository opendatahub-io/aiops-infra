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
- Write its own version of the resolution guide instead of rendering the script-generated file verbatim
- Show only a subset of violations (e.g. only "uncovered" ones) — the FULL guide for ALL violations must be presented
- Ask the user about submission (step 10) before the full guide content has been rendered in a response

**Output presentation**: See [script-output-presentation.md](../references/script-output-presentation.md). In short: plain-text output goes in a code block (copy-to-clipboard), markdown output is rendered directly. Content is always verbatim — no LLM interpretation. If output is not informative enough, the fix belongs in the script.

If the user only asks "does a report exist?" — answer the existence question (branch check + fetch attempt) and then **ask** whether to run the full analysis. Never produce partial analysis output as a substitute for the full workflow.

**Violation of this rule is a hard failure.** If you catch yourself about to do any of the above, STOP immediately and follow the workflow from step 1.

---

This skill knows about **violations** only. It has no knowledge of exceptions, policy files, Jira tickets, or GitLab Merge Requests. For exception management, see the `conforma-exception` skill. Output from this skill is consumed by `conforma-exception`'s `--assess-expired` mode -- see the "Managing Expired Exceptions" section in `conforma-exception`'s SKILL.md for the full cross-skill workflow.

## Violations-First Philosophy

When presenting violation data — whether standalone or when handing off to the `conforma-exception` skill — always frame violations as issues to be **resolved in component code first**. Conforma exceptions are a last resort for cases where the violation genuinely cannot be fixed within the release timeline (e.g., third-party RPM signing keys that Red Hat cannot control). Never default to suggesting "create an exception" without first acknowledging the code-fix path.

## Prerequisites

**Setup:** See [README.md](README.md) for installation and one-time authentication setup.

**Execution rules:** Read and follow [`skills/references/script-execution-rules.md`](../references/script-execution-rules.md) — all scripts in this workflow require unrestricted network access and must not be run in a restricted sandbox.

**Output presentation:** Read and follow [`skills/references/script-output-presentation.md`](../references/script-output-presentation.md) — all script output must be presented verbatim using the format rules defined there.

**Step 0 — Resolve repo root**: Before running any script, ensure `context.yaml` exists with `aiops_infra_root` by running the Step 0 block from the workflow (see `workflows/full-analysis.md`). All `python3` commands below use `$_R` as the repo root prefix, resolved from `context.yaml`.

**Always run the unified prerequisite check first**:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py" --fix
```

This single command verifies:
- Python dependencies installed
- `~/.conforma/.env` exists with tokens
- Infrastructure discovered (GITLAB_HOST, KONFLUX_CLUSTER_DOMAIN)
- GitHub authentication (conforma-reporter access)
- GitLab authentication (VPN + token)
- Jira authentication (token + email)
- Slack authentication (slackdump + session)

**All checks must pass** before proceeding to the workflow. If any fail, the `--fix` flag shows remediation instructions. For first-time setup, the primary path is infrastructure discovery (GITLAB_HOST + TENANT) — see the conforma [README.md](README.md).

**Component-maturity catalog** (required for Jira Component enrichment): The parse step enriches every component with its owning Jira Component from the component-maturity catalog. This requires VPN and GitLab auth. The parse script will clone/refresh the catalog automatically and fail hard if the catalog is unreachable:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/component_catalog_ops.py" ensure-repo
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

## Counting Model

- **Violation** = code + component + details. Each distinct failing check is one violation. The "details" are rule-specific (e.g. specific package for sbom rules, nothing extra for hermetic). In the CSV, the `message` field encodes the details — same message on different image digests = same violation, different message = different violation.
- Each violation corresponds to one exception entry if an exception is needed.
- **Image occurrences** (CSV rows) include digest-level duplication and are reported as context only ("Source CSV rows" in the Summary table).
- All executive summary, analysis, and resolution guide metrics MUST use violation counts, not code counts.
- Violation codes (e.g. `hermetic_task.hermetic`) are grouping labels, not counting units.
- Coverage is binary: each violation either has an exception or does not. There is no "partially covered" category.
- All counting uses `scripts/conforma_counting.py` — no script may independently compute violation counts.
- All counting, formatting, and presentation is done by scripts. The agent presents script output verbatim. The agent MUST NOT compute violation counts, percentages, or coverage metrics itself.


## Workflow Routing

| Intent | Workflow file |
|--------|---------------|
| Full violation analysis (fetch, parse, analyze, coverage, guide) | Read `workflows/full-analysis.md` |
| Trace when a violation appeared/disappeared | Read `workflows/violation-history.md` |

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
