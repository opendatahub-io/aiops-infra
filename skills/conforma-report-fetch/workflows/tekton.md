# Tekton JSON Reports Workflow

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
- **Environment variables** (via infrastructure discovery, or manually in `~/.conforma/.env`):
  - `KONFLUX_CLUSTER_DOMAIN` — Konflux cluster domain (Tekton route and API URL are derived from this)
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
| `KONFLUX_CLUSTER_DOMAIN` | Required (unless `TEKTON_RESULTS_API_DOMAIN` is set). Cluster domain — Tekton route is derived automatically. |
| `KONFLUX_NAMESPACE` | Required. Target Konflux namespace. |
| `TEKTON_RESULTS_API_DOMAIN` | Optional. Overrides the Tekton Results hostname (derived from `KONFLUX_CLUSTER_DOMAIN` by default). |

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

