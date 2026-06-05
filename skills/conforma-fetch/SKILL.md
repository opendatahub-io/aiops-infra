---
name: conforma-fetch
description: Fetch raw Conforma (EC) verification report JSON from a Konflux PipelineRun via the Tekton Results API, with live-pod fallback. Outputs a handover state document for downstream pipeline steps.
allowed-tools: Bash(oc:*,curl:*,jq:*,awk:*,sed:*)
user-invocable: true
---

# Conforma Fetch

Fetch the raw Conforma Enterprise Contract (EC) verification report JSON for a specific PipelineRun from the Konflux cluster. Uses the Tekton Results API as the primary data source, with automatic fallback to live pod container logs when archive data is not yet populated.

The output is a handover state document that records fetch status and the path to the raw report file. Downstream tools (e.g. `conforma-parse`) consume this handover — they MUST check `report_fetch.status`, not the script exit code. The script exits non-zero if it cannot resolve any required infrastructure coordinate — PipelineRun UUID, verify TaskRun, or log record — and no handover is produced. It exits 0 with `report_fetch.status: "failed"` if the run was found but report extraction failed.

## Prerequisites

- **VPN**: Connected to the corporate VPN (required for internal Tekton Results API domain routing)
- **`oc` CLI**: Installed and authenticated to the Konflux cluster:
  ```bash
  oc login --server=https://api.stone-prod-p02.hjvn.p1.openshiftapps.com:6443
  ```
- **`jq`**: Installed (used for JSON parsing and handover assembly)
- **`curl`**, **`awk`**, **`sed`**: Standard Unix tools (used for API requests and log extraction)
- **Namespace access**: Read access to the `rhoai-tenant` namespace

## Workflow

When the user asks to fetch a Conforma report:

1. **Get the PipelineRun name** from the user. They typically copy this from the Konflux UI.

2. **Run the fetch script**:
   ```bash
   ./scripts/conforma-fetch.sh <pipelinerun-name> --output /tmp/conforma-handover.json
   ```

3. **Check the handover output**: Read the handover JSON. If `report_fetch.status` is `"completed"`, the raw report is at the path in `report_fetch.raw_report_path`. If `"failed"`, report the error from `report_fetch.error`.

4. **Pass downstream**: Hand the state file to the next pipeline step (e.g. `conforma-parse`).

## Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `<pipelinerun-name>` | yes | -- | Konflux PipelineRun name (positional argument). Trailing `-verify` is stripped automatically if present. |
| `--handover` | no | -- | Path to an existing handover JSON to update (preserves state from prior steps) |
| `--output` | no | stdout | Path to write the updated handover JSON |
| *(stdin pipe)* | no | -- | Alternative to `--handover`: pipe a handover JSON via stdin (e.g. `echo '{}' \| ./scripts/conforma-fetch.sh <name>`) |

## Environment Variables

| Variable | Description |
|---|---|
| `KONFLUX_TOKEN` | Optional. Bearer token for cluster auth. Falls back to `oc whoami -t` if unset. |

## Handover Output

```json
{
  "metadata": {
    "pipeline_run": "conforma-registry-rhoai-prod-v3-4-future-abc123",
    "namespace": "rhoai-tenant",
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

## Relationship to Other Skills

- **`conforma-analyze`**: Fetches CSV violation reports from the `conforma-reporter` GitHub repo (historical, violations-only, no warnings). Good for cross-release analysis. This skill fetches raw JSON directly from the cluster (fresh, full fidelity, violations + warnings).
- **`conforma-parse`** (downstream): Consumes the handover from this skill to parse violations and warnings from the raw report.
- **`conforma-exception`**: Manages exception creation. Can consume parsed output from either fetch mechanism.
