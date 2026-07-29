# Script Execution Rules

Rules that apply to every conforma skill workflow that runs Python scripts. These are agent-agnostic — they apply regardless of the AI platform (Cursor, Claude Code, etc.).

## Script Paths and Repo Root (HARD REQUIREMENT)

Every script invocation in conforma workflows uses the `~/.conforma/bin/conforma_run.sh` wrapper. The wrapper resolves the aiops-infra repo root internally and dispatches to the target Python script:

```bash
~/.conforma/bin/conforma_run.sh scripts/foo.py --arg1 val1
~/.conforma/bin/conforma_run.sh skills/conforma-analyze/scripts/bar.py --help
```

The wrapper's resolution chain (first match wins):
1. `~/.conforma/.conforma-active/context.yaml` → `aiops_infra_root` key
2. `$AIOPS_INFRA_ROOT` environment variable
3. `git rev-parse --show-toplevel`
4. `~/.local/share/aiops-infra` fallback

The `context.yaml` file is created by **Step 0** of every workflow via `init_conforma_run.py`, which resolves the repo root and stores it in a timestamped run directory under `~/.conforma/`. The `.conforma-active` symlink points to the current run. Step 0 also installs/refreshes the wrapper from the repo template `scripts/conforma_run.sh.tpl`.

**Do NOT** use bare `python3 scripts/...` or `python3 skills/...` paths — always use the wrapper.

**Do NOT** inline the repo-root resolution (the old `_R="$(grep...)"` pattern) — the wrapper handles this internally.

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
