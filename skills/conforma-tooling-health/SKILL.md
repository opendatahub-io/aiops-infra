---
name: conforma-tooling-health
description: Check the health of conforma infrastructure tools (GitHub Actions workflows). Reports status, classifies failures against known failure modes, and surfaces actionable remediation steps.
allowed-tools: Bash(python3:*,git:*)
user-invocable: true
---

# Conforma Tooling Health

Check the health of conforma infrastructure tools -- starting with the `conforma-reporter` GitHub Action. Queries the GitHub Actions API for recent workflow runs, classifies health status, and matches failures against known failure modes from the [tooling-health-catalog.yaml](../references/tooling-health-catalog.yaml).

## Quick Start

This skill is part of the conforma suite in [aiops-infra](https://github.com/opendatahub-io/aiops-infra).

**Setup:** See [README.md](../conforma/README.md) for installation and prerequisites. This skill requires GitHub authentication (same as other conforma skills).

## Prerequisites

**Step 0 — Resolve repo root**: Before running any script, ensure `context.yaml` exists with `aiops_infra_root` by running the Step 0 block from the workflow. All `python3` commands below use `$_R` as the repo root prefix, resolved from `context.yaml`.

**Always run the unified prerequisite check first**:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py" --fix
```

Only the `github` check is required for this skill. Other checks (GitLab, Jira, Slack) are not needed.

## Workflow

### Standalone usage

When the user asks about reporter status, tooling health, or workflow status:

0. **Initialize conforma run**: Pass the user's release text to Step 0:

```bash
_R="${AIOPS_INFRA_ROOT:-$(python3 -c 'from _repo_root import REPO_ROOT; print(REPO_ROOT)' 2>/dev/null || git rev-parse --show-toplevel 2>/dev/null)}"
python3 "$_R/scripts/init_conforma_run.py" "<user_release_text>"
```

1. **Prerequisites check**: Run `_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py" --format markdown`. Only github auth is required -- other failures can be ignored for this skill.

2. **Resolve release context**:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/resolve_release_context.py"
```

3. **Check tooling health**: The script reads release, environment, and output path from `context.yaml` automatically. Do NOT pass `--release` or `--output`:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-tooling-health/scripts/check_tooling_health.py"
```

4. **Present results**: Parse the JSON output and present the tooling health table.

   - If `overall_health` is `"healthy"` -- show a brief confirmation with the latest successful run link.
   - If `overall_health` is `"unhealthy"` or `"error"` -- show the full tooling health table with failure classification and remediation steps from the catalog.
   - If `overall_health` is `"in_progress"` -- show the in-progress run details and last completed run.
   - If `overall_health` is `"no_runs"` -- warn that no runs were found for this branch.

### Integration with conforma-analyze

This skill is invoked as **Step 2b** of the `conforma-analyze` workflow (between "Resolve release context" and "Fetch reports"). See the `conforma-analyze` SKILL.md for the full integration details and agent behavior rules.

## Output JSON Schema

```json
{
  "release": "rhoai-3.5-ea.1",
  "checked_at": "2026-06-18T17:00:00Z",
  "tools": [
    {
      "name": "conforma-reporter",
      "type": "github_actions_workflow",
      "workflow_url": "https://github.com/...",
      "total_runs_checked": 5,
      "latest_run": {
        "id": 12345,
        "status": "completed",
        "conclusion": "failure",
        "created_at": "2026-06-17T10:00:00Z",
        "updated_at": "2026-06-17T10:05:00Z",
        "url": "https://github.com/.../actions/runs/12345",
        "head_sha": "abc123def4",
        "run_attempt": 1
      },
      "recent_runs": ["..."],
      "health": {
        "status": "unhealthy",
        "reason": "Latest run failed (2026-06-17)",
        "consecutive_failures": 3,
        "last_success": {
          "id": 12340,
          "completed_at": "2026-06-15T10:05:00Z",
          "url": "..."
        }
      },
      "failure_classification": {
        "id": "ec_policy_timeout",
        "title": "Enterprise Contract evaluation timed out",
        "classification": {"severity": "medium", "typical_owner": "konflux_team", "auto_recoverable": true},
        "remediation": [{"action": "Re-run the workflow -- often transient"}]
      }
    }
  ],
  "overall_health": "unhealthy"
}
```

## Health Statuses

| Status | Meaning |
|--------|---------|
| `healthy` | Latest run succeeded |
| `unhealthy` | Latest run failed or was cancelled |
| `in_progress` | Latest run is still running (queued/in_progress) |
| `no_runs` | No workflow runs found for the branch |
| `error` | API call failed (network, auth, etc.) |

## Failure Classification

When a tool is unhealthy, the script matches failure context against symptom patterns in [`skills/references/tooling-health-catalog.yaml`](../references/tooling-health-catalog.yaml). Each classified failure includes:

- **severity**: high / medium / low
- **typical_owner**: who should fix it (devops, konflux_team, component_team)
- **auto_recoverable**: whether a re-run is likely to fix it
- **remediation**: ordered list of fix actions with optional reference URLs

## Extending to New Tools

To add a new tool to monitor:

1. Add an entry to `skills/references/tooling-health-catalog.yaml` under `tools:`
2. Define failure modes with symptom patterns and remediation steps
3. The script automatically checks all tools listed in the catalog
