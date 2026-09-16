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

## Long-running steps (>30s)

Some conforma scripts run for several minutes — most notably the CSV report fetch (`fetch_csv_reports.py`) and the `ec validate` coverage cross-reference (`violations_coverage.py`). The agent's foreground command tool is hard-capped at ~30s, so running these in the foreground always times out.

**Do NOT** move a long-running step to the background with a raw `nohup ... &` and then poll it with a repeated `sleep; ps; tail` command. A polling loop whose commands are byte-for-byte identical each round is indistinguishable from a stuck agent, and the harness's "repeated identical call" loop detector (5–6 consecutive identical `run_commands` calls) aborts the task. This is a known, recurring failure mode.

Instead, route every long-running step through the deterministic long-task runner, which owns both the background launch and the wait loop:

```bash
# 1. Launch the step in the background:
~/.conforma/bin/conforma_run.sh scripts/run_long_task.py launch <step> <script-path>

# 2. Run the exact next_command from the launch JSON (a wait call):
~/.conforma/bin/conforma_run.sh scripts/run_long_task.py wait <step> --seq 1 --timeout 25
```

Each `wait` round blocks up to ~25s (below the foreground cap), then returns JSON with `status` (`running` / `done` / `failed`) and a new `next_command` whose `--seq` has incremented. **Run the returned `next_command` verbatim** — never edit or re-derive it — and repeat until `status` is `done` or `failed`. The incrementing `--seq` guarantees that no two wait-loop commands are ever byte-identical, so the loop detector cannot fire no matter how long the step runs. The script decides what to run next; the agent is a pure relay.

State is persisted to `<run_dir>/<step>.state.json`, `<run_dir>/<step>.log`, and `<run_dir>/<step>.exit`, so a killed or restarted agent can resume from the files without re-launching. On `status: "failed"`, read `<run_dir>/<step>.log` and report the error before continuing.

The runner is defined in `scripts/run_long_task.py` (dual-mode CLI + importable). This rule is tool-agnostic and applies to every conforma skill, not just `conforma-analyze`.

