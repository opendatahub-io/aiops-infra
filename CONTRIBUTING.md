# Contributing

Practical guide for contributing to aiops-infra. For design principles and architecture, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Developer Setup

```bash
# Clone
git clone https://github.com/opendatahub-io/aiops-infra.git
cd aiops-infra

# Install dependencies (choose one)
uv sync --group dev          # preferred (~200ms)
pip install -e ".[dev]"      # fallback

# Set up pre-commit hooks
pre-commit install
```

## Where to Put Code

### Decision tree

```
Is it a generic primitive (works for any project)?
├── YES → scripts/*_ops.py (dual-mode, repo root)
│         Examples: create_mr(), verify_auth(), load_yaml()
│
└── NO → Is it conforma-specific logic used by MULTIPLE skills?
    ├── YES → scripts/conforma_*_ops.py (dual-mode, repo root)
    │         Examples: search_open_exception_mrs(), prefetch_open_jira_tickets()
    │
    └── NO → Is it specific to a SINGLE skill's domain?
        ├── YES → skills/<skill-name>/scripts/<script>.py
        │         Examples: apply_exception_to_policy_file(), _build_psx_description()
        │
        └── NO → Is it a routing/documentation/per-function skill?
            ├── YES → skills/<skill-name>/SKILL.md (no scripts/)
            │         Examples: conforma entry-point, gitlab-auth, search-conforma-open-exception-mrs
            │
            └── NO → scripts/<name>.py (standalone utility)
                      Examples: existing onboarding scripts
```

### Naming conventions

| Location | Convention | Example |
|----------|-----------|---------|
| `scripts/` generic primitives | `*_ops.py` | `gitlab_ops.py`, `jira_ops.py` |
| `scripts/` domain-specific shared | `conforma_*_ops.py` | `conforma_mr_ops.py`, `conforma_policy_ops.py` |
| Skill-local scripts | Descriptive verb-noun | `create_gitlab_mr.py`, `parse_violations.py` |
| Test files (repo-root scripts) | `test_<name>.py` | `test_gitlab_ops.py` |
| Test files (skill scripts) | `test_<skill_underscored>_<name>.py` | `test_conforma_exception_create_gitlab_mr.py` |

## Writing Scripts

### Dual-mode pattern (required for `*_ops.py`)

Every shared script must be both importable and CLI-runnable:

```python
"""example_ops.py -- Example primitives (dual-mode: CLI + importable)."""
import argparse
import json


def do_something(param: str) -> dict:
    """Do something useful. Returns structured result."""
    ...
    return {"ok": True, "result": param}


def main():
    parser = argparse.ArgumentParser(description="Example primitives")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("do-something")
    p.add_argument("--param", required=True)

    args = parser.parse_args()
    if args.command == "do-something":
        result = do_something(args.param)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

**Requirements**:
- Functions return `dict` (JSON-serializable)
- CLI subcommands use kebab-case (`verify-auth`, `create-mr`)
- Functions use snake_case (`verify_auth`, `create_mr`)
- `main()` prints JSON to stdout
- No side effects on import

### Skill-local scripts

Scripts inside `skills/<name>/scripts/` can import shared primitives via `_setup_env.py`:

```python
import _setup_env  # noqa: F401 — adds scripts/ to sys.path, bootstraps deps
import gitlab_ops

result = gitlab_ops.create_mr(
    project_path="releng/konflux-release-data",
    source_branch="my-branch",
    target_branch="main",
    title="Add exception for hermetic_task.hermetic",
)
```

## Skill Structure

```
skills/<skill-name>/
├── SKILL.md                 # Required: skill definition + instructions
├── scripts/                 # Optional: Python scripts
│   ├── _setup_env.py        # Required if importing from scripts/*_ops.py
│   ├── main_script.py
│   └── helper.py
└── references/              # Optional: reference data files
    └── some-data.yaml
```

### SKILL.md format

Every SKILL.md must have a YAML frontmatter block:

```yaml
---
name: conforma-example
description: One-line description of what this skill does.
allowed-tools: Bash(python3:*,gh:*,git:*)
user-invocable: true
---
```

## Testing

### Hard rule

**Every new script MUST have a corresponding test file.** The `check_test_coverage.py` pre-commit hook enforces this. Existing legacy onboarding scripts are exempted via `tests/.test-ignore-list`.

Conforma scripts are NOT exempted — they must always have tests.

### Test file naming

| Script location | Test file |
|----------------|-----------|
| `scripts/gitlab_ops.py` | `tests/unit/test_gitlab_ops.py` |
| `skills/conforma-exception/scripts/create_gitlab_mr.py` | `tests/unit/test_conforma_exception_create_gitlab_mr.py` |

Pattern for skill scripts: dashes in the skill name become underscores, then prefix with `test_`.

### Writing unit tests

```python
"""tests/unit/test_gitlab_ops.py"""
from unittest.mock import MagicMock, patch

import pytest

import gitlab_ops


@pytest.fixture
def mock_gitlab_client():
    with patch("gitlab_ops.gitlab.Gitlab") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


def test_verify_auth_success(mock_gitlab_client):
    mock_gitlab_client.auth.return_value = None
    mock_gitlab_client.user = MagicMock(username="testuser")

    result = gitlab_ops.verify_auth()

    assert result["ok"] is True
    assert result["user"] == "testuser"


def test_verify_auth_failure(mock_gitlab_client):
    mock_gitlab_client.auth.side_effect = Exception("401 Unauthorized")

    result = gitlab_ops.verify_auth()

    assert result["ok"] is False
    assert "401" in result["error"]
