---
name: github-auth
description: Verify and troubleshoot GitHub authentication for conforma skills. References scripts/github_ops.py for programmatic verification.
allowed-tools: Bash(python3:*,gh:*)
user-invocable: true
---

# GitHub Auth

Verify and troubleshoot GitHub authentication. This skill does not own any scripts — it references the shared `scripts/github_ops.py` for programmatic auth verification.

## Quick Verification

```bash
python3 scripts/github_ops.py verify-auth
```

This checks:
- `gh` CLI is available and authenticated
- Returns the authenticated user name

## Common Failure Modes

### "gh not found on PATH"

The `gh` CLI is not installed.

**Fix:**

```bash
# Fedora/RHEL
sudo dnf install gh

# macOS
brew install gh

# Or download from https://cli.github.com/
```

### "not logged in"

gh CLI is installed but not authenticated.

**Fix:**

```bash
gh auth login
```

Follow the interactive prompts. Choose HTTPS protocol and authenticate via browser or token.

### "Cannot access private repository"

Authenticated but token doesn't have access to the required private repo (e.g., `red-hat-data-services/conforma-reporter`).

**Fix:**

- Ensure your `GITHUB_TOKEN` has `repo` scope (for private repos)
- Ask your team lead for repository access
- Check organization membership

### "Token expired"

GitHub tokens can expire if configured with an expiration date.

**Fix:**

```bash
# Re-authenticate
gh auth login

# Or refresh
gh auth refresh
```

## Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | Auto-discovered from `gh auth token` |
| `GH_TOKEN` | Alternative to `GITHUB_TOKEN` | — |

## Checking from gh CLI

```bash
# Check auth status
gh auth status

# Get current token
gh auth token

# Check access to a specific repo
gh api repos/red-hat-data-services/conforma-reporter --jq '.full_name'
```
