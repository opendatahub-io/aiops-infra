## References (load these before executing)

No additional references needed.

---

# Tekton JSON Reports Workflow

Fetch the raw EC verification report JSON for a specific PipelineRun directly from Konflux via the Tekton Results API. This is the **most up-to-date source** — it reads the exact output of the verification run, with no scheduled-job lag.

The script `fetch_conforma_tekton_result.py` accepts either a **version shortcode** (e.g. `3.5`, `3.5ea.2`, `rhoai-3.5`) or an **exact PipelineRun name**. Version shortcodes are automatically resolved to the newest matching multi-component PipelineRun.

Three **policy types** are supported via `--type`: `registry` (default), `chart`, `fbc`. Each type searches for PipelineRuns with a distinct naming prefix.

Configuration is resolved in order: CLI arg > `context.yaml` > env var > default. When `context.yaml` is populated (by `resolve_release_context.py`), no CLI args or env vars are needed beyond the version.

The output is a handover state document that records fetch status and the path to the raw report file. Downstream tools (e.g. `conforma-parse`) consume this handover — they MUST check `report_fetch.status`, not the script exit code.

### Prerequisites

See [README.md](../README.md) for shared prerequisites. Tekton mode requires:

- **VPN**: Connected to the corporate VPN (required for internal Tekton Results API domain routing)
- **`oc` CLI**: Installed and authenticated to the Konflux cluster:
  ```bash
  oc login --server=$KONFLUX_INTERNAL_API
  ```

### Usage

```bash
# By version shortcode (resolves to newest matching PipelineRun):
python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py 3.5 --output /tmp/conforma-handover.json

# By version shortcode with EA suffix:
python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py 3.5ea.2 --output /tmp/conforma-handover.json

# By policy type (chart):
python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py 3.5 --type chart --output /tmp/conforma-handover.json

# FBC policy type:
python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py 3.5ea.1 --type fbc --output /tmp/conforma-handover.json

# By exact PipelineRun name:
python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py conforma-registry-rhoai-prod-v3-5-c7tjp --output /tmp/conforma-handover.json

# Version from context.yaml (after resolve_release_context.py):
python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py --output /tmp/conforma-handover.json
```

### Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `<version-or-name>` | no | from context.yaml | RHOAI version shortcode (e.g. `3.5`, `3.5ea.2`) or exact PipelineRun name. Falls back to `resolve.version_dir` in context.yaml if omitted. |
| `--type` | no | `registry` | Policy type: `registry`, `chart`, or `fbc`. |
| `--namespace` | no | from context/env/default | Konflux namespace. Falls back to `resolve.tenant` in context, then `KONFLUX_NAMESPACE` env, then `rhoai-tenant`. |
| `--cluster-domain` | no | from context/env/default | Konflux cluster domain. Falls back to `resolve.cluster_domain` in context, then `KONFLUX_CLUSTER_DOMAIN` env, then p02 default. |
| `--environment` | no | from context/default | `prod` or `stage`. Falls back to `environment` in context, then `prod`. |
| `--handover` | no | -- | Path to an existing handover JSON to update (preserves state from prior steps). |
| `--output` | no | stdout | Path to write the updated handover JSON. |
| *(stdin pipe)* | no | -- | Alternative to `--handover`: pipe a handover JSON via stdin. |

### Environment Variables

| Variable | Description |
|---|---|
| `KONFLUX_TOKEN` | Optional. Bearer token for cluster auth. Falls back to `oc whoami -t` if unset. |
| `KONFLUX_NAMESPACE` | Optional. Namespace fallback when not in context.yaml. |
| `KONFLUX_CLUSTER_DOMAIN` | Optional. Cluster domain fallback when not in context.yaml. |
| `TEKTON_RESULTS_API_DOMAIN` | Optional. Full Tekton Results API domain override. |

### PipelineRun Discovery

When a version shortcode is provided, the script builds an ITS prefix based on the policy type and searches for matching PipelineRuns:

| Type | ITS prefix pattern | Example match |
|---|---|---|
| `registry` | `conforma-registry-{app}-{env}-{ver}` | `conforma-registry-rhoai-prod-v3-5-c7tjp` |
| `chart` | `conforma-registry-{app}-chart-{env}-{ver}` | `conforma-registry-rhoai-chart-prod-v3-5-abc12` |
| `fbc` | `conforma-fbc-{app}-{env}-{ver}` | `conforma-fbc-rhoai-prod-v3-5-ea-1-xyz99` |

The search uses regex `^{PREFIX}-[a-z0-9]+$` to match only the Tekton random suffix, avoiding GA/EA cross-matching.

Search strategy:
1. Query live cluster PipelineRuns sorted by creation time (fastest)
2. If no primary match: search with `-future` suffix backup
3. Fall back to Tekton Results API archive for pruned runs

### Handover Output

```json
{
  "metadata": {
    "pipeline_run": "conforma-registry-rhoai-prod-v3-5-c7tjp",
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

### Workflow

When the user asks to fetch a Conforma report:

**Script path convention**: Every `python3` command below uses `$_R` to reference the aiops-infra repo root. The `$_R` variable is resolved from `context.yaml` at the start of each command. Do NOT remove or modify the `_R="..."` prefix — it ensures scripts are found regardless of the current working directory.

0. **Resolve aiops-infra root (REQUIRED before any script)**: Run with Bash description: `"Resolve aiops-infra repository root and create run context"`:

```bash
_ROOT="${AIOPS_INFRA_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$_ROOT" ] && _ROOT="$HOME/.local/share/aiops-infra"
[ -f "$_ROOT/pyproject.toml" ] || { echo "ERROR: aiops-infra repo not found at $_ROOT. Set AIOPS_INFRA_ROOT or clone to ~/.local/share/aiops-infra"; exit 1; }
_RUNDIR="$HOME/.conforma/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$_RUNDIR"
cat > "$_RUNDIR/context.yaml" << EOF
aiops_infra_root: $_ROOT
run:
  created_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
  run_dir: ${_RUNDIR/#$HOME/\~}
steps: {}
EOF
ln -sfn "$_RUNDIR" "$HOME/.conforma/.conforma-active"
echo "aiops_infra_root=$_ROOT"
echo "run_dir=$_RUNDIR"
```

   If the output path does not contain a `pyproject.toml`, stop and instruct the user to set `AIOPS_INFRA_ROOT` or clone the repo to `~/.local/share/aiops-infra`.

1. **Get the version or PipelineRun name** from the user. They can provide a version shortcode (e.g. `3.5`, `3.5ea.2`) or an exact PipelineRun name copied from the Konflux UI. Also ask which policy type if not obvious (registry is default).

2. **Run the fetch script**:
   ```bash
   python3 skills/conforma-report-fetch/scripts/fetch_conforma_tekton_result.py <version-or-name> --type <registry|chart|fbc> --output /tmp/conforma-handover.json
   ```

3. **Check the handover output**: Read the handover JSON. If `report_fetch.status` is `"completed"`, the raw report is at the path in `report_fetch.raw_report_path`. If `"failed"`, report the error from `report_fetch.error`.

4. **Pass downstream**: Hand the state file to the next pipeline step (e.g. `conforma-parse`).

---
