---
name: conforma-report-fetch
description: Fetch conforma reports from two sources -- CSV violation reports from the conforma-reporter GitHub repo, and raw EC JSON from Konflux PipelineRuns via the Tekton Results API.
allowed-tools: Bash(python3:*,gh:*,oc:*)
user-invocable: true
---

# Conforma Report Fetch

**Experimental and unfinished path:** This skill is not the default route for ordinary Conforma report or status requests. Those requests MUST enter through `conforma` and route to `conforma-analyze`. Do not invoke this skill or its scripts unless the user explicitly requests raw Tekton/PipelineRun report data. Do not use the direct fetch path until this instruction is changed.

Fetch conforma reports from two independent sources:

1. **Tekton JSON reports** (`fetch_conforma_tekton_result.py`) -- raw Enterprise Contract (EC) verification report JSON fetched directly from a Konflux PipelineRun via the Tekton Results API. **This is the preferred source** because it reflects the exact state of the most recent verification run in real time. Supports three policy types (`--type`): `registry` (default), `chart`, `fbc`. Accepts a version shortcode (e.g. `3.5`, `3.5ea.2`) or an exact PipelineRun name. Configuration is resolved from: CLI args > `context.yaml` > env vars > defaults. Writes step status to `context.yaml` when available.
2. **CSV violation reports** (`fetch_csv_reports.py`) -- historical per-release violation data from the `conforma-reporter` GitHub repo. CSV reports are generated on a schedule and **may be hours or days behind** the latest Konflux pipeline results. Use CSVs for historical trend analysis, cross-release comparisons, or when Konflux/VPN access is unavailable.

The direct fetch path is not a default choice. Ordinary report requests must use `conforma-analyze`, which owns the complete deterministic workflow. This skill is only for an explicit request for raw Tekton/PipelineRun report data; the direct path remains experimental and unfinished.

---

**Output presentation**: See [script-output-presentation.md](../references/script-output-presentation.md).

**Filesystem prerequisite**: Fetch workflows create run contexts, reports, caches, clones, and helper binaries under `~/.conforma/`. Before running any fetch script, the agent must ensure the command execution environment can write to `~/.conforma/` and the repository workspace. If the active sandbox does not allow that path, request the platform's approved custom writable-root or elevated execution before initialization; do not start the workflow in the restricted sandbox.


## Workflow Routing

| Intent | Workflow file |
|--------|---------------|
| Fetch CSV violation reports from GitHub | Read `workflows/csv.md` |
| Fetch Tekton JSON from Konflux (version shortcode, exact name, any policy type) | Read `workflows/tekton.md` |

## Relationship to Other Skills

- **`conforma-analyze`**: Consumes both violation and warnings CSV reports from this skill. Calls `fetch_csv_reports.py` with `--output-dir` to write CSVs into its own `~/.conforma/` directory, then parses violations and identifies upcoming violations from warnings.
- **`conforma-parse`** (downstream): Consumes the Tekton handover from `fetch_conforma_tekton_result.py` to parse violations and warnings from the raw JSON report.
- **`conforma-exception`**: Manages exception creation. Can consume parsed output from either fetch mechanism.
