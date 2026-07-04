# Tool Reference

## Listing Current Exceptions

When the user asks to see current Conforma exceptions (e.g. "show me current exceptions", "list exceptions", "what exceptions exist"), use the deterministic `list_exceptions.py` script. **Do NOT manually parse policy files or format output yourself** — the script produces a complete, ready-to-display Markdown report.

1. **Ensure the clone is fresh** — always fetch and abort if unreachable (or let the script clone a temp copy):

```bash
if [ -d ~/.conforma/konflux-release-data/.git ]; then
  git -C ~/.conforma/konflux-release-data fetch origin main || { echo "ERROR: git fetch failed — remote unreachable (VPN down?). Aborting." >&2; exit 1; }
  git -C ~/.conforma/konflux-release-data reset --hard origin/main
else
  GITLAB_TOKEN=$(glab config get token --host "$GITLAB_HOST")
  git clone --depth 1 "https://oauth2:${GITLAB_TOKEN}@${GITLAB_HOST}/releng/konflux-release-data.git" ~/.conforma/konflux-release-data || { echo "ERROR: git clone failed. Aborting." >&2; exit 1; }
fi
```

2. **Run the script** (from the skill directory):

```bash
python3 skills/conforma-exception/scripts/list_exceptions.py --clone-dir ~/.conforma/konflux-release-data
```

3. **Print the output verbatim** — do NOT modify, reformat, or summarize the Markdown. The script produces a deterministic report with consistent table columns across all sections (Rule, Component / Image, RHOAI Version, Effective Until, Reference). RHOAI versions are derived from the actual data (componentName version suffixes like `-v3-4` → `3.4`, or `all` for imageUrl-scoped / unscoped exceptions) — never from YAML comments. All Jira ticket IDs and policy file names are rendered as clickable Markdown links.

**Only analyze prod by default.** If the user specifically asks for stage exceptions, add `--environment stage`. Never show both environments unless the user explicitly asks.

The `--soon-days` flag controls the "expiring soon" threshold (default: 14 days). Example: `--soon-days 30` includes exceptions expiring within 30 days in the "expiring soon" section rather than in per-date sections.

The report groups exceptions into sections by expiry status:
- **Expired** — `effectiveUntil` is in the past (need cleanup)
- **Expiring within N days** — approaching deadline
- **Expiring YYYY-MM-DD** — one section per remaining date, sorted chronologically

## Searching Open Exception Merge Requests

When the user asks about open/pending conforma exception Merge Requests (e.g. "are there open Merge Requests for rpm_signature?", "show me open exception Merge Requests", "any pending Merge Requests for rhoai-3.4?"), use `search_open_mrs.py`. **Do NOT call `glab api` directly** — the script handles GitLab auth, search, title parsing, and structured output.

