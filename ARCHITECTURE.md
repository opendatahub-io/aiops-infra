# Architecture

This document describes the design principles, structure, and key decisions behind the aiops-infra repository. Read this first to understand the system design.

For practical contributor guidance, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Design Principles

1. **Skills that perform actions have Python scripts; routing and documentation skills may be SKILL.md-only.** Auth/troubleshooting skills reference shared scripts without owning them.
2. **One skill, one domain.** Each `conforma-*` skill handles a single coherent area.
3. **Shared operations live in `scripts/*_ops.py` (dual-mode).** Each file is both CLI-runnable (`argparse` + `if __name__ == "__main__"`) and importable. These contain ONLY generic primitives — domain-specific logic stays in skill scripts.
4. **`*_ops.py` use Python libraries** (`python-gitlab`, `jira`, `ruamel.yaml`) — matching the approach of existing onboarding scripts. Conforma skills migrate from raw REST+subprocess to library-based calls when they start importing from `*_ops.py`.
5. **Inter-skill data passes through YAML files in `.work/`.** Each skill writes a file with a distinctive top-level key matching the skill name. Files are individually readable AND composable into a single YAML.
6. **The `conforma` skill is the single entry point** — routes 20+ intents to atomic skills.
7. **Every new script (in `scripts/` OR `skills/*/scripts/`) MUST have tests.** Existing scripts are on an ignore list. `*_ops.py` replaces existing onboarding scripts over time.

## Architecture Diagram

```mermaid
flowchart TD
    user[User query] --> entry["conforma (entry-point)"]
    entry -->|"violations/status"| analyze["conforma-analyze"]
    entry -->|"fetch tekton report"| reportFetch["conforma-report-fetch"]
    analyze -->|"fetches CSVs via"| reportFetch
    entry -->|"create/extend/manage exception"| exception["conforma-exception"]
    entry -->|"fix violations"| remedy["conforma-remedy"]
    entry -->|"search docs"| docs["conforma-docs"]
    entry -->|"can X ship?"| readiness["conforma-release-readiness"]
    entry -->|"troubleshoot auth"| auth["gitlab-auth / jira-auth / github-auth"]

    readiness -->|"reads violations"| analyze
    readiness -->|"queries GitLab"| sharedScripts
    exception -->|"YAML handover"| analyze
    exception --> sharedScripts["scripts/*_ops.py"]
    remedy --> sharedScripts
    readiness --> sharedScripts
    docs --> sharedScripts
```

## Skill Inventory

### User-facing atomic skills

| Skill | Purpose | Status |
|-------|---------|--------|
| `conforma-analyze` | Parse violation CSVs into YAML index, trace history | Exists |
| `conforma-report-fetch` | Fetch conforma reports: CSV from GitHub, JSON from Tekton | Exists |
| `conforma-exception` | Create/extend/manage/view/review exceptions (Jira, GitLab MRs, linking, expired exception assessment) | Exists |
| `conforma-remedy` | Find and apply fixes to underlying violations | Planned |
| `conforma-docs` | Full-text search across conforma documentation and runbooks | Planned |
| `conforma-release-readiness` | "Can version X ship?" — detailed breakdown and verdict | Planned |

### Troubleshooting skills (SKILL.md only, no local scripts)

| Skill | Purpose |
|-------|---------|
| `gitlab-auth` | Verify and fix GitLab auth. References `scripts/gitlab_ops.py verify-auth` |
| `jira-auth` | Verify and fix Jira/acli auth. References `scripts/jira_ops.py verify-auth` |
| `github-auth` | Verify and fix GitHub/gh auth. References `scripts/github_ops.py verify-auth` |

### Entry-point skill

| Skill | Purpose |
|-------|---------|
| `conforma` | Intent detection and routing to atomic skills. SKILL.md-only. |

## Shared Scripts: Dual-Mode Design

Location: `scripts/` at repo root. These contain ONLY generic primitives — not domain-specific business logic. They use Python libraries for API calls.

### Script inventory

| Script | Functions | Library |
|--------|-----------|---------|
| `gitlab_ops.py` | `get_client`, `verify_auth`, `get_project`, `clone_repo`, `push_branch`, `create_mr`, `update_mr`, `find_mr` | `python-gitlab` |
| `jira_ops.py` | `get_client`, `verify_auth`, `create_issue`, `update_issue`, `add_watchers`, `search_user`, `link_issues`, `transition_issue` | `jira` |
| `github_ops.py` | `verify_auth`, `create_pr`, `get_file`, `get_repo`, `check_workflow_run` | `gh` CLI + `requests` |
| `yaml_ops.py` | `load`, `load_multi_doc`, `dump`, `dump_preserving_comments`, `merge` | `ruamel.yaml` |
| `cli_runner.py` | `run`, `run_with_retry`, `run_json` | `subprocess` |

### Primitive vs. domain-specific boundary

**Primitive** (goes in `*_ops.py`):
- `gitlab_ops.create_mr(project, branch, title, description)` — creates any MR
- `jira_ops.add_watchers(ticket_key, account_ids)` — adds watchers to any ticket
- `jira_ops.create_issue(project, summary, description, issue_type)` — creates any ticket

