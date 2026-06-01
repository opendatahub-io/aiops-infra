# RHOAI Y-Stream Onboarding Refactoring

## Summary

Refactored the `/rhoai-y-stream-onboarding` skill to follow best practices:

1. **Removed all bash code from SKILL.md** - Now just collects inputs and invokes the orchestration script
2. **Created centralized orchestration script** - `run_y_stream_pipeline.py` handles all logic
3. **Made it fully idempotent** - Can run multiple times, automatically resumes from last completed step

## Changes

### Before
- SKILL.md contained ~600 lines of complex bash code
- Multiple bash blocks for each step
- Difficult to maintain and test
- Logic scattered across the skill file

### After
- SKILL.md is ~100 lines - just input collection and script invocation
- All logic in `run_y_stream_pipeline.py` (~500 lines of clean Python)
- Easy to test, maintain, and extend
- Clear separation of concerns

## New File Structure

```
.claude/skills/
├── rhoai-y-stream-onboarding/
│   └── SKILL.md (simplified - just invokes script)
└── common/scripts/
    ├── run_y_stream_pipeline.py (new - main orchestrator)
    ├── run_rbc_release.py (existing)
    ├── run_rbc_main.py (existing)
    ├── run_konflux_onboard.py (existing)
    ├── run_pipelinerun_replicator.py (existing)
    └── rhoai_release_jira.py (existing)
```

## Key Features

### 1. Idempotent Execution
```bash
# First run - executes all steps
uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5

# Second run - detects all steps done, shows summary
uv run run_y_stream_pipeline.py --resume rhoai-release-rhoai-3.4-ea.5-state.json
```

### 2. Automatic Resume
The script automatically:
- Creates a state file tracking each step's status
- Checks dependencies before executing steps
- Updates Jira status (Pending → In Progress → Resolved/Failed)
- Can be re-run at any time to resume from last successful step

### 3. State Tracking
Each run creates/updates a JSON state file:
```json
{
  "release_info": {
    "previous_version": "rhoai-3.4",
    "new_version": "rhoai-3.4-ea.5",
    "konflux_repo_dir": "konflux-release-data",
    "dry_run": false,
    "created_at": "2026-06-01T15:00:00Z"
  },
  "jira": {
    "parent_key": "RHOAIENG-65411",
    "parent_url": "https://redhat.atlassian.net/browse/RHOAIENG-65411",
    "child_tasks": {
      "rbc_release": "RHOAIENG-65412",
      "rbc_main": "RHOAIENG-65413",
      "konflux": "RHOAIENG-65414",
      "pipelinerun_replicator": "RHOAIENG-65415"
    }
  },
  "steps": {
    "rbc_release": {
      "status": "done",
      "pr_url": "https://github.com/red-hat-data-services/RHOAI-Build-Config/pull/23059",
      "completed_at": "2026-06-01T15:05:00Z",
      "depends_on": []
    },
    ...
  }
}
```

### 4. Clean Output
The script provides colored, formatted output:
- ✓ Success messages in green
- ✗ Error messages in red
- ▸ Info messages in yellow
- Clear step headers with progress (1/4, 2/4, etc.)

### 5. Jira Integration
Automatically updates Jira throughout the pipeline:
- Creates parent issue and 4 child tasks
- Updates each child task: To Do → In Progress → Resolved/Failed
- Adds PR/MR URLs as comments
- Updates parent issue with final summary

## Usage Examples

### New Pipeline
```bash
# Interactive - skill will ask for inputs
/rhoai-y-stream-onboarding

# Direct script invocation
uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5

# Dry-run mode (no PRs/MRs, no Jira)
uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5 --dry-run

# Custom konflux repo directory
uv run run_y_stream_pipeline.py rhoai-3.4 rhoai-3.4-ea.5 --repo-dir my-konflux-dir
```

### Resume Existing Pipeline
```bash
# Resume from state file
uv run run_y_stream_pipeline.py --resume rhoai-release-rhoai-3.4-ea.5-state.json

# Or just re-run the skill - it will detect the state file
/rhoai-y-stream-onboarding
```

## Benefits

1. **Maintainability** - Python is easier to read, test, and debug than bash
2. **Reliability** - Idempotent execution prevents duplicate work
3. **Visibility** - Clear state tracking and Jira integration
4. **Simplicity** - SKILL.md is now simple and focused
5. **Testability** - Can test the script independently
6. **Extensibility** - Easy to add new steps or modify existing ones

## Migration Notes

- **No breaking changes** - The skill works exactly the same from user perspective
- **Backward compatible** - Can resume existing pipelines
- **State files** - Old state files work with new script
- **Jira tracking** - Works with existing Jira issues

## Testing

Tested with existing state file from rhoai-3.4 → rhoai-3.4-ea.5 release:
- ✓ Successfully detected all completed steps
- ✓ Showed final summary
- ✓ Updated parent Jira issue
- ✓ Skipped cleanup (repos already removed)

## Future Improvements

Possible enhancements:
1. Add `--skip-jira` flag to skip Jira creation entirely
2. Add `--parallel` to run independent steps in parallel
3. Add retry logic for transient failures
4. Add email notifications on completion
5. Add Slack integration for status updates
