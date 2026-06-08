# aiops-infra

AI-powered automation for ODH/RHOAI component onboarding and Conforma policy compliance.

## Quick Start

```bash
git clone https://github.com/opendatahub-io/aiops-infra.git
cd aiops-infra

uv sync --group dev        # or: pip install -e ".[dev]"
pre-commit install
```

## Site Configuration

This is a **public** repository. Internal infrastructure details (hostnames, cluster
URLs, API endpoints) are never committed. Instead, skills read them from
environment variables populated by a private site config file.

### Setup (one-time)

1. Copy the template:

```bash
mkdir -p ~/.config/aiops-infra
cp site-config.example.yaml ~/.config/aiops-infra/site-config.yaml
```

2. Fill in your organization's values (obtain from your team's internal docs).

3. Verify:

```bash
python3 scripts/site_config.py --validate
```

### How it works

```
Public repo (git-tracked)          Private user config (NOT tracked)
┌─────────────────────────┐        ┌───────────────────────────────────┐
│ site-config.example.yaml│ copy → │ ~/.config/aiops-infra/            │
│   (all keys, no values) │        │   site-config.yaml                │
│                         │        │     gitlab.host: <your-host>      │
│ scripts/site_config.py  │ reads→ │     konflux.namespace: <ns>       │
│   (config loader)       │        │     ...                           │
│                         │        └───────────────────────────────────┘
│ _setup_env.py           │
│   (auto-loads on import)│
└─────────────────────────┘
```

- `site-config.example.yaml` documents every required variable with empty values
- `scripts/site_config.py` loads the private config and populates environment variables
- `_setup_env.py` auto-loads the site config when any skill script starts
- Environment variables already set take precedence (CI can override via `export`)
- The private `site-config.yaml` is git-ignored and never committed

### Config search order

1. Environment variables (highest priority, never overwritten)
2. `$AIOPS_SITE_CONFIG` (explicit path override)
3. `~/.config/aiops-infra/site-config.yaml` (user-level default)

### CLI

```bash
python3 scripts/site_config.py              # show current config status
python3 scripts/site_config.py --validate   # check all required vars are set
python3 scripts/site_config.py --export     # print shell export statements
```

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
- [site-config.example.yaml](site-config.example.yaml) — all configurable infrastructure variables
