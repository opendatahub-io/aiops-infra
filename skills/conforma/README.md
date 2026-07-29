# Conforma Skills

AI-powered automation for RHOAI [Conforma](https://conforma.dev/docs/policy/release_policy.html) policy compliance -- violation analysis, exception management, release readiness, remediation, and documentation search.

## Install

> **Note:** The conforma skills live on the `skill/conforma` branch. The `main` branch does not include them.

Requires **Python 3.11+**. On first run, the skill's prerequisite check will guide you through configuring secrets and authentication.

### Quick setup (use the skills, no development)

Use this if you just want to run the conforma skills and don't plan on contributing to them.

```bash
# Clone the repo — the Python scripts need a local checkout to run
git clone -b skill/conforma https://github.com/opendatahub-io/aiops-infra.git ~/.local/share/aiops-infra
cd ~/.local/share/aiops-infra && pip install -e .

# Register the skills globally in Claude Code
for skill in ~/.local/share/aiops-infra/skills/*/; do
  ln -sf "$skill" ~/.claude/skills/"$(basename "$skill")"
done
```

That's it — the conforma skills are now available in any project. `conforma_run.sh` auto-detects the repo at `~/.local/share/aiops-infra`.

### Development setup (contribute / fix skills)

If you want to modify the skills or their scripts, see [CONTRIBUTING.md](../../CONTRIBUTING.md) for the full developer setup. In short:

```bash
git clone https://github.com/opendatahub-io/aiops-infra.git
cd aiops-infra
git checkout skill/conforma
pip install -e ".[dev]"
pre-commit install
```

Skills are auto-discovered from the `skills/` directory when working inside the repo.

## Usage

Open a Claude Code session and ask a conforma-related question. The `conforma` skill is the single entry point -- it routes your intent to the right sub-skill automatically.

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
