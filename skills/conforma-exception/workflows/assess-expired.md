## References (load these before executing)

- `skills/conforma-exception/references/managing-exceptions-workflow.md` (~307 lines)

---

# Assess Expired Workflow

## Prerequisites

**Setup:** See [README.md](../README.md) for installation and one-time authentication setup.

**Always run preflight first** before creating any tickets or Merge Requests:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-exception/scripts/verify_auth.py"
```

**Component-maturity catalog** (required for RHOAIENG tickets): The Jira Component field is **mandatory** on all RHOAIENG tickets created by this skill. The catalog is auto-cloned by the orchestrator when needed. To set up manually:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/component_catalog_ops.py" ensure-repo
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


### Steps

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


## Managing Exceptions

For the full workflow on discovering, assessing, and handling expired/active exceptions (extend, modernize, narrow, remove), read `references/managing-exceptions-workflow.md`.


