# conforma-exception

End-to-end automation for RHOAI Conforma exception management: check existing
exceptions, create new ones, extend effectiveUntil dates, validate inputs,
create required Jira tickets (RHOAIENG + PSX/OCPEXCEPT), generate exception
YAML, create GitLab MRs in `releng/konflux-release-data`, and cross-link all
artifacts.

See [SKILL.md](SKILL.md) for full usage documentation.

## Quick Install

Install for both Claude Code and Cursor in one command:

```bash
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash
```

### Target a specific environment

```bash
# Claude Code only
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --target claude

# Cursor only
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --target cursor

# Also install into a specific project
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --project /path/to/my-project
```

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --uninstall
```

## Install from Within Claude Code

Start a Claude Code session and paste:

> Install the conforma-exception skill from
> https://github.com/opendatahub-io/aiops-infra into my environment.

Or run the installer directly in the session:

```
Run this command:
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --target claude
```

Once installed, invoke the skill with:

> Create a conforma exception for RHOAIENG-XXXXX

## Install from Within Cursor

Open the Cursor chat and paste:

> Install the conforma-exception skill from
> https://github.com/opendatahub-io/aiops-infra into my Cursor environment.

Or ask it to run the installer:

> Run this in a terminal:
> `curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --target cursor`

Once installed, the skill appears in your available skills list. Invoke with:

> Create a conforma exception for RHOAIENG-XXXXX

## Where Files Are Installed

| Environment | Install location |
|---|---|
| Claude Code (global) | `~/.claude/skills/conforma-exception/` |
| Cursor (global) | `~/.cursor/skills-cursor/conforma-exception/` |
| Project-local | `<project>/.claude/skills/conforma-exception/` |

Project-local installations are auto-discovered by both Claude Code and Cursor
when the workspace is opened.

## Prerequisites

After installation, you still need:

- **Python 3.10+**
- **`glab`** (GitLab CLI) — `sudo dnf install glab` or `brew install glab`
- **VPN access** to `gitlab.cee.redhat.com`
- **`acli`** (Atlassian CLI) — auto-installed on first use

### One-time authentication

```bash
# Jira (generate token at https://id.atlassian.com/manage-profile/security/api-tokens)
echo "$TOKEN" | acli jira auth login --site redhat.atlassian.net --email "$USER@redhat.com" --token

# GitLab (generate token at https://gitlab.cee.redhat.com/-/user_settings/personal_access_tokens)
glab auth login --hostname gitlab.cee.redhat.com --token "$TOKEN"
```

## Updating

Re-run the install command to update to the latest version:

```bash
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash
```

Or from a specific branch:

```bash
curl -fsSL https://raw.githubusercontent.com/opendatahub-io/aiops-infra/conforma-exception-ai-skill/skills/conforma-exception/install.sh | bash -s -- --branch feature-branch
```
