# Conforma Skills

AI-powered automation for RHOAI [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy compliance -- violation analysis, exception management, release readiness, remediation, and documentation search.

## Install

```bash
git clone https://github.com/opendatahub-io/aiops-infra.git
cd aiops-infra
pip install -e .   # or: uv sync
```

Requires **Python 3.11+**. On first run, the skill's prerequisite check will guide you through configuring secrets and authentication.

### Remote installation (skills installed via `claude skill install`)

If you install conforma skills remotely into `~/.claude/` while working in a different project, the Python scripts still need access to the aiops-infra repo:

```bash
git clone https://github.com/opendatahub-io/aiops-infra.git ~/.local/share/aiops-infra
cd ~/.local/share/aiops-infra && pip install -e .
```

Then set the environment variable so workflows can find the repo:

```bash
export AIOPS_INFRA_ROOT="$HOME/.local/share/aiops-infra"
```

Or add it to `~/.conforma/.env` for persistence:

```bash
echo "AIOPS_INFRA_ROOT=$HOME/.local/share/aiops-infra" >> ~/.conforma/.env
```

## Usage

Open a Cursor chat and ask a conforma-related question. The `conforma` skill is the single entry point -- it routes your intent to the right sub-skill automatically.

**Examples:**

```
what is conforma
```

```
what's the conforma status for rhoai-3.4
```

```
are there any blocking violations for rhoai-3.5-ea.1
```

```
create an exception for rule xyz on component abc
```
