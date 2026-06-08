---
description: Repository architecture and contribution conventions for aiops-infra
globs:
  - "**/*.py"
  - "**/*.md"
  - "skills/**/*"
  - "scripts/**/*"
  - "tests/**/*"
---

# Repository Architecture

Before making changes to this repository, read:

- **[ARCHITECTURE.md](../../ARCHITECTURE.md)** — design principles, skill inventory, shared script conventions, inter-skill handover patterns, and key architectural decisions
- **[CONTRIBUTING.md](../../CONTRIBUTING.md)** — how to write scripts (dual-mode pattern), where to put code (decision tree), testing requirements, and skill structure

## Quick Reference

- Shared primitives: `scripts/*_ops.py` (dual-mode: CLI + importable)
- Domain logic: `skills/<name>/scripts/` (imports from `*_ops.py` via `_setup_env.py`)
- Every new script MUST have a test in `tests/unit/`
- Test naming: `test_<script>.py` for repo-root scripts, `test_<skill_underscored>_<script>.py` for skill scripts
- Inter-skill data: YAML files in `.work/` with skill-name top-level key
