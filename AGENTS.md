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

## Secrets Policy

**NEVER ask the user to paste tokens, API keys, or credentials into the chat window.** Always instruct them to write secrets to the project's designated env file directly (using their editor or terminal). See [CONTRIBUTING.md](CONTRIBUTING.md#secrets-and-credentials-policy) for details.

## Repository Clone Policy

Never use a pre-existing local clone of a repo. Always clone fresh into the designated work directory or use an existing clone with `git fetch` first. If the fetch fails, **abort** — never silently use stale data. See [CONTRIBUTING.md](CONTRIBUTING.md#repository-clone-policy) for details.

## Script Failure Policy

When a deterministic script or skill workflow fails (import errors, missing dependencies, auth failures, unexpected exceptions), the agent MUST:

1. **Stop** -- do not silently fall back to manual exploration, ad-hoc cloning, or AI-improvised alternatives.
2. **Report** -- tell the user which script failed, the exact error, and what step of the workflow was interrupted.
3. **Ask** -- present the user with three choices:
   - **(Recommended)** Fix the underlying script/skill issue and retry the deterministic path.
   - File a GitHub issue for the skill maintainer with full error context.
   - Proceed with AI-assisted manual exploration, with the explicit warning that results may be incomplete, inconsistent, or different from the established workflow output.

The deterministic scripted path is always the default. Manual exploration is a last resort that requires explicit user consent.

## Repository Structure

- `scripts/` — shared automation scripts (onboarding + `*_ops.py` primitives)
- `skills/` — conforma and other skills (`.cursor/skills` is a symlink here)
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

### Behavior and Workflow

- **Maximum determinism**: All logic MUST live in scripts. The AI presents script output verbatim. Leave nothing to LLM interpretation.
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
- Solutions must work with minimal dependencies, across different environments