```

### Running tests

```bash
# Unit tests only (fast, no network)
pytest tests/unit/

# Integration tests (requires real API credentials)
pytest tests/integration/ -m integration

# With coverage
pytest tests/unit/ --cov --cov-report=term-missing

# Single test file
pytest tests/unit/test_gitlab_ops.py -v
```

### Two test tiers

| Tier | When | What | Network |
|------|------|------|---------|
| Unit | Pre-commit + CI on every PR | Fast, fully mocked | No |
| Integration | CI on push to main only | Real API calls with test credentials | Yes |

## Pre-commit Hooks

After `pre-commit install`, every commit runs:

1. **ruff check** — lint Python files (auto-fix enabled)
2. **ruff format** — format Python files
3. **pytest unit** — run unit tests
4. **check-test-coverage** — verify test files exist for any new/modified scripts
5. **check-no-internal-refs** — scan all tracked files for hardcoded internal hostnames

To bypass hooks in emergencies: `git commit --no-verify` (use sparingly).

### No Internal References Rule

This is a **public** repository. Hardcoded internal hostnames, cluster IDs, and
infrastructure URLs must never be committed. The `check-no-internal-refs` hook
scans for patterns like internal GitLab hostnames, Konflux cluster identifiers,
and OpenShift domain names.

**If the hook blocks your commit:**
- Replace the hardcoded value with an environment variable (e.g. `$GITLAB_HOST`)
- See `.work/.env.example` for the full list of configurable variables
- See `tests/check_no_internal_refs.py` for the exact forbidden patterns

The same check runs as a pytest test (`tests/unit/test_no_internal_refs.py`) in CI.

## CI Workflows

| Workflow | Trigger | What it tests |
|----------|---------|---------------|
| `scripts-test.yaml` | Changes to `scripts/`, `tests/unit/`, `pyproject.toml` | Unit + integration tests for `scripts/*_ops.py` |
| `skills-test.yaml` | Changes to `skills/**/scripts/`, `tests/unit/`, `pyproject.toml` | Unit tests for skill-local scripts |
| `lint.yml` | All pushes/PRs to main | skillsaw linter |

## Inter-Skill Data

Skills communicate via YAML files in `.work/` (git-ignored). Each file has a top-level key matching the skill name:

```yaml
# .work/conforma-analyze.yaml
conforma-analyze:
  status: completed
  violations: [...]
```

**Rules**:
- Each skill writes ONLY its own key
- Downstream skills read upstream files for input
- Always include `status: completed | failed | pending`

## Repository Clone Policy

Scripts that need a local clone of an external repository (e.g. `konflux-release-data`, `component-maturity`) **must** follow these rules:

1. **Never use a pre-existing local clone** outside of `.work/`. Only `.work/` clones are trusted.
2. **Always fetch before use.** If a `.work/` clone already exists, run `git fetch origin <branch>` and `git reset --hard origin/<branch>` before reading any data.
3. **Abort on fetch failure.** If the fetch fails (VPN down, host unreachable, auth expired), the script **must** abort with a clear error. Never silently fall back to stale data.
4. **Clone fresh if no `.work/` clone exists.** Use `git clone --depth 1` into `.work/`.

The shared functions that enforce this are:
- `conforma_policy_ops._refresh_workdir_clone()` — fetch + hard-reset, raises on failure
- `manage_exceptions._clone_repo()` — clone-or-refresh with abort-on-failure
- `component_catalog_ops.ensure_catalog_repo()` — returns `ok: False` on pull failure

When adding new scripts that clone repos, use these primitives or follow the same pattern.

## Secrets and Credentials Policy

**Tokens and secrets MUST NEVER be pasted into an AI chat window.** The agent must never ask the user to paste tokens, API keys, or credentials into the conversation.

All secrets go in `.work/.env` (gitignored). Instruct users to write secrets there directly:

```bash
# Example: instruct user to run in their terminal
echo 'GITLAB_TOKEN=glpat-XXXXX' >> .work/.env
echo 'JIRA_API_TOKEN=ATATT3xxx' >> .work/.env
```

The `.work/` directory:
- Is gitignored (never committed)
- Contains `.env` for secrets and API tokens
- Contains transient skill working data (clones, temp files)
- Is loaded automatically by `_setup_env.py` and `konflux_environment.load()`

When writing skills or scripts that need auth, always reference `.work/.env` as the token location and point users to the relevant `-auth` skill for setup instructions.

## Terminology

All user-facing text (script output, skill docs, agent responses) MUST use full terms — never abbreviations. This applies to print/log/label strings in scripts and prose in skill markdown.

| Wrong | Correct |
|-------|---------|
| MR, MRs | Merge Request, Merge Requests |
| PR, PRs | Pull Request, Pull Requests |
| rules (when referring to conforma violations) | violations |

Abbreviations are acceptable only in internal variable names (e.g. `prefetched_mrs`) and code comments that are not rendered to the user.

See also [`skills/references/script-output-presentation.md`](skills/references/script-output-presentation.md).

## Code Style

- Python 3.11+
- Line length: 120 characters
- Formatter/linter: ruff (configured in `pyproject.toml`)
- Type hints encouraged but not enforced
- Docstrings for all public functions

## Pull Request Checklist

- [ ] New scripts have corresponding test files
- [ ] Tests pass locally (`pytest tests/unit/`)
- [ ] Linter passes (`ruff check .`)
- [ ] No internal hostnames or infrastructure URLs (`python tests/check_no_internal_refs.py`)
- [ ] SKILL.md updated if skill behavior changed
- [ ] No secrets committed
