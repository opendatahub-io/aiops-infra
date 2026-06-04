# RHOAI Z-Stream Onboarding

Master orchestrator skill for the complete RHOAI z-stream release onboarding pipeline.

## Overview

This skill automates the end-to-end z-stream release process for RHOAI (Red Hat OpenShift AI), coordinating three major steps:

1. **RBC Release** — Update the release branch on RHOAI-Build-Config
2. **RBC Main** — Update main branch Tekton fragments
3. **Konflux** — Update konflux-release-data

## Key Features

- **Idempotent**: Run multiple times for the same z-stream release - automatically resumes from last completed step
- **State Tracking**: Maintains JSON state file to track pipeline progress
- **Dependency Management**: Ensures steps execute in correct order with proper dependencies
- **Jira Integration**: Creates and updates Jira tracking issues (placeholder for now)
- **Dry-Run Mode**: Preview all changes without creating PRs/MRs

## Prerequisites

### Required Tools
- `uv` — Python package installer
- `git` — Version control
- `jq` — JSON processor

### Required Environment Variables
- `GITHUB_TOKEN` — GitHub personal access token with repo scope
- `KONFLUX_REPO_TOKEN` — GitLab personal access token with API scope
- `JIRA_API_TOKEN` — Jira personal access token (for tracking)

### Network Requirements
- **VPN active** for Konflux step (GitLab access)

## Usage

### Interactive Mode

```bash
/rhoai-z-stream-onboarding
```

The skill will interactively prompt for:
1. Previous z-stream version (e.g., `3.4.1`, `3.4.0-ea.1`)
2. New z-stream version (e.g., `3.4.2`, `3.4.1-ea.1`)
3. Konflux repo directory (default: `konflux-release-data`)
4. Dry-run mode (yes/no)

### Resume Mode

If you have an existing state file from a previous run:

```bash
/rhoai-z-stream-onboarding --resume
```

The skill will detect the state file and offer to resume from where it left off.

### Direct Script Usage

You can also run the underlying Python script directly:

```bash
# Basic usage
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2

# Dry-run mode
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2 --dry-run

# Custom Konflux directory
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py 3.4.1 3.4.2 --repo-dir my-konflux-dir

# Resume from state file
uv run .claude/skills/common/scripts/run_z_stream_pipeline.py --resume rhoai-zstream-3.4.2-state.json
```

## Pipeline Steps

### Step 1: RBC Release
**Script**: `rbc_zstream_release.py` (from rhoai-release-onboarding repo)

Updates the release branch on RHOAI-Build-Config:
- Trusty AI PIG config (`config/trustyai-pig-build-config.yaml`)
- Bundle patch (`bundle/bundle-patch.yaml`)
- Catalog patch (`catalog/catalog-patch.yaml`)
- Tekton files (`.tekton/*.yaml`)

**Output**: GitHub PR URL

### Step 2: RBC Main
**Script**: `rbc_zstream_main.py` (from rhoai-release-onboarding repo)

Updates main branch Tekton fragment pipelines:
- Finds stage Tekton fragment files matching the train
- Updates `rhoai-version` parameter from previous → new version

**Output**: GitHub PR URL

### Step 3: Konflux Onboard
**Script**: `konflux_zstream_onboard.py` (from rhoai-release-onboarding repo)

Updates konflux-release-data repository:
- Locates existing tenant directory (e.g., `v3.4/`)
- Updates ProdReleasePlans and StageReleasePlans YAML files
- Runs `build-manifests.sh`

**Output**: GitLab MR URL

## State File

The pipeline maintains a state file named `rhoai-zstream-{new_version}-state.json` with:

