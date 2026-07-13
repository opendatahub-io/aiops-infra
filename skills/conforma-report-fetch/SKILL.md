---
name: conforma-report-fetch
description: Fetch conforma reports from two sources -- CSV violation reports from the conforma-reporter GitHub repo, and raw EC JSON from Konflux PipelineRuns via the Tekton Results API.
allowed-tools: Bash(python3:*,gh:*,oc:*)
user-invocable: true
---

# Conforma Report Fetch

Fetch conforma reports from two independent sources:

1. **Tekton JSON reports** (`fetch_conforma_tekton_result.py`) -- raw Enterprise Contract (EC) verification report JSON fetched directly from a Konflux PipelineRun via the Tekton Results API. **This is the preferred source** because it reflects the exact state of the most recent verification run in real time. Supports three policy types (`--type`): `registry` (default), `chart`, `fbc`. Accepts a version shortcode (e.g. `3.5`, `3.5ea.2`) or an exact PipelineRun name. Configuration is resolved from: CLI args > `context.yaml` > env vars > defaults. Writes step status to `context.yaml` when available.
2. **CSV violation reports** (`fetch_csv_reports.py`) -- historical per-release violation data from the `conforma-reporter` GitHub repo. CSV reports are generated on a schedule and **may be hours or days behind** the latest Konflux pipeline results. Use CSVs for historical trend analysis, cross-release comparisons, or when Konflux/VPN access is unavailable.

**Default choice: `fetch_conforma_tekton_result.py`.** When the user asks to "fetch a conforma report" without specifying a source, use `fetch_conforma_tekton_result.py`. The user can provide either a version shortcode (e.g. `3.5`) or an exact PipelineRun name. The `--type` flag selects the policy type (registry, chart, fbc). Fall back to CSVs when the user wants a broad cross-release overview, historical data, or cannot connect to the Konflux cluster.

---

**Output presentation**: See [script-output-presentation.md](../references/script-output-presentation.md).


## Workflow Routing

| Intent | Workflow file |
|--------|---------------|
| Fetch CSV violation reports from GitHub | Read `workflows/csv.md` |
| Fetch Tekton JSON from Konflux (version shortcode, exact name, any policy type) | Read `workflows/tekton.md` |

## Relationship to Other Skills

- **`conforma-analyze`**: Consumes both violation and warnings CSV reports from this skill. Calls `fetch_csv_reports.py` with `--output-dir` to write CSVs into its own `~/.conforma/` directory, then parses violations and identifies upcoming violations from warnings.
- **`conforma-parse`** (downstream): Consumes the Tekton handover from `fetch_conforma_tekton_result.py` to parse violations and warnings from the raw JSON report.
- **`conforma-exception`**: Manages exception creation. Can consume parsed output from either fetch mechanism.
