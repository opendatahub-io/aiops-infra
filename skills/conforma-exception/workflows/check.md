## References (load these before executing)

No additional references needed.

---

# Check Workflow

## Prerequisites

**Setup:** See [README.md](../README.md) for installation and one-time authentication setup.

**Always run preflight first** before creating any tickets or Merge Requests:

```bash
python3 skills/conforma-exception/scripts/verify_auth.py
```

**Component-maturity catalog** (required for RHOAIENG tickets): The Jira Component field is **mandatory** on all RHOAIENG tickets created by this skill. The catalog is auto-cloned by the orchestrator when needed. To set up manually:

```bash
python3 scripts/component_catalog_ops.py ensure-repo
```

Jira Component values are auto-resolved from the catalog by mapping Konflux component names to their corresponding Jira Component. If auto-resolution fails (component not found in the catalog), ticket creation is **blocked** and the agent must ask the user for the correct Jira Component name, then pass it via `--jira-components`. No RHOAIENG ticket is created without this field.


## Listing, Searching, and Watchers

For instructions on listing current exceptions (`list_exceptions.py`), searching open Merge Requests (`search_open_mrs.py`), and managing Jira watchers (`add_jira_watchers.py`), read `references/tool-reference.md`.


