---
name: gitlab-auth
description: Verify and troubleshoot GitLab authentication for conforma skills. References scripts/gitlab_ops.py for programmatic verification.
allowed-tools: Bash(python3:*,glab:*,git:*)
user-invocable: true
---

# GitLab Auth

Verify and troubleshoot GitLab authentication. This skill does not own any scripts — it references the shared `scripts/gitlab_ops.py` for programmatic auth verification.

## Quick Verification

```bash
python3 scripts/gitlab_ops.py verify-auth
```

This checks:
- GitLab token is discoverable (from `GITLAB_TOKEN` env or `~/.config/glab-cli/config.yml`)
- Token authenticates successfully against `gitlab.cee.redhat.com`
- Returns the authenticated user name

## Common Failure Modes

### "No GitLab token found"

The token is discovered in this order:
1. `GITLAB_TOKEN` environment variable
2. `~/.config/glab-cli/config.yml` (glab CLI config, matched by host)

**Fix:**

```bash
# Option A: Set environment variable
export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"

# Option B: Login with glab CLI (creates config file)
glab auth login --hostname gitlab.cee.redhat.com
```

### "401 Unauthorized"

Token exists but is invalid or expired.

**Fix:**

```bash
# Re-authenticate with glab
glab auth login --hostname gitlab.cee.redhat.com

# Or generate a new Personal Access Token:
# 1. Go to https://gitlab.cee.redhat.com/-/user_settings/personal_access_tokens
# 2. Create token with scopes: api, read_repository, write_repository
# 3. Export: export GITLAB_TOKEN="glpat-xxxxxxxxxxxxxxxxxxxx"
```

### "SSL certificate verify failed"

VPN may be required for `gitlab.cee.redhat.com`.

**Fix:**

```bash
# Check VPN connection first
# If VPN is connected but SSL still fails:
export GITLAB_SSL_VERIFY=false  # temporary workaround
```

### "Network is unreachable" / timeout

**Fix:**

- Connect to VPN (required for `gitlab.cee.redhat.com`)
- Check `ping gitlab.cee.redhat.com`
- Check proxy settings if behind a corporate proxy

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `GITLAB_TOKEN` | Personal Access Token | Auto-discovered from glab config |
| `GITLAB_HOST` | GitLab instance hostname | `gitlab.cee.redhat.com` |
| `GL_HOST` | Alternative to `GITLAB_HOST` | — |
| `GITLAB_SSL_VERIFY` | SSL certificate verification | `true` |

## Checking from glab CLI

```bash
# Check auth status
glab auth status

# Check which host is configured
glab config get host

# Re-login
glab auth login --hostname gitlab.cee.redhat.com
```