```bash
# All open conforma exception Merge Requests:
python3 skills/conforma-exception/scripts/search_open_mrs.py

# Filter by rule code (prefix or full):
python3 skills/conforma-exception/scripts/search_open_mrs.py --rule rpm_signature
python3 skills/conforma-exception/scripts/search_open_mrs.py --rule hermetic_task.hermetic

# Filter by RHOAI version:
python3 skills/conforma-exception/scripts/search_open_mrs.py --version rhoai-3.4

# Combine filters:
python3 skills/conforma-exception/scripts/search_open_mrs.py --rule rpm_signature --version 3.4

# Output formats (default: text):
python3 skills/conforma-exception/scripts/search_open_mrs.py --format markdown
python3 skills/conforma-exception/scripts/search_open_mrs.py --format json
```

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--rule` | *(all)* | Filter by rule code or prefix (e.g. `rpm_signature`, `hermetic_task.hermetic`, `rpm_signature.allowed:9386b48a`) |
| `--version` | *(all)* | Filter by RHOAI version in MR title (e.g. `rhoai-3.4` or `3.4`) |
| `--author` | *(all)* | Filter by MR author GitLab username |
| `--format` | `text` | Output format: `text`, `markdown`, or `json` |

### How it works

The script reuses `_glab_get_mrs()` from `preflight_check.py` (python-gitlab with glab CLI fallback). When `--rule` is given, it searches by the full rule, by any suffix after `:`, and by the rule family prefix (e.g. `rpm_signature` from `rpm_signature.allowed:9386b48a`). Without `--rule`, it performs a broad search for Merge Requests with "Conforma exception" in the title.

Standard MR titles (e.g. `[AMD] [RHOAI] Conforma exception: rpm_signature.allowed:9386b48a for rhoai-3.3, rhoai-3.4`) are parsed to extract vendor, rule, and version fields for structured output. Non-standard titles still appear but with fewer parsed fields.

### When to use

| User question | Command |
|---------------|---------|
| "Are there open Merge Requests for rpm_signature?" | `--rule rpm_signature` |
| "Any pending exception Merge Requests for rhoai-3.4?" | `--version rhoai-3.4` |
| "Show me all open conforma exception Merge Requests" | *(no filters)* |
| "Open Merge Requests for hermetic build exceptions?" | `--rule hermetic_task` |
| "What's my open exception Merge Requests?" | `--author <username>` |

## Adding Jira Watchers

When the user asks to add watchers to Jira tickets (e.g. "add Akshay Ghodake as watcher to PSX-1040", "add watchers to these tickets"), use the deterministic `add_jira_watchers.py` script. **Do NOT use the Jira REST API directly or write inline watcher logic** — the script handles all project-specific differences.

The script auto-selects the correct mechanism per project:

| Project | Mechanism | Notes |
|---------|-----------|-------|
| PSX, OCPEXCEPT | `customfield_10705` ("Additional watchers" custom field) | Standard watcher API fails because users lack PSX view permissions. Editing the custom field requires the caller to be the reporter or assignee. |
| RHOAIENG, others | Standard Jira watchers API (`POST /issue/{key}/watchers`) | Works for any user with project access. |

### Automatic team discovery

The `--auto-discover` flag discovers the caller's Jira group members and adds them as watchers automatically. The script:

1. Calls GET /myself to identify the caller
2. Fetches the caller's Jira groups
3. **Skips groups with > 100 members** (org-wide groups like `jira-users`, `employee`, etc.)
4. Fetches members only from small team-sized groups (≤ 100 members)
5. Adds all discovered team members (excluding the caller) as watchers

When creating PSX/OCPEXCEPT tickets, the agent MUST run `discover_team()` during the questionnaire, present the discovered team to the user for confirmation, then pass the confirmed names via `--watchers`. The mandatory watchers (Jay Koehler, Lindani Phiri) are always included. See the questionnaire "Batch 3, item 10" for the exact agent flow.

### Usage

Add explicit watchers:

```bash
python3 skills/conforma-exception/scripts/add_jira_watchers.py \
  --tickets PSX-1038,PSX-1039,PSX-1040 \
  --watchers 'Akshay Ghodake,Jane Doe' \
  --dry-run
```

Auto-discover team and add them:

```bash
python3 skills/conforma-exception/scripts/add_jira_watchers.py \
  --tickets PSX-1040 \
  --auto-discover \
  --dry-run
```

Combine both — explicit names plus auto-discovered team:

```bash
python3 skills/conforma-exception/scripts/add_jira_watchers.py \
  --tickets PSX-1040 \
  --watchers 'Akshay Ghodake' \
  --auto-discover
```

Mixed projects in a single call are supported — the script routes each ticket to the correct mechanism:

```bash
python3 skills/conforma-exception/scripts/add_jira_watchers.py \
  --tickets PSX-1040,RHOAIENG-38414 \
  --watchers 'Akshay Ghodake'
```

### Flags

| Flag | Required | Description |
|------|----------|-------------|
| `--tickets` | yes | Comma-separated ticket keys (e.g. `PSX-1038,RHOAIENG-38414`) |
| `--watchers` | no | Comma-separated Jira display names (must match exactly). Required if `--auto-discover` is not set. |
| `--auto-discover` | no | Discover caller's team from Jira groups and add as watchers. Can combine with `--watchers`. |
| `--dry-run` | no | Preview what would change without writing |

### Output

Structured JSON with per-ticket results. Each ticket reports:
- `method`: `custom_field` or `standard_api`
- `status`: `updated`, `no_change`, `dry_run`, or `error`
- `added` / `already_present`: which names were added vs already there
- `errors`: detailed error messages (e.g. permission issues with reporter/assignee context)

When `--auto-discover` is used, the output includes a `team_discovery` section showing which groups were checked, which were included vs skipped (with member counts), and how many team members were discovered.

### Integration

Other scripts in this skill (e.g. `create_jira_ticket.py`) import `add_jira_watchers.add_watchers_to_tickets()` as a library function instead of implementing their own watcher logic. For PSX/OCPEXCEPT tickets, `create_jira_ticket.py` passes `auto_discover=True` so the caller's team is added automatically at ticket creation time. When adding watcher support to new scripts, import from `add_jira_watchers` — do not duplicate the logic.

### Known limitations

- **PSX/OCPEXCEPT custom field**: Only the reporter or assignee on the ticket can edit `customfield_10705`. If the caller is neither, the script reports the error with the reporter/assignee names so the user knows who to ask.
- **Display name matching**: User lookup requires an exact match on the Jira display name. The script fails early if any name cannot be resolved, before modifying any ticket.
- **Team discovery group threshold**: Groups with > 100 members are skipped. If the caller's team group happens to be larger than 100, team discovery won't find it. The threshold is `MAX_TEAM_GROUP_SIZE` in `add_jira_watchers.py`.
