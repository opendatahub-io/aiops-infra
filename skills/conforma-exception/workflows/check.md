## References (load these before executing)

No additional references needed.

---

# Check Workflow

## Prerequisites

**Setup:** See [README.md](../README.md) for installation and one-time authentication setup.

**Always run preflight first** before creating any tickets or Merge Requests:

```bash
~/.conforma/bin/conforma_run.sh skills/conforma-exception/scripts/verify_auth.py
```

**Component-maturity catalog** (required for RHOAIENG tickets): The Jira Component field is **mandatory** on all RHOAIENG tickets created by this skill. The catalog is auto-cloned by the orchestrator when needed. To set up manually:

```bash
~/.conforma/bin/conforma_run.sh scripts/component_catalog_ops.py ensure-repo
```

Jira Component values are auto-resolved from the catalog by mapping Konflux component names to their corresponding Jira Component. If auto-resolution fails (component not found in the catalog), ticket creation is **blocked** and the agent must ask the user for the correct Jira Component name, then pass it via `--jira-components`. No RHOAIENG ticket is created without this field.


### Steps

**Script path convention**: Every command below uses `~/.conforma/bin/conforma_run.sh` to resolve the aiops-infra repo root and dispatch to the target Python script. Do NOT use bare `python3` paths — always use the wrapper.

0. **Resolve aiops-infra root (REQUIRED before any script)**: Run with Bash description: `"Resolve aiops-infra repository root and create run context"`:

```bash
[ -x ~/.conforma/bin/conforma_run.sh ] || { _R="${AIOPS_INFRA_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo $HOME/.local/share/aiops-infra)}"; mkdir -p ~/.conforma/bin; cp "$_R/scripts/conforma_run.sh.tpl" ~/.conforma/bin/conforma_run.sh; chmod +x ~/.conforma/bin/conforma_run.sh; }
~/.conforma/bin/conforma_run.sh scripts/init_conforma_run.py "<describe_the_request>"
```

   If the output path does not contain a `pyproject.toml`, stop and instruct the user to set `AIOPS_INFRA_ROOT` or clone the repo to `~/.local/share/aiops-infra`.


## Listing, Searching, and Watchers

For instructions on listing current exceptions (`list_exceptions.py`), searching open Merge Requests (`search_open_mrs.py`), and managing Jira watchers (`add_jira_watchers.py`), read `references/tool-reference.md`.