**Domain-specific** (stays in skill scripts):
- `create_gitlab_mr.py::apply_exception_to_policy_file()` — conforma-specific
- `create_jira_ticket.py::_build_psx_description()` — conforma-specific template
- `create_jira_ticket.py::reconcile_ticket()` — conforma workflow logic

### Dual-mode pattern

Every `*_ops.py` script is both importable and CLI-runnable:

```python
"""gitlab_ops.py -- GitLab primitives (dual-mode: CLI + importable)."""
import argparse
import json
import gitlab

def get_client(instance_url=None, token=None):
    """Get authenticated GitLab client."""
    ...

def verify_auth(instance_url=None):
    """Check gitlab auth works. Returns {"ok": bool, "user": str, "error": str|None}."""
    ...

def create_mr(project_path, source_branch, target_branch, title, description=""):
    """Create MR. Returns {"mr_url": str, "mr_iid": int}."""
    ...

def main():
    parser = argparse.ArgumentParser(description="GitLab primitives")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("verify-auth")
    p_mr = sub.add_parser("create-mr")
    p_mr.add_argument("--project", required=True)
    p_mr.add_argument("--source-branch", required=True)
    p_mr.add_argument("--target-branch", default="main")
    p_mr.add_argument("--title", required=True)
    args = parser.parse_args()
    if args.command == "verify-auth":
        result = verify_auth()
    elif args.command == "create-mr":
        result = create_mr(args.project, args.source_branch, args.target_branch, args.title)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
```

## Path Resolution and Auto-Bootstrap

Skills that import from `scripts/` include `_setup_env.py` in their local `scripts/` directory. This module:

1. **Resolves the repo root** — walks up from its own location (4 parents: `scripts/` → `<skill>/` → `skills/` → `<repo>/`), falls back to `AIOPS_INFRA_ROOT` env var, then `~/.local/share/aiops-infra`
2. **Ensures dependencies** — uses `uv sync` if available (~200ms), falls back to `pip install -e .` with mtime-based caching, skips entirely if packages are already importable (CI)
3. **Adds `scripts/` to sys.path** — so skill scripts can `import gitlab_ops` directly

Zero user action required. First skill run bootstraps everything automatically.

## Inter-Skill Handover Pattern

Skills communicate via YAML files in `.work/`. Each file has a single top-level key matching the producing skill:

```yaml
# .work/conforma-analyze.yaml
conforma-analyze:
  status: completed
  completed_at: "2026-06-05T10:00:00Z"
  violations:
    - component: model-registry
      rule: hermetic_task.hermetic
      msg: "Task is not hermetic"
      severity: failure
  violation_count: 3
```

```yaml
# .work/conforma-exception.yaml
conforma-exception:
  status: completed
  completed_at: "2026-06-05T10:05:00Z"
  jira_url: "https://issues.redhat.com/browse/RHOAIENG-12345"
  mr_url: "https://gitlab.cee.redhat.com/.../merge_requests/789"
  exception_rule: hermetic_task.hermetic
```

**Rules**:
- Each skill writes ONLY its own key
- Downstream skills read upstream files to get input
- Files are individually readable AND composable (merge all into one YAML for full pipeline state)
- `status: completed | failed | pending` in every handover file

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Python libraries over raw REST/subprocess | Type safety, pagination, error handling built in. Matches existing onboarding scripts. |
| Dual-mode scripts (`argparse` + importable) | Skills call Python functions directly; agents and humans can use CLI. No shell wrapper needed. |
| `*_ops.py` naming | Clear convention. `grep -r _ops.py` finds all shared primitives instantly. |
| Flat `scripts/` directory | Simple path resolution. No nested packages to manage. |
| `.work/` for inter-skill data | Git-ignored, machine-readable, human-inspectable. No database or service needed. |
| `.test-ignore-list` for legacy scripts | Pragmatic: existing 54 onboarding scripts work but lack tests. New scripts are gated from day one. |
| `_setup_env.py` per skill (copied, not symlinked) | Symlinks break when repo is cloned to different paths. Copies are self-contained. |
| `uv sync` preferred over `pip` | 10-50x faster dependency resolution. Falls back gracefully if `uv` is not installed. |

## Repository Layout

```
aiops-infra/
  scripts/                    # Shared scripts (54 existing + new *_ops.py)
  skills/                     # Conforma skills (.cursor/skills -> symlink)
    conforma/                 # Entry-point orchestrator (SKILL.md only)
    conforma-analyze/         # Violation report analysis
    conforma-report-fetch/    # Fetch reports: CSV from GitHub, JSON from Tekton
    conforma-exception/       # Exception management (create, extend, assess, cleanup)
    conforma-remedy/          # Fix violations in code
    conforma-docs/            # Documentation search
    conforma-release-readiness/ # Ship/no-ship verdict
    gitlab-auth/              # GitLab auth troubleshooting (SKILL.md only)
    jira-auth/                # Jira auth troubleshooting (SKILL.md only)
    github-auth/              # GitHub auth troubleshooting (SKILL.md only)
  .claude/skills/             # Onboarding pipeline skills (17 existing)
  tests/                      # Unit + integration tests
  .github/workflows/          # CI: lint + test workflows
  pyproject.toml              # Project metadata, deps, tool config
  .pre-commit-config.yaml     # Ruff + pytest + test coverage check
```
