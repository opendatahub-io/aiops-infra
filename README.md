# aiops-infra

AI-powered automation for ODH/RHOAI component onboarding and RHOAI Conforma policy compliance.

## Quick Start

```bash
git clone https://github.com/opendatahub-io/aiops-infra.git
cd aiops-infra

uv sync --group dev        # or: pip install -e ".[dev]"
pre-commit install
```

## Infrastructure Configuration

This is a **public** repository. Internal infrastructure details (hostnames, cluster
URLs, API endpoints) are never committed. Instead, skills read them from
environment variables populated from `~/.conforma/.env` and auto-discovery.

### Setup (one-time)

Add your GitLab host and Konflux tenant to `~/.conforma/.env`:

```
GITLAB_HOST=your-gitlab-host
TENANT=your-tenant-name
```

Everything else (`KONFLUX_CLUSTER_DOMAIN`, API URLs, policy paths) is auto-discovered from the `konflux-release-data` GitLab repository on first run.

### Verify

```bash
python3 scripts/verify_conforma_prerequisites.py --fix
```

### How it works

```
~/.conforma/.env (git-ignored)              Auto-discovery
┌───────────────────────────┐         ┌─────────────────────────────────┐
│ GITLAB_HOST=...           │ ──┐     │ konflux_tenant_env_discovery.py │
│ TENANT=...                │   ├──→  │   discovers KONFLUX_CLUSTER_DOMAIN  │
│ GITHUB_TOKEN=...          │   │     │   + derived vars (cached 72h)   │
│ GITLAB_TOKEN=...          │   │     └─────────────────────────────────┘
│ JIRA_API_TOKEN=...        │ ──┘
└───────────────────────────┘
```

- `~/.conforma/.env` holds all user-provided values (secrets + infrastructure config)
- `_setup_env.py` loads `~/.conforma/.env` and runs discovery when any skill script starts
- Environment variables already set take precedence (CI can override via `export`)
- If auto-discovery fails, add the required variables to `~/.conforma/.env` manually

## Repository Structure

- `scripts/` — shared automation scripts (`*_ops.py` primitives)
- `skills/` — conforma skills (`.cursor/skills` is a symlink here)
- `.claude/skills/` — onboarding pipeline skills
- `tests/` — unit and integration tests
- `schemas/` — JSON schemas for validation
- `docs/` — skill documentation and RFDs

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — design principles, skill inventory, key decisions
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to write scripts, add tests, structure skills
- [env.example](env.example) — all configurable infrastructure variables and secrets
