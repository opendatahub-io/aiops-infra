# RHOAI Release Onboarding Automation

Automated pipeline for onboarding new RHOAI releases to the Red Hat OpenShift AI build and release infrastructure.

## Overview

When a new RHOAI release is created (e.g., `rhoai-3.5-ea.2`), it must be onboarded to three systems:

1. **RHOAI-Build-Config** (GitHub) - Release branch + Main branch catalog/Tekton updates
2. **konflux-release-data** (GitLab) - Konflux CI/CD pipeline configuration

This automation handles all three steps, creates Jira tracking tickets, and provides resumable execution with state persistence.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  /rhoai-release-onboard (Master Orchestrator)               │
│  • State management & dependency tracking                   │
│  • Jira integration & progress tracking                     │
│  • Idempotent execution (resume from any point)             │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ├──> Step 1: RBC Release Branch
                   │    (/rhoai-rbc-release)
                   │    • Create rhoai-X.Y branch
                   │    • Copy catalog from previous release
                   │    • Update operator versions
                   │    • Raise GitHub PR
                   │
                   ├──> Step 2: RBC Main Branch  
                   │    (/rhoai-rbc-main)
                   │    • Add catalog to main branch
                   │    • Add Tekton configs
                   │    • Preserve existing content
                   │    • Raise GitHub PR
                   │
                   └──> Step 3: Konflux Onboard
                        (/rhoai-konflux-onboard)
                        • Clone konflux-release-data
                        • Create release YAML
                        • Update target versions
                        • Raise GitLab MR
```

## Pipeline Flow

### State-Driven Execution

The orchestrator maintains a JSON state file (`rhoai-release-<version>-state.json`) tracking:
- Release versions (previous → new)
- Step status (pending → in_progress → done/failed)
- PR/MR URLs for each step
- Jira tracking issue keys
- Timestamps and metadata

**Example state file:**
```json
{
  "release_info": {
    "previous_version": "rhoai-3.5-ea.1",
    "new_version": "rhoai-3.5-ea.2",
    "dry_run": false
  },
  "jira": {
    "parent_key": "RHOAIENG-12345",
    "child_tasks": {
      "rbc_release": "RHOAIENG-12346",
      "rbc_main": "RHOAIENG-12347",
      "konflux": "RHOAIENG-12348"
    }
  },
  "steps": {
    "rbc_release": {"status": "done", "pr_url": "https://..."},
    "rbc_main": {"status": "in_progress", "pr_url": null},
    "konflux": {"status": "pending", "mr_url": null}
  }
}
```

### Dependency Chain

```
rbc_release (no dependencies)
    ↓
rbc_main (depends_on: rbc_release)
    ↓
konflux (depends_on: rbc_main)
```

Each step:
1. Checks if already completed (reads state file)
2. Verifies dependencies are satisfied
3. Executes only if unblocked
4. Updates state with PR/MR URL
5. Updates corresponding Jira ticket

## Prerequisites

### Required Tools
```bash
# Package manager for Python scripts
curl -LsSf https://astral.sh/uv/install.sh | sh

# JSON processor
sudo dnf install jq  # Fedora/RHEL
# or
brew install jq     # macOS
```

### Required Environment Variables
```bash
# GitHub token with repo scope
export GITHUB_TOKEN=ghp_...

# GitLab token for konflux-release-data (API scope)
export KONFLUX_REPO_TOKEN=glpat-...

# github user id
export GITHUB_USER=...

# gitlab user id
export GITLAB_USER=...

# gitlab token
export GITLAB_TOKEN=...

# Jira user email
export JIRA_USER_EMAIL=...

# Jira aPI token
export JIRA_API_TOKEN=...
```

### Network Requirements
- **VPN**: Required for GitLab (konflux-release-data) access
- **GitHub Access**: Public internet or VPN
- **Jira Access**: Red Hat network

## Usage

### Method 1: Claude Code Skills (Recommended)

The easiest way is to use the Claude Code skills interface:

```bash
# Start new release onboarding
/rhoai-release-onboard

# Resume an interrupted pipeline
/rhoai-release-onboard --resume

# Preview changes without creating PRs/MRs
/rhoai-release-onboard --dry-run
```

Claude will interactively ask you for:
- Previous version (e.g., `rhoai-3.5-ea.1`)
- New version (e.g., `rhoai-3.5-ea.2`)
- Whether to create new Jira or use existing one
- Dry-run mode preference

### Method 2: Web UI

For real-time progress monitoring with live logs:

```bash
# Launch the web UI
/rhoai-release-ui

