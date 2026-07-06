# Lifecycle Workflow

## Prerequisites

**Setup:** See [README.md](README.md) for installation and one-time authentication setup.

**Always run preflight first** before creating any tickets or Merge Requests:

```bash
python3 skills/conforma-exception/scripts/verify_auth.py
```

**Component-maturity catalog** (required for RHOAIENG tickets): The Jira Component field is **mandatory** on all RHOAIENG tickets created by this skill. The catalog is auto-cloned by the orchestrator when needed. To set up manually:

```bash
python3 scripts/component_catalog_ops.py ensure-repo
```

Jira Component values are auto-resolved from the catalog by mapping Konflux component names to their corresponding Jira Component. If auto-resolution fails (component not found in the catalog), ticket creation is **blocked** and the agent must ask the user for the correct Jira Component name, then pass it via `--jira-components`. No RHOAIENG ticket is created without this field.


## Remote Data Access Policy

When fetching data from remote repositories (GitLab, GitHub):

- **ALWAYS** use the remote API directly (`glab api`, `gh api`, raw HTTP download via `curl`)
- **NEVER** use `find` to locate local clones, `cd` into them, or `git checkout`/`git show` on a local working tree
- **NEVER** assume a local clone is up-to-date or on the correct branch

Local clones on a dev workstation may be on a feature branch, days out of date, or modified with uncommitted changes. Using the remote API guarantees you always read the canonical, production state of the repository at the exact ref you specify.

```bash
# GOOD — fetch a file from GitLab
glab api "projects/releng%2Fkonflux-release-data/repository/files/path%2Fto%2Ffile.yaml/raw?ref=main" \
  --hostname $GITLAB_HOST

# BAD — using a local clone
cd ~/dev/gitlab/releng/konflux-release-data && git show origin/main:path/to/file.yaml
```


## Reconcile Mode

The `--reconcile TICKET_KEY` flag on `create_jira_ticket.py` enables idempotent re-runs:

```bash
python3 skills/conforma-exception/scripts/create_jira_ticket.py --project PSX \
  --reconcile PSX-1098 \
  --rule rpm_signature.allowed:9386b48a1a693c5c \
  --components odh-workbench-jupyter-pytorch-rocm-py312-v2-25 \
  --rhoai-version rhoai-2.25 \
  --effective-until 2027-05-03T00:00:00Z \
  --rhoaieng-url https://redhat.atlassian.net/browse/RHOAIENG-38426 \
  --template rpm_signature_thirdparty \
  --vendor-tag AMD \
  --authorized-party "Len DiMaggio"
```

Behavior:
- Reads the ticket's current state via REST API
- Computes what's missing (labels, links, description, authorized party, Jira Component)
- Applies **only** the needed changes (including Jira Component on RHOAIENG tickets)
- Ends with full verification
- Returns `"status": "reconciled"` if all checks pass, `"status": "partial"` if unmet expectations remain

This handles cases where a previous run partially succeeded (ticket created but fields missing).


## Existing Exception Deduplication

Handled deterministically by `create_gitlab_mr.py` → `apply_exception_to_policy_file()`. The behavior is governed by `preflight_check.py` → `hard_rules.old_style_exception_handling` and `hard_rules.matching_componentNames_exception_handling`. The agent does not make deduplication decisions — the script detects existing exceptions and applies the correct action automatically.


## Managing Exceptions

For the full workflow on discovering, assessing, and handling expired/active exceptions (extend, modernize, narrow, remove), read `references/managing-exceptions-workflow.md`.


