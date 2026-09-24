# aiops-infra

AI-powered automation for ODH/RHOAI component onboarding and RHOAI Conforma policy compliance.

## Architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) for design principles, skill inventory, shared script conventions, and key decisions.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for how to write scripts, add tests, structure skills, and submit changes.

## Key Conventions

- Shared primitives live in `scripts/*_ops.py` (dual-mode: CLI + importable)
- Domain-specific logic stays in `skills/<name>/scripts/`
- Every new script MUST have a corresponding test in `tests/unit/`

## Plans

Durable feature/work plans (implementation plans, design records for in-flight work) SHOULD be saved in `.agents/plans/` in this repository — a plain, tool-agnostic location any AI harness can read and write, so plans stay portable across tools (unlike harness-local plan storage such as `~/.claude/plans/`). This is a soft rule: ephemeral single-session scratch plans may still live in the harness's own plan area, but any plan worth reusing or reviewing belongs in `.agents/plans/` and is version-controlled with the work it describes.

### TODO documents (hard rule)

Every TODO or outstanding work item for a skill MUST have its own separate Markdown document in that skill's `todo/` directory: `skills/<skill-name>/todo/<item>.md`. Do not combine multiple independent TODO items in one document. The `todo/README.md` MAY provide an index, status summary, dependencies, and execution order, but it MUST contain only active or outstanding work and MUST link to each item document.

### Completed TODO documents (hard rule)

When a TODO or outstanding work item is completed, its document MUST be moved to the adjacent `done/` directory: `skills/<skill-name>/done/<item>.md`. Completed documents MUST remain as durable implementation and validation records. The `done/README.md` MUST index completed work.

## Secrets Policy

**NEVER ask the user to paste tokens, API keys, or credentials into the chat window.** Always instruct them to write secrets to the project's designated env file directly (using their editor or terminal). See [CONTRIBUTING.md](CONTRIBUTING.md#secrets-and-credentials-policy) for details.

## Development Runtime Filesystem Access

Source code and tests are developed in this repository. Conforma workflow scripts also create and update runtime state under `~/.conforma/`, including run contexts, generated reports, caches, external repository clones, installed helper binaries, and the designated environment file.

When running the repository from a sandboxed development agent, the agent must have write access to `~/.conforma/` in addition to the repository workspace. This access is required by the deterministic scripts themselves; it does not move source development outside the repository. Prefer a session- or repository-scoped writable-root configuration for `~/.conforma/` rather than unrestricted filesystem access. Never commit runtime files or credentials from `~/.conforma/` to this repository.

## Repository Clone Policy

