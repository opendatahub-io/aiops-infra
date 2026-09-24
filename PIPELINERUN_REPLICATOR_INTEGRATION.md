# PipelineRun Replicator Integration

## Summary

Added a new step to the RHOAI Y-stream onboarding pipeline that triggers the `pipelinerun-replicator` GitHub Actions workflow in the `red-hat-data-services/konflux-central` repository. This workflow replicates PipelineRun YAML configurations from a source RHOAI release to a target RHOAI release.

## Changes Made

### 1. New Python Script: `run_pipelinerun_replicator.py`

**Location:** `.claude/skills/common/scripts/run_pipelinerun_replicator.py`

**Purpose:** Wrapper script that triggers and monitors the pipelinerun-replicator GitHub Actions workflow.

**Features:**
- Accepts source and target RHOAI versions as arguments
- Automatically normalizes the RHOAI version to MAJOR.MINOR.PATCH[-SUFFIX] format
  - Example: `rhoai-3.5` → `3.5.0`
  - Example: `rhoai-3.5-ea.1` → `3.5.0-ea.1`
- Triggers the workflow with four inputs:
  - `source_branch`: Previous RHOAI version (e.g., rhoai-3.4)
  - `target_branch`: New RHOAI version (e.g., rhoai-3.5)
  - `rhoai_version`: Normalized version (e.g., 3.5.0 or 3.5.0-ea.1)
  - `dry_run`: Boolean value (false for production)
- Monitors workflow execution until completion
- Supports `--dry-run` mode for testing
- Returns the GitHub Actions workflow run URL

**Usage:**
```bash
uv run --script run_pipelinerun_replicator.py rhoai-3.4 rhoai-3.5
uv run --script run_pipelinerun_replicator.py rhoai-3.4 rhoai-3.5 --dry-run
```

**Prerequisites:**
- `GITHUB_USER` environment variable
- `GITHUB_TOKEN` environment variable with `repo` + `actions:write` scope

---

### 2. Updated: `rhoai_release_jira.py`

**Location:** `.claude/skills/common/scripts/rhoai_release_jira.py`

**Changes:**
- Added a 4th child task: "PipelineRun Replicator"
- Updated parent issue description to reflect 4 steps instead of 3
- Updated state file structure to include `pipelinerun_replicator` child task
- Updated summary output to display all 4 child tasks

**Impact:** When creating Jira tracking issues for RHOAI releases, a 4th sub-task will now be created to track the PipelineRun Replicator step.

---

### 3. Updated: `rhoai-y-stream-onboarding` Skill

**Location:** `.claude/skills/rhoai-y-stream-onboarding/SKILL.md`

**Changes:**

#### State File Structure
Added new step to `pipeline_state.json`:
```json
{
  "steps": {
    "rbc_release": { ... },
    "rbc_main": { ... },
    "konflux": { ... },
    "pipelinerun_replicator": {
      "status": "pending",
      "run_url": null,
      "completed_at": null,
      "depends_on": ["konflux"]
    }
  }
}
```

#### New Step 4: PipelineRun Replicator
- Runs after the konflux step completes successfully
- Executes `run_pipelinerun_replicator.py` with source and target versions
- Updates state file with workflow run URL and status
- Updates Jira child task with workflow URL and status
- Skipped in dry-run mode (preview only)

#### Pipeline Summary Updates
- Updated from 3 steps to 4 steps
- Added PipelineRun Replicator workflow URL to final summary output
- Updated Jira parent comment to include all 4 workflow URLs

---

### 4. New Skill: `trigger-pipelinerun-replicator`

**Location:** `.claude/skills/trigger-pipelinerun-replicator/SKILL.md`

**Purpose:** Standalone skill for triggering just the PipelineRun Replicator workflow independently (not as part of the full y-stream onboarding pipeline).

**Usage:**
```bash
/trigger-pipelinerun-replicator
/trigger-pipelinerun-replicator --dry-run
```

**Features:**
- Interactive prompts for source and target versions
- Dry-run mode support
- Prerequisite checks for `uv`, `GITHUB_USER`, `GITHUB_TOKEN`
- Workflow execution and monitoring
- Clear success/failure reporting

**Use Cases:**
- Re-running just the PipelineRun Replicator step after a failure
- Testing the workflow trigger independently
- Manual invocation outside the full pipeline

---

## Workflow Details

### GitHub Actions Workflow

**Repository:** `red-hat-data-services/konflux-central`  
**Workflow File:** `.github/workflows/pipelinerun-replicator.yml`  
**Workflow URL:** https://github.com/red-hat-data-services/konflux-central/actions/workflows/pipelinerun-replicator.yml

### Workflow Inputs

1. **source_branch** (required)
   - Description: Source branch to copy Tekton files from
   - Example: `rhoai-3.4`

2. **target_branch** (required)
   - Description: Target branch to create
   - Example: `rhoai-3.5`

3. **rhoai_version** (optional)
   - Description: RHOAI version in MAJOR.MINOR.PATCH[-SUFFIX] format
   - Example: `3.5.0` (from `rhoai-3.5`)
   - Example: `3.4.0-ea.3` (from `rhoai-3.4-ea.3`)
   - Note: The script automatically normalizes versions to include the patch version (.0 if missing)

