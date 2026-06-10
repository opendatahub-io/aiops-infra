# aiops-infra

AI-powered automation for ODH/RHOAI component onboarding and Conforma policy compliance.

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

## Script Failure Policy

When a deterministic script or skill workflow fails (import errors, missing dependencies, auth failures, unexpected exceptions), the agent MUST:

1. **Stop** -- do not silently fall back to manual exploration, ad-hoc cloning, or AI-improvised alternatives.
2. **Report** -- tell the user which script failed, the exact error, and what step of the workflow was interrupted.
3. **Ask** -- present the user with two choices:
   - **(Recommended)** Fix the underlying script/skill issue and retry the deterministic path.
   - Proceed with AI-assisted manual exploration, with the explicit warning that results may be incomplete, inconsistent, or different from the established workflow output.

The deterministic scripted path is always the default. Manual exploration is a last resort that requires explicit user consent.

## Repository Structure

- `scripts/` — shared automation scripts (54 onboarding + `*_ops.py` primitives)
- `skills/` — conforma skills (`.cursor/skills` is a symlink here)
- `.claude/skills/` — onboarding pipeline skills
- `tests/` — unit and integration tests
- `schemas/` — JSON schemas for validation
- `docs/` — skill documentation and RFDs