# Then open browser to http://localhost:8000
```

The web UI provides:
- Real-time progress indicators
- Streaming logs from each step
- Visual state diagram
- Jira links and PR/MR URLs
- Restart/resume controls


## Individual Skills

### `/rhoai-release-jira`
Creates Jira tracking structure:
- Parent epic for the release
- Child tasks for each pipeline step (RBC Release, RBC Main, Konflux)
- Automated status updates as steps complete

**Output:** `rhoai-release-<version>-jira.json`

### `/rhoai-rbc-release`
Creates the release branch on RHOAI-Build-Config:
- Creates `rhoai-X.Y` branch from previous version
- Copies entire catalog directory
- Updates operator image references
- Sets up release-specific configurations

**Output:** GitHub PR URL to RHOAI-Build-Config

### `/rhoai-rbc-main`
Onboards release to main branch:
- Adds new catalog directory (non-destructive, preserves existing)
- Creates Tekton pipeline configs
- Updates build automation

**Output:** GitHub PR URL to RHOAI-Build-Config

### `/rhoai-konflux-onboard`
Configures Konflux release pipeline:
- Clones konflux-release-data repository
- Creates release YAML with component mappings
- Updates target version references
- Raises GitLab MR

**Output:** GitLab MR URL to konflux-release-data

### `/rhoai-release-ui`
Launches FastAPI web server with:
- Real-time WebSocket progress updates
- HTML UI with step status visualization
- Streaming logs from each subprocess
- Jira integration display

**URL:** http://localhost:8000

## Resumable Execution

The pipeline is **fully idempotent** and **resumable**:

```bash
# Initial run - completes Step 1, starts Step 2, then fails
/rhoai-release-onboard
# Error in Step 2...

# Fix the issue manually, then resume
/rhoai-release-onboard --resume
# Skips completed Step 1, retries Step 2, continues to Step 3
```

State persistence ensures:
- Completed steps are never re-executed
- Progress is preserved across Claude sessions
- Safe to Ctrl+C and resume later
- No duplicate PRs/MRs created

## Dry-Run Mode

Test the entire pipeline without making changes:

```bash
/rhoai-release-onboard --dry-run
```

Dry-run will:
- Validate all inputs and prerequisites
- Clone repositories and generate diffs
- Show what would be changed
- **NOT** create any PRs, MRs, or Jira tickets
- Generate state file marked as `dry_run: true`

Perfect for:
- Testing before production releases
- Validating version compatibility
- Training new team members
- Debugging pipeline issues

## Monitoring Progress

### State File Inspection
```bash
# View current pipeline state
cat rhoai-release-rhoai-3.5-ea.2-state.json | jq

# Check which steps are complete
jq '.steps | to_entries[] | "\(.key): \(.value.status)"' \
  rhoai-release-rhoai-3.5-ea.2-state.json

# Get all PR/MR URLs
jq '.steps[] | select(.pr_url or .mr_url) | .pr_url // .mr_url' \
  rhoai-release-rhoai-3.5-ea.2-state.json
```

### Jira Dashboard
Each pipeline creates:
- 1 parent epic (e.g., RHOAIENG-12345)
- 3 child tasks (one per step)

Visit the parent Jira URL to see:
- Real-time status updates
- PR/MR links as they're created
- Automated comments with progress
- Final summary when complete

### Web UI (Real-time)
```bash
/rhoai-release-ui
# Open http://localhost:8000
```

Provides live updates via WebSocket:
- Step progress bars
- Streaming command output
- Interactive state visualization

## Error Handling

### Common Issues

| Error | Cause | Solution |
|-------|-------|----------|
| `GITHUB_TOKEN not set` | Missing env var | `export GITHUB_TOKEN=ghp_...` |
| `KONFLUX_REPO_TOKEN not set` | Missing GitLab token | `export KONFLUX_REPO_TOKEN=glpat-...` |
| `Connection refused (GitLab)` | VPN not connected | Connect to Red Hat VPN |
| `Branch already exists` | Re-running without state | Use `--resume` or delete remote branch |
| `Jira permission denied` | Invalid/expired token | Refresh JIRA_TOKEN |
| `uv: command not found` | Missing dependency | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

### Recovery from Failures

1. **Check state file** to see which step failed
2. **Review error output** in terminal or web UI logs
3. **Fix the underlying issue** (permissions, network, etc.)
4. **Resume the pipeline** with `/rhoai-release-onboard --resume`

The orchestrator will:
- Skip completed steps
- Retry the failed step
- Continue with remaining steps

### Manual Intervention

If a step needs manual fixes:

1. Let the step fail
2. Manually fix the PR/MR (edit files, resolve conflicts)
3. Update state file to mark step as done:
   ```bash
   jq '.steps.rbc_release.status = "done" | 
       .steps.rbc_release.pr_url = "https://github.com/..."' \
     state.json > state.tmp && mv state.tmp state.json
   ```
4. Resume: `/rhoai-release-onboard --resume`

## File Structure

```
.claude/skills/
├── RHOAI-RELEASE-ONBOARDING.md          # This file
├── rhoai-release-onboard/               # Master orchestrator
│   └── SKILL.md
├── rhoai-rbc-release/                   # Step 1: Release branch
│   └── SKILL.md
├── rhoai-rbc-main/                      # Step 2: Main branch
│   └── SKILL.md
├── rhoai-konflux-onboard/               # Step 3: Konflux
│   └── SKILL.md
├── rhoai-release-jira/                  # Jira integration
│   └── SKILL.md
├── rhoai-release-ui/                    # Web UI
│   ├── SKILL.md
│   ├── web_ui.py
│   └── templates/index.html
└── common/
    └── scripts/
        ├── run_rbc_release.py           # RBC release logic
        ├── run_rbc_main.py              # RBC main logic
        ├── run_konflux_onboard.py       # Konflux logic
        ├── rhoai_release_jira.py        # Jira API client
        └── check_prerequisites.sh        # Env validation