4. **dry_run** (required, boolean, default: true)
   - Description: Dry run mode - no changes are committed when true
   - Values: `true` or `false`

---

## Integration Flow

### Full Y-Stream Onboarding Pipeline (Updated)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. RBC Release                                               │
│    Create release branch on RHOAI-Build-Config              │
│    Output: GitHub PR URL                                     │
└───────────────────┬─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. RBC Main                                                  │
│    Onboard catalog + Tekton to main branch                  │
│    Output: GitHub PR URL                                     │
│    Depends on: RBC Release                                   │
└───────────────────┬─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Konflux Onboard                                           │
│    Update konflux-release-data                              │
│    Output: GitLab MR URL                                     │
│    Depends on: RBC Main                                      │
└───────────────────┬─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. PipelineRun Replicator (NEW)                             │
│    Replicate PipelineRuns in konflux-central                │
│    Output: GitHub Actions Workflow Run URL                   │
│    Depends on: Konflux                                       │
└─────────────────────────────────────────────────────────────┘
```

### State Tracking

Each step tracks:
- **status**: `pending` → `in_progress` → `done` or `failed`
- **URL**: PR/MR/Workflow Run URL
- **completed_at**: ISO 8601 timestamp
- **depends_on**: Array of prerequisite steps

### Jira Integration

When creating a new RHOAI release tracking issue, 4 child tasks are now created:
1. RBC Release
2. RBC Main
3. Konflux
4. **PipelineRun Replicator** (NEW)

Each child task is updated with:
- PR/MR/Workflow URL as a comment
- Status transition (Resolved or Failed)

---

## Testing

### Dry-Run Mode

Test the integration without actually triggering workflows:

```bash
# Full pipeline in dry-run mode
/rhoai-y-stream-onboarding --dry-run

# Standalone skill in dry-run mode
/trigger-pipelinerun-replicator --dry-run
```

### Production Run

Execute the full pipeline (requires all environment variables):

```bash
# Prerequisites
export GITHUB_USER=yourusername
export GITHUB_TOKEN=yourtoken  # needs: repo + actions:write
export KONFLUX_REPO_TOKEN=yourtoken  # for GitLab
export JIRA_TOKEN=yourtoken

# Run the pipeline
/rhoai-y-stream-onboarding
```

---

## Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| `GITHUB_TOKEN not set` | Missing environment variable | `export GITHUB_TOKEN=yourtoken` |
| `actions:write permission denied` | Token lacks workflow trigger permission | Regenerate token with `actions:write` scope |
| `Workflow not found` | Workflow doesn't exist or incorrect path | Verify workflow exists at `.github/workflows/pipelinerun-replicator.yml` |
| `Invalid version format` | Version doesn't match expected pattern | Use format `rhoai-X.Y` or `rhoai-X.Y-ea.N` |
| `Workflow failed` | GitHub Actions workflow encountered an error | Check workflow run logs at the returned URL |

### Recovery

If the PipelineRun Replicator step fails:

1. **Check the workflow run logs** at the returned URL
2. **Fix any issues** in the workflow or inputs
3. **Re-run the pipeline** with `--resume`:
   ```bash
   /rhoai-y-stream-onboarding --resume
   ```
4. Or **run just this step** independently:
   ```bash
   /trigger-pipelinerun-replicator
   ```

---

## Files Modified

```
.claude/skills/common/scripts/
├── run_pipelinerun_replicator.py  (NEW)
└── rhoai_release_jira.py          (MODIFIED)

.claude/skills/
├── rhoai-y-stream-onboarding/
│   └── SKILL.md                   (MODIFIED)
└── trigger-pipelinerun-replicator/ (NEW)
    └── SKILL.md                   (NEW)
```

---

## Next Steps

1. **Test the integration** in dry-run mode
2. **Verify the workflow** exists and is accessible in konflux-central
3. **Run a production test** with a test release version
4. **Document** any issues or edge cases discovered
5. **Update documentation** if workflow inputs change

---

## Version

- **Created:** 2026-06-01
- **RHOAI Version:** Compatible with all RHOAI versions
- **Workflow:** pipelinerun-replicator.yml in konflux-central

---

## Version Format Fix (2026-06-01)

### Issue
The workflow requires RHOAI versions in the format `MAJOR.MINOR.PATCH[-SUFFIX]` (e.g., `3.4.0-ea.3`), but the initial implementation was sending versions without the patch version (e.g., `3.4-ea.3`).

### Fix
Updated the `extract_v_prefix_release()` function to normalize versions:
- `rhoai-3.4` → `3.4.0`
- `rhoai-3.4-ea.3` → `3.4.0-ea.3`
- `rhoai-3.5.1` → `3.5.1`
- `rhoai-3.5.1-ea.2` → `3.5.1-ea.2`

The normalization ensures:
1. Removes "rhoai-" and "v" prefixes
2. Splits into base version and suffix
3. Ensures base version has exactly 3 parts (MAJOR.MINOR.PATCH)
4. Adds `.0` for missing patch version
5. Rejoins with suffix

### Verification
✅ All test cases pass
✅ Workflow successfully triggered and completed with normalized versions
✅ Run #26740546199: SUCCESS
