---
name: jira-auth
description: Verify and troubleshoot Jira authentication for conforma skills. References scripts/jira_ops.py for programmatic verification.
allowed-tools: Bash(python3:*,acli:*)
user-invocable: true
---

# Jira Auth

Verify and troubleshoot Jira authentication. This skill does not own any scripts — it references the shared `scripts/jira_ops.py` for programmatic auth verification.

## CRITICAL: Token Handling

**NEVER ask the user to paste tokens or secrets into the chat window.**

Always instruct the user to write tokens to the `~/.conforma/.env` file directly (using their editor, `echo >>`, or another non-chat method). The `~/.conforma/` directory is the designated location for secrets.

## Quick Verification

```bash
~/.conforma/bin/conforma_run.sh scripts/jira_ops.py verify-auth
```

This checks:
- Jira credentials are discoverable (email + API token from environment)
- Credentials authenticate successfully against `redhat.atlassian.net`
- Returns the authenticated user name

## Common Failure Modes

### "Missing credentials"

Auth requires both email and API token.

**Fix — instruct the user:**

```bash
# Add credentials to ~/.conforma/.env (create if missing):
echo 'JIRA_EMAIL=your.name@redhat.com' >> ~/.conforma/.env
echo 'JIRA_API_TOKEN=ATATT3xxxxxxxxxxx' >> ~/.conforma/.env
```

Generate a token at: https://id.atlassian.com/manage-profile/security/api-tokens

### "401 Unauthorized"

Token exists but is invalid or expired.

**Fix — instruct the user:**

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Create a new API token
3. Update the token in `~/.conforma/.env` (edit the `JIRA_API_TOKEN=` line)

### "acli not found" (for conforma-exception workflows)

The `acli` CLI is used by conforma-exception for some operations. It auto-installs on first use. If auto-install fails:

```bash
# Manual install
curl -fsSL https://acli.atlassian.com/linux/acli -o ~/.local/bin/acli
chmod +x ~/.local/bin/acli
```

### acli config

If using acli directly, config goes in `~/.acli/` or `~/.config/acli/`:

```yaml
# ~/.acli/acli.properties or similar
jira_server = https://redhat.atlassian.net
jira_user = your.name@redhat.com
jira_token = ATATT3xxxxxxxxxxx
```

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| `JIRA_API_TOKEN` | Atlassian API token | `~/.conforma/.env` |
| `JIRA_EMAIL` | Atlassian account email | `~/.conforma/.env` |
| `JIRA_URL` | Jira instance URL | `https://redhat.atlassian.net` (default) |

## Token Storage

All secrets go in `~/.conforma/.env` (gitignored, loaded by `_setup_env.py` and `konflux_environment.load()`):

```
# ~/.conforma/.env — NOT committed to git
JIRA_EMAIL=your.name@redhat.com
JIRA_API_TOKEN=ATATT3xxxxxxxxxxx
```

## Two Auth Systems

This repo uses two different Jira auth mechanisms:

1. **`scripts/jira_ops.py`** — Uses the `jira` Python library with email + API token (for new shared scripts)
2. **`skills/conforma-exception/scripts/cli_runner.py`** — Uses `acli` CLI with its own config (for existing conforma-exception workflows)

Both require the same underlying Atlassian API token. If one works but the other doesn't, check that both systems can find the token.
