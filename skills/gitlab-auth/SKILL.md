---
name: gitlab-auth
description: Verify and troubleshoot GitLab authentication for conforma skills. References scripts/gitlab_ops.py for programmatic verification.
allowed-tools: Bash(python3:*,glab:*,git:*)
user-invocable: true
---

# GitLab Auth

Verify and troubleshoot GitLab authentication. This skill does not own any scripts — it references the shared `scripts/gitlab_ops.py` for programmatic auth verification.

## CRITICAL: Token Handling

**NEVER ask the user to paste tokens or secrets into the chat window.**

Always instruct the user to write tokens to the `.work/.env` file directly (using their editor, `echo >>`, or another non-chat method). The `.work/` directory is gitignored and is the designated location for secrets.

```bash
# Tell the user to run this in their terminal (NOT paste the token into chat):
echo 'GITLAB_TOKEN=glpat-XXXXX' >> .work/.env
```

## Quick Verification

```bash
python3 scripts/gitlab_ops.py verify-auth
```

This checks:
- GitLab token is discoverable (from `GITLAB_TOKEN` env or `~/.config/glab-cli/config.yml`)
- Token authenticates successfully against the configured `$GITLAB_HOST`
- Returns the authenticated user name

## Common Failure Modes

### "No GitLab token found"

The token is discovered in this order:
1. `GITLAB_TOKEN` environment variable (loaded from `.work/.env` by `_setup_env.py`)
2. `~/.config/glab-cli/config.yml` (glab CLI config, matched by host)

**Fix — instruct the user to do ONE of:**

```bash
# Option A: Add token to .work/.env (preferred — loaded automatically by skills)
#   1. Generate token at: https://$GITLAB_HOST/-/user_settings/personal_access_tokens
#      Scopes needed: api, read_repository, write_repository
#   2. Add to .work/.env (create if missing):
echo 'GITLAB_TOKEN=glpat-YOUR-TOKEN-HERE' >> .work/.env

# Option B: Login with glab CLI (creates ~/.config/glab-cli/config.yml)
glab auth login --hostname "$GITLAB_HOST"
```

### "401 Unauthorized"

Token exists but is invalid or expired.

**Fix — instruct the user:**

1. Generate a new Personal Access Token at `https://$GITLAB_HOST/-/user_settings/personal_access_tokens`
   - Scopes: `api`, `read_repository`, `write_repository`
2. Replace the old token in `.work/.env`:
   ```bash
   # Edit .work/.env and update the GITLAB_TOKEN line
   ```

Or re-authenticate with glab:
```bash
glab auth login --hostname "$GITLAB_HOST"
```

### "SSL certificate verify failed"

VPN may be required for the internal GitLab instance.

**Fix:**

- Check VPN connection first
- If VPN is connected but SSL still fails, add to `.work/.env`:
  ```
  GITLAB_SSL_VERIFY=false
  ```

### "Network is unreachable" / timeout

**Fix:**

- Connect to VPN (required for internal GitLab)
- Check `ping $GITLAB_HOST`
- Check proxy settings if behind a corporate proxy

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| `GITLAB_TOKEN` | Personal Access Token | `.work/.env` or glab config |
| `GITLAB_HOST` | GitLab instance hostname | `.work/.env` (auto-discovery uses this) |
| `GL_HOST` | Alternative to `GITLAB_HOST` | — |
| `GITLAB_SSL_VERIFY` | SSL certificate verification | `.work/.env` (default: `true`) |

## Token Storage

Tokens are stored in `.work/.env` (gitignored, loaded by `_setup_env.py` and `konflux_environment.load()`):

```
# .work/.env — NOT committed to git
GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

## Checking from glab CLI

```bash
# Check auth status
glab auth status

# Check which host is configured
glab config get host

# Re-login
glab auth login --hostname "$GITLAB_HOST"
```
