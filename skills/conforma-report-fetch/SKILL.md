---
name: conforma-report-fetch
description: Fetch conforma reports from two sources -- CSV violation reports from the conforma-reporter GitHub repo, and raw EC JSON from Konflux PipelineRuns via the Tekton Results API.
allowed-tools: Bash(python3:*,gh:*,oc:*,curl:*,jq:*,awk:*,sed:*)
user-invocable: true
---

# Conforma Report Fetch

Fetch conforma reports from two independent sources:

1. **Tekton JSON reports** (`fetch_tekton_report.sh`) -- raw Enterprise Contract (EC) verification report JSON fetched directly from a Konflux PipelineRun via the Tekton Results API. **This is the preferred source** because it reflects the exact state of the most recent verification run in real time.
2. **CSV violation reports** (`fetch_csv_reports.py`) -- historical per-release violation data from the `conforma-reporter` GitHub repo. CSV reports are generated on a schedule and **may be hours or days behind** the latest Konflux pipeline results. Use CSVs for historical trend analysis, cross-release comparisons, or when Konflux/VPN access is unavailable.

**Default choice: Tekton (Konflux).** When the user asks to "fetch a conforma report" without specifying a source, prefer the Tekton JSON mode if a PipelineRun name is available or can be looked up. Fall back to CSVs when the user wants a broad cross-release overview, historical data, or cannot connect to the Konflux cluster.

---

## 1. CSV Violation Reports (GitHub)

> **Staleness warning:** CSV reports are generated on a schedule by the `conforma-reporter` CI job and committed to the repo. They can lag behind the live Konflux state by hours or days. When using CSV data, always inform the user of the report's `created_at` timestamp (returned by the fetch script) so they know how current it is. For the freshest data, use the Tekton JSON mode instead.

Downloads CSV violation reports from each release branch of the private `red-hat-data-services/conforma-reporter` repository via `raw.githubusercontent.com`. Handles multi-megabyte files reliably without GitHub Contents API size limits.

### Prerequisites

See [README.md](README.md) for installation and shared prerequisites.

**Auth check:**

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```

### Data Source

- **Repo**: `red-hat-data-services/conforma-reporter` (private)
- **Branch per release**: `rhoai-2.25`, `rhoai-3.3`, `rhoai-3.4`, etc.
- **Columns**: `type`, `component_name`, `image`, `message`, `effective_on`, `code`, `title`, `description`, `solution`

The script tries multiple CSV paths within the `prod/` directory in order for both violations and warnings:

**Violations** (`conforma-violations-report.csv`):
1. `prod/release_day/conforma-violations-report.csv` (primary)
2. `prod/future/build_type_latest/conforma-violations-report.csv`
3. `prod/future/build_type_nightly/conforma-violations-report.csv`

**Warnings** (`conforma-warnings-report.csv`, fetched by default):
1. `prod/release_day/conforma-warnings-report.csv` (primary)
2. `prod/future/build_type_latest/conforma-warnings-report.csv`
3. `prod/future/build_type_nightly/conforma-warnings-report.csv`

If `release_day` is unavailable (e.g. for in-development versions), the script automatically falls back to the next available report. Use `--no-warnings` to skip fetching warnings CSVs.

### Usage

```bash
# Auto-detect releases, auto-create .work/<timestamp>/:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py

# Explicit releases:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py --releases rhoai-2.25,rhoai-3.4

# Explicit output directory (used by conforma-analyze):
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --releases rhoai-3.4 \
  --output-dir /path/to/output

# Skip fetching warnings CSVs:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py --no-warnings

# Use pre-downloaded CSVs instead of fetching:
python3 skills/conforma-report-fetch/scripts/fetch_csv_reports.py \
  --local-dir /path/to/csvs