Never use a pre-existing local clone of a repo. Always clone fresh into the designated work directory or use an existing clone with `git fetch` first. If the fetch fails, **abort** — never silently use stale data. See [CONTRIBUTING.md](CONTRIBUTING.md#repository-clone-policy) for details.

## Script Failure Policy

When a deterministic script or skill workflow fails (import errors, missing dependencies, auth failures, unexpected exceptions), the agent MUST:

1. **Stop** -- do not silently fall back to manual exploration, ad-hoc cloning, or AI-improvised alternatives.
2. **Preserve remediation output** -- if the script returns structured output containing a `display`, `instructions`, `fix`, or equivalent user-facing field, relay that field verbatim before adding any failure explanation. Never replace deterministic remediation instructions with a generic summary such as “fix authentication”.
3. **Report** -- tell the user which script failed, the exact error, and what step of the workflow was interrupted.
4. **Ask** -- present the user with three choices:
   - **(Recommended)** Fix the underlying script/skill issue and retry the deterministic path.
   - File a GitHub issue for the skill maintainer with full error context.
   - Proceed with AI-assisted manual exploration, with the explicit warning that results may be incomplete, inconsistent, or different from the established workflow output.

The deterministic scripted path is always the default. Manual exploration is a last resort that requires explicit user consent.

## Repository Structure

- `scripts/` — shared automation scripts (onboarding + `*_ops.py` primitives)
- `skills/` — conforma and other skills (`.cursor/skills` is a symlink here)
- `.agents/plans/` — durable feature/work plans (see Plans above)
- `.claude/skills/` — onboarding pipeline skills
- `tests/` — unit and integration tests
- `schemas/` — JSON schemas for validation
- `docs/` — skill documentation and RFDs

## User Coding Preferences

These are established preferences extracted from repeated user corrections across historical sessions.
Follow them in ALL generated content — code, comments, commit messages, documentation, and conversation.

### Terminology

| Write | Never write | Context |
|-------|-------------|---------|
| Merge Request | MR, MRs | All user-facing text |
| Pull Request | PR | All text (exception: `gh pr` CLI commands) |
| KONFLUX_TENANT | TENANT | Variable names |

- **Never abbreviate** in user-facing output (chat, reports, docs, comments). Abbreviations are only acceptable in internal variable names, log prefixes, and non-rendered code comments.
- Always use "`skills/references/violation-catalog.yaml`](../../references/violation-catalog.yaml" (never "`skills/references/violation-catalog.yaml`](../references/violation-catalog.yaml")
- Always use "README.md](../README.md" (never "README.md](README.md")
- Always use "script-output-presentation.md](../../references/script-output-presentation.md" (never "script-output-presentation.md](../references/script-output-presentation.md")
- Always use "~/.conforma/bin/conforma_run.sh" (never "python3")
- Always use "11" (never "10")

### Behavior and Workflow

- **Maximum determinism**: All logic MUST live in scripts. The AI presents script output verbatim. Leave nothing to LLM interpretation.
- **Conforma routing**: Every ordinary Conforma report, status, violation, scan, or "what is failing" request MUST enter through the `conforma` skill and route to `conforma-analyze`. Do not invoke `conforma-report-fetch` or its scripts directly for these requests. Direct report fetching is reserved for an explicit user request for raw Tekton/PipelineRun data and remains experimental and unfinished; do not use it until this instruction is changed.
- **Never ask for tokens/secrets in chat**: Always instruct the user to write credentials to the project's env file directly.
- **Never auto-submit**: Always show output to the user first and ask for explicit confirmation before publishing, submitting, or pushing anything.
- **Missing auth is a hard stop**: If authentication fails or is missing (GitHub, GitLab, Jira, Slack), stop completely. Never skip a data source or produce incomplete reports.
- **Don't add unrequested files**: Never create files (Makefiles, configs, etc.) the user didn't ask for.
- **Always write tests**: Every new testable script or function must have a corresponding test.
- **Fix root causes**: Never apply ad-hoc workarounds. Fix the underlying issue in the script/skill.
- **Don't depend on external CLI tools** when Python libraries can do the same job (e.g. prefer `requests` over shelling out to `gh` or `glab`).
- **Scripts handle their own env vars**: The user should never see approval prompts for environment variable access.
- **Never answer confidently from dummy/example data**: If data retrieval failed, say so. Never fabricate or infer from placeholder values.
- **Never silently skip data sources**: If Slack, Jira, or any source is unreachable, report it explicitly — do not silently omit it.
- **Don't launch heavyweight subagents** when a direct file read suffices. Route queries efficiently.
- **Auto-discover values from context**: Infer KONFLUX_APPLICATION, cluster domains, etc. from the user's query rather than asking the user to provide them manually.
- **Confirmation-before-action**: Show analysis results before offering next-step actions. Never assume the user wants to proceed.

### Structure and Formatting

- Show TODO progress checklist before running multi-step workflows
- Keep skill READMEs short — installation instructions only. Operational details belong in the skill workflow itself.

### Code Style

- No hardcoding product-specific values (team names, application names) in scripts — discover them dynamically
- Use a single variable for repeated text strings (DRY principle)
- Konflux UI URLs use `konflux-ui.apps.` prefix (not `console.`)
- No backward-compatibility shims unless explicitly requested — remove deprecated paths completely
- Variable and function names must be self-explanatory (reject cryptic abbreviations)

### Tool-Agnosticism

- Skills and rules must NOT depend on any specific AI tool (Cursor, Claude, Copilot, etc.)
- Presentation rules must produce identical output regardless of which AI model executes them
- All rules belong in skill files or AGENTS.md, never in tool-specific config alone
- When a skill catalog provides an alias such as `r0 = /path/to/skills`,
  expand the alias to its mapped root; never treat the alias name (`r0`) as a
  literal directory component. Resolve `r0/<skill>/SKILL.md` as
  `/path/to/skills/<skill>/SKILL.md`.
- Skill-root aliases are catalog notation, not filesystem directories. If an
  alias expansion does not resolve, report the mapped root and attempted
  expanded path; do not retry by inserting the alias name into the path.
- Solutions must work with minimal dependencies, across different environments