```

## Output Artifacts

Each pipeline run generates:

| File | Purpose | Persist? |
|------|---------|----------|
| `rhoai-release-<version>-state.json` | Pipeline state & progress | No (gitignored) |
| `rhoai-release-<version>-jira.json` | Jira ticket mapping | No (gitignored) |
| `konflux-release-data/` | Cloned GitLab repo | No (gitignored) |
| `__pycache__/` | Python bytecode cache | No (gitignored) |

These are **runtime artifacts** - the actual changes are persisted via:
- GitHub PRs on RHOAI-Build-Config
- GitLab MR on konflux-release-data
- Jira tickets on redhat.atlassian.net

## Best Practices

### Before Running

1. **Check prerequisites** - all tokens set, VPN connected
2. **Verify previous version** - ensure base branch exists
3. **Use dry-run first** - test before production
4. **Create Jira manually** if you need custom fields/labels

### During Execution

1. **Monitor Jira** - watch for status updates
2. **Check PR/MR diffs** - review automated changes
3. **Don't Ctrl+C unnecessarily** - but safe to do if needed
4. **Use web UI** for long-running pipelines

### After Completion

1. **Review all PRs/MRs** - don't auto-merge
2. **Test builds** - verify Konflux pipelines
3. **Update Jira** - add manual verification notes
4. **Clean up state files** - safe to delete after PRs merged

## Advanced Usage

### Custom Jira Templates

Create child tasks from existing Jira:

```bash
/rhoai-release-jira --parent RHOAIENG-12345
```

### Partial Pipeline Runs

Run only specific steps:

```bash
# Only RBC release
uv run --script .claude/skills/common/scripts/run_rbc_release.py \
  rhoai-3.5-ea.1 rhoai-3.5-ea.2

# Only Konflux (requires RBC steps done first)
uv run --script .claude/skills/common/scripts/run_konflux_onboard.py \
  rhoai-3.5-ea.1 rhoai-3.5-ea.2
```

### State File Manipulation

```bash
# Reset a step to retry
jq '.steps.rbc_main.status = "pending" | 
    .steps.rbc_main.pr_url = null' state.json > state.tmp
mv state.tmp state.json

# Check all dependencies
jq '.steps | to_entries[] | 
    {step: .key, depends_on: .value.depends_on}' state.json
```

## Troubleshooting

### Enable Debug Logging

```bash
export DEBUG=1
/rhoai-release-onboard
```

### Check Script Output

All Python scripts support `--help`:

```bash
uv run --script .claude/skills/common/scripts/run_rbc_release.py --help
uv run --script .claude/skills/common/scripts/rhoai_release_jira.py --help
```

### Validate Prerequisites

```bash
.claude/skills/common/scripts/check_prerequisites.sh \
  --env "GITHUB_TOKEN KONFLUX_REPO_TOKEN JIRA_TOKEN" \
  --tools "uv git jq"
```

## Support

For issues or questions:
1. Check this documentation
2. Review skill SKILL.md files for implementation details
3. Inspect state files and logs
4. Contact the RHOAI AIOps team

## Version History

- **v1.0** (2026-05-26) - Initial implementation
  - Orchestrator with state management
  - Jira integration
  - Web UI with real-time progress
  - Idempotent, resumable execution
  - Dry-run support