```

When `--output-dir` is omitted, the script creates a timestamped directory under `.work/` (relative to this skill) and updates the `.work/latest` symlink. The output directory contains `{release}.csv` (violations) and `{release}-warnings.csv` (warnings) for each release.

### Release Auto-Detection

When `--releases` is omitted, the script fetches the list of supported release branches from [`rhoai-release-data.yaml`](https://github.com/red-hat-data-services/rhods-devops-infra/blob/main/src/config/rhoai-release-data.yaml) in `rhods-devops-infra`. This is the single source of truth for which RHOAI versions are currently supported, including EA/in-development releases.

Some in-development/EA branches may not have a violations report CSV yet. The script reports failures per release -- this is expected and not a blocker.

### Handling User-Provided URLs

If the user provides a GitHub URL to a specific report (e.g. `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.4/prod/release_day/conforma-violations-report.csv`), extract the release branch from the URL path (the segment after `/blob/` and before the next `/`) and pass it via `--releases`.

---

## 2. Tekton JSON Reports (Konflux) — Preferred

Fetch the raw EC verification report JSON for a specific PipelineRun directly from the Konflux cluster. This is the **most up-to-date source** — it reads the exact output of the verification run, with no scheduled-job lag. Uses the Tekton Results API as the primary data source, with automatic fallback to live pod container logs when archive data is not yet populated.

The output is a handover state document that records fetch status and the path to the raw report file. Downstream tools (e.g. `conforma-parse`) consume this handover -- they MUST check `report_fetch.status`, not the script exit code. The script exits non-zero if it cannot resolve any required infrastructure coordinate (PipelineRun UUID, verify TaskRun, or log record) and no handover is produced. It exits 0 with `report_fetch.status: "failed"` if the run was found but report extraction failed.

### Prerequisites

See [README.md](README.md) for shared prerequisites. Tekton mode requires these additional tools:

- **VPN**: Connected to the corporate VPN (required for internal Tekton Results API domain routing)
- **`oc` CLI**: Installed and authenticated to the Konflux cluster:
  ```bash
  oc login --server=$KONFLUX_INTERNAL_API
  ```
- **`jq`**: Installed (used for JSON parsing and handover assembly)
- **`curl`**, **`awk`**, **`sed`**: Standard Unix tools (used for API requests and log extraction)
- **Namespace access**: Read access to the namespace specified by `KONFLUX_NAMESPACE`
- **Environment variables** (via `site-config.yaml` or explicit export):
  - `KRD_CLUSTER_DOMAIN` — Konflux cluster domain (Tekton route and API URL are derived from this)
  - `KONFLUX_NAMESPACE` — target Konflux namespace

### Usage

```bash
skills/conforma-report-fetch/scripts/fetch_tekton_report.sh <pipelinerun-name> --output /tmp/conforma-handover.json
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `<pipelinerun-name>` | yes | -- | Konflux PipelineRun name (positional argument). Trailing `-verify` is stripped automatically if present. |
| `--handover` | no | -- | Path to an existing handover JSON to update (preserves state from prior steps) |
| `--output` | no | stdout | Path to write the updated handover JSON |
| *(stdin pipe)* | no | -- | Alternative to `--handover`: pipe a handover JSON via stdin (e.g. `echo '{}' \| skills/conforma-report-fetch/scripts/fetch_tekton_report.sh <name>`) |

### Environment Variables

| Variable | Description |
|---|---|
| `KONFLUX_TOKEN` | Optional. Bearer token for cluster auth. Falls back to `oc whoami -t` if unset. |
| `KRD_CLUSTER_DOMAIN` | Required (unless `TEKTON_RESULTS_DOMAIN` is set). Cluster domain — Tekton route is derived automatically. |
| `KONFLUX_NAMESPACE` | Required. Target Konflux namespace. |
| `TEKTON_RESULTS_DOMAIN` | Optional. Overrides the Tekton Results hostname (derived from `KRD_CLUSTER_DOMAIN` by default). |

### Handover Output

```json
{
  "metadata": {
    "pipeline_run": "conforma-registry-rhoai-prod-v3-4-future-abc123",
    "namespace": "<KONFLUX_NAMESPACE>",
    "created_at": "2026-06-05T14:00:00Z",
    "policy_source": "github.com/conforma/config//default"
  },
  "report_fetch": {
    "status": "completed",
    "completed_at": "2026-06-05T14:00:05Z",
    "raw_report_path": "/tmp/conforma-report-<uuid>.json",
    "error": null
  },
  "violation_parse": null,
  "investigation": null
}
```

The raw EC JSON report is written to `/tmp/` (path recorded in `raw_report_path`). It is not embedded in the handover.

### Workflow

When the user asks to fetch a Conforma report from a PipelineRun:

1. **Get the PipelineRun name** from the user. They typically copy this from the Konflux UI.

2. **Run the fetch script**:
   ```bash
   skills/conforma-report-fetch/scripts/fetch_tekton_report.sh <pipelinerun-name> --output /tmp/conforma-handover.json
   ```

3. **Check the handover output**: Read the handover JSON. If `report_fetch.status` is `"completed"`, the raw report is at the path in `report_fetch.raw_report_path`. If `"failed"`, report the error from `report_fetch.error`.

4. **Pass downstream**: Hand the state file to the next pipeline step (e.g. `conforma-parse`).

---

## Relationship to Other Skills

- **`conforma-analyze`**: Consumes both violation and warnings CSV reports from this skill. Calls `fetch_csv_reports.py` with `--output-dir` to write CSVs into its own `.work/` directory, then parses violations and identifies upcoming violations from warnings.
- **`conforma-parse`** (downstream): Consumes the Tekton handover from `fetch_tekton_report.sh` to parse violations and warnings from the raw JSON report.
- **`conforma-exception`**: Manages exception creation. Can consume parsed output from either fetch mechanism.
