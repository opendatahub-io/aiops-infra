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
- Inter-skill data flows through `context.yaml` files in `~/.conforma/` run directories
- The `conforma` skill is the single entry point for all conforma-related queries

## Secrets Policy

**NEVER ask the user to paste tokens, API keys, or credentials into the chat window.** Always instruct them to write secrets to `~/.conforma/.env` directly (using their editor or terminal). The `~/.conforma/` directory is loaded automatically by `_setup_env.py` and `konflux_environment.load()`. See [CONTRIBUTING.md](CONTRIBUTING.md#secrets-and-credentials-policy) for details.

## Repository Clone Policy

Never use a pre-existing local clone of a repo. Always clone fresh into `~/.conforma/` or use the existing `~/.conforma/` clone with `git fetch` first. If the fetch fails, **abort** — never silently use stale data. See [CONTRIBUTING.md](CONTRIBUTING.md#repository-clone-policy) for details.

## Script Failure Policy

When a deterministic script or skill workflow fails (import errors, missing dependencies, auth failures, unexpected exceptions), the agent MUST:

1. **Stop** -- do not silently fall back to manual exploration, ad-hoc cloning, or AI-improvised alternatives.
2. **Report** -- tell the user which script failed, the exact error, and what step of the workflow was interrupted.
3. **Ask** -- present the user with three choices:
   - **(Recommended)** Fix the underlying script/skill issue and retry the deterministic path.
   - File a GitHub issue for the skill maintainer with full error context (uses `conforma-feedback` skill's `from-error` mode). Use `classify-error` first to check if the error matches a known infrastructure pattern.
   - Proceed with AI-assisted manual exploration, with the explicit warning that results may be incomplete, inconsistent, or different from the established workflow output.

The deterministic scripted path is always the default. Manual exploration is a last resort that requires explicit user consent.

## Conforma Report Analysis Policy

Conforma violation reports MUST ONLY be analyzed through the full deterministic `conforma-analyze` workflow (steps 1–7). The agent MUST NEVER:

- Produce ad-hoc or "quick" summaries of report data outside the prescribed workflow
- Run analysis scripts with shortcuts (`--csv` directly, `| head`, `| tail`, truncation)
- Skip workflow steps (fetch → parse → analyze with ownership → coverage check → generate resolution guide)
- Manually read, interpret, or summarize CSV file contents
- Present partial analysis output as a stand-in for the complete workflow output

If only report existence is asked, confirm existence and ask whether to run the full analysis. **This is a hard failure rule — no exceptions, no "just this once."**

## Repository Structure

- `scripts/` — shared automation scripts (54 onboarding + `*_ops.py` primitives)
- `skills/` — conforma skills (`.cursor/skills` is a symlink here)
- `.claude/skills/` — onboarding pipeline skills
- `tests/` — unit and integration tests
- `schemas/` — JSON schemas for validation
- `docs/` — skill documentation and RFDs

## User Coding Preferences

These are established preferences extracted from repeated user corrections across historical sessions.
Follow them in ALL generated content — code, comments, commit messages, documentation, and conversation.

### Terminology

- **Never abbreviate** in user-facing output (chat, reports, docs, comments). Always spell out full terms. Abbreviations are only acceptable in internal variable names, log prefixes, and non-rendered code comments.
- Always write "Merge Request" in full (never abbreviate to "MR" or "MRs")
- Always write "Pull Request" in full (never abbreviate to "PR")
  - Exception: GitHub CLI commands (e.g. `gh pr create`) use the short form
- Use "violations" not "rules" when referring to conforma coverage counts (e.g. "4 of 7 violations covered" not "4 of 7 rules covered")
- Always use "violation code" — never bare "code" or "rule" when referring to the Conforma policy identifier. "Rule" is acceptable only when quoting Conforma engine output verbatim.
- "Violations" always means atomic instances: 1 violation = 1 unique (violation code + component + semantic detail) triple. The semantic detail is the actionable root cause (e.g., repo ID, attribute name, package name). Multiple CSV rows with different image digests or package PURLs sharing the same root cause are the SAME violation. Never use code-level counts as the primary coverage metric. Express coverage as "X of Y violations covered".
- Use "No exception coverage" not "No coverage" — be explicit about what kind of coverage
- Use "Exception granted, violation should disappear on next Conforma run" not "Exception active"
- Use "Rerun Conforma report in Konflux/GitHub and verify the violation is gone from the report" not vague phrases like "Verify on next compliance evaluation"
- Use "KONFLUX_TENANT" not "TENANT" — variable names must be self-explanatory
- Conforma is RHOAI-only — never refer to it as "ODH/RHOAI Conforma" or imply ODH coverage
- Never use "EC" anywhere — always use "Conforma". This applies to all contexts: variable names, function names, documentation, conversation, plans, comments, commit messages. "EC" is a legacy name that no longer exists. Examples: say "Conforma engine" not "EC engine", "Conforma exclusion hint" not "EC hint", "Conforma policy" not "EC policy".
- Use "Executive Summary" not "Key Takeaways" for report summary sections
- Use "manual search" or "search manually" for actionable search links — not bare "search"
- Merge Request titles for exceptions must be prefixed with [stage] or [prod]

### Behavior and Workflow

- **Maximum determinism**: All logic MUST live in scripts. The AI presents script output verbatim. Leave nothing to LLM interpretation.
- **Never ask for tokens/secrets in chat**: Always instruct the user to write credentials to `~/.conforma/.env` directly.
- **Never auto-submit**: Always show output to the user first and ask for explicit confirmation before publishing, submitting, or pushing anything.
- **Missing auth is a hard stop**: If authentication fails or is missing (GitHub, GitLab, Jira, Slack), stop completely. Never skip a data source or produce incomplete reports.
- **Don't add unrequested files**: Never create files (Makefiles, configs, etc.) the user didn't ask for.
- **Always write tests**: Every new testable script or function must have a corresponding test.
- **Fix root causes**: Never apply ad-hoc workarounds. Fix the underlying issue in the script/skill.
- **Don't depend on external CLI tools** when Python libraries can do the same job (e.g. prefer `requests` over shelling out to `gh` or `glab`).
- **Scripts handle their own env vars**: The user should never see approval prompts for environment variable access. Scripts load from `~/.conforma/.env` internally.
- **Never answer confidently from dummy/example data**: If data retrieval failed, say so. Never fabricate or infer from placeholder values.
- **Never silently skip data sources**: If Slack, Jira, or any source is unreachable, report it explicitly — do not silently omit it.
- **Don't launch heavyweight subagents** when a direct file read suffices. Route queries efficiently.
- **Auto-discover values from context**: Infer KONFLUX_APPLICATION, cluster domains, etc. from the user's query rather than asking the user to provide them manually.
- **Confirmation-before-action**: Show analysis results before offering next-step actions. Never assume the user wants to proceed.

### Structure and Formatting

- Show TODO progress checklist before running multi-step workflows
- One component per table row (never combine multiple components in a single row)
- List policy files as bullets, not comma-delimited
- Exception links belong in the resolution guide section, not the summary table
- Components column must always be populated, even for fully-covered violations
- Reports must have an Executive Summary section above the main table
- Source CSV references must link to exact git commit hash, not branch name (branches are moving targets)
- Report header must identify which specific report version was analyzed
- Next-steps column: keep brief (one line). Detailed steps go in the resolution guide below.
- Keep skill READMEs short — installation instructions only. Operational details belong in the skill workflow itself.
- When violations are fully covered by exceptions, the resolution guide should say "rerun Conforma" — not show full remediation steps.

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
