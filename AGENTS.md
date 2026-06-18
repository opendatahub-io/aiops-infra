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
- Inter-skill data flows through YAML files in `.work/` (git-ignored)
- The `conforma` skill is the single entry point for all conforma-related queries

## Secrets Policy

**NEVER ask the user to paste tokens, API keys, or credentials into the chat window.** Always instruct them to write secrets to `.work/.env` directly (using their editor or terminal). The `.work/` directory is gitignored and loaded automatically by `_setup_env.py` and `konflux_environment.load()`. See [CONTRIBUTING.md](CONTRIBUTING.md#secrets-and-credentials-policy) for details.

## Repository Clone Policy

Never use a pre-existing local clone of a repo. Always clone fresh into `.work/` or use the existing `.work/` clone with `git fetch` first. If the fetch fails, **abort** — never silently use stale data. See [CONTRIBUTING.md](CONTRIBUTING.md#repository-clone-policy) for details.

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