```json
{
  "release_info": {
    "previous_version": "3.4.1",
    "new_version": "3.4.2",
    "konflux_repo_dir": "konflux-release-data",
    "dry_run": false,
    "created_at": "2026-06-02T12:00:00Z"
  },
  "jira": {
    "parent_key": "RHOAIENG-1234",
    "parent_url": "https://issues.redhat.com/browse/RHOAIENG-1234",
    "child_tasks": {
      "rbc_release": "RHOAIENG-1235",
      "rbc_main": "RHOAIENG-1236",
      "konflux": "RHOAIENG-1237"
    }
  },
  "steps": {
    "rbc_release": {
      "status": "done",
      "pr_url": "https://github.com/org/RHOAI-Build-Config/pull/123",
      "completed_at": "2026-06-02T12:15:00Z",
      "depends_on": []
    },
    "rbc_main": {
      "status": "in_progress",
      "pr_url": null,
      "completed_at": null,
      "depends_on": ["rbc_release"]
    },
    "konflux": {
      "status": "pending",
      "mr_url": null,
      "completed_at": null,
      "depends_on": ["rbc_main"]
    }
  }
}
```

## Version Format

The pipeline accepts version strings in various formats:

- With prefix: `rhoai-3.4.1`, `rhoai-3.4.2`
- Without prefix: `3.4.1`, `3.4.2`
- EA versions: `3.4.0-ea.1`, `3.4.1-ea.1`

### Validation Rules

- **Major.Minor must match**: Source `3.4.1` can upgrade to `3.4.2` (not `3.5.0`)
- **Patch must increase**: Source patch must be less than target patch
- **EA suffix must match**: Both must be GA or both must be EA with same number

## Error Handling

### Common Errors

| Error | Solution |
|-------|----------|
| `GITHUB_TOKEN not set` | `export GITHUB_TOKEN=your-token` |
| `KONFLUX_REPO_TOKEN not set` | `export KONFLUX_REPO_TOKEN=your-token` |
| `JIRA_API_TOKEN not set` | `export JIRA_API_TOKEN=your-token` |
| `uv not found` | Install uv: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| VPN not active | Connect to Red Hat VPN before Konflux step |
| Step failed | Check output, fix issue, re-run to resume |

### Resume After Failure

If a step fails:

1. Check the error output
2. Fix the underlying issue (e.g., merge conflicts, missing permissions)
3. Re-run the skill - it will automatically resume from the failed step

## Differences from Y-Stream Onboarding

### Z-Stream (Patch Releases)
- Updates **existing** release branch (not creating new one)
- Updates **in-place** within existing tenant directory
- 3 steps: RBC Release → RBC Main → Konflux
- No PipelineRun Replicator step
- Simpler version validation (same major.minor, increasing patch)

### Y-Stream (Minor Releases)
- Creates **new** release branch
- Creates **new** tenant directory structure
- 4 steps: RBC Release → RBC Main → Konflux → PipelineRun Replicator
- Broader changes across the codebase
- More complex version progression

## File Locations

```
aiops-infra/
├── .claude/
│   └── skills/
│       ├── common/
│       │   └── scripts/
│       │       ├── run_y_stream_pipeline.py  # Y-stream orchestrator
│       │       └── run_z_stream_pipeline.py  # Z-stream orchestrator (NEW)
│       ├── rhoai-y-stream-onboarding/
│       │   ├── SKILL.md
│       │   └── README.md
│       └── rhoai-z-stream-onboarding/        # NEW
│           ├── SKILL.md
│           └── README.md

rhoai-release-onboarding/
└── src/
    ├── rbc_zstream_release.py      # Step 1 implementation
    ├── rbc_zstream_main.py         # Step 2 implementation
    └── konflux_zstream_onboard.py  # Step 3 implementation
```

## Future Enhancements

- [ ] Full Jira integration (currently placeholder)
- [ ] Automatic PR/MR merging after CI passes
- [ ] Notification system (Slack/email)
- [ ] Rollback capability
- [ ] Multi-version batch processing

## Related Skills

- **rhoai-y-stream-onboarding** — For minor version releases
- **rhoai-release-jira** — Jira ticket management
- **trigger-pipelinerun-replicator** — PipelineRun replication

## Support

For issues or questions:
- Check error messages in pipeline output
- Review state file for current status
- Consult RHOAI release team documentation
- Create issue in aiops-infra repository
