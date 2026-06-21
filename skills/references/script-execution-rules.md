# Script Execution Rules

Rules that apply to every conforma skill workflow that runs Python scripts. These are agent-agnostic — they apply regardless of the AI platform (Cursor, Claude Code, etc.).

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
