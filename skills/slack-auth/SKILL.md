---
name: slack-auth
description: Verify and troubleshoot Slack authentication for conforma skills. Uses slackdump (browser-cookie auth) — no Slack app installation required.
allowed-tools: Bash(python3:*,slackdump:*)
user-invocable: true
---

# Slack Auth

Verify and troubleshoot Slack authentication. This skill references `scripts/slack_ops.py` for programmatic auth verification.

## Why slackdump?

Installing any app into the Red Hat Internal Slack workspace requires RH Slack admin approval — a process that is slow and often blocked. To avoid this organizational friction, we use [slackdump](https://github.com/rusq/slackdump) which authenticates via your existing browser session cookies. No app installation, no admin approval needed.

## Quick Verification

```bash
python3 scripts/slack_ops.py verify-auth
```

This checks:
- `slackdump` binary is installed and on PATH
- Auth credentials exist in `~/.cache/slackdump/`
- The session is still valid
- `SLACK_WORKSPACE_URL` is available (from site-config) for building search links

## First-Time Setup

### 1. Install slackdump

```bash
./scripts/install_slackdump.sh
```

Or install manually from [GitHub releases](https://github.com/rusq/slackdump/releases).

### 2. Authenticate

```bash
slackdump login
```

This opens your default browser. Log in with your Red Hat SSO credentials as you normally would for Slack. The session cookie is saved to `~/.cache/slackdump/` — one-time setup.

### 3. Set workspace URL (site-config)

Ensure `SLACK_WORKSPACE_URL` is available via site-config. If using the team's remote config, this is automatic. Otherwise:

```bash
python3 scripts/site_config.py --write-local slack.workspace_url=https://redhat-internal.slack.com
```

### 4. Verify

```bash
python3 scripts/slack_ops.py verify-auth
```

## Common Failure Modes

### "slackdump binary not found"

The `slackdump` CLI is not installed or not on PATH.

**Fix:**

```bash
./scripts/install_slackdump.sh
```

### "No slackdump auth credentials found"

Binary is installed but no login has been performed.

**Fix:**

```bash
slackdump login
```

### "slackdump session expired"

Browser cookies have expired (typically after several weeks of inactivity).

**Fix:**

```bash
slackdump login
```

### "team_url is empty in verify-auth output"

`SLACK_WORKSPACE_URL` is not set. Search links in coverage reports won't be clickable.

**Fix:**

```bash
python3 scripts/site_config.py --write-local slack.workspace_url=https://redhat-internal.slack.com
```

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| `SLACK_WORKSPACE_URL` | Slack workspace base URL for search links | Site-config (`slack.workspace_url`) |

## How It Works

Slackdump stores browser session cookies in `~/.cache/slackdump/<workspace>.bin`. When `slack_ops.py` runs a search, it:

1. Invokes `slackdump search messages -no-channel-users -o <tmpdir> "<query>"`
2. Reads the resulting SQLite database (`SEARCH_MESSAGE` table)
3. Normalizes results into the same format used by the coverage check
4. Cleans up the temp directory
