---
name: slack-auth
description: Verify and troubleshoot Slack authentication for conforma skills. Uses slackdump (manual token/cookie import) — no Slack app installation required, works in any environment.
allowed-tools: Bash(python3:*,slackdump:*,bash:*)
user-invocable: true
---

# Slack Auth

Verify and troubleshoot Slack authentication. This skill references `scripts/slack_ops.py` for programmatic auth verification.

## CRITICAL: Token Handling

**NEVER ask the user to paste tokens or secrets into the chat window.**

All credentials go in `.work/.slack-secrets` (temporary, deleted after import) or `.work/.env`. Never accept secrets via chat — always instruct the user to write them to a file directly using their editor or terminal.

## Slack is Optional in the Conforma Workflow

Slack enriches the coverage table with links to related discussion threads, but it is **not required**. The conforma-analyze workflow can proceed without it — the coverage table will simply omit the Slack column.

Slack setup is more involved than other services (GitHub/GitLab/Jira use simple API tokens; Slack requires extracting token+cookie from browser DevTools). The prerequisites check reports Slack as a **warning**, not a failure, and the agent should inform the user of this tradeoff before proceeding.

## Why slackdump?

Installing any app into the Red Hat Internal Slack workspace requires RH Slack admin approval — a process that is slow and often blocked. To avoid this organizational friction, we use [slackdump](https://github.com/rusq/slackdump) which authenticates via your existing Slack session cookies. No app installation, no admin approval needed.

## Quick Verification

```bash
python3 scripts/slack_ops.py verify-auth
```

This checks:
- `slackdump` binary is installed and on PATH
- Auth credentials exist in `~/.cache/slackdump/`
- The session is still valid
- `SLACK_WORKSPACE_URL` is available (from infrastructure discovery or `.work/.env`) for building search links

## First-Time Setup

### 1. Install slackdump

```bash
./scripts/install_slackdump.sh
```

Or install manually from [GitHub releases](https://github.com/rusq/slackdump/releases).

### 2. Authenticate

There are two methods. **Method A** (manual token/cookie) is the primary method — it works universally in any environment (WSL, Docker, CI, remote servers). **Method B** (browser automation) is an alternative for systems with a local browser available.

#### Method A: Manual token/cookie (universal — works everywhere)

This method requires only a browser where you're already logged into Slack. No local browser automation, no display server, no extra dependencies.

**Tell the user to perform these steps:**

1. Open https://redhat-internal.slack.com in your browser (any OS, any browser)

2. Open Developer Tools (F12 or Ctrl+Shift+I)

3. **Get the token** — switch to the Console tab and paste:
   ```javascript
   JSON.parse(localStorage.localConfig_v2).teams[document.location.pathname.match(/^\/client\/([A-Z0-9]+)/)[1]].token
   ```
   Copy the `xoxc-...` value that appears.

4. **Get the cookie** — switch to Application tab (Chrome/Edge) or Storage tab (Firefox) → Cookies → select your Slack domain → find the cookie named `d` → copy its value (starts with `xoxd-`).

5. Write both values to `.work/.slack-secrets`:
   ```
   SLACK_TOKEN=xoxc-...
   SLACK_COOKIE=xoxd-...
   ```

**Agent imports and cleans up:**

```bash
slackdump workspace import .work/.slack-secrets
rm -f .work/.slack-secrets
```

The credentials are encrypted and stored in `~/.cache/slackdump/`. The secrets file is deleted immediately after import.

#### Method B: Browser automation (alternative — requires local browser)

If a Chromium-family browser (Chrome, Edge, Brave) is installed locally and accessible:

```bash
slackdump workspace new https://redhat-internal.slack.com
```

This opens a browser window for interactive login. Works well on native Linux/macOS with a display server, but **will not work** in WSL without a Linux browser, Docker containers, CI, or headless servers.

### 3. Set workspace URL

Ensure `SLACK_WORKSPACE_URL` is available. If auto-discovery populates it, no action needed. Otherwise add to `.work/.env`:

```
SLACK_WORKSPACE_URL=https://redhat-internal.slack.com
```

### 4. Verify

```bash
python3 scripts/slack_ops.py verify-auth
```

## Agent Workflow for Slack Auth

When the agent detects that Slack auth is missing or expired, follow this exact sequence:

1. **Inform the user** that Slack credentials are needed and provide the workspace URL:
   > Open https://redhat-internal.slack.com in your browser, then follow the steps below to extract your token and cookie.

2. **Provide the extraction steps** (Console snippet for token, Application → Cookies for `d` cookie).

3. **Instruct the user** to write the values to `.work/.slack-secrets`:
   > Using your editor or terminal, create `.work/.slack-secrets` with:
   > ```
   > SLACK_TOKEN=xoxc-<your-token>
   > SLACK_COOKIE=xoxd-<your-cookie>
   > ```

4. **Wait for the user** to confirm the file is written.

5. **Import and verify**:
   ```bash
   slackdump workspace import .work/.slack-secrets && rm -f .work/.slack-secrets
   python3 scripts/slack_ops.py verify-auth
   ```

**NEVER** skip steps, and **NEVER** ask the user to paste credentials in the chat.

## Common Failure Modes

### "slackdump binary not found"

The `slackdump` CLI is not installed or not on PATH.

**Fix:**

```bash
./scripts/install_slackdump.sh
```

### "No slackdump auth credentials found"

Binary is installed but no login has been performed.

**Fix:** Follow the authentication steps above (Method A or B).

### "slackdump session expired"

Session cookies have expired (typically after several weeks of inactivity).

**Fix:** Repeat the authentication steps above. For Method A, the user extracts fresh token/cookie from the browser. The agent re-imports:

```bash
slackdump workspace import .work/.slack-secrets && rm -f .work/.slack-secrets
```

### "team_url is empty in verify-auth output"

`SLACK_WORKSPACE_URL` is not set. Search links in coverage reports won't be clickable.

**Fix:** Add to `.work/.env`:

```
SLACK_WORKSPACE_URL=https://redhat-internal.slack.com
```

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| `SLACK_WORKSPACE_URL` | Slack workspace base URL for search links | Site-config (`slack.workspace_url`) |

## How It Works

Slackdump stores encrypted session credentials in `~/.cache/slackdump/<workspace>.bin`. When `slack_ops.py` runs a search, it:

1. Invokes `slackdump search messages -no-channel-users -o <tmpdir> "<query>"`
2. Reads the resulting SQLite database (`SEARCH_MESSAGE` table)
3. Normalizes results into the same format used by the coverage check
4. Cleans up the temp directory
