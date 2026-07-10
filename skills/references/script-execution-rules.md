# Script Execution Rules

Rules that apply to every conforma skill workflow that runs Python scripts. These are agent-agnostic — they apply regardless of the AI platform (Cursor, Claude Code, etc.).

## Script Paths and Repo Root (HARD REQUIREMENT)

Every `python3` command in conforma workflows uses the `$_R` variable prefix to reference the aiops-infra repo root. This prefix is resolved from `context.yaml` at the start of each Bash command:

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/foo.py"
```

The `context.yaml` file is created by **Step 0** of every workflow, which resolves the repo root and stores it in a timestamped run directory under `~/.conforma/`. The `.conforma-active` symlink points to the current run.

**Do NOT** remove or modify the `_R="..."` prefix from any command. It ensures scripts are found regardless of the current working directory, the model executing the workflow, or whether the skill was installed remotely via `claude skill install`.

**Do NOT** use bare `_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/...`" or `python3 skills/...` paths — always use `python3 "$_R/scripts/..."` or `python3 "$_R/skills/..."`.

## Network Access

All conforma scripts call external APIs (GitHub, GitLab, Jira, Slack). The agent MUST ensure unrestricted network access is available **before** running any conforma Python script.

Platform-specific mechanisms:
- **Cursor**: pass `required_permissions: ["full_network"]` on the Shell tool invocation
- **Claude Code**: use `--dangerously-skip-permissions` or approve network access when prompted
- **Other platforms**: disable network sandboxing for conforma script invocations

**Never run a conforma script in a restricted sandbox and then retry with permissions after it fails.** The retry-after-failure pattern wastes time, confuses the user, and is always avoidable because the network requirement is known in advance.

Scripts that require network access:
- `scripts/verify_conforma_prerequisites.py`
- `scripts/resolve_release_context.py`
- `scripts/component_catalog_ops.py`
- `skills/conforma-*/scripts/*.py`
- `skills/conforma-report-fetch/scripts/*.py`
- `skills/conforma-tooling-health/scripts/*.py`
- Any `python3` invocation that imports from `scripts/*_ops.py`

## Failure Handling

When a script fails, the agent MUST NOT silently work around the failure with ad-hoc alternatives (manual cloning, direct API calls, improvised analysis). Follow the Script Failure Policy in CLAUDE.md: stop, report, and ask the user before proceeding.

## VPN Connectivity

When a workflow is blocked on VPN connectivity (e.g. GitLab/catalog clone fails), phrase the retry message as: "Connect to the Red Hat VPN, then tell me to continue" — not "re-run the workflow". The agent can pick up where it left off without requiring the user to re-invoke the full command.
