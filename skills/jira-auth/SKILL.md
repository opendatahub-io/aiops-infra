---
name: jira-auth
description: Verify and troubleshoot Jira authentication for conforma skills. References scripts/jira_ops.py for programmatic verification.
allowed-tools: Bash(python3:*,acli:*)
user-invocable: true
---

# Jira Auth

Verify and troubleshoot Jira authentication. This skill does not own any scripts — it references the shared `scripts/jira_ops.py` for programmatic auth verification.

## Quick Verification

```bash
python3 scripts/jira_ops.py verify-auth
```

This checks:
- Jira credentials are discoverable (email + API token from environment)
- Credentials authenticate successfully against `redhat.atlassian.net`
- Returns the authenticated user name

## Common Failure Modes

### "Missing credentials"

Auth requires both email and API token.

**Fix:**

```bash
# Set both environment variables
export JIRA_EMAIL="your.name@redhat.com"
export JIRA_API_TOKEN="ATATT3xxxxxxxxxxx"
```

### "401 Unauthorized"

Token exists but is invalid or expired.

**Fix:**

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Create a new API token
3. Export: `export JIRA_API_TOKEN="ATATT3xxxxxxxxxxx"`

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

| Variable | Purpose | Default |
|----------|---------|---------|
| `JIRA_API_TOKEN` | Atlassian API token | — |
| `JIRA_EMAIL` | Atlassian account email | — |
| `JIRA_URL` | Jira instance URL | `https://redhat.atlassian.net` |

## Two Auth Systems

This repo uses two different Jira auth mechanisms:

1. **`scripts/jira_ops.py`** — Uses the `jira` Python library with email + API token (for new shared scripts)
2. **`skills/conforma-exception/scripts/cli_runner.py`** — Uses `acli` CLI with its own config (for existing conforma-exception workflows)

Both require the same underlying Atlassian API token. If one works but the other doesn't, check that both systems can find the token.
