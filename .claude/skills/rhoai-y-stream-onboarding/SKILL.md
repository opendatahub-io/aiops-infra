---
name: rhoai-y-stream-onboarding
description: Master orchestrator for the full RHOAI Y-stream onboarding pipeline (RBC Release → RBC Main → Konflux → PipelineRun Replicator). Idempotent - run any number of times for the same release.
allowed-tools: Bash, AskUserQuestion
user-invocable: true
---

# RHOAI Y-Stream Onboarding

Orchestrates the complete RHOAI release onboarding pipeline with state tracking and idempotent re-run capability:

1. **RBC Release** — Create release branch on RHOAI-Build-Config
2. **RBC Main** — Onboard catalog + Tekton to main branch
3. **Konflux** — Update konflux-release-data
4. **PipelineRun Replicator** — Replicate PipelineRuns in konflux-central

**Re-run model:** Invoke this skill any number of times for the same release. Each run checks which steps are complete and executes only the next unblocked steps.

## Prerequisites

- `uv` must be installed and in PATH
- `git` must be installed and in PATH
- `jq` must be installed and in PATH
- `GITHUB_TOKEN` — GitHub personal access token with repo scope
- `KONFLUX_REPO_TOKEN` — GitLab personal access token with API scope
- `JIRA_API_TOKEN` — Jira personal access token (for tracking)
- **VPN active** for Konflux step

## Usage

```
/rhoai-y-stream-onboarding
/rhoai-y-stream-onboarding --resume
```

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.
COMMON_SCRIPTS_DIR is `<SKILL_DIR>/../common/scripts`.

---

## Step 1: Check for resume mode

Check if there's an existing state file in the current directory that can be resumed:

```bash
STATE_FILES=(rhoai-release-rhoai-*-state.json)
if [[ -f "${STATE_FILES[0]}" && "${STATE_FILES[0]}" != "rhoai-release-rhoai-*-state.json" ]]; then
  EXISTING_STATE="${STATE_FILES[0]}"
  echo "Found existing state file: $EXISTING_STATE"
  
  # Ask user if they want to resume
  # Use AskUserQuestion to ask:
  # "Do you want to resume the existing pipeline or start a new one?"
  # Options: "Resume existing pipeline", "Start new pipeline"
  
  # If "Resume existing pipeline":
  #   Run: uv run --script "$COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py" --resume "$EXISTING_STATE"
  #   Exit after completion
fi
```

## Step 2: Collect inputs for new pipeline

If not resuming, ask the user using AskUserQuestion:

**Question 1 - Previous version:**
> What is the previous RHOAI version?
> Examples: `rhoai-3.4`, `rhoai-3.5-ea.1`

→ Store in `PREVIOUS_VERSION`.

**Question 2 - New version:**
> What is the new RHOAI version?
> Examples: `rhoai-3.5`, `rhoai-3.5-ea.2`

→ Store in `NEW_VERSION`.

**Question 3 - Konflux clone directory (optional):**
> What directory should be used for konflux-release-data clone?
> Default: konflux-release-data

→ Store in `REPO_DIR`. Default: `konflux-release-data`.

**Question 4 - Dry-run mode (optional):**
> Should this run in dry-run mode?
> Note: Dry-run will preview all changes but not create PRs/MRs or Jira.
> Options: Yes, No (Recommended)

→ Store in `DRY_RUN`. Default: `no`.

## Step 3: Execute the pipeline

Build and execute the command:

```bash
CMD="uv run --script $COMMON_SCRIPTS_DIR/run_y_stream_pipeline.py $PREVIOUS_VERSION $NEW_VERSION"

# Add optional arguments
if [[ "$REPO_DIR" != "konflux-release-data" ]]; then
  CMD="$CMD --repo-dir $REPO_DIR"
fi

if [[ "$DRY_RUN" == "yes" ]]; then
  CMD="$CMD --dry-run"
fi

# Execute
$CMD
```

That's it! The Python script handles:
- Prerequisites checking
- Jira creation/retrieval
- State management
- Step execution with dependency tracking
- Jira status updates (In Progress → Resolved/Failed)
- Final summary and cleanup
- Automatic resume on re-run

---

## Error Reference

| Error | Action |
|-------|--------|
| `GITHUB_TOKEN` not set | `export GITHUB_TOKEN=your-token` |
| `KONFLUX_REPO_TOKEN` not set | `export KONFLUX_REPO_TOKEN=your-token` |
| `JIRA_API_TOKEN` not set | `export JIRA_API_TOKEN=your-jira-token` |
| `uv`/`git`/`jq` not installed | Install the missing tool |
| Step failed | Check output, fix issue, re-run skill to resume |
| VPN not active | Connect to VPN before Konflux step |
